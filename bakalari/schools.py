"""The public directory of schools that use Bakaláři (sluzby.bakalari.cz): municipalities and school addresses.

The official app finds a school's Bakaláři address through this service: ``GET /municipality`` lists the
municipalities with their number of schools and ``GET /municipality/{name}`` the schools of a municipality. The
service matches that name as a case-insensitive prefix, so ``Brno`` also returns the schools of ``Brno - Bystrc``.
It needs no login and is not part of a school's installation, so it has its own small client,
:class:`SchoolDirectory`, instead of a :class:`~bakalari.BakalariClient` mixin.
"""
from __future__ import annotations

import html
import logging
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional, Sequence, Set, Tuple, Union

from ._core import USER_AGENT, normalize_base_url
from ._parse import check_shape, ident, objects, quote_segment, require_list, require_mapping, text, to_int
from .errors import BakalariConfigError, BakalariContractError, BakalariHTTPError, BakalariNotFoundError
from .http import HttpResponse, Transport, urllib_transport
from .models import Model

log = logging.getLogger("bakalari.schools")

DIRECTORY_URL = "https://sluzby.bakalari.cz/api/v1"
DEFAULT_MAX_REQUESTS = 15
_DASH = re.compile(r"\s*-\s*")

__all__ = [
    "DEFAULT_MAX_REQUESTS",
    "DIRECTORY_URL",
    "Municipality",
    "School",
    "SchoolDirectory",
    "find",
    "municipalities",
    "schools",
]


@dataclass(frozen=True)
class Municipality(Model):
    """A municipality of the school directory with the number of its schools that use Bakaláři. The directory also
    lists schools under an empty ``name``; those cannot be listed one by one."""

    name: str
    school_count: int = 0
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "Municipality":
        """Parses ``{"name": ..., "schoolCount": ...}``."""
        return cls(name=text(data.get("name")), school_count=to_int(data.get("schoolCount")) or 0, raw=dict(data))


@dataclass(frozen=True)
class School(Model):
    """A school of the directory: ``url`` is the address of its Bakaláři installation as listed (pass it as the
    ``base_url`` of :class:`~bakalari.BakalariClient`), ``id`` the directory's school id."""

    id: str
    name: str
    url: str
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def base_url(self) -> str:
        """``url`` normalized the way the client does it (``https://``, no trailing slash or page path); empty when
        the directory lists no address, and ``url`` as listed when it is too malformed to normalize."""
        if not self.url:
            return ""
        try:
            return normalize_base_url(self.url)
        except ValueError:  # e.g. an unbalanced IPv6 bracket in a mistyped address
            return self.url

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "School":
        """Parses ``{"id": ..., "name": ..., "schoolUrl": ...}``."""
        return cls(
            id=ident(data.get("id")), name=text(data.get("name")), url=text(data.get("schoolUrl")), raw=dict(data)
        )


class SchoolDirectory:
    """Client of the public school directory at ``base_url`` (default :data:`DIRECTORY_URL`; ``https://`` is added
    when the scheme is missing, as for the client); no login.

    A status other than 200 raises :class:`~bakalari.BakalariNotFoundError` (HTTP 404) or
    :class:`~bakalari.BakalariHTTPError`, an answer that is not JSON :class:`~bakalari.BakalariContractError` and an
    unreachable service :class:`~bakalari.BakalariConnectionError`. ``transport`` exists for tests.
    """

    def __init__(
        self, base_url: str = DIRECTORY_URL, *, timeout: float = 30.0, transport: Optional[Transport] = None
    ) -> None:
        self.base_url = _directory_url(base_url)
        self.timeout = timeout
        self._transport = transport or urllib_transport()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self.base_url!r})"

    def municipalities(self, *, validate: bool = True) -> List[Municipality]:
        """``GET /municipality``: every municipality with schools that use Bakaláři and their number of schools, in
        the directory's alphabetical order, including one without a name. With ``validate`` (default) an entry that
        is not an object with a ``name`` raises :class:`~bakalari.BakalariContractError`."""
        entries = require_list(self._get_json("/municipality"), "municipality list")
        if validate:
            bad = sum(1 for entry in entries if not (isinstance(entry, Mapping) and isinstance(entry.get("name"), str)))
            if bad:
                problem = f"{bad} of {len(entries)} entries are not objects with a 'name'"
                raise BakalariContractError([problem], "municipality list")
        return [Municipality.from_json(entry) for entry in objects(entries)]

    def schools(self, municipality: Union[str, Municipality], *, validate: bool = True) -> List[School]:
        """``GET /municipality/{name}``: the schools of a municipality, given by name or as a :class:`Municipality`.

        The service matches the name as a case-insensitive prefix: ``"Brno"`` also returns the schools of
        ``"Brno - Bystrc"`` and every other municipality whose name starts with it. When it answers 404 for a name
        with a dot (a known quirk with names such as ``Ostrava-Mar.Hory``), the part before the dot is asked for,
        which may add schools of the other municipalities starting with that part. An unknown name raises
        :class:`~bakalari.BakalariNotFoundError`; an empty name raises ``ValueError`` because the service cannot
        list the unnamed municipality.
        """
        name = text(municipality.name if isinstance(municipality, Municipality) else municipality)
        if not name:
            raise ValueError("The school directory cannot list the schools of a municipality without a name")
        try:
            data = self._get_json("/municipality/" + quote_segment(name))
        except BakalariNotFoundError:
            head = name.split(".", 1)[0].strip()
            if not head or head == name:
                raise
            data = self._get_json("/municipality/" + quote_segment(head))
        if validate:
            check_shape(data, "school list", lists=("schools",))
        payload = require_mapping(data, "school list")
        return [School.from_json(entry) for entry in objects(payload.get("schools"))]

    def find(self, text: str, *, max_requests: int = DEFAULT_MAX_REQUESTS, validate: bool = True) -> List[School]:
        """The schools of every municipality whose name contains ``text``, ignoring case, diacritics and the spacing
        around dashes (``"praha 4-modrany"`` finds ``Praha 4 - Modřany``), without duplicates: ``GET /municipality``,
        then ``GET /municipality/{name}`` for the matches.

        Only the matching municipalities are asked for, and a municipality whose name starts with the name of
        another match comes with that one's answer (see :meth:`schools`), so ``"Praha"`` takes about a dozen
        requests. A ``text`` that needs more than ``max_requests`` of them raises ``ValueError`` before any of them
        is sent; so does an empty one. Should an answer list fewer schools than the directory counts for its group,
        the other names of the group are asked for one by one, even beyond ``max_requests``, so that no school is
        missed. No match returns an empty list.
        """
        wanted = _fold(text)
        if not wanted:
            raise ValueError("Pass a part of a municipality name to search for, e.g. find('Kocourkov')")
        matches = [item for item in self.municipalities(validate=validate) if item.name and wanted in _fold(item.name)]
        groups = _prefix_groups(matches)
        if len(groups) > max_requests:
            raise ValueError(
                f"{text!r} matches {len(matches)} municipalities, which takes {len(groups)} requests "
                f"(max_requests={max_requests}): use a more specific name"
            )
        found: List[School] = []
        for head, covered in groups:
            listed = self.schools(head, validate=validate)
            if len(covered) > 1 and len(listed) < sum(item.school_count for item in covered):
                # The answer lacks schools of the longer names: the service matched the name exactly after all.
                for other in covered:
                    if other is not head:  # the directory may list a longer name before the head
                        listed += self.schools(other, validate=validate)
            found.extend(listed)
        return list(dict.fromkeys(found))

    def _get_json(self, path: str) -> Any:
        url = self.base_url + path
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        response = self._transport("GET", url, headers, None, self.timeout)
        log.debug("GET %s -> HTTP %s", url, response.status)
        if response.status != 200:
            error = BakalariNotFoundError if response.status == 404 else BakalariHTTPError
            raise error("GET", url, response.status, 200, _error_body(response))
        try:
            return response.json()
        except ValueError:
            kind = response.content_type or "no content type"
            raise BakalariContractError([f"GET {url} returned {kind} instead of JSON"], "school directory") from None


