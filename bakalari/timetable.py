"""Timetable model of the Bakaláři REST API v3.

Every timetable endpoint (``/api/3/timetable/actual``, ``/api/3/timetable/permanent`` and their ``/class/{id}``
variants) returns the same shape: ``Hours`` (lesson slots with Caption, BeginTime and EndTime), ``Days``
(DayOfWeek, Date, DayType such as WorkDay, Holiday or Celebration, and ``Atoms``, the lessons, which reference
the other lists by id) and the lookup lists ``Classes``, ``Groups``, ``Subjects``, ``Teachers``, ``Rooms`` and
``Cycles``. In the actual timetable an atom carries a ``Change`` for substitutions, cancellations and events; such
an event can replace a lesson and then has no subject. Ids are opaque strings and may be space-padded (``" 2"``),
so they are used exactly as the server sends them.

This module validates that contract and resolves the atoms into readable :class:`Lesson` objects. Its
:class:`Change` model also describes the entries of the substitutions list (:mod:`bakalari.substitutions`).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, TypeVar, Union

from ._core import ClientCore, api_path
from ._parse import (
    DateLike,
    format_date,
    ident,
    objects,
    parse_date,
    quote_segment,
    strings,
    text,
    to_bool,
    to_date,
    to_int,
    week_of,
)
from .errors import TimetableContractError
from .models import Item, Model

LOOKUP_LISTS = ("Classes", "Groups", "Subjects", "Teachers", "Rooms", "Cycles")
REQUIRED_LISTS = ("Hours", "Days") + LOOKUP_LISTS
HOUR_FIELDS = ("Id", "Caption", "BeginTime", "EndTime")
DAY_FIELDS = ("DayOfWeek", "Date", "DayType", "Atoms")
SINGLE_REFERENCES = (("HourId", "Hours"), ("SubjectId", "Subjects"), ("TeacherId", "Teachers"), ("RoomId", "Rooms"))
MULTI_REFERENCES = (("GroupIds", "Groups"), ("CycleIds", "Cycles"))
CZECH_DAY_ABBREVIATIONS = ("po", "út", "st", "čt", "pá", "so", "ne")

TIMETABLE_KINDS = ("actual", "permanent")
# The known values of Days.DayType and Change.ChangeType; the server may add others.
DAY_TYPES = ("WorkDay", "Weekend", "Celebration", "Holiday", "DirectorDay", "Undefined")
CHANGE_TYPES = ("Canceled", "Added", "Removed", "RoomChanged", "Substitution", "Absence")

__all__ = [
    "CHANGE_TYPES",
    "DAY_TYPES",
    "Change",
    "ChangeLessonInfo",
    "Day",
    "DateLike",
    "Hour",
    "Item",
    "Lesson",
    "LessonHomework",
    "Timetable",
    "TimetableEndpoints",
    "contract_problems",
    "to_date",
    "validate_timetable",
    "week_of",
]

_T = TypeVar("_T")


@dataclass(frozen=True)
class Hour(Model):
    """A lesson slot: ``caption`` is the lesson number shown in the timetable (``"0"``, ``"1"``, ...), ``begin``
    and ``end`` the times as the server writes them (``"8:00"``); newer servers also send ``start`` (minutes
    after midnight) and ``duration`` (minutes)."""

    id: int
    caption: str
    begin: str
    end: str
    start: Optional[int] = None
    duration: Optional[int] = None

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "Hour":
        """Parses an entry of ``Hours`` (also used by the class book and the lesson details)."""
        return cls(
            id=_hour_id(data.get("Id")),
            caption=text(data.get("Caption")),
            begin=text(data.get("BeginTime")),
            end=text(data.get("EndTime")),
            start=to_int(data.get("Start")),
            duration=to_int(data.get("Duration")),
        )


@dataclass(frozen=True)
class ChangeLessonInfo(Model):
    """The lesson a change concerns, as the substitutions list names it: the class, group, subject and room
    abbreviations; ``is_class_group`` is true when the group is the whole class. ``str()`` joins the group (or
    class), subject and room, e.g. ``1.A Chl, M, 105``."""

    class_abbrev: str = ""
    group_abbrev: str = ""
    is_class_group: bool = False
    subject_abbrev: str = ""
    room_abbrev: str = ""

    def __str__(self) -> str:
        values = (self.group_abbrev or self.class_abbrev, self.subject_abbrev, self.room_abbrev)
        return ", ".join(value for value in values if value)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "ChangeLessonInfo":
        """Parses a ``ChangeLessonInfo`` object."""
        return cls(
            class_abbrev=text(data.get("ClassAbbrev")),
            group_abbrev=text(data.get("GroupAbbrev")),
            is_class_group=to_bool(data.get("IsClassGroup")),
            subject_abbrev=text(data.get("SubjectAbbrev")),
            room_abbrev=text(data.get("RoomAbbrev")),
        )

    @classmethod
    def optional(cls, data: Any) -> Optional["ChangeLessonInfo"]:
        """Parses a ``ChangeLessonInfo`` that may be ``null`` (the timetable always sends ``null``)."""
        return cls.from_json(data) if isinstance(data, Mapping) else None


@dataclass(frozen=True)
class Change(Model):
    """A change of the timetable: ``change_type`` is one of :data:`CHANGE_TYPES` (Absence, Canceled, Added,
    Removed, RoomChanged, Substitution), ``description`` the text shown in the timetable.

    ``day`` is the date, ``hours`` the lesson numbers (``"1. hod"``, ``"1. - 3. hod"``) and ``time`` their time
    range (``"8:00 - 8:45"``). The substitutions list also fills ``begin_time``, ``end_time`` (``"8:00"``) and
    often ``lesson_info``, while the timetable fills ``start`` (minutes after midnight) and ``duration``
    (minutes); unset values are empty or ``None``. ``display_type`` is ChangeDisplayType (OriginalTeacher,
    SubstituteTeacher) and ``atom_type`` AtomType (Hour).
    """

    change_type: str
    description: str
    type_name: str = ""
    type_abbrev: str = ""
    time: str = ""
    day: Optional[dt.date] = None
    hours: str = ""
    display_type: str = ""
    atom_type: str = ""
    change_subject: str = ""
    begin_time: str = ""
    end_time: str = ""
    lesson_info: Optional[ChangeLessonInfo] = None
    start: Optional[int] = None
    duration: Optional[int] = None
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "Change":
        """Parses the ``Change`` of a timetable atom or an entry of the substitutions list's ``Changes``."""
        return cls(
            change_type=text(data.get("ChangeType")),
            description=text(data.get("Description")),
            type_name=text(data.get("TypeName")),
            type_abbrev=text(data.get("TypeAbbrev")),
            time=text(data.get("Time")),
            day=parse_date(data.get("Day")),
            hours=text(data.get("Hours")),
            display_type=text(data.get("ChangeDisplayType")),
            atom_type=text(data.get("AtomType")),
            change_subject=_scalar_text(data.get("ChangeSubject")),
            begin_time=text(data.get("BeginTime")),
            end_time=text(data.get("EndTime")),
            lesson_info=ChangeLessonInfo.optional(data.get("ChangeLessonInfo")),
            # The substitutions list sends Start 0 and Duration 0 for "not set"; no lesson starts at midnight.
            start=to_int(data.get("Start")) or None,
            duration=to_int(data.get("Duration")) or None,
            raw=dict(data),
        )

    def format(self, *, with_date: bool = True) -> str:
        """One readable line: the day, the lesson hours and time, the change type with its description and the
        lesson concerned, e.g. ``2026-10-19 3. hod (10:00 - 10:45) Substitution: Suplování: ... | 1.A, M, 105``."""
        time = self.time or "-".join(value for value in (self.begin_time, self.end_time) if value)
        what = ": ".join(value for value in (self.change_type, self.description) if value)
        parts = [self.day.isoformat() if with_date and self.day else "", self.hours, f"({time})" if time else "", what]
        line = " ".join(part for part in parts if part)
        lesson = str(self.lesson_info) if self.lesson_info else ""
        return f"{line} | {lesson}" if lesson else line


