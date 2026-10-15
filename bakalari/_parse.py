"""Parsing helpers shared by the response models (internal module).

The server sends ISO 8601 timestamps with an offset (``2026-10-12T00:00:00+02:00``), sometimes with .NET's seven
fractional digits or the minimum date ``0001-01-01`` for "no date"; it pads some display strings with spaces
(``"ČJL "``, ``"2,86 "``), writes decimals with a comma and sends Komens message bodies as HTML. Ids are opaque
strings that may be space-padded (``" 2"``), so they are kept exactly as sent.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import enum
import math
import re
import urllib.parse
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from .errors import BakalariContractError

DateLike = Union[dt.date, dt.datetime, str]

_FRACTION = re.compile(r"\.(\d+)")
_COMPACT_OFFSET = re.compile(r"([+-]\d{2})(\d{2})$")


def to_date(value: DateLike) -> dt.date:
    """Converts a date, a datetime or an ISO string (``2026-10-12`` or ``2026-10-12T00:00:00+02:00``); raises
    ``ValueError`` for a string that is not an ISO date and ``TypeError`` for other types."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        return dt.date.fromisoformat(value.strip()[:10])
    raise TypeError(f"Expected a date, datetime or ISO date string, got {type(value).__name__}")


def week_of(value: DateLike) -> Tuple[dt.date, dt.date]:
    """Returns the Monday and the Sunday of the week that contains ``value``."""
    day = to_date(value)
    monday = day - dt.timedelta(days=day.weekday())
    return monday, monday + dt.timedelta(days=6)


def format_date(value: Optional[DateLike]) -> Optional[str]:
    """A ``YYYY-MM-DD`` query parameter; ``None`` and ``""`` mean "not sent". Strings go to the server unchanged,
    so it validates them (an invalid date answers HTTP 400)."""
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    return str(value)


def parse_datetime(value: Any) -> Optional[dt.datetime]:
    """Parses a server timestamp leniently: ``None`` for empty or unparseable values and for ``0001-01-01``.

    Accepts an offset (``+02:00``, ``+0200`` or ``Z``) and one to seven fractional digits, on every supported
    Python version. A value without an offset stays naive.
    """
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day)
    text = str(value).strip()
    if not text or text.startswith("0001-01-01"):
        return None
    if text[-1] in "Zz":
        text = text[:-1] + "+00:00"
    text = _COMPACT_OFFSET.sub(r"\1:\2", text) if "T" in text else text
    text = _FRACTION.sub(lambda match: "." + match.group(1)[:6].ljust(6, "0"), text, count=1)
    try:
        return dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def parse_date(value: Any) -> Optional[dt.date]:
    """The calendar date of a server timestamp as the server wrote it (no time zone conversion), or ``None``."""
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value
    parsed = parse_datetime(value)
    return parsed.date() if parsed else None


def text(value: Any) -> str:
    """A display string: ``None`` becomes ``""`` and the padding the server adds is removed."""
    return "" if value is None else str(value).strip()


def ident(value: Any) -> str:
    """An id exactly as the server sends it (never stripped: ``" 2"`` and ``"2"`` differ); ``None`` becomes ``""``."""
    return "" if value is None else str(value)


def to_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    """An integer from a JSON number or a numeric string, else ``default``."""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(float(str(value).strip().replace(",", ".")))
    except (ValueError, OverflowError):  # garbage, NaN and infinity
        return default


def to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    """A finite float from a JSON number or a string with a decimal comma or padding (``"2,86 "`` is 2.86);
    ``default`` for anything else, including NaN and infinity."""
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        cleaned = str(value).strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
        try:
            number = float(cleaned)
        except (ValueError, OverflowError):
            return default
    return number if math.isfinite(number) else default


def to_bool(value: Any) -> bool:
    """A boolean from a JSON boolean (``None`` is ``False``) or the strings ``true``/``false``."""
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def objects(value: Any) -> List[Mapping[str, Any]]:
    """The JSON objects of a list; ``None`` and non-object entries are skipped (lenient parsing)."""
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def mapping(value: Any) -> Mapping[str, Any]:
    """The value if it is a JSON object, else an empty mapping."""
    return value if isinstance(value, Mapping) else {}


def strings(value: Any) -> Tuple[str, ...]:
    """A list of ids or names as a tuple of strings; ``None`` entries are skipped."""
    return tuple(ident(item) for item in value if item is not None) if isinstance(value, list) else ()


def quote_segment(value: Any) -> str:
    """Percent-encodes an id as one URL path segment (``ZSQCVE[IMJ`` becomes ``ZSQCVE%5BIMJ``, a space ``%20``)."""
    return urllib.parse.quote(str(value), safe="")


