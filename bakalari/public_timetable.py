"""The public timetable web pages (no login): the classes, teachers and rooms a school publishes, and their timetables.

These are HTML pages of the web application, not REST endpoints. ``/Timetable/Public`` lists the targets as
``<select id="selectedClass|selectedTeacher|selectedRoom">`` options, as off-canvas links (``<div id="class_canvas">``
... ``<a href=".../timetable/public/Actual/class/<id>">``) or both; target ids are opaque and may contain spaces
(``"U  19"``). ``/Timetable/Public/{Actual|Permanent|Next}/{Class|Teacher|Room}/{id}`` shows one timetable: newer
servers embed it as the JSON object ``const timetableData = {...};`` that the browser renders, older ones render it
on the server with a JSON ``data-detail`` attribute on every lesson cell. Both are parsed with the standard library's
:mod:`html.parser`. A school that does not publish a timetable redirects to an error page
(``next/errinfo.aspx?e=K+po%c5%beadovan%c3%a9+str%c3%a1nce+nem%c3%a1te+p%c5%99%c3%adstup.``) or to the login page;
the endpoint methods raise :class:`~bakalari.BakalariPermissionError` then.

The pages show dates without the year (``12.10.``); a :class:`PublicDay` has a ``date`` only when the page
determines it (newer servers name the full date in the lessons and supervision entries), never by guessing.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import urllib.parse
from dataclasses import dataclass, field, replace
from html import unescape as html_unescape
from html.parser import HTMLParser
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from ._core import ClientCore
from ._parse import (
    check_shape,
    html_to_text,
    mapping,
    objects,
    parse_date,
    quote_segment,
    require_mapping,
    text,
    to_bool,
    to_date,
    to_int,
)
from .errors import BakalariContractError, BakalariHTTPError, BakalariPermissionError
from .http import HttpResponse
from .models import Model
from .timetable import CZECH_DAY_ABBREVIATIONS, Hour

__all__ = [
    "PUBLIC_KINDS",
    "PUBLIC_TIMETABLE_PATH",
    "PUBLIC_WEEKS",
    "PublicDay",
    "PublicLesson",
    "PublicTarget",
    "PublicTargets",
    "PublicTimetable",
    "PublicTimetableEndpoints",
    "parse_public_targets",
    "parse_public_timetable",
    "public_timetable_path",
]

PUBLIC_TIMETABLE_PATH = "/Timetable/Public"
PUBLIC_KINDS = ("class", "teacher", "room")
PUBLIC_WEEKS = ("actual", "permanent", "next")
NOT_PUBLISHED = "The school does not publish this public timetable."
LOGIN_REQUIRED = "The public timetable requires a login."

_REDIRECT_STATUSES = (301, 302, 303, 307, 308)
_SELECT_IDS = {"selectedClass": "class", "selectedTeacher": "teacher", "selectedRoom": "room"}
_CANVAS_IDS = {"class_canvas": "class", "teacher_canvas": "teacher", "room_canvas": "room"}
_VOID_TAGS = frozenset("area base br col embed hr img input link meta param source track wbr".split())
_BREAK = "\x00"  # stands for a <br> in collected text, which separates e.g. the groups of a lesson cell
# Parts of a server-rendered lesson cell, by CSS class (the first match wins; badges are left out of the text).
_CELL_PARTS = (
    ("change-badge", ""), ("released-badge", ""), ("cycle", "cycle"), ("teacher-name", "teacher"),
    ("middle", "subject"), ("first", "room"), ("left", "group"), ("bottom", "bottom"),
)
_DATA_ASSIGNMENT = re.compile(r"\btimetableData\s*=\s*")
_FULL_DATE = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})")
_DAY_MONTH = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.")
_CLOCK = re.compile(r"(\d{1,2}):(\d{2})")
# "1 (8:00 - 8:45)" or "8:00 - 8:45"; a lesson number is always followed by the parenthesised times.
_CAPTION_TIME = re.compile(r"^\s*(?:([^\s(]+)\s*\(\s*)?(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})")
_JS_ESCAPE = re.compile(r"\\(u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)", re.S)


def _choice(value: str, allowed: Sequence[str], what: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in allowed:
        raise ValueError(f"Unknown {what} {value!r}: use one of {', '.join(allowed)}")
    return normalized


def _target_id(target: Union[str, "PublicTarget"]) -> str:
    """The id of a target given as its id or as a :class:`PublicTarget` (whose ``str()`` is its name, not its id)."""
    return target.id if isinstance(target, PublicTarget) else target


def public_timetable_path(kind: str, target_id: Union[str, "PublicTarget"], *, week: str = "actual") -> str:
    """The path of a public timetable page, e.g. ``/Timetable/Public/Actual/Teacher/U%20%2019``: ``kind`` is
    ``class``, ``teacher`` or ``room``, ``week`` is ``actual``, ``permanent`` or ``next`` (both case-insensitive)
    and ``target_id`` (an id or a :class:`PublicTarget`) is percent-encoded exactly as given."""
    kind_name = _choice(kind, PUBLIC_KINDS, "public timetable kind").capitalize()
    week_name = _choice(week, PUBLIC_WEEKS, "public timetable week").capitalize()
    target_id = _target_id(target_id)
    if target_id is None or not str(target_id).strip():
        raise ValueError("A public timetable needs the id of a class, teacher or room")
    return f"{PUBLIC_TIMETABLE_PATH}/{week_name}/{kind_name}/{quote_segment(target_id)}"


# --- Models ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PublicTarget(Model):
    """A class, teacher or room whose timetable the school publishes: ``kind`` is ``class``, ``teacher`` or
    ``room``, ``id`` exactly what the page lists (it may contain spaces, e.g. ``"U  19"``), ``name`` the label."""

    kind: str
    id: str
    name: str = ""

    def __str__(self) -> str:
        return self.name or self.id


@dataclass(frozen=True)
class PublicTargets(Model):
    """The targets of the public timetable, in the order of the page."""

    classes: Tuple[PublicTarget, ...] = ()
    teachers: Tuple[PublicTarget, ...] = ()
    rooms: Tuple[PublicTarget, ...] = ()

    @property
    def all_targets(self) -> List[PublicTarget]:
        """The classes, then the teachers, then the rooms."""
        return [*self.classes, *self.teachers, *self.rooms]

    def of_kind(self, kind: str) -> Tuple[PublicTarget, ...]:
        """The targets of one kind: ``class``, ``teacher`` or ``room``."""
        kind = _choice(kind, PUBLIC_KINDS, "public timetable kind")
        return {"class": self.classes, "teacher": self.teachers, "room": self.rooms}[kind]

    def find(self, key: str, kind: Optional[str] = None) -> Optional[PublicTarget]:
        """The target (of ``kind``, when given) whose id is ``key`` exactly, else the first whose name or id
        equals ``key`` ignoring case and spaces; ``None`` when there is none."""
        candidates = self.of_kind(kind) if kind else self.all_targets
        exact = next((target for target in candidates if target.id == key), None)
        if exact is not None:
            return exact
        wanted = "".join(str(key).split()).casefold()
        return next(
            (
                target
                for target in candidates
                if wanted in ("".join(target.name.split()).casefold(), "".join(target.id.split()).casefold())
            ),
            None,
        )


@dataclass(frozen=True)
class PublicLesson(Model):
    """A lesson of a public timetable.

    ``hour_index`` is the server's number of the lesson slot (``HourIndex``, the hour id of the REST timetable;
    ``None`` when the page does not say) and ``hour_caption`` the lesson number shown in the timetable (``"1"``);
    ``begin`` and ``end`` are times such as ``"8:00"``. ``subject``, ``teacher`` and ``room_name`` are full names,
    ``subject_abbrev``, ``teacher_abbrev`` and ``room`` abbreviations, ``group`` the group abbreviations and
    ``group_name`` their full names (several groups are joined with ``, ``). ``change_info`` describes a change
    (substitution, room change, removal) and ``change_type`` names it as the server does (Substitution, RoomChanged,
    Added, ...; Removed for a lesson taken out of the timetable, whose ``atom_type`` is ``removed``). ``absent_info``
    tells about an absence, ``cycle`` the week cycle of a lesson of the permanent timetable that runs only in some
    weeks.
    """

    hour_index: Optional[int] = None
    begin: str = ""
    end: str = ""
    subject: str = ""
    subject_abbrev: str = ""
    teacher: str = ""
    teacher_abbrev: str = ""
    room: str = ""
    room_name: str = ""
    group: str = ""
    theme: str = ""
    notice: str = ""
    change_info: str = ""
    changed: bool = False
    absent_info: str = ""
    hour_caption: str = ""
    group_name: str = ""
    change_type: str = ""
    cycle: str = ""
    atom_type: str = "atom"
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any], slot: Optional[Mapping[str, Any]] = None) -> "PublicLesson":
        """Parses an atom of ``timetableData`` (``Days[].Hours[].Atoms[]``) with its ``TooltipDetails`` JSON string;
        ``slot`` is the enclosing entry of ``Days[].Hours``, which supplies the slot number and the times when the
        atom lacks them (a removed lesson has ``HourIndex`` 0)."""
        slot = slot or {}
        tooltip = _json_object(data.get("TooltipDetails"))
        atom_type = _first_text(data.get("Type"), tooltip.get("type")) or "atom"
        removed = atom_type == "removed"
        times = _time_range(data.get("Time")) or _time_range(tooltip.get("time"))
        change_code = text(tooltip.get("infoChangeCode"))
        return cls(
            hour_index=to_int(data.get("HourIndex")) or to_int(slot.get("Index")) or None,
            begin=_clock(data.get("Begin")) or (times[0] if times else "") or _clock(slot.get("Begin")),
            end=_clock(data.get("End")) or (times[1] if times else "") or _clock(slot.get("End")),
            subject=_first_text(data.get("SubjectText"), tooltip.get("subjecttext"), data.get("SubjectName")),
            subject_abbrev=text(data.get("SubjectAbbrev")),
            teacher=_first_text(data.get("TeacherFullname"), tooltip.get("teacher")),
            teacher_abbrev=text(data.get("Teacher")),
            room=text(data.get("Room")),
            room_name=_first_text(data.get("RoomFullName"), tooltip.get("room")),
            group=_markup_text(data.get("GroupsNames")),
            theme=_first_text(data.get("Theme"), tooltip.get("theme")),
            notice=_first_text(data.get("Notice"), tooltip.get("notice")),
            change_info=_first_text(data.get("ChangeInfo"), tooltip.get("changeinfo"), tooltip.get("removedinfo")),
            changed=to_bool(data.get("HasChanged")) or removed,
            absent_info=_first_text(
                tooltip.get("absentInfoText"), data.get("AbsentInfo"), tooltip.get("absentinfo"),
                data.get("AtomAbsenceText"),
            ),
            hour_caption=_caption(tooltip.get("time")),
            group_name=_markup_text(data.get("GroupsFullNames")) or _first_text(tooltip.get("group")),
            change_type="Removed" if removed else ("" if change_code in ("", "NoChange") else change_code),
            cycle=text(data.get("CycleText")),
            atom_type=atom_type,
            raw=dict(data),
        )

    @property
    def removed(self) -> bool:
        """True for a lesson taken out of the timetable (shown crossed out)."""
        return self.atom_type == "removed"

    @property
    def title(self) -> str:
        """The subject name, else its abbreviation, else the change description (of a removed lesson)."""
        return self.subject or self.subject_abbrev or self.change_info or "-"

    def format(self) -> str:
        """One readable line: lesson number, time, subject, teacher, room, group and the change, if any."""
        line = f"{self.hour_caption:>2}. {self.begin:>5}-{self.end:<5} {self.title}"
        line += "".join(f" | {detail}" for detail in (self.teacher, self.room, self.group) if detail)
        if self.changed and self.change_info and self.change_info != self.title:
            line += f" [{self.change_info}]"
        return line


@dataclass(frozen=True)
class PublicDay(Model):
    """A day of a public timetable. ``day_abbrev`` is the Czech weekday abbreviation (``po`` ... ``ne``),
    ``date_text`` the date as the page shows it (``"12.10."``; empty in the permanent timetable) and ``date`` the
    calendar date when the page determines its year, else ``None``. ``day_off``/``day_off_name`` mark a day
    without teaching (a holiday)."""

    day_abbrev: str
    date_text: str = ""
    date: Optional[dt.date] = None
    day_off: bool = False
    day_off_name: str = ""
    lessons: Tuple[PublicLesson, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def day_of_week(self) -> Optional[int]:
        """1 for Monday to 7 for Sunday, from the abbreviation (or the date); ``None`` when unknown."""
        abbrev = self.day_abbrev.lower()
        if abbrev in CZECH_DAY_ABBREVIATIONS:
            return CZECH_DAY_ABBREVIATIONS.index(abbrev) + 1
        return self.date.isoweekday() if self.date else None

    def format_summary(self) -> str:
        """``po 12.10. (2026-10-12): 6 lesson(s)``, or the name of a day off."""
        label = " ".join(part for part in (self.day_abbrev, self.date_text) if part)
        if self.date:
            label += f" ({self.date.isoformat()})"
        if self.day_off:
            return f"{label}: day off" + (f" ({self.day_off_name})" if self.day_off_name else "")
        return f"{label}: {len(self.lessons)} lesson(s)"


@dataclass(frozen=True)
class PublicTimetable(Model):
    """A public timetable: ``kind`` (``class``, ``teacher`` or ``room``), ``target_id`` and ``week`` (``actual``,
    ``permanent`` or ``next``) as requested, the hour slots and the days. The ``Hour`` slots have the server's hour
    numbers as ids where a lesson reveals them; the other slots continue that numbering, and without any such lesson
    the ids are just positions counted from 0. ``raw`` holds the embedded ``timetableData`` object (empty for a
    server-rendered page)."""

    kind: str = ""
    target_id: str = ""
    week: str = ""
    hours: Tuple[Hour, ...] = ()
    days: Tuple[PublicDay, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(
        cls, data: Any, *, kind: str = "", target_id: str = "", week: str = "", validate: bool = True
    ) -> "PublicTimetable":
        """Parses the ``timetableData`` object a newer server embeds in the page. With ``validate`` (default) it
        must hold the lists ``Hours`` and ``Days`` of objects (else :class:`~bakalari.BakalariContractError`); a
        day's ``Hours`` may be ``null`` (no lessons)."""
        if validate:
            payload = check_shape(data, "public timetable", lists=("Hours", "Days"))
        else:
            payload = require_mapping(data, "public timetable")
        day_objects = objects(payload.get("Days"))
        known: Dict[int, int] = {}
        for day in day_objects:
            for slot in objects(day.get("Hours")):
                _remember_index(known, slot.get("Begin"), slot.get("Index"))
                for atom in objects(slot.get("Atoms")):
                    _remember_index(known, atom.get("Begin"), atom.get("HourIndex"))
        hours = _hour_slots(
            [(text(hour.get("Caption")), text(hour.get("BeginTime")), text(hour.get("EndTime")))
             for hour in objects(payload.get("Hours"))],
            known,
        )
        days = [
            PublicDay(
                day_abbrev=text(day.get("DayAbbrev")),
                date_text=text(day.get("Date")),
                day_off=to_bool(day.get("DayOff")),
                day_off_name=text(day.get("DayOffName")),
                lessons=_arranged(
                    [PublicLesson.from_json(atom, slot) for slot in objects(day.get("Hours"))
                     for atom in objects(slot.get("Atoms"))],
                    hours,
                ),
                raw=dict(day),
            )
            for day in day_objects
        ]
        dates = _resolve_dates(
            [(day.day_abbrev, day.date_text, _page_dates(source)) for day, source in zip(days, day_objects)]
        )
        return cls(
            kind=kind,
            target_id=target_id,
            week=week,
            hours=tuple(hours),
            days=tuple(replace(day, date=date) for day, date in zip(days, dates)),
            raw=dict(payload),
        )

    @property
    def lessons(self) -> List[PublicLesson]:
        """Every lesson, day by day in the order of their times."""
        return [lesson for day in self.days for lesson in day.lessons]

    @property
    def changed_lessons(self) -> List[PublicLesson]:
        """The substituted, moved, added and removed lessons."""
        return [lesson for lesson in self.lessons if lesson.changed]

    def day(self, key: Union[str, dt.date]) -> Optional[PublicDay]:
        """The day with the abbreviation ``key`` (``po`` ... ``ne``) or the date ``key`` (a date or an ISO string;
        only days whose date is known match), or ``None``."""
        if isinstance(key, str) and key.strip().lower() in CZECH_DAY_ABBREVIATIONS:
            wanted = key.strip().lower()
            return next((day for day in self.days if day.day_abbrev.lower() == wanted), None)
        date = to_date(key)
        return next((day for day in self.days if day.date == date), None)

    def hour_of(self, lesson: PublicLesson) -> Optional[Hour]:
        """The hour slot of a lesson (by its lesson number, else by its begin time), or ``None``."""
        if lesson.hour_caption:
            found = next((hour for hour in self.hours if hour.caption == lesson.hour_caption), None)
            if found is not None:
                return found
        begin = _minutes(lesson.begin)
        return next((hour for hour in self.hours if begin is not None and _minutes(hour.begin) == begin), None)

    def format(self) -> str:
        """Readable timetable: a summary line per day followed by its lessons."""
        lines: List[str] = []
        for day in self.days:
            lines.append(day.format_summary())
            lines.extend("    " + lesson.format() for lesson in day.lessons)
        return "\n".join(lines)


