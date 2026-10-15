"""Subjects with their teachers' contacts, and the lesson themes of a subject.

``GET /api/3/subjects`` lists the student's subjects with the teacher and the teacher's contacts, which most schools
leave ``null``. ``GET /api/3/subjects/themes/{id}`` lists the lessons of one subject in the school year with the
theme recorded in the class book. Subject ids may be space-padded (``" 2"``), so they are used exactly as the server
sends them.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Mapping, Optional, Tuple, Union

from ._core import ClientCore, api_path
from ._parse import check_shape, ident, mapping, objects, parse_date, quote_segment, require_mapping, text, to_int
from .models import Item, Model

__all__ = ["SubjectInfo", "SubjectThemes", "SubjectsEndpoints", "Theme", "find_subject", "parse_subjects"]

# Besides letters and digits, the only characters a subject id may contain to be sent in the URL path. Others do not
# reach the server intact even percent-encoded: a backslash (``%5C``) answers an IIS HTML 404 (verified); by default
# ASP.NET (requestPathInvalidCharacters, Windows path rules) and IIS request filtering (double escaping) reject
# ``% & * : < > ? + " |``, ASP.NET decodes ``%2F`` to a slash before routing, a dot makes the last segment look like a
# file name (``quote`` leaves dots alone, so ``.`` and ``..`` would even address another endpoint) and Windows path
# rules drop a trailing space. The themes of such a subject are requested through the query string, which the server
# answers the same way (verified).
_PATH_PUNCTUATION = frozenset(" -_()[]{}")


def _fits_url_path(subject_id: str) -> bool:
    """True when the id can be sent as a URL path segment (see ``_PATH_PUNCTUATION``)."""
    return not subject_id.endswith(" ") and all(
        character.isalnum() or character in _PATH_PUNCTUATION for character in subject_id
    )


@dataclass(frozen=True)
class SubjectInfo(Model):
    """A subject of the student with its teacher (an entry of ``GET /api/3/subjects``). ``id`` is exactly what the
    server sent (it may be space-padded), ``teacher`` is ``None`` for a subject without a teacher and the contacts are
    empty unless the school publishes them (live servers send ``null``)."""

    id: str
    name: str
    abbrev: str = ""
    teacher: Optional[Item] = None
    teacher_email: str = ""
    teacher_web: str = ""
    teacher_school_phone: str = ""
    teacher_home_phone: str = ""
    teacher_mobile_phone: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "SubjectInfo":
        """Parses one entry of ``Subjects`` (``SubjectID``, ``SubjectName``, ``TeacherID``, ``TeacherEmail``, ...)."""
        teacher = Item.optional(
            {"Id": data.get("TeacherID"), "Abbrev": data.get("TeacherAbbrev"), "Name": data.get("TeacherName")}
        )
        return cls(
            id=ident(data.get("SubjectID")),
            name=text(data.get("SubjectName")),
            abbrev=text(data.get("SubjectAbbrev")),
            teacher=teacher,
            teacher_email=text(data.get("TeacherEmail")),
            teacher_web=text(data.get("TeacherWeb")),
            teacher_school_phone=text(data.get("TeacherSchoolPhone")),
            teacher_home_phone=text(data.get("TeacherHomePhone")),
            teacher_mobile_phone=text(data.get("TeacherMobilePhone")),
            raw=dict(data),
        )


def parse_subjects(data: Any, *, validate: bool = True) -> List[SubjectInfo]:
    """Parses a ``GET /api/3/subjects`` payload into the subjects in the server's order. With ``validate`` (default)
    a payload without a ``Subjects`` list of objects raises :class:`~bakalari.BakalariContractError`; a payload that
    is not a JSON object always does."""
    if validate:
        check_shape(data, "subject list", lists=("Subjects",))
    payload = require_mapping(data, "subject list")
    return [SubjectInfo.from_json(subject) for subject in objects(payload.get("Subjects"))]


def find_subject(subjects: Iterable[SubjectInfo], key: str) -> Optional[SubjectInfo]:
    """The subject that ``key`` names, trying in turn the exact id, the id without its padding (``"2"`` finds
    ``" 2"``), the abbreviation and the name, the last three case-insensitively; ``None`` when none matches or
    ``key`` is blank."""
    wanted = text(key).casefold()
    if not wanted:
        return None
    candidates = list(subjects)
    exact = next((subject for subject in candidates if subject.id == key), None)
    if exact is not None:
        return exact
    for attribute in ("id", "abbrev", "name"):
        found = next((item for item in candidates if text(getattr(item, attribute)).casefold() == wanted), None)
        if found is not None:
            return found
    return None


def _clock_time(minutes: Optional[int]) -> Optional[dt.time]:
    if minutes is None or not 0 <= minutes < 24 * 60:
        return None
    return dt.time(minutes // 60, minutes % 60)


@dataclass(frozen=True)
class Theme(Model):
    """One lesson of a subject with its class-book theme: ``hour_caption`` names the lesson slot (``"1. hod"``),
    ``lesson_label`` is the lesson's number in the subject (``"12"``), ``start`` the slot's start in minutes after
    midnight (480 is 8:00) and ``duration`` its length in minutes; older servers send neither."""

    date: Optional[dt.date]
    theme: str = ""
    note: str = ""
    hour_caption: str = ""
    lesson_label: str = ""
    start: Optional[int] = None
    duration: Optional[int] = None
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "Theme":
        """Parses one entry of ``Themes``."""
        return cls(
            date=parse_date(data.get("Date")),
            theme=text(data.get("Theme")),
            note=text(data.get("Note")),
            hour_caption=text(data.get("HourCaption")),
            lesson_label=text(data.get("LessonLabel")),
            start=to_int(data.get("Start")),
            duration=to_int(data.get("Duration")),
            raw=dict(data),
        )

    @property
    def start_time(self) -> Optional[dt.time]:
        """The time the lesson starts (``start`` as a clock time), or ``None`` when unknown. A ``start`` of 0 without
        a ``duration`` is unknown too: the server sends 0 for both where an entry has no time (as substitutions do)."""
        if self.start == 0 and not self.duration:
            return None
        return _clock_time(self.start)

    @property
    def end_time(self) -> Optional[dt.time]:
        """The time the lesson ends (``start`` plus ``duration``), or ``None`` when unknown (a ``duration`` that is
        missing or not positive)."""
        if self.start is None or self.duration is None or self.duration <= 0:
            return None
        return _clock_time(self.start + self.duration)


@dataclass(frozen=True)
class SubjectThemes(Model):
    """The lessons of one subject in the school year with their themes (``GET /api/3/subjects/themes/{id}``), in
    the server's order."""

    subject: Item
    themes: Tuple[Theme, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Any, *, validate: bool = True) -> "SubjectThemes":
        """Parses the payload. With ``validate`` (default) a payload without the ``Subject`` object and the
        ``Themes`` list of objects raises :class:`~bakalari.BakalariContractError`; without it, a missing subject
        becomes an empty :class:`~bakalari.Item` and missing themes an empty tuple. A payload that is not a JSON
        object is always an error."""
        if validate:
            check_shape(data, "subject theme list", lists=("Themes",), objects_=("Subject",))
        payload = require_mapping(data, "subject theme list")
        return cls(
            subject=Item.from_json(mapping(payload.get("Subject"))),
            themes=tuple(Theme.from_json(theme) for theme in objects(payload.get("Themes"))),
            raw=dict(payload),
        )