def _abbrev(item: Optional[Item]) -> str:
    return item.abbrev if item else ""


def _name(item: Optional[Item]) -> str:
    return item.name if item else ""


@dataclass(frozen=True)
class LessonHomework(Model):
    """A homework attached to a lesson (``Homeworks`` of a timetable atom): its ``id`` and ``text``; the whole
    homework comes from the homeworks endpoint."""

    id: str
    text: str

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "LessonHomework":
        """Parses an entry of an atom's ``Homeworks``."""
        return cls(id=ident(data.get("Id")), text=text(data.get("Text")))


@dataclass(frozen=True)
class Lesson(Model):
    """One timetable atom with every id resolved. ``subject``, ``teacher`` and ``room`` are ``None`` for an
    event that replaces a lesson (e.g. a class teacher's hour), which only carries its ``change``.

    ``homeworks`` and ``homework_ids`` list the homeworks given in the lesson, ``notice`` is the lesson's note and
    ``week_theme`` the theme of the week, ``is_last_room_lesson`` marks the last lesson in the room that day, and
    ``start`` and ``duration`` are the minutes after midnight and the length (newer servers). ``raw`` is the
    server's atom, with the keys this model does not map (LessonRelease, Assistants, PlannedClasification).
    """

    date: dt.date
    day_of_week: int
    hour: Hour
    subject: Optional[Item]
    teacher: Optional[Item]
    room: Optional[Item]
    groups: Tuple[Item, ...] = ()
    cycles: Tuple[Item, ...] = ()
    theme: str = ""
    change: Optional[Change] = None
    homeworks: Tuple[LessonHomework, ...] = ()
    homework_ids: Tuple[str, ...] = ()
    notice: str = ""
    week_theme: str = ""
    is_last_room_lesson: bool = False
    start: Optional[int] = None
    duration: Optional[int] = None
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def changed(self) -> bool:
        """True when the lesson carries a change (substitution, cancellation, room change, event, ...)."""
        return self.change is not None

    @property
    def is_taught(self) -> bool:
        """True for a lesson with a subject, False for an event that replaces it."""
        return self.subject is not None

    @property
    def has_homework(self) -> bool:
        """True when a homework was given in the lesson."""
        return bool(self.homeworks or self.homework_ids)

    @property
    def title(self) -> str:
        """The subject name, or the change type name of an event without a subject."""
        if self.subject:
            return self.subject.name
        if self.change and self.change.type_name:
            return self.change.type_name
        return "-"

    def to_dict(self) -> Dict[str, Any]:
        """Flat, JSON-serialisable form; unset values are empty strings and ``homeworks`` joins the homework
        texts with ``"; "``."""
        return {
            "date": self.date.isoformat(),
            "day_of_week": self.day_of_week,
            "hour": self.hour.caption,
            "begin": self.hour.begin,
            "end": self.hour.end,
            "subject_abbrev": _abbrev(self.subject),
            "subject": _name(self.subject),
            "teacher_abbrev": _abbrev(self.teacher),
            "teacher": _name(self.teacher),
            "room": _abbrev(self.room),
            "room_name": _name(self.room),
            "groups": ", ".join(group.abbrev for group in self.groups),
            "cycles": ", ".join(cycle.abbrev for cycle in self.cycles),
            "theme": self.theme,
            "changed": self.changed,
            "change_type": self.change.change_type if self.change else "",
            "change_description": self.change.description if self.change else "",
            "notice": self.notice,
            "week_theme": self.week_theme,
            "homeworks": "; ".join(homework.text for homework in self.homeworks),
        }

    def format(self, *, with_date: bool = True) -> str:
        """One readable line: hour, time, subject, teacher, room, groups and the change, if any."""
        details = [_name(self.teacher), _abbrev(self.room), ", ".join(group.abbrev for group in self.groups)]
        line = f"{self.hour.caption:>2}. {self.hour.begin:>5}-{self.hour.end:<5} {self.title}"
        line += "".join(f" | {detail}" for detail in details if detail)
        if self.change:
            line += f" [{self.change.change_type}: {self.change.description}]"
        return f"{self.date.isoformat()} {line}" if with_date else line