# --- Value helpers ---------------------------------------------------------------------------------------------


def _json_object(value: Any) -> Mapping[str, Any]:
    """A JSON object given as an object or as a JSON string (``TooltipDetails``, ``data-detail``); else empty."""
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return mapping(json.loads(value))
        except ValueError:
            return {}
    return {}


def _first_text(*values: Any) -> str:
    """The first non-empty display string among the values (objects, lists and booleans are skipped)."""
    for value in values:
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            found = text(value)
            if found:
                return found
    return ""


def _markup_text(value: Any) -> str:
    """A display string the page renders as HTML: ``GroupsNames`` and ``GroupsFullNames`` put a ``<br/>`` between
    groups (``Z8.C Sk89<br/>Z9.C Sk89``), which becomes ``, `` (as in the tooltip); other markup is dropped."""
    if not isinstance(value, str) or not ("<" in value or "&" in value):
        return _first_text(value)
    return ", ".join(line for line in html_to_text(value).split("\n") if line)


def _minutes(value: Any) -> Optional[int]:
    """Minutes after midnight of ``"8:00"`` or ``"08:00:00"``."""
    match = _CLOCK.search(value) if isinstance(value, str) else None
    return int(match.group(1)) * 60 + int(match.group(2)) if match else None


def _clock(value: Any) -> str:
    """A time as ``"8:00"`` (the format of the hour slots) from ``"08:00:00"`` or ``"8:00"``; else ``""``."""
    minutes = _minutes(value)
    return "" if minutes is None else f"{minutes // 60}:{minutes % 60:02d}"


