"""Teacher endpoints: the class book, lesson details, marking and the emergency module.

Only teacher accounts may use them; other accounts get HTTP 403 ``Some privilege is missing (IsTeacher)``, raised
as :class:`~bakalari.BakalariPermissionError`. The models follow the community documentation and captured traffic
(no teacher account was available to verify them against a live server), so every model keeps the server's object
in ``raw`` and the raw endpoints return the JSON unchanged.

The class book (``GET /api/3/classbook``) lists days with their lesson records (``Days[].Hours[]``) and the hour
slots (``Hours``). A record's ``Id`` addresses it for ``POST /api/3/classbook/{Id}``; its ``LessonId`` addresses the
lesson details under ``/api/3/lesson/{LessonId}/...``.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple, Union

from ._core import ClientCore, api_path
from ._parse import (
    DateLike,
    check_shape,
    ident,
    objects,
    parse_date,
    parse_datetime,
    quote_segment,
    require_list,
    require_mapping,
    shape_problems,
    strings,
    text,
    to_bool,
    to_int,
)
from .errors import BakalariContractError
from .models import Item, Model
from .timetable import Hour

__all__ = [
    "ClassBook",
    "ClassBookDay",
    "ClassBookGroup",
    "ClassBookRecord",
    "LessonPast",
    "LessonTag",
    "MarkingAtom",
    "MarkingMark",
    "MarkingSheet",
    "MarkingStudent",
    "TeacherEndpoints",
    "classbook_problems",
    "format_classbook_time",
]


def format_classbook_time(value: DateLike, *, end_of_day: bool = False) -> str:
    """A ``from``/``to`` parameter of the class book: ``YYYY-MM-DDTHH:mm:ss.SSS`` without an offset.

    A date (or an ISO date string) becomes the start of the day, or with ``end_of_day`` its last millisecond
    (``T23:59:59.999``); a datetime (or an ISO datetime string) keeps its wall-clock time and drops its offset.
    Other strings go to the server unchanged, so it validates them.
    """
    if isinstance(value, str):
        stripped = value.strip()
        parsed: Optional[dt.date] = parse_datetime(stripped) if "T" in stripped else None
        if parsed is None and len(stripped) == 10:
            try:
                parsed = dt.date.fromisoformat(stripped)
            except ValueError:
                parsed = None
        return stripped if parsed is None else format_classbook_time(parsed, end_of_day=end_of_day)
    if isinstance(value, dt.datetime):
        return (
            f"{value.year:04d}-{value.month:02d}-{value.day:02d}T"
            f"{value.hour:02d}:{value.minute:02d}:{value.second:02d}.{value.microsecond // 1000:03d}"
        )
    if isinstance(value, dt.date):
        return value.isoformat() + ("T23:59:59.999" if end_of_day else "T00:00:00.000")
    raise TypeError(f"Expected a date, datetime or ISO date string, got {type(value).__name__}")


@dataclass(frozen=True)
class ClassBookGroup(Item):
    """A group (or a whole class) a class-book record is written for; ``class_id`` is the id of its class."""

    class_id: str = ""

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "ClassBookGroup":
        """Parses a ``{ClassId, Id, Abbrev, Name}`` object."""
        return cls(
            id=ident(data.get("Id")),
            abbrev=text(data.get("Abbrev")),
            name=text(data.get("Name")),
            class_id=ident(data.get("ClassId")),
        )


def _tag_ids(value: Any) -> Tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(ident(tag.get("Id")) if isinstance(tag, Mapping) else ident(tag) for tag in value if tag is not None)


def _name_text(value: Any) -> str:
    """An enum name such as ``WorkDay``; the save answer sends a bare number (``0``) instead, which names nothing."""
    return text(value) if isinstance(value, str) else ""


# Text fields of the save body: the official app sends "" where the class book has null (captured traffic).
_BODY_TEXTS = ("Label", "Notice", "PrivateNotice", "Theme", "WeekTheme")


@dataclass(frozen=True)
class ClassBookRecord(Model):
    """One lesson record of the class book (an entry of ``Days[].Hours``).

    ``id`` addresses the record for :meth:`TeacherEndpoints.save_classbook_record`, ``lesson_id`` the lesson
    details (:meth:`TeacherEndpoints.lesson_absence`, :meth:`~TeacherEndpoints.lesson_past`, ...). ``label`` is
    the lesson's sequence number in the subject, ``level`` the ``ClassBookLevel`` (e.g. SecondLevel), ``tags`` the
    ids of its lesson tags, ``start`` and ``duration`` minutes (after midnight / long), ``editable_groups`` the ids
    of the groups the teacher may write for. ``supervision`` is the server's ``Supervision`` value as sent (its
    shape is undocumented).
    """

    id: str
    lesson_id: str = ""
    label: str = ""
    theme: str = ""
    notice: str = ""
    private_notice: str = ""
    week_theme: str = ""
    tags: Tuple[str, ...] = ()
    level: str = ""
    hour_id: Optional[int] = None
    date: Optional[dt.date] = None
    start: Optional[int] = None
    duration: Optional[int] = None
    hour_caption: str = ""
    hour_time: str = ""
    subject: Optional[Item] = None
    groups: Tuple[ClassBookGroup, ...] = ()
    editable_groups: Tuple[str, ...] = ()
    change_text: str = ""
    supervision: Any = None
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "ClassBookRecord":
        """Parses a record leniently: missing fields get their defaults."""
        return cls(
            id=ident(data.get("Id")),
            lesson_id=ident(data.get("LessonId")),
            label=text(data.get("Label")),
            theme=text(data.get("Theme")),
            notice=text(data.get("Notice")),
            private_notice=text(data.get("PrivateNotice")),
            week_theme=text(data.get("WeekTheme")),
            tags=_tag_ids(data.get("Tags")),
            level=text(data.get("ClassBookLevel")),
            hour_id=to_int(data.get("HourId")),
            date=parse_date(data.get("Date")),
            start=to_int(data.get("Start")),
            duration=to_int(data.get("Duration")),
            hour_caption=text(data.get("HourCaption")),
            hour_time=text(data.get("HourTime")),
            subject=Item.optional(data.get("Subject")),
            groups=tuple(ClassBookGroup.from_json(group) for group in objects(data.get("Groups"))),
            editable_groups=strings(data.get("EditableGroups")),
            change_text=text(data.get("ChangeText")),
            supervision=data.get("Supervision"),
            raw=dict(data),
        )

    @property
    def is_written(self) -> bool:
        """True when the lesson's theme has been written."""
        return bool(self.theme)

    def request_body(
        self,
        *,
        theme: Optional[str] = None,
        notice: Optional[str] = None,
        private_notice: Optional[str] = None,
        week_theme: Optional[str] = None,
        label: Optional[str] = None,
        tags: Optional[Iterable[Any]] = None,
    ) -> Dict[str, Any]:
        """The JSON body :meth:`TeacherEndpoints.save_classbook_record` sends for this record: the documented keys
        (``Id``, ``LessonId``, ``ClassBookLevel``, ``Label``, ``Notice``, ``PrivateNotice``, ``Tags``, ``Theme``,
        ``WeekTheme``, ``Groups``) with the server's own values from ``raw``, changed by the arguments that are not
        ``None``. As in the official app's requests, the text fields are ``""`` instead of ``null`` and ``Groups``
        lists the editable groups (``EditableGroups``) as ``{Id, ClassId}`` with the class ids of their ``Groups``
        entries; every group is listed when none of them is editable. ``tags`` are tag ids (or :class:`LessonTag`
        objects, sent as their ids). A record that is not written yet has an empty ``label``: pass the ``next_label``
        of :meth:`TeacherEndpoints.lesson_past`, as the official app does."""
        raw = self.raw
        groups: List[Mapping[str, Any]] = objects(raw.get("Groups")) if "Groups" in raw else [
            {"Id": group.id, "ClassId": group.class_id} for group in self.groups
        ]
        editable = strings(raw.get("EditableGroups")) if "EditableGroups" in raw else self.editable_groups
        groups = [group for group in groups if ident(group.get("Id")) in editable] or groups
        raw_tags = raw.get("Tags")
        body: Dict[str, Any] = {
            "Id": raw.get("Id", self.id),
            "LessonId": raw.get("LessonId", self.lesson_id),
            "ClassBookLevel": raw.get("ClassBookLevel", self.level),
            "Label": raw.get("Label", self.label),
            "Notice": raw.get("Notice", self.notice),
            "PrivateNotice": raw.get("PrivateNotice", self.private_notice),
            "Tags": list(raw_tags) if isinstance(raw_tags, list) else ([] if "Tags" in raw else list(self.tags)),
            "Theme": raw.get("Theme", self.theme),
            "WeekTheme": raw.get("WeekTheme", self.week_theme),
            "Groups": [{"Id": group.get("Id"), "ClassId": group.get("ClassId")} for group in groups],
        }
        body.update({key: "" for key in _BODY_TEXTS if body[key] is None})
        changes = {"Theme": theme, "Notice": notice, "PrivateNotice": private_notice, "WeekTheme": week_theme,
                   "Label": label}
        body.update({key: value for key, value in changes.items() if value is not None})
        if tags is not None:
            chosen = [tags] if isinstance(tags, str) else list(tags)  # one tag id, not its characters
            body["Tags"] = [tag.id if isinstance(tag, LessonTag) else tag for tag in chosen]
        return body


