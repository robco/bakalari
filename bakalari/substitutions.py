"""Substitutions: the changes of the timetable (substitutions, cancellations, room changes, added and removed
lessons, events) for two weeks, ``GET /api/3/substitutions``.

Each entry has the shape of the ``Change`` of a timetable atom and is parsed into the same
:class:`~bakalari.timetable.Change` model; the substitutions list additionally names the lesson concerned
(``ChangeLessonInfo``) and its begin and end time.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ._core import ClientCore, api_path
from ._parse import DateLike, check_shape, format_date, objects, parse_date, require_mapping, to_date
from .models import Model
from .timetable import Change, ChangeLessonInfo

__all__ = ["Change", "ChangeLessonInfo", "Substitutions", "SubstitutionsEndpoints"]


@dataclass(frozen=True)
class Substitutions(Model):
    """The payload of ``GET /api/3/substitutions``: the changes of the timetable for 14 days, in the server's
    order. ``start`` and ``end`` are the server's ``From`` and ``To`` (``end`` is 14 days after ``start``) and
    every entry of ``changes`` is a :class:`~bakalari.timetable.Change` with its ``day``."""

    start: Optional[dt.date]
    end: Optional[dt.date]
    changes: Tuple[Change, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Any, *, validate: bool = True) -> "Substitutions":
        """Parses the payload. With ``validate`` (default) a payload without a ``Changes`` list of objects raises
        :class:`~bakalari.BakalariContractError`; without it, entries that are not objects are skipped. A
        payload that is not a JSON object always raises."""
        if validate:
            check_shape(data, "substitutions", lists=("Changes",))
        data = require_mapping(data, "substitutions")
        return cls(
            start=parse_date(data.get("From")),
            end=parse_date(data.get("To")),
            changes=tuple(Change.from_json(change) for change in objects(data.get("Changes"))),
            raw=dict(data),
        )

    @property
    def dates(self) -> List[dt.date]:
        """The days that have at least one change, in calendar order."""
        return sorted({change.day for change in self.changes if change.day is not None})

    def on(self, date: DateLike) -> List[Change]:
        """The changes of one day (``date`` is a date, a datetime or an ISO string)."""
        wanted = to_date(date)
        return [change for change in self.changes if change.day == wanted]

    def by_day(self) -> Dict[dt.date, List[Change]]:
        """The changes grouped by day, in calendar order; changes without a day are left out."""
        return {day: self.on(day) for day in self.dates}

    def format(self) -> str:
        """Readable list: one line per change (see :meth:`Change.format <bakalari.timetable.Change.format>`),
        or an empty string when there are no changes."""
        return "\n".join(change.format() for change in self.changes)


class SubstitutionsEndpoints(ClientCore):
    """Substitution endpoints of :class:`~bakalari.BakalariClient`."""

    def substitutions(self, since: Optional[DateLike] = None, *, validate: bool = True) -> Substitutions:
        """``GET /api/3/substitutions?from=``: the changes of the timetable for 14 days from ``since`` (a date, a
        datetime or an ISO string); without it the server starts on Monday of the current week. Needs the
        Substitutions module (HTTP 403 :class:`~bakalari.BakalariPermissionError` otherwise)."""
        data = self.get_json(api_path("substitutions"), {"from": format_date(since)})
        return Substitutions.from_json(data, validate=validate)