def _time_range(value: Any) -> Optional[Tuple[str, str]]:
    """``("8:00", "8:45")`` from ``"8:00 - 8:45"`` or ``"1 (8:00 - 8:45)"``."""
    match = _CAPTION_TIME.search(value) if isinstance(value, str) else None
    return (_clock(match.group(2)), _clock(match.group(3))) if match else None


def _caption(value: Any) -> str:
    """The lesson number of ``"1 (8:00 - 8:45)"``; ``""`` for a time without it."""
    match = _CAPTION_TIME.search(value) if isinstance(value, str) else None
    return match.group(1) if match and match.group(1) else ""


def _remember_index(known: Dict[int, int], begin: Any, index: Any) -> None:
    minutes, number = _minutes(begin), to_int(index)
    if minutes is not None and number:
        known.setdefault(minutes, number)


def _hour_slots(slots: Sequence[Tuple[str, str, str]], known: Mapping[int, int]) -> List[Hour]:
    """Hour slots from ``(caption, begin, end)``. The page gives them no ids: a slot gets the server's hour number
    of a lesson that begins at its time, the others continue the numbering of the nearest such slot (the server's
    numbering may skip hidden hours) or count from 0 without any."""
    numbers: Dict[int, int] = {}
    for position, (_, begin, _) in enumerate(slots):
        minutes = _minutes(begin)
        if minutes is not None and minutes in known:
            numbers[position] = known[minutes]

    def number(position: int) -> int:
        if position in numbers or not numbers:
            return numbers.get(position, position)
        nearest = min(numbers, key=lambda other: (abs(other - position), other))
        return numbers[nearest] + position - nearest

    return [
        Hour(id=number(position), caption=caption, begin=begin, end=end)
        for position, (caption, begin, end) in enumerate(slots)
    ]