@dataclass(frozen=True)
class ClassBookDay(Model):
    """A class-book day with its lesson records; ``day_of_week`` is 1 for Monday to 7 for Sunday, ``day_type``
    WorkDay, Holiday, Celebration, ... as in the timetable and ``description`` names a holiday or event. The answer
    of a save sends ``DayOfWeek`` and ``DayType`` as ``0``: the day of the week then comes from the date and the
    day type is empty."""

    date: Optional[dt.date]
    day_of_week: Optional[int] = None
    day_type: str = ""
    description: str = ""
    records: Tuple[ClassBookRecord, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "ClassBookDay":
        """Parses a day leniently; its records are the objects of ``Hours`` (``null`` means none)."""
        date = parse_date(data.get("Date"))
        return cls(
            date=date,
            day_of_week=to_int(data.get("DayOfWeek")) or (date.isoweekday() if date else None),
            day_type=_name_text(data.get("DayType")),
            description=text(data.get("DayDescription")),
            records=tuple(ClassBookRecord.from_json(record) for record in objects(data.get("Hours"))),
            raw=dict(data),
        )


def _list_problems(value: Any, where: str) -> List[str]:
    """The problems of a list of objects that may be ``null`` (``where`` names it, e.g. ``'Hours'``)."""
    if value is None:
        return []
    if not isinstance(value, list):
        return [f"{where} must be a JSON array or null"]
    bad = sum(1 for entry in value if not isinstance(entry, Mapping))
    return [f"{where} contains {bad} entr{'y' if bad == 1 else 'ies'} other than JSON objects"] if bad else []


def classbook_problems(data: Any) -> List[str]:
    """Lists the contract violations of a class-book payload: an object with the list ``Days`` of objects, whose
    ``Hours`` (the lesson records, like the top-level ``Hours`` slots) are lists of objects or ``null``."""
    problems = shape_problems(data, "class book", lists=("Days",))
    if not isinstance(data, Mapping):
        return problems
    problems += _list_problems(data.get("Hours"), "'Hours'")
    for day in objects(data.get("Days")):
        problems += _list_problems(day.get("Hours"), f"Day {str(day.get('Date', '?'))[:10]}: 'Hours'")
    return problems


@dataclass(frozen=True)
class ClassBook(Model):
    """The class book of an interval: the days with their lesson records and the hour slots. The answer of a
    save has no hour slots (the server sends ``Hours: null``), so ``hours`` may be empty."""

    days: Tuple[ClassBookDay, ...] = ()
    hours: Tuple[Hour, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Any, *, validate: bool = True) -> "ClassBook":
        """Parses a class-book payload. With ``validate`` (default) a contract violation (see
        :func:`classbook_problems`) raises :class:`~bakalari.BakalariContractError`; a non-object always does."""
        if validate:
            problems = classbook_problems(data)
            if problems:
                raise BakalariContractError(problems, "class book")
        payload = require_mapping(data, "class book")
        return cls(
            days=tuple(ClassBookDay.from_json(day) for day in objects(payload.get("Days"))),
            hours=tuple(Hour.from_json(hour) for hour in objects(payload.get("Hours"))),
            raw=dict(payload),
        )

    @property
    def records(self) -> List[ClassBookRecord]:
        """Every lesson record, day by day."""
        return [record for day in self.days for record in day.records]

    def record(self, key: str) -> Optional[ClassBookRecord]:
        """The record with the record id or the lesson id ``key`` (compared exactly), or ``None``."""
        return next((record for record in self.records if key in (record.id, record.lesson_id)), None)

    def hour(self, hour_id: Optional[int]) -> Optional[Hour]:
        """The hour slot with the id ``hour_id`` (a record's ``hour_id``), or ``None``."""
        return next((hour for hour in self.hours if hour_id is not None and hour.id == hour_id), None)


@dataclass(frozen=True)
class LessonTag(Model):
    """A tag a teacher can attach to a class-book record (``GET /api/3/classbook/lessonTags``)."""

    id: str
    abbreviation: str = ""
    title: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "LessonTag":
        """Parses an ``{Id, Abbreviation, Title}`` object."""
        return cls(
            id=ident(data.get("Id")),
            abbreviation=text(data.get("Abbreviation")),
            title=text(data.get("Title")),
            raw=dict(data),
        )


@dataclass(frozen=True)
class LessonPast(Model):
    """The last theme taught in a lesson's subject and group, and the label (sequence number) for the next record
    (``GET /api/3/lesson/{id}/past``)."""

    lesson_id: str
    last_theme: str = ""
    next_label: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Any) -> "LessonPast":
        """Parses a ``{LessonId, LastTheme, NextLabel}`` object; a non-object raises
        :class:`~bakalari.BakalariContractError`."""
        payload = require_mapping(data, "lesson history")
        return cls(
            lesson_id=ident(payload.get("LessonId")),
            last_theme=text(payload.get("LastTheme")),
            next_label=text(payload.get("NextLabel")),
            raw=dict(payload),
        )