@dataclass(frozen=True)
class Day(Model):
    """A timetable day; holidays and days outside the school year have no lessons. ``day_type`` is one of
    :data:`DAY_TYPES` and ``description`` names a holiday (e.g. "podzimní prázdniny")."""

    date: dt.date
    day_of_week: int
    day_type: str
    description: str = ""
    lessons: Tuple[Lesson, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def is_work_day(self) -> bool:
        """True for a regular school day (``WorkDay``)."""
        return self.day_type == "WorkDay"

    def format_summary(self) -> str:
        """One line: the date, the Czech weekday abbreviation, the day type, the description and the number of
        lessons."""
        description = f" ({self.description})" if self.description else ""
        weekday = CZECH_DAY_ABBREVIATIONS[self.date.weekday()]
        return f"{self.date.isoformat()} {weekday} {self.day_type}{description}: {len(self.lessons)} lesson(s)"

    def to_dict(self) -> Dict[str, Any]:
        """JSON-serialisable form with the lessons in their flat form (see :meth:`Lesson.to_dict`)."""
        return {
            "date": self.date.isoformat(),
            "day_of_week": self.day_of_week,
            "day_type": self.day_type,
            "description": self.description,
            "lessons": [lesson.to_dict() for lesson in self.lessons],
        }


@dataclass
class Timetable(Model):
    """A parsed actual or permanent timetable (``GET /api/3/timetable/actual``, ``/permanent`` or their
    ``/class/{id}`` variants). The lookup dictionaries are keyed by the raw server ids."""

    hours: Tuple[Hour, ...]
    days: Tuple[Day, ...]
    classes: Dict[str, Item]
    groups: Dict[str, Item]
    subjects: Dict[str, Item]
    teachers: Dict[str, Item]
    rooms: Dict[str, Item]
    cycles: Dict[str, Item]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any], *, validate: bool = True) -> "Timetable":
        """Parses a timetable payload. With ``validate`` (default) a contract violation raises
        :class:`TimetableContractError`; without it, unknown references resolve to ``None`` and entries that
        cannot be parsed (non-objects, a day without a valid date) are skipped."""
        if validate:
            validate_timetable(data)
        elif not isinstance(data, Mapping):
            raise TimetableContractError(["The timetable must be a JSON object"])
        hours = _index(data.get("Hours"), Hour.from_json)
        lookups = {name: _index(data.get(name), Item.from_json) for name in LOOKUP_LISTS}
        parsed = (_parse_day(day, hours, lookups) for day in objects(data.get("Days")))
        return cls(
            hours=tuple(hours.values()),
            days=tuple(day for day in parsed if day is not None),
            classes=lookups["Classes"],
            groups=lookups["Groups"],
            subjects=lookups["Subjects"],
            teachers=lookups["Teachers"],
            rooms=lookups["Rooms"],
            cycles=lookups["Cycles"],
            raw=dict(data),
        )

    @property
    def lessons(self) -> List[Lesson]:
        """Every lesson, in the order the server returns them (by day, then by hour)."""
        return [lesson for day in self.days for lesson in day.lessons]

    @property
    def taught_lessons(self) -> List[Lesson]:
        """The lessons with a subject (without the events that replace lessons)."""
        return [lesson for lesson in self.lessons if lesson.is_taught]

    @property
    def changed_lessons(self) -> List[Lesson]:
        """The lessons that carry a change."""
        return [lesson for lesson in self.lessons if lesson.changed]

    @property
    def dates(self) -> List[dt.date]:
        """The dates of the days, in the server's order."""
        return [day.date for day in self.days]

    def day(self, date: DateLike) -> Optional[Day]:
        """The day with the given date, or ``None`` when the timetable does not list it."""
        wanted = to_date(date)
        return next((day for day in self.days if day.date == wanted), None)

    def lessons_on(self, date: DateLike) -> List[Lesson]:
        """The lessons of one day (empty for a day the timetable does not list)."""
        day = self.day(date)
        return list(day.lessons) if day else []

    def covers_week_of(self, date: DateLike) -> bool:
        """True when the timetable lists at least one day and only days of the week that contains ``date``."""
        monday, sunday = week_of(date)
        return bool(self.days) and all(monday <= day.date <= sunday for day in self.days)

    def format(self) -> str:
        """Readable timetable: a summary line per day followed by its lessons."""
        lines: List[str] = []
        for day in self.days:
            lines.append(day.format_summary())
            lines.extend("    " + lesson.format(with_date=False) for lesson in day.lessons)
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """JSON-serialisable form: the days with their resolved lessons (see :meth:`Day.to_dict`)."""
        return {"days": [day.to_dict() for day in self.days]}