def _arranged(lessons: Sequence[PublicLesson], hours: Sequence[Hour]) -> Tuple[PublicLesson, ...]:
    """The lessons ordered by their begin time (the page lists them in no particular order), with the lesson number
    of a lesson that lacks it taken from the hour slot that begins at its time."""
    by_begin: Dict[int, str] = {}
    for hour in hours:
        minutes = _minutes(hour.begin)
        if minutes is not None and hour.caption:
            by_begin.setdefault(minutes, hour.caption)
    completed: List[PublicLesson] = []
    for lesson in lessons:
        minutes = _minutes(lesson.begin)
        if not lesson.hour_caption and minutes is not None and minutes in by_begin:
            lesson = replace(lesson, hour_caption=by_begin[minutes])
        completed.append(lesson)

    def position(index: int) -> Tuple[int, int]:
        minutes = _minutes(completed[index].begin)
        return (24 * 60 if minutes is None else minutes, index)

    return tuple(completed[index] for index in sorted(range(len(completed)), key=position))


def _full_dates(values: Iterable[Any]) -> List[dt.date]:
    """The calendar dates written in the values as ``12.10.2026`` or as ISO timestamps."""
    found: List[dt.date] = []
    for value in values:
        if not isinstance(value, str):
            continue
        match = _FULL_DATE.search(value)
        if match:
            try:
                found.append(dt.date(int(match.group(3)), int(match.group(2)), int(match.group(1))))
            except ValueError:
                pass
            continue
        iso = parse_date(value) if re.match(r"\s*\d{4}-\d{2}-\d{2}", value) else None
        if iso:
            found.append(iso)
    return found