@dataclass(frozen=True)
class MarkingAtom(Model):
    """A unit a teacher gives marks in (a subject taught to a class or group), from ``GET /api/3/marking/atoms``;
    ``disabled_text`` explains why a disabled atom cannot be marked."""

    id: str
    name: str = ""
    subject: Optional[Item] = None
    disabled: bool = False
    disabled_text: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "MarkingAtom":
        """Parses an ``{Id, Name, Subject, Disabled, DisabledText}`` object."""
        return cls(
            id=ident(data.get("Id")),
            name=text(data.get("Name")),
            subject=Item.optional(data.get("Subject")),
            disabled=to_bool(data.get("Disabled")),
            disabled_text=text(data.get("DisabledText")),
            raw=dict(data),
        )


@dataclass(frozen=True)
class MarkingMark(Model):
    """A student's mark on a marking sheet. ``header_id`` groups the marks of one test or assessment,
    ``mark_value`` is the mark as written (``"1"``, ``"2-"``, ...), ``confirmation_state`` the server's
    ``MarkConfirmationState`` (Confirmed, Unconfirmed) and ``confirmed_at``/``confirmed_by`` its
    ``ConfirmedWhen``/``ConfirmedBy``."""

    id: str
    mark_date: Optional[dt.datetime] = None
    edit_date: Optional[dt.datetime] = None
    teacher_id: str = ""
    header_id: str = ""
    mark_value: str = ""
    theme: str = ""
    student_id: str = ""
    read_only: bool = False
    read_only_description: str = ""
    publish_date: Optional[dt.datetime] = None
    confirmed_at: Optional[dt.datetime] = None
    confirmed_by: str = ""
    confirmation_state: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "MarkingMark":
        """Parses a mark leniently: missing fields get their defaults."""
        return cls(
            id=ident(data.get("Id")),
            mark_date=parse_datetime(data.get("MarkDate")),
            edit_date=parse_datetime(data.get("EditDate")),
            teacher_id=ident(data.get("TeacherId")),
            header_id=ident(data.get("HeaderId")),
            mark_value=text(data.get("MarkValue")),
            theme=text(data.get("Theme")),
            student_id=ident(data.get("StudentId")),
            read_only=to_bool(data.get("ReadOnly")),
            read_only_description=text(data.get("ReadOnlyDescription")),
            publish_date=parse_datetime(data.get("PublishDate")),
            confirmed_at=parse_datetime(data.get("ConfirmedWhen")),
            confirmed_by=ident(data.get("ConfirmedBy")),
            confirmation_state=text(data.get("MarkConfirmationState")),
            raw=dict(data),
        )

    @property
    def is_confirmed(self) -> bool:
        """True when a parent or adult student has confirmed (signed) the mark."""
        return self.confirmation_state == "Confirmed"