def _is_key(value: Any) -> bool:
    """False for JSON lists and objects, which are never ids and cannot be dictionary keys."""
    return not isinstance(value, (list, Mapping))


def _index(entries: Any, parse: Callable[[Mapping[str, Any]], _T]) -> Dict[Any, _T]:
    """A list of objects with an ``Id`` (Hours or a lookup list) keyed by the raw ids."""
    return {entry.get("Id"): parse(entry) for entry in objects(entries) if _is_key(entry.get("Id"))}


def _hour_id(value: Any) -> int:
    return to_int(value) or 0


def _scalar_text(value: Any) -> str:
    return "" if isinstance(value, (list, Mapping)) else text(value)


def _day_date(value: Any) -> Optional[dt.date]:
    """The calendar date of a day's ``Date`` (``2026-10-12T00:00:00+02:00``), or ``None`` when it is not one."""
    if not isinstance(value, (dt.date, str)):
        return None
    try:
        return to_date(value)
    except ValueError:
        return None


def _lookup(index: Mapping[Any, _T], key: Any) -> Optional[_T]:
    return index.get(key) if key is not None and _is_key(key) else None


def _resolve(index: Mapping[Any, Item], refs: Any) -> Tuple[Item, ...]:
    if not isinstance(refs, list):
        return ()
    return tuple(index[ref] for ref in refs if _is_key(ref) and ref in index)