def municipalities() -> List[Municipality]:
    """The municipalities of the public school directory (:meth:`SchoolDirectory.municipalities`)."""
    return SchoolDirectory().municipalities()


def schools(name: Union[str, Municipality]) -> List[School]:
    """The schools of a municipality in the public school directory (:meth:`SchoolDirectory.schools`)."""
    return SchoolDirectory().schools(name)


def find(text: str) -> List[School]:
    """The schools of the municipalities whose name contains ``text`` (:meth:`SchoolDirectory.find`)."""
    return SchoolDirectory().find(text)


def _directory_url(value: str) -> str:
    """The directory address without a trailing slash, with ``https://`` when the scheme is missing; anything but an
    http(s) URL with a host raises :class:`~bakalari.BakalariConfigError`."""
    url = (value or "").strip()
    if url and "://" not in url:
        url = "https://" + url
    url = url.rstrip("/")
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:  # e.g. an unclosed IPv6 bracket
        parts = urllib.parse.SplitResult("", "", "", "", "")
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise BakalariConfigError(
            f"No valid school directory address ({value!r}): pass an http(s) base_url or keep the default."
        )
    return parts.geturl()  # the scheme in lower case


def _fold(value: str) -> str:
    """Lower case without diacritics, every dash (``-``, ``–``, ...) as ``-`` without spaces around it and single
    spaces, for matching names."""
    chars = (char for char in unicodedata.normalize("NFKD", value) if not unicodedata.combining(char))
    plain = "".join("-" if unicodedata.category(char) == "Pd" else char for char in chars).casefold()
    return " ".join(_DASH.sub("-", plain).split())


def _prefix_groups(matches: Sequence[Municipality]) -> List[Tuple[Municipality, List[Municipality]]]:
    """Groups the matches of :meth:`SchoolDirectory.find` by request: each group is a head, a name that no other match
    is a case-insensitive prefix of, with every match that starts with it (the head included, in the directory's
    order), because the service lists their schools too when asked for the head. The groups keep the directory's
    order."""
    keys = [item.name.lower() for item in matches]
    groups: List[Tuple[Municipality, List[Municipality]]] = []
    heads: Set[str] = set()
    for item, key in zip(matches, keys):
        if key in heads or any(other != key and key.startswith(other) for other in keys):
            continue
        heads.add(key)
        groups.append((item, [match for match, other in zip(matches, keys) if other.startswith(key)]))
    return groups


def _error_body(response: HttpResponse) -> Any:
    """The JSON error body, the ``<title>`` of an HTML error page or the start of a text body (``None`` if empty)."""
    if not response.body:
        return None
    try:
        return response.json()
    except ValueError:
        if "html" not in response.content_type:
            return response.text[:500]
        title = re.search(r"<title[^>]*>(.*?)</title>", response.text, re.I | re.S)
        return " ".join(html.unescape(title.group(1)).split()) if title else ""