class _TextExtractor(HTMLParser):
    BLOCKS = frozenset(
        "address article blockquote dd div dl dt figcaption footer h1 h2 h3 h4 h5 h6 header hr li ol p pre "
        "section table tbody thead tfoot tr ul".split()
    )
    SKIPPED = frozenset(("script", "style", "head", "title", "template"))

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self._skipping = 0
        self._links: List[Tuple[str, int]] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag in self.SKIPPED:
            self._skipping += 1
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in ("td", "th"):
            self.parts.append(" ")
        elif tag in self.BLOCKS:
            self.parts.append("\n")
        elif tag == "a":
            self._links.append((dict(attrs).get("href") or "", len(self.parts)))

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIPPED:
            self._skipping = max(0, self._skipping - 1)
        elif tag in self.BLOCKS and tag != "li":  # the next item starts its own line
            self.parts.append("\n")
        elif tag == "a" and self._links:
            href, start = self._links.pop()
            label = "".join(self.parts[start:]).strip()
            if href.startswith(("http://", "https://", "mailto:")) and href.removeprefix("mailto:") not in label:
                self.parts.append(f" ({href})")

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.parts.append(data)


def html_to_text(value: Any) -> str:
    """Readable plain text of an HTML fragment such as a Komens message body: block elements and ``<br>``
    become line breaks, list items start with ``- ``, link targets follow their text, entities are decoded and
    scripts, styles and embedded images are dropped."""
    if not value:
        return ""
    parser = _TextExtractor()
    parser.feed(str(value))
    parser.close()
    lines = [re.sub(r"[ \t\r\f\v\u00a0]+", " ", line).strip() for line in "".join(parser.parts).split("\n")]
    result: List[str] = []
    for line in lines:
        if line or (result and result[-1]):
            result.append(line)
    return "\n".join(result).strip()


def to_jsonable(value: Any) -> Any:
    """Converts a model to JSON-serialisable data: dataclasses become dicts of the fields shown in ``repr()``
    (``raw`` payloads and secrets are hidden from both), dates and times become ISO strings and tuples lists."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value) if f.repr}
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, bytes):
        return None
    return value


def shape_problems(data: Any, what: str, lists: Sequence[str] = (), objects_: Sequence[str] = ()) -> List[str]:
    """Problems of a JSON payload that must be an object with the given lists of objects and nested objects."""
    if not isinstance(data, Mapping):
        return [f"The {what} must be a JSON object"]
    problems = [f"Missing list '{name}'" for name in lists if not isinstance(data.get(name), list)]
    problems += [f"Missing object '{name}'" for name in objects_ if not isinstance(data.get(name), Mapping)]
    for name in lists:
        entries = data.get(name)
        if isinstance(entries, list):
            bad = sum(1 for entry in entries if not isinstance(entry, Mapping))
            if bad == 1:
                problems.append(f"1 entry of '{name}' is not a JSON object")
            elif bad:
                problems.append(f"{bad} entries of '{name}' are not JSON objects")
    return problems


def check_shape(data: Any, what: str, lists: Sequence[str] = (), objects_: Sequence[str] = ()) -> Mapping[str, Any]:
    """Returns the payload as a mapping or raises :class:`BakalariContractError` listing every shape problem."""
    problems = shape_problems(data, what, lists, objects_)
    if problems:
        raise BakalariContractError(problems, what)
    return data


def require_mapping(data: Any, what: str) -> Mapping[str, Any]:
    """The payload as a mapping; even lenient parsing needs a JSON object, so anything else raises
    :class:`BakalariContractError`."""
    if not isinstance(data, Mapping):
        raise BakalariContractError([f"The {what} must be a JSON object"], what)
    return data


def require_list(data: Any, what: str) -> List[Any]:
    """The payload as a list, or :class:`BakalariContractError`."""
    if not isinstance(data, list):
        raise BakalariContractError([f"The {what} must be a JSON array"], what)
    return data


def require_int(data: Any, what: str) -> int:
    """A bare JSON number payload (the ``count-new``/``unread`` counters), or :class:`BakalariContractError`."""
    if isinstance(data, bool) or not isinstance(data, (int, float, str)) or to_int(data) is None:
        raise BakalariContractError([f"The {what} must be a number, got {type(data).__name__}"], what)
    return int(to_int(data) or 0)


def first(values: Iterable[Any], default: Any = None) -> Any:
    return next(iter(values), default)


def compact(mapping_: Mapping[str, Any]) -> Dict[str, Any]:
    """The entries of a request parameter mapping whose value is not ``None``."""
    return {key: value for key, value in mapping_.items() if value is not None}