def _parse_day(
    day: Mapping[str, Any], hours: Mapping[Any, Hour], lookups: Mapping[str, Mapping[Any, Item]]
) -> Optional[Day]:
    date = _day_date(day.get("Date"))
    if date is None:  # only without validation; a day that cannot be placed is skipped
        return None
    day_of_week = to_int(day.get("DayOfWeek")) or date.isoweekday()
    lessons = tuple(_parse_lesson(atom, date, day_of_week, hours, lookups) for atom in objects(day.get("Atoms")))
    return Day(
        date=date,
        day_of_week=day_of_week,
        day_type=text(day.get("DayType")),
        description=text(day.get("DayDescription")),
        lessons=lessons,
        raw=dict(day),
    )


def _parse_lesson(
    atom: Mapping[str, Any],
    date: dt.date,
    day_of_week: int,
    hours: Mapping[Any, Hour],
    lookups: Mapping[str, Mapping[Any, Item]],
) -> Lesson:
    hour_id = atom.get("HourId")
    change = atom.get("Change")
    return Lesson(
        date=date,
        day_of_week=day_of_week,
        hour=_lookup(hours, hour_id) or Hour(id=_hour_id(hour_id), caption="", begin="", end=""),
        subject=_lookup(lookups["Subjects"], atom.get("SubjectId")),
        teacher=_lookup(lookups["Teachers"], atom.get("TeacherId")),
        room=_lookup(lookups["Rooms"], atom.get("RoomId")),
        groups=_resolve(lookups["Groups"], atom.get("GroupIds")),
        cycles=_resolve(lookups["Cycles"], atom.get("CycleIds")),
        theme=text(atom.get("Theme")),
        change=Change.from_json(change) if isinstance(change, Mapping) and change else None,
        homeworks=tuple(LessonHomework.from_json(homework) for homework in objects(atom.get("Homeworks"))),
        homework_ids=strings(atom.get("HomeworkIds")),
        notice=text(atom.get("Notice")),
        week_theme=text(atom.get("WeekTheme")),
        is_last_room_lesson=to_bool(atom.get("IsLastRoomLesson")),
        start=to_int(atom.get("Start")),
        duration=to_int(atom.get("Duration")),
        raw=dict(atom),
    )