def _page_dates(day: Mapping[str, Any]) -> List[dt.date]:
    """The full dates a ``timetableData`` day mentions in its lessons, supervisions and absences."""
    values: List[Any] = []
    for slot in objects(day.get("Hours")):
        for atom in objects(slot.get("Atoms")):
            values += [atom.get("Day"), _json_object(atom.get("TooltipDetails")).get("day")]
    for key in ("PauseGuards", "HourGuards", "GeneralGuards", "Absences"):
        for entry in objects(day.get(key)):
            values += [mapping(entry.get("Day")).get("Date"), _json_object(entry.get("TooltipDetails")).get("day")]
    return _full_dates(values)


def _weekday_matches(abbrev: str, date: dt.date) -> bool:
    abbrev = abbrev.strip().lower()
    return abbrev not in CZECH_DAY_ABBREVIATIONS or CZECH_DAY_ABBREVIATIONS.index(abbrev) == date.weekday()


def _resolve_dates(days: Sequence[Tuple[str, str, Sequence[dt.date]]]) -> List[Optional[dt.date]]:
    """The calendar date of each ``(day_abbrev, date_text, full dates on the page)``: a full date with the day's day
    and month, else (for a day without one, e.g. a holiday) the only date with its day and month within a week of
    another day's date. ``None`` when the page does not determine it or the weekday contradicts it."""
    day_months: List[Optional[Tuple[int, int]]] = []
    for _, date_text, _ in days:
        match = _DAY_MONTH.search(date_text)
        day_months.append((int(match.group(1)), int(match.group(2))) if match else None)
    dates: List[Optional[dt.date]] = []
    for (abbrev, _, candidates), day_month in zip(days, day_months):
        date = next((found for found in candidates if (found.day, found.month) == day_month), None)
        dates.append(date if date is not None and _weekday_matches(abbrev, date) else None)
    anchor = next((date for date in dates if date is not None), None)
    for position, ((abbrev, _, _), day_month) in enumerate(zip(days, day_months)):
        if dates[position] is not None or day_month is None or anchor is None:
            continue
        nearby = []
        for year in (anchor.year - 1, anchor.year, anchor.year + 1):
            try:
                candidate = dt.date(year, day_month[1], day_month[0])
            except ValueError:
                continue
            if abs((candidate - anchor).days) <= 7 and _weekday_matches(abbrev, candidate):
                nearby.append(candidate)
        dates[position] = nearby[0] if len(nearby) == 1 else None
    return dates


# --- HTML parsing ----------------------------------------------------------------------------------------------


@dataclass
class _Cell:
    """A server-rendered lesson cell: its ``data-detail`` JSON, CSS classes and visible texts."""

    detail: str
    classes: Tuple[str, ...]
    parts: Dict[str, str] = field(default_factory=dict)


@dataclass
class _Row:
    """A server-rendered timetable row (one day)."""

    day: str = ""
    date: str = ""
    day_off: bool = False
    day_off_name: str = ""
    cells: List[_Cell] = field(default_factory=list)