@dataclass(frozen=True)
class MarkingStudent(Model):
    """A student on a marking sheet: ``name`` is the display name, ``average_text1``/``average_text2`` the
    averages as the server writes them, ``released`` whether the student is released from the subject."""

    id: str
    name: str = ""
    class_id: str = ""
    first_name: str = ""
    middle_name: str = ""
    last_name: str = ""
    registration_number: str = ""
    average_text1: str = ""
    average_text2: str = ""
    released: bool = False
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def __str__(self) -> str:
        return self.name or self.id

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "MarkingStudent":
        """Parses a student; without ``DisplayName`` the name is composed of the last, first and middle names."""
        first, middle, last = (text(data.get(key)) for key in ("FirstName", "MiddleName", "LastName"))
        return cls(
            id=ident(data.get("Id")),
            name=text(data.get("DisplayName")) or " ".join(part for part in (last, first, middle) if part),
            class_id=ident(data.get("ClassId")),
            first_name=first,
            middle_name=middle,
            last_name=last,
            registration_number=text(data.get("RegistrationNumber")),
            average_text1=text(data.get("AverageText1")),
            average_text2=text(data.get("AverageText2")),
            released=to_bool(data.get("ReleasedOfSubject")),
            raw=dict(data),
        )


@dataclass(frozen=True)
class MarkingSheet(Model):
    """The marks of one marking atom (``GET /api/3/marking/marks/{atomId}``): the mark options, every student's
    marks, the students and the teachers the marks refer to."""

    mark_options: Tuple[Item, ...] = ()
    marks: Tuple[MarkingMark, ...] = ()
    students: Tuple[MarkingStudent, ...] = ()
    teachers: Tuple[Item, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Any, *, validate: bool = True) -> "MarkingSheet":
        """Parses a marking sheet. With ``validate`` (default) the payload must hold the list ``Marks`` of objects
        (else :class:`~bakalari.BakalariContractError`); the other lists are optional."""
        payload = check_shape(data, "marking sheet", lists=("Marks",)) if validate else require_mapping(
            data, "marking sheet"
        )
        return cls(
            mark_options=tuple(Item.from_json(option) for option in objects(payload.get("MarkOptions"))),
            marks=tuple(MarkingMark.from_json(mark) for mark in objects(payload.get("Marks"))),
            students=tuple(MarkingStudent.from_json(student) for student in objects(payload.get("Students"))),
            teachers=tuple(Item.from_json(teacher) for teacher in objects(payload.get("Teachers"))),
            raw=dict(payload),
        )

    def student(self, student_id: str) -> Optional[MarkingStudent]:
        """The student with the id ``student_id`` (compared exactly), or ``None``."""
        return next((student for student in self.students if student.id == student_id), None)

    def marks_of(self, student: Union[str, MarkingStudent]) -> List[MarkingMark]:
        """The marks of a student (a :class:`MarkingStudent` or its id)."""
        student_id = student.id if isinstance(student, MarkingStudent) else student
        return [mark for mark in self.marks if mark.student_id == student_id]