def _atom_shape_problems(atom: Mapping[str, Any]) -> List[str]:
    """The nested values of an atom that lenient parsing would drop: ``Change`` must be an object (or null),
    ``HomeworkIds`` and ``Homeworks`` lists (or null) and the homeworks objects. Values are not quoted, because
    they carry descriptions with names."""
    problems = []
    change = atom.get("Change")
    if change is not None and not isinstance(change, Mapping):
        problems.append("Change is not a JSON object")
    for name in ("HomeworkIds", "Homeworks"):
        value = atom.get(name)
        if value is not None and not isinstance(value, list):
            problems.append(f"{name} is not a list")
    homeworks = atom.get("Homeworks")
    if isinstance(homeworks, list) and not all(isinstance(homework, Mapping) for homework in homeworks):
        problems.append("a homework of Homeworks is not a JSON object")
    return problems


def contract_problems(data: Any) -> List[str]:
    """Lists every contract violation of a timetable payload (empty when it is valid): the required lists,
    at least one hour slot, the hour and day fields (including a valid day date), the shape of the nested
    values (the Atoms, GroupIds, CycleIds, HomeworkIds and Homeworks lists and a Change object), and that every
    atom references a defined hour slot and only defined subjects, teachers, rooms, groups and cycles."""
    if not isinstance(data, Mapping):
        return ["The timetable must be a JSON object"]
    problems = [f"Missing list '{name}'" for name in REQUIRED_LISTS if not isinstance(data.get(name), list)]
    if problems:
        return problems
    if not data["Hours"]:
        problems.append("No hour slots are defined")
    for hour in data["Hours"]:
        missing = [name for name in HOUR_FIELDS if not isinstance(hour, Mapping) or name not in hour]
        if missing:
            label = hour.get("Id") if isinstance(hour, Mapping) else hour
            problems.append(f"Hour slot {label!r} lacks {', '.join(missing)}")
    for day in data["Days"]:
        missing = [name for name in DAY_FIELDS if not isinstance(day, Mapping) or name not in day]
        if missing:
            label = day.get("Date") if isinstance(day, Mapping) else day
            problems.append(f"Day {label!r} lacks {', '.join(missing)}")
        if isinstance(day, Mapping) and "Date" in day and _day_date(day["Date"]) is None:
            problems.append(f"Day {day['Date']!r} has no valid Date")
    indexes = {
        name: {item.get("Id") for item in data[name] if isinstance(item, Mapping) and _is_key(item.get("Id"))}
        for name in ("Hours",) + LOOKUP_LISTS
    }
    for day in data["Days"]:
        if not isinstance(day, Mapping):
            continue
        label = str(day.get("Date", "?"))[:10]
        atoms = day.get("Atoms")
        if not isinstance(atoms, list):
            if atoms is not None:  # a missing Atoms list is reported above; null has always been accepted
                problems.append(f"{label}: Atoms is not a list")
            continue
        for atom in atoms:
            if not isinstance(atom, Mapping):
                problems.append(f"{label}: a lesson is not a JSON object")
                continue
            if atom.get("HourId") is None:
                problems.append(f"{label}: a lesson has no HourId")
            problems.extend(f"{label}: {problem}" for problem in _atom_shape_problems(atom))
            for field_name, table in SINGLE_REFERENCES:
                ref = atom.get(field_name)
                if ref is not None and not (_is_key(ref) and ref in indexes[table]):
                    problems.append(f"{label}: {field_name} {ref!r} is not defined in {table}")
            for field_name, table in MULTI_REFERENCES:
                refs = atom.get(field_name)
                if refs is not None and not isinstance(refs, list):
                    problems.append(f"{label}: {field_name} is not a list")
                    continue
                for ref in refs or []:
                    if not (_is_key(ref) and ref in indexes[table]):
                        problems.append(f"{label}: {field_name} entry {ref!r} is not defined in {table}")
    return problems