class _PageParser(HTMLParser):
    """Collects in one pass what this module needs from a public timetable page: the target lists, the scripts
    (with ``timetableData``), server-rendered timetable rows and the signs of an error or login page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.options: Dict[str, List[List[Optional[str]]]] = {kind: [] for kind in PUBLIC_KINDS}
        self.links: Dict[str, List[List[Optional[str]]]] = {kind: [] for kind in PUBLIC_KINDS}
        self.has_target_lists = False
        self.scripts: List[str] = []
        self.form_actions: List[str] = []
        self.error_texts: List[str] = []
        self.has_password_input = False
        self.week = ""
        self.rows: List[_Row] = []
        self._stack: List[Tuple[str, Optional[Callable[[], None]]]] = []
        self._sinks: List[List[str]] = []
        self._select: Optional[str] = None
        self._canvas: Optional[str] = None
        self._row: Optional[_Row] = None
        self._cell: Optional[_Cell] = None

    # Element bookkeeping: every open element may register a callback that runs when it ends (or is implicitly
    # closed by the end of an enclosing element); text goes to the innermost collecting element.

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag == "br" and self._sinks:
            self._sinks[-1].append(_BREAK)
        on_end = self._start(tag, {name: value or "" for name, value in attrs})
        if tag in _VOID_TAGS:
            if on_end is not None:
                on_end()
        else:
            self._stack.append((tag, on_end))

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID_TAGS or all(open_tag != tag for open_tag, _ in self._stack):
            return
        while self._stack:
            open_tag, on_end = self._stack.pop()
            if on_end is not None:
                on_end()
            if open_tag == tag:
                break

    def handle_data(self, data: str) -> None:
        if self._sinks:
            self._sinks[-1].append(data.replace(_BREAK, ""))

    def close(self) -> None:
        super().close()
        while self._stack:
            _, on_end = self._stack.pop()
            if on_end is not None:
                on_end()

    def _collect(self, store: Callable[[str], None], *, raw: bool = False) -> Callable[[], None]:
        sink: List[str] = []
        self._sinks.append(sink)

        def finish() -> None:
            self._sinks[:] = [open_sink for open_sink in self._sinks if open_sink is not sink]
            collected = "".join(sink)
            lines = (" ".join(line.split()) for line in collected.split(_BREAK))
            store(collected if raw else ", ".join(line for line in lines if line))

        return finish

    def _start(self, tag: str, attrs: Dict[str, str]) -> Optional[Callable[[], None]]:
        classes = tuple(attrs.get("class", "").split())
        if tag == "script":
            return self._collect(self.scripts.append, raw=True)
        if tag == "form":
            self.form_actions.append(attrs.get("action", ""))
        elif tag == "input":
            self._input(attrs)
        elif tag == "select" and attrs.get("id") in _SELECT_IDS:
            return self._open_list("_select", _SELECT_IDS[attrs["id"]])
        elif tag == "option" and self._select:
            return self._entry(self.options[self._select], attrs.get("value") if "value" in attrs else None)
        elif tag == "div" and attrs.get("id") in _CANVAS_IDS:
            return self._open_list("_canvas", _CANVAS_IDS[attrs["id"]])
        elif tag == "a" and self._canvas:
            return self._entry(self.links[self._canvas], attrs.get("href", ""))
        elif "chyba" in classes:
            return self._collect(self.error_texts.append)
        elif "bk-timetable-row" in classes:
            return self._open_row()
        elif self._row is not None:
            return self._row_part(self._row, classes, attrs)
        return None

    def _input(self, attrs: Dict[str, str]) -> None:
        kind = attrs.get("type", "").lower()
        if kind == "password":
            self.has_password_input = True
        elif kind == "radio" and "checked" in attrs and attrs.get("value", "").lower() in PUBLIC_WEEKS:
            self.week = attrs["value"].lower()

    def _open_list(self, slot: str, kind: str) -> Callable[[], None]:
        self.has_target_lists = True
        previous = getattr(self, slot)
        setattr(self, slot, kind)
        return lambda: setattr(self, slot, previous)

    def _entry(self, entries: List[List[Optional[str]]], value: Optional[str]) -> Callable[[], None]:
        entry: List[Optional[str]] = [value, ""]
        entries.append(entry)  # in document order even when an option's end tag is missing

        def store(label: str) -> None:
            entry[1] = label

        return self._collect(store)

    def _open_row(self) -> Callable[[], None]:
        row, previous = _Row(), self._row
        self.rows.append(row)
        self._row = row

        def finish() -> None:
            self._row = previous

        return finish

    def _row_part(self, row: _Row, classes: Tuple[str, ...], attrs: Dict[str, str]) -> Optional[Callable[[], None]]:
        for css, name in (("bk-day-day", "day"), ("bk-day-date", "date"), ("dayoff-name", "day_off_name")):
            if css in classes:
                return self._collect(_setter(row, name))
        if "day-item-volno" in classes:
            row.day_off = True
            return None
        if "day-item-hover" in classes and "data-detail" in attrs:
            cell, previous = _Cell(attrs["data-detail"], classes), self._cell
            row.cells.append(cell)
            self._cell = cell

            def finish() -> None:
                self._cell = previous

            return finish
        part = next((name for css, name in _CELL_PARTS if css in classes), None)
        if self._cell is None or part is None:
            return None
        parts = self._cell.parts

        def store(value: str) -> None:
            if part:  # badges ("" part) are left out of the texts
                parts.setdefault(part, value)

        return self._collect(store)

    # Results.

    def timetable_data(self) -> Optional[Mapping[str, Any]]:
        """The ``timetableData`` object assigned in a script, or ``None``."""
        decoder = json.JSONDecoder()
        for script in self.scripts:
            for match in _DATA_ASSIGNMENT.finditer(script):
                try:
                    data, _ = decoder.raw_decode(script, match.end())
                except ValueError:
                    continue
                if isinstance(data, Mapping):
                    return data
        return None

    def script_constant(self, name: str) -> str:
        """The string a script assigns to ``name`` (``const objectId = 'G0';``), or ``""``."""
        pattern = re.compile(r"\b" + re.escape(name) + r"""\s*=\s*(?:'((?:[^'\\\n]|\\.)*)'|"((?:[^"\\\n]|\\.)*)")""")
        for script in self.scripts:
            match = pattern.search(script)
            if match:
                value = match.group(1) if match.group(1) is not None else match.group(2)
                return _JS_ESCAPE.sub(_js_unescape, value)
        return ""

    def refusal(self) -> Optional[str]:
        """The reason when the page is the error page of a refused request or the login page, else ``None``."""
        for action in self.form_actions:
            if "errinfo.aspx" in action.lower():
                return _reason_of(action) or next((error for error in self.error_texts if error), NOT_PUBLISHED)
        if self.has_password_input and not self.has_target_lists and self.timetable_data() is None:
            return LOGIN_REQUIRED
        return None


def _setter(target: Any, name: str) -> Callable[[str], None]:
    def store(value: str) -> None:
        setattr(target, name, value)

    return store


def _js_unescape(match: "re.Match[str]") -> str:
    escaped = match.group(1)
    if escaped[0] in "ux" and len(escaped) > 1:
        return chr(int(escaped[1:], 16))
    return escaped


def _parse_page(page: str) -> _PageParser:
    parser = _PageParser()
    parser.feed(page)
    parser.close()
    return parser


def _target_of(href: Optional[str]) -> Optional[Tuple[str, str]]:
    """``(kind, id)`` of a link ``.../timetable/public/<week>/<kind>/<id>``; the id is percent-decoded (pages write
    it with literal spaces or encoded)."""
    path = (href or "").split("#", 1)[0].split("?", 1)[0]
    segments = path.split("/")
    lowered = [segment.lower() for segment in segments]
    for position in range(1, len(segments) - 3):
        if lowered[position - 1] == "timetable" and lowered[position] == "public":
            target_id = urllib.parse.unquote("/".join(segments[position + 3:]))
            return lowered[position + 2], target_id
    return None


