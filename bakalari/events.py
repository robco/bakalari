"""School events: the school's event plan, the user's own events and the public events.

Each event lists its ``Times``, one entry per day (an event can span or recur on several days); a whole-day entry
runs from 00:00 to 23:59 of its day. ``IntervalStartTime`` and ``IntervalEndTime`` are the times entered for that day
and are ``null`` when the day has no own start or end time: the entry then starts at 00:00 or runs until 23:59, as
on the days of an event that runs past midnight (whole-day entries have neither).
Event types, classes, teachers, rooms and students are ``{Id, Abbrev, Name}`` objects; ids are opaque and may contain
spaces (``"U  12"``). From about the middle of the summer holidays the server stops listing last year's events;
asked with ``from``, the public list still returns them, but with the classes and rooms that no longer exist as
empty objects, which this module leaves out.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional, Tuple

from ._core import ClientCore, api_path
from ._parse import (
    DateLike,
    check_shape,
    format_date,
    ident,
    objects,
    parse_date,
    parse_datetime,
    require_mapping,
    shape_problems,
    text,
    to_bool,
)
from .errors import BakalariContractError
from .models import Item, Model

EVENT_SCOPES = ("all", "my", "public")

__all__ = ["EVENT_SCOPES", "Event", "EventTime", "EventsEndpoints", "parse_events"]


def _has_text(value: str) -> bool:
    return any(character.isalnum() for character in value)


def _items(value: Any) -> Tuple[Item, ...]:
    """The ``{Id, Abbrev, Name}`` objects of a list without the placeholders the server sends for classes, rooms and
    students that no longer exist: all fields empty, or an empty id with an abbreviation and name like ``" ()"``."""
    items = (Item.optional(data) for data in objects(value))
    return tuple(
        item for item in items if item is not None and (item.id.strip() or _has_text(item.abbrev + item.name))
    )


def _instant(value: dt.datetime) -> dt.datetime:
    """A sort key that orders aware and (unexpected) naive timestamps together without a ``TypeError``."""
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.timezone.utc)


@dataclass(frozen=True)
class EventTime(Model):
    """One day of an event. ``start`` and ``end`` bound the event on that day (00:00 and 23:59 for a whole-day entry);
    ``interval_start`` and ``interval_end`` are the start and end times entered for that day, ``None`` when the day
    has none (``start`` is then 00:00 or ``end`` 23:59); ``interval_date`` is the calendar day of the entry."""

    whole_day: bool = False
    start: Optional[dt.datetime] = None
    end: Optional[dt.datetime] = None
    interval_start: Optional[dt.datetime] = None
    interval_end: Optional[dt.datetime] = None
    interval_date: Optional[dt.date] = None

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "EventTime":
        """Parses one entry of an event's ``Times``."""
        return cls(
            whole_day=to_bool(data.get("WholeDay")),
            start=parse_datetime(data.get("StartTime")),
            end=parse_datetime(data.get("EndTime")),
            interval_start=parse_datetime(data.get("IntervalStartTime")),
            interval_end=parse_datetime(data.get("IntervalEndTime")),
            interval_date=parse_date(data.get("IntervalDate")),
        )

    @property
    def date(self) -> Optional[dt.date]:
        """The calendar day of the entry: ``interval_date``, else the day of ``start``."""
        if self.interval_date is not None:
            return self.interval_date
        return self.start.date() if self.start is not None else None


@dataclass(frozen=True)
class Event(Model):
    """A school event such as a trip, an exam or a parents' evening, with its type, its times and the classes,
    teachers, rooms and students it concerns (and the sets of them, which the server usually leaves empty).
    ``description`` and ``note`` are plain text; ``changed`` is when the school last edited the event."""

    id: str
    title: str
    description: str = ""
    note: str = ""
    event_type: Optional[Item] = None
    times: Tuple[EventTime, ...] = ()
    classes: Tuple[Item, ...] = ()
    class_sets: Tuple[Item, ...] = ()
    teachers: Tuple[Item, ...] = ()
    teacher_sets: Tuple[Item, ...] = ()
    rooms: Tuple[Item, ...] = ()
    room_sets: Tuple[Item, ...] = ()
    students: Tuple[Item, ...] = ()
    changed: Optional[dt.datetime] = None
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "Event":
        """Parses one entry of the ``Events`` list; missing optional fields get their defaults."""
        return cls(
            id=ident(data.get("Id")),
            title=text(data.get("Title")),
            description=text(data.get("Description")),
            note=text(data.get("Note")),
            event_type=Item.optional(data.get("EventType")),
            times=tuple(EventTime.from_json(time) for time in objects(data.get("Times"))),
            classes=_items(data.get("Classes")),
            class_sets=_items(data.get("ClassSets")),
            teachers=_items(data.get("Teachers")),
            teacher_sets=_items(data.get("TeacherSets")),
            rooms=_items(data.get("Rooms")),
            room_sets=_items(data.get("RoomSets")),
            students=_items(data.get("Students")),
            changed=parse_datetime(data.get("DateChanged")),
            raw=dict(data),
        )

    @property
    def start(self) -> Optional[dt.datetime]:
        """The earliest start of the event's times, or ``None`` when it has none."""
        starts = [time.start for time in self.times if time.start is not None]
        return min(starts, key=_instant) if starts else None

    @property
    def end(self) -> Optional[dt.datetime]:
        """The latest end of the event's times, or ``None`` when it has none."""
        ends = [time.end for time in self.times if time.end is not None]
        return max(ends, key=_instant) if ends else None

    @property
    def whole_day(self) -> bool:
        """True when the event has times and every one of them is a whole-day entry."""
        return bool(self.times) and all(time.whole_day for time in self.times)

    @property
    def dates(self) -> Tuple[dt.date, ...]:
        """The calendar days the event takes place on, in order and without duplicates."""
        return tuple(sorted({time.date for time in self.times if time.date is not None}))


def parse_events(data: Any, *, validate: bool = True) -> List[Event]:
    """Parses an event list payload (``{"Events": [...]}``). With ``validate`` (default) a payload without the
    ``Events`` list of objects, or an event without its ``Times`` list, raises :class:`BakalariContractError`; without
    it, malformed entries are skipped. A payload that is not a JSON object always raises."""
    if not validate:
        return [Event.from_json(event) for event in objects(require_mapping(data, "event list").get("Events"))]
    payload = check_shape(data, "event list", lists=("Events",))
    problems = [
        f"Event {event.get('Id', index)!r}: {problem}"
        for index, event in enumerate(payload["Events"])
        for problem in shape_problems(event, "event", lists=("Times",))
    ]
    if problems:
        raise BakalariContractError(problems, "event list")
    return [Event.from_json(event) for event in payload["Events"]]


class EventsEndpoints(ClientCore):
    """Event endpoints of :class:`~bakalari.BakalariClient`."""

    def events(self, since: Optional[DateLike] = None, *, scope: str = "all", validate: bool = True) -> List[Event]:
        """``GET /api/3/events`` (``scope="all"``), ``GET /api/3/events/my`` (the user's own events) or
        ``GET /api/3/events/public``: the events from ``since`` on (``?from=YYYY-MM-DD``), or the events of the whole
        school year without it. Needs the Events module (right ShowEvents); the server answers an invalid date string
        with HTTP 400 (:class:`~bakalari.BakalariHTTPError`)."""
        if scope not in EVENT_SCOPES:
            raise ValueError(f"Unknown event scope {scope!r}: use 'all', 'my' or 'public'")
        path = api_path("events") if scope == "all" else api_path("events", scope)
        return parse_events(self.get_json(path, {"from": format_date(since)}), validate=validate)