def validate_timetable(data: Any) -> None:
    """Raises :class:`TimetableContractError` listing every contract violation of a timetable payload."""
    problems = contract_problems(data)
    if problems:
        raise TimetableContractError(problems)


def _class_id(value: Any) -> str:
    if isinstance(value, Item):
        class_id = ident(value.id)
    elif isinstance(value, str) or value is None:
        class_id = ident(value)
    else:  # e.g. the whole profile instead of its school_class: never send an object's repr as the id
        raise TypeError(f"A class id must be a string or an Item, not {type(value).__name__}")
    if not class_id.strip():
        raise ValueError("A class timetable needs a class id or Item, e.g. the profile's school_class")
    return class_id


class TimetableEndpoints(ClientCore):
    """Timetable endpoints of :class:`~bakalari.BakalariClient`."""

    def timetable_json(
        self, kind: str = "actual", date: Optional[DateLike] = None, *, class_id: Optional[Union[str, Item]] = None
    ) -> Dict[str, Any]:
        """Raw timetable payload of ``GET /api/3/timetable/actual?date=`` or ``GET /api/3/timetable/permanent``.
        ``kind`` is ``actual`` (the Monday-Friday week that contains ``date``, default today, with this week's
        substitutions, cancellations and events) or ``permanent`` (the regular timetable with its week cycles;
        ``date`` does not apply). With ``class_id`` (an id or an :class:`~bakalari.models.Item`) it is the
        timetable of that whole class with all its groups, ``GET /api/3/timetable/{kind}/class/{id}``."""
        if kind not in TIMETABLE_KINDS:
            raise ValueError(f"Unknown timetable kind {kind!r}: use 'actual' or 'permanent'")
        segments = ["timetable", kind]
        if class_id is not None:
            segments += ["class", quote_segment(_class_id(class_id))]
        params = {"date": format_date(date)} if kind == "actual" else None
        data = self.get_json(api_path(*segments), params)
        if not isinstance(data, dict):
            raise TimetableContractError(["The timetable must be a JSON object"])
        return data

    def actual_timetable(self, date: Optional[DateLike] = None, *, validate: bool = True) -> Timetable:
        """``GET /api/3/timetable/actual?date=``: the actual timetable of the week that contains ``date`` (default
        today); a weekend date returns its own week, holidays come back as days without lessons."""
        return Timetable.from_json(self.timetable_json("actual", date), validate=validate)

    def permanent_timetable(self, *, validate: bool = True) -> Timetable:
        """``GET /api/3/timetable/permanent``: the permanent (regular) timetable; a lesson that runs only in some
        weeks lists its week cycles."""
        return Timetable.from_json(self.timetable_json("permanent"), validate=validate)

    def class_timetable(
        self,
        class_id: Union[str, Item],
        date: Optional[DateLike] = None,
        *,
        permanent: bool = False,
        validate: bool = True,
    ) -> Timetable:
        """``GET /api/3/timetable/actual/class/{id}?date=``, or ``GET /api/3/timetable/permanent/class/{id}``
        with ``permanent`` (``date`` does not apply then): the timetable of a whole class with the lessons of all
        its groups, in the shape of :meth:`actual_timetable`. ``class_id`` is a class id or an
        :class:`~bakalari.models.Item` such as the profile's ``school_class`` (an empty id raises ``ValueError``,
        another type ``TypeError``); an id with a backslash cannot be addressed (IIS answers HTTP 404 for ``%5C``
        in a path)."""
        kind = "permanent" if permanent else "actual"
        data = self.timetable_json(kind, date, class_id=_class_id(class_id))
        return Timetable.from_json(data, validate=validate)