def _targets_of(page: _PageParser) -> PublicTargets:
    """The targets of the select lists and the off-canvas links, merged by id in the page's order."""
    found: Dict[str, Dict[str, str]] = {kind: {} for kind in PUBLIC_KINDS}
    for kind in PUBLIC_KINDS:
        entries: List[Tuple[Optional[str], str]] = [(value, label or "") for value, label in page.options[kind]]
        for href, label in page.links[kind]:
            target = _target_of(href)
            entries.append((target[1] if target else None, label or ""))
        for target_id, label in entries:
            if target_id is None or not target_id.strip():
                continue
            if not found[kind].get(target_id):
                found[kind][target_id] = label
    built = {
        kind: tuple(PublicTarget(kind=kind, id=target_id, name=label) for target_id, label in found[kind].items())
        for kind in PUBLIC_KINDS
    }
    return PublicTargets(classes=built["class"], teachers=built["teacher"], rooms=built["room"])


def parse_public_targets(html: str) -> PublicTargets:
    """Parses the target lists of a public timetable page (``/Timetable/Public`` or any timetable page): the
    ``<select>`` options (without the empty first option) and the off-canvas links, merged by id. A page without
    any target list raises :class:`~bakalari.BakalariContractError`."""
    page = _parse_page(html)
    if not page.has_target_lists:
        reason = page.refusal()
        detail = f" (the page says: {reason})" if reason else ""
        raise BakalariContractError([f"The page lists no public timetable targets{detail}"], "public timetable page")
    return _targets_of(page)


def _legacy_lesson(cell: _Cell) -> Tuple[PublicLesson, str]:
    """A lesson of a server-rendered cell and the day text of its detail (``po 10.11.``)."""
    detail = _json_object(cell.detail)
    values = {key: html_unescape(value) if isinstance(value, str) else value for key, value in detail.items()}
    parts = [part.strip() for part in text(values.get("subjecttext")).split("|")]
    time_text = _first_text(values.get("time")) or (parts[2] if len(parts) > 2 else "")
    times = _time_range(time_text)
    atom_type = _first_text(values.get("type")) or "atom"
    removed = atom_type == "removed" or "removed" in cell.classes
    change_info = _first_text(values.get("changeinfo"), values.get("removedinfo"))
    change_code = _first_text(values.get("infoChangeCode"))
    lesson = PublicLesson(
        hour_index=to_int(values.get("hourIndex")) or None,
        begin=times[0] if times else "",
        end=times[1] if times else "",
        subject=parts[0],
        subject_abbrev=cell.parts.get("subject", ""),
        teacher=_first_text(values.get("teacher")),
        teacher_abbrev=cell.parts.get("teacher") or cell.parts.get("bottom", ""),
        room=cell.parts.get("room") or _first_text(values.get("room")),
        room_name=_first_text(values.get("room")),
        group=cell.parts.get("group") or _markup_text(values.get("group")),
        theme=_first_text(values.get("theme")),
        notice=_first_text(values.get("notice")),
        change_info=change_info,
        changed=bool(change_info) or removed or "hasChange" in cell.classes,
        absent_info=_first_text(values.get("absentInfoText"), values.get("absentinfo"), values.get("absencetext")),
        hour_caption=_caption(time_text),
        group_name=_markup_text(values.get("group")),
        change_type="Removed" if removed else ("" if change_code in ("", "NoChange") else change_code),
        cycle=cell.parts.get("cycle", ""),
        atom_type="removed" if removed else atom_type,
        raw=dict(detail),
    )
    return lesson, _first_text(values.get("day")) or (parts[1] if len(parts) > 1 else "")


def _legacy_timetable(rows: Sequence[_Row], kind: str, target_id: str, week: str) -> PublicTimetable:
    """A timetable from server-rendered rows; the hour slots are those the lessons name."""
    parsed = [(row, [_legacy_lesson(cell) for cell in row.cells]) for row in rows]
    slots: Dict[str, Tuple[str, str]] = {}
    known: Dict[int, int] = {}
    for _, lessons in parsed:
        for lesson, _ in lessons:
            if lesson.hour_caption and lesson.begin:
                slots.setdefault(lesson.hour_caption, (lesson.begin, lesson.end))
            _remember_index(known, lesson.begin, lesson.hour_index)
    ordered = sorted(slots.items(), key=lambda item: _minutes(item[1][0]) or 0)
    hours = _hour_slots([(caption, begin, end) for caption, (begin, end) in ordered], known)
    days = [
        PublicDay(
            day_abbrev=row.day,
            date_text=row.date,
            day_off=row.day_off,
            day_off_name=row.day_off_name,
            lessons=_arranged([lesson for lesson, _ in lessons], hours),
        )
        for row, lessons in parsed
    ]
    dates = _resolve_dates([
        (day.day_abbrev, day.date_text, _full_dates(day_text for _, day_text in lessons))
        for day, (_, lessons) in zip(days, parsed)
    ])
    return PublicTimetable(
        kind=kind,
        target_id=target_id,
        week=week,
        hours=tuple(hours),
        days=tuple(replace(day, date=date) for day, date in zip(days, dates)),
    )


def _timetable_of(page: _PageParser, kind: str, target_id: str, week: str, validate: bool) -> PublicTimetable:
    kind = kind or page.script_constant("objectType").lower()
    target_id = target_id or page.script_constant("objectId")
    week = week or page.week
    data = page.timetable_data()
    if data is not None:
        return PublicTimetable.from_json(data, kind=kind, target_id=target_id, week=week, validate=validate)
    # A server-rendered day names its weekday; the empty rows of a newer page's template (whose day-off block is in
    # the markup too) are not days.
    rows = [row for row in page.rows if row.day or row.cells]
    if rows:
        return _legacy_timetable(rows, kind, target_id, week)
    reason = page.refusal()
    detail = f" (the page says: {reason})" if reason else ""
    raise BakalariContractError(
        [f"The page contains neither the timetableData JSON nor server-rendered timetable rows{detail}"],
        "public timetable page",
    )