class SubjectsEndpoints(ClientCore):
    """Subject endpoints of :class:`~bakalari.BakalariClient`."""

    def subjects(self, *, validate: bool = True) -> List[SubjectInfo]:
        """``GET /api/3/subjects``: the student's subjects with their teachers and the teachers' contacts (module
        Subjects, right ``ShowSubjects``)."""
        return parse_subjects(self.get_json(api_path("subjects")), validate=validate)

    def subject_themes(self, subject_id: Union[str, SubjectInfo, Item], *, validate: bool = True) -> SubjectThemes:
        """``GET /api/3/subjects/themes/{id}``: the lessons of a subject in the school year with their class-book
        themes (right ``ShowSubjectThemes``). ``subject_id`` is an id exactly as the server sends it (``" 2"`` is
        sent as ``%202``), a :class:`SubjectInfo` or an :class:`~bakalari.Item`. An id that a URL path cannot carry
        (anything but letters, digits, spaces that are not trailing and ``- _ ( ) [ ] { }``, e.g. a backslash, a
        slash or a dot) is sent as ``GET /api/3/subjects/themes/get?subjectid=<id>``, which the server answers the
        same way."""
        key = subject_id.id if isinstance(subject_id, (SubjectInfo, Item)) else ident(subject_id)
        if not key:
            raise ValueError("subject_themes() needs a subject id")
        if _fits_url_path(key):
            data = self.get_json(api_path("subjects", "themes", quote_segment(key)))
        else:
            data = self.get_json(api_path("subjects", "themes", "get"), {"subjectid": key})
        return SubjectThemes.from_json(data, validate=validate)