class TeacherEndpoints(ClientCore):
    """Teacher endpoints of :class:`~bakalari.BakalariClient` (teacher accounts only; others get
    :class:`~bakalari.BakalariPermissionError`)."""

    def classbook(self, since: DateLike, until: DateLike, *, validate: bool = True) -> ClassBook:
        """``GET /api/3/classbook?from=&to=``: the teacher's class book between ``since`` and ``until``. A date
        covers the whole day (``T00:00:00.000`` to ``T23:59:59.999``); a datetime is sent as its wall-clock time
        with milliseconds and without an offset (see :func:`format_classbook_time`)."""
        params = {
            "from": format_classbook_time(since),
            "to": format_classbook_time(until, end_of_day=True),
        }
        return ClassBook.from_json(self.get_json(api_path("classbook"), params), validate=validate)

    def save_classbook_record(
        self, record: Union[Mapping[str, Any], ClassBookRecord], *, validate: bool = True
    ) -> ClassBook:
        """``POST /api/3/classbook/{Id}``: writes a class-book record and returns the saved day (its ``hours``
        are empty, the server answers ``Hours: null``).

        ``record`` is the JSON body (the keys of :meth:`ClassBookRecord.request_body`; the record id is taken from
        its ``Id``) or a :class:`ClassBookRecord`, whose :meth:`~ClassBookRecord.request_body` is sent.
        """
        body = record.request_body() if isinstance(record, ClassBookRecord) else dict(record)
        record_id = ident(body.get("Id"))
        if not record_id.strip():
            raise ValueError("The class-book record has no 'Id'")
        data = self.post_json(api_path("classbook", quote_segment(record_id)), json_body=body)
        return ClassBook.from_json(data, validate=validate)

    def lesson_tags(self) -> List[LessonTag]:
        """``GET /api/3/classbook/lessonTags``: the tags a teacher can attach to class-book records."""
        data = require_list(self.get_json(api_path("classbook", "lessonTags")), "lesson tag list")
        return [LessonTag.from_json(tag) for tag in objects(data)]

    def lesson_absence(self, lesson_id: str) -> Dict[str, Any]:
        """``GET /api/3/lesson/{lessonId}/absence``: the attendance of a lesson as raw JSON (``LessonId``,
        ``ClassBookRecordId``, ``AbsencesGroups`` with the students' absences and the allowed absence types,
        ``HourId``, ``Start``, ``Duration``, ``Hours`` and ``SchoolEvents``). ``lesson_id`` is a record's
        ``lesson_id``, not its ``id``."""
        data = self.get_json(api_path("lesson", quote_segment(lesson_id), "absence"))
        return dict(require_mapping(data, "lesson absence"))

    def lesson_past(self, lesson_id: str) -> LessonPast:
        """``GET /api/3/lesson/{lessonId}/past``: the last theme taught and the label for the next record."""
        return LessonPast.from_json(self.get_json(api_path("lesson", quote_segment(lesson_id), "past")))

    def lesson_students_timetable(self, lesson_id: str) -> Dict[str, Any]:
        """``GET /api/3/lesson/{lessonId}/studentsTimetable``: the timetables of the students a lesson concerns, as
        raw JSON (``StudentTimetables``: entries with ``Id``, ``Abbrev``, ``Name`` and the ``Hours`` they attend;
        captured traffic shows one entry per student, whose ``Id`` is the student id of :meth:`lesson_absence`,
        while the community docs describe groups)."""
        data = self.get_json(api_path("lesson", quote_segment(lesson_id), "studentsTimetable"))
        return dict(require_mapping(data, "students' timetable"))

    def marking_atoms(self, *, validate: bool = True) -> List[MarkingAtom]:
        """``GET /api/3/marking/atoms``: the subjects and groups the teacher gives marks in (the server also
        accepts superusers: ``Some privilege is missing (IsTeacher,IsSuperuser)`` otherwise)."""
        data = self.get_json(api_path("marking", "atoms"))
        payload = check_shape(data, "marking atom list", lists=("Atoms",)) if validate else require_mapping(
            data, "marking atom list"
        )
        return [MarkingAtom.from_json(atom) for atom in objects(payload.get("Atoms"))]

    def marking_marks(self, atom_id: str, *, validate: bool = True) -> MarkingSheet:
        """``GET /api/3/marking/marks/{atomId}``: the marking sheet of a marking atom (see :meth:`marking_atoms`)."""
        data = self.get_json(api_path("marking", "marks", quote_segment(atom_id)))
        return MarkingSheet.from_json(data, validate=validate)

    def emergency_configuration(self) -> Any:
        """``GET /api/3/emergency/configuration``: the configuration of the emergency (crisis alarm) module as raw
        JSON; its shape is undocumented. Teacher accounts only."""
        return self.get_json(api_path("emergency", "configuration"))