def parse_public_timetable(
    html: str, *, kind: str = "", target_id: str = "", week: str = "", validate: bool = True
) -> PublicTimetable:
    """Parses a public timetable page: the embedded ``timetableData`` JSON (newer servers) or else the
    server-rendered rows with their ``data-detail`` JSON (older servers). ``kind``, ``target_id`` and ``week``
    default to what the page names (its ``objectType``/``objectId`` script constants and the checked week); given
    ones are checked and lower-cased like :func:`public_timetable_path` does. A page with neither raises
    :class:`~bakalari.BakalariContractError`; ``validate`` applies to the JSON (see
    :meth:`PublicTimetable.from_json`)."""
    kind = _choice(kind, PUBLIC_KINDS, "public timetable kind") if kind else ""
    week = _choice(week, PUBLIC_WEEKS, "public timetable week") if week else ""
    return _timetable_of(_parse_page(html), kind, target_id, week, validate)


def _reason_of(url: str) -> str:
    """The message an error page URL carries in its ``e`` parameter (``K požadované stránce nemáte přístup.``)."""
    query = urllib.parse.urlsplit(url).query
    return text(urllib.parse.parse_qs(query).get("e", [""])[0])


def _refusal_of_url(url: str, requested_path: str) -> Optional[str]:
    """The reason when ``url`` (a redirect target or the final URL) is an error or login page rather than the
    requested page itself, else ``None``."""
    path = urllib.parse.urlsplit(url or "").path.lower().rstrip("/")
    if not path or path.endswith(requested_path.lower().rstrip("/")):
        return None
    if path.endswith("errinfo.aspx"):
        return _reason_of(url) or NOT_PUBLISHED
    if path.rsplit("/", 1)[-1] == "login":
        return LOGIN_REQUIRED
    return None


def _decode_page(response: HttpResponse) -> str:
    """The page as text, decoded with the charset of the ``Content-Type`` header, else of the page's ``<meta>`` tag
    (older IIS pages are windows-1250), else as UTF-8."""
    header = re.search(r"charset=[\"']?([\w.-]+)", response.header("Content-Type") or "", re.I)
    meta = None if header else re.search(rb"<meta[^>]*charset=[\"']?([\w.-]+)", response.body[:4096], re.I)
    charset = header.group(1) if header else (meta.group(1).decode("ascii") if meta else "utf-8")
    if charset.lower() in ("utf-8", "utf8"):
        charset = "utf-8-sig"
    try:
        return response.body.decode(charset, errors="replace")
    except LookupError:
        return response.body.decode("utf-8", errors="replace")


class PublicTimetableEndpoints(ClientCore):
    """Public timetable endpoints of :class:`~bakalari.BakalariClient`: HTML pages that need no login."""

    def public_timetable_targets(self) -> PublicTargets:
        """``GET /Timetable/Public`` (no login): the classes, teachers and rooms whose timetables the school
        publishes. Raises :class:`~bakalari.BakalariPermissionError` when the school redirects to an error or
        login page (it does not publish public timetables)."""
        page = self._public_page(PUBLIC_TIMETABLE_PATH)
        if not page.has_target_lists:
            raise BakalariContractError(["The page lists no public timetable targets"], "public timetable page")
        return _targets_of(page)

    def public_timetable(
        self, kind: str, target_id: Union[str, PublicTarget], *, week: str = "actual", validate: bool = True
    ) -> PublicTimetable:
        """``GET /Timetable/Public/{Actual|Permanent|Next}/{Class|Teacher|Room}/{id}`` (no login): the timetable of
        a class, teacher or room (``kind``) for the current week, the permanent timetable or the next week
        (``week``). ``target_id`` is a :class:`PublicTarget` id (or the target itself), sent percent-encoded. A
        school that does not publish the timetable redirects to an error or login page:
        :class:`~bakalari.BakalariPermissionError`."""
        path = public_timetable_path(kind, target_id, week=week)
        page = self._public_page(path)
        return _timetable_of(
            page,
            _choice(kind, PUBLIC_KINDS, "public timetable kind"),
            _target_id(target_id),
            _choice(week, PUBLIC_WEEKS, "public timetable week"),
            validate,
        )

    def public_timetable_url(self, kind: str, target_id: Union[str, PublicTarget], *, week: str = "actual") -> str:
        """The browser URL of a public timetable page (see :meth:`public_timetable`)."""
        return self.base_url + public_timetable_path(kind, target_id, week=week)

    def _public_page(self, path: str) -> _PageParser:
        """Fetches and parses a public page; an error or login page (followed redirect, a redirect answer or the
        page itself) raises :class:`~bakalari.BakalariPermissionError`."""
        response = self.request(
            "GET", path, headers={"Accept": "text/html"}, authorized=False,
            expected_status=(200,) + _REDIRECT_STATUSES,
        )
        location = (response.header("Location") or "") if response.status in _REDIRECT_STATUSES else ""
        page = _parse_page(_decode_page(response))
        reason = _refusal_of_url(location, path) or _refusal_of_url(response.url, path) or page.refusal()
        if reason is not None:
            raise BakalariPermissionError("GET", path, 403, 200, reason)
        if response.status != 200:
            raise BakalariHTTPError("GET", path, response.status, 200, f"redirect to {location}" if location else None)
        return page
