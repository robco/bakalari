"""Marks: subjects with their marks and averages, final (certificate) marks, pedagogical measures, mark prediction
and the confirmation of marks by parents.

``GET /api/3/marks`` returns ``Subjects``, each with its ``Subject`` (``{Id, Abbrev, Name}``), its ``Marks`` and its
``AverageText`` exactly as the web shows it (``"2,86 "``: a decimal comma and a trailing space), and ``MarkOptions``,
the mark values the school uses (an option's ``Id`` is the ``MarkText`` of a mark). Subject abbreviations are
space-padded (``"ČJL "``) and subject ids may be too (``" 4"``), so ids are kept exactly as sent. A classic mark's
``MarkText`` is ``"1"`` to ``"5"``, a trailing ``-`` meaning half a grade worse (``"2-"``); a point mark has
``IsPoints``, ``MaxPoints`` and no ``Weight``. Where parents confirm (sign) marks, every mark carries
``MarkConfirmationState`` (``Confirmed`` or ``Unconfirmed``), ``ConfirmedWhen`` and ``ConfirmedBy``.
"""
from __future__ import annotations

import datetime as dt
import html
import math
from collections import abc
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, TypeVar, Union

from ._core import ClientCore, api_path
from ._parse import (
    DateLike,
    check_shape,
    format_date,
    ident,
    mapping,
    objects,
    parse_date,
    parse_datetime,
    require_int,
    require_mapping,
    shape_problems,
    text,
    to_bool,
    to_float,
    to_int,
)
from .errors import BakalariContractError
from .models import Item, Model

__all__ = [
    "CertificateTerm",
    "FinalMark",
    "Mark",
    "Marks",
    "MarksEndpoints",
    "PedagogicalMeasure",
    "SubjectMarks",
    "parse_final_marks",
    "parse_pedagogical_measures",
]

# Czech classic marks; a trailing "-" is half a grade worse. There is no "5-".
_CLASSIC_MARKS = {"1": 1.0, "1-": 1.5, "2": 2.0, "2-": 2.5, "3": 3.0, "3-": 3.5, "4": 4.0, "4-": 4.5, "5": 5.0}

_T = TypeVar("_T")


def _classic_value(mark_text: str) -> Optional[float]:
    return _CLASSIC_MARKS.get(mark_text.strip())


def _finite(value: Optional[float]) -> Optional[float]:
    """``None`` instead of NaN or infinity (``to_float("NaN")``), which ``to_dict()`` could not encode as JSON."""
    return value if value is not None and math.isfinite(value) else None


def _find(entries: Iterable[_T], item_of: Callable[[_T], Optional[Item]], key: Union[str, Item]) -> Optional[_T]:
    """The first entry whose item matches ``key`` by exact id, then by id without padding, then by abbreviation and
    finally by name (both ignoring case). An :class:`Item` key matches with its own id, abbreviation and name."""
    if isinstance(key, Item):
        wanted_id, wanted_abbrev, wanted_name = key.id, key.abbrev, key.name
    else:
        wanted_id = wanted_abbrev = wanted_name = str(key)
    tests: List[Callable[[Item], bool]] = []
    if wanted_id.strip():
        tests.append(lambda item: item.id == wanted_id)
        tests.append(lambda item: item.id.strip() == wanted_id.strip())
    if wanted_abbrev.strip():
        tests.append(lambda item: item.abbrev.casefold() == wanted_abbrev.strip().casefold())
    if wanted_name.strip():
        tests.append(lambda item: item.name.casefold() == wanted_name.strip().casefold())
    candidates = [(entry, item_of(entry)) for entry in entries]
    for test in tests:
        for entry, item in candidates:
            if item is not None and test(item):
                return entry
    return None


def _check_nested(
    data: Any, what: str, list_name: str, lists: Sequence[str] = (), objects_: Sequence[str] = ()
) -> None:
    """Raises :class:`BakalariContractError` listing every shape problem of a payload whose ``list_name`` must be a
    list of objects that each hold the given lists and objects."""
    problems = shape_problems(data, what, lists=(list_name,))
    entries = data.get(list_name) if isinstance(data, abc.Mapping) else None
    for index, entry in enumerate(entries if isinstance(entries, list) else []):
        if isinstance(entry, abc.Mapping):
            problems += [f"{list_name}[{index}]: {problem}" for problem in shape_problems(entry, what, lists, objects_)]
    if problems:
        raise BakalariContractError(problems, what)


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _term_parts(school_year: str, semester: str) -> List[str]:
    return [part for part in (school_year, f"semester {semester}" if semester else "") if part]


@dataclass(frozen=True)
class Mark(Model):
    """A mark of a subject (``GET /api/3/marks``).

    ``text`` is the mark as shown (``"1"``, ``"2-"``, ``"N"``, or points such as ``"42"`` when ``is_points``),
    ``date`` the day it was given and ``edit_date`` its last change; ``weight`` is ``None`` for point marks.
    ``confirmation_state`` is ``Confirmed`` or ``Unconfirmed`` where parents confirm marks, else empty.
    """

    id: str
    subject_id: str
    text: str
    caption: str = ""
    theme: str = ""
    date: Optional[dt.date] = None
    edit_date: Optional[dt.datetime] = None
    teacher_id: str = ""
    type: str = ""
    type_note: str = ""
    weight: Optional[int] = None
    is_new: bool = False
    is_points: bool = False
    points_text: str = ""
    max_points: int = 0
    calculated_text: str = ""
    class_rank_text: str = ""
    verbal_evaluation: str = ""
    is_invalid_date: bool = False
    confirmation_state: str = ""
    confirmed_at: Optional[dt.datetime] = None
    confirmed_by: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "Mark":
        """Parses one entry of a subject's ``Marks`` list."""
        return cls(
            id=ident(data.get("Id")),
            subject_id=ident(data.get("SubjectId")),
            text=text(data.get("MarkText")),
            caption=text(data.get("Caption")),
            theme=text(data.get("Theme")),
            date=parse_date(data.get("MarkDate")),
            edit_date=parse_datetime(data.get("EditDate")),
            teacher_id=ident(data.get("TeacherId")),
            type=text(data.get("Type")),
            type_note=text(data.get("TypeNote")),
            weight=to_int(data.get("Weight")),
            is_new=to_bool(data.get("IsNew")),
            is_points=to_bool(data.get("IsPoints")),
            points_text=text(data.get("PointsText")),
            max_points=to_int(data.get("MaxPoints")) or 0,
            calculated_text=text(data.get("CalculatedMarkText")),
            class_rank_text=text(data.get("ClassRankText")),
            verbal_evaluation=text(data.get("VerbalEvaluation")),
            is_invalid_date=to_bool(data.get("IsInvalidDate")),
            confirmation_state=text(data.get("MarkConfirmationState")),
            confirmed_at=parse_datetime(data.get("ConfirmedWhen")),
            confirmed_by=ident(data.get("ConfirmedBy")),
            raw=dict(data),
        )

    @property
    def is_confirmed(self) -> bool:
        """True when the server reports the mark as confirmed by a parent (``MarkConfirmationState`` ``Confirmed``)."""
        return self.confirmation_state.casefold() == "confirmed"

    @property
    def is_unconfirmed(self) -> bool:
        """True when the mark waits for a parent's confirmation (``Unconfirmed``); False for confirmed marks and on
        servers that send no confirmation state."""
        return self.confirmation_state.casefold() == "unconfirmed"

    @property
    def is_hypothetical(self) -> bool:
        """True for a hypothetical mark of a prediction result, which has no id."""
        return not self.id

    @property
    def numeric_value(self) -> Optional[float]:
        """The value of a Czech classic mark: ``"1"`` to ``"5"``, a trailing ``-`` adding 0.5 (``"1-"`` is 1.5; there
        is no ``"5-"``); ``None`` for point marks and for marks such as ``"N"``, ``"X"``, ``"?"`` or ``"A"``."""
        return None if self.is_points else _classic_value(self.text)

    def what_if_entry(self) -> Dict[str, Any]:
        """The mark as one entry of a :meth:`~MarksEndpoints.what_if` request: ``{Id, MarkText, Weight, MaxPoints,
        SubjectId}``, with ``Id`` null for a hypothetical mark."""
        return {
            "Id": self.id or None,
            "MarkText": self.text,
            "Weight": self.weight,
            "MaxPoints": self.max_points,
            "SubjectId": self.subject_id,
        }

    def format(self) -> str:
        """One readable line: date, mark (points as ``42/50``), weight, caption, theme, type, verbal evaluation and
        the new, unconfirmed and hypothetical flags."""
        value = self.text or "-"
        if self.is_points and self.max_points:
            value = f"{value}/{self.max_points}"
        weight = f"weight {self.weight}" if self.weight is not None else ""
        title = ": ".join(part for part in (self.caption, self.theme) if part)
        if self.type_note:
            title = f"{title} ({self.type_note})" if title else self.type_note
        if self.verbal_evaluation:
            title = f"{title} - {self.verbal_evaluation}" if title else self.verbal_evaluation
        states = (("new", self.is_new), ("unconfirmed", self.is_unconfirmed), ("hypothetical", self.is_hypothetical))
        flags = [name for name, on in states if on]
        date = self.date.isoformat() if self.date else "-"
        line = f"{date:<10}  {value:<7} {weight:<9} {_one_line(title)}".rstrip()
        return line + (f" [{', '.join(flags)}]" if flags else "")


@dataclass(frozen=True)
class SubjectMarks(Model):
    """A subject with its marks: an entry of ``GET /api/3/marks`` and the result of a mark prediction.

    ``average_text`` is the average as the server formats it (``"2,86"``, may be empty) and ``average`` its value
    (``None`` when it is not a finite number); ``prediction_enabled`` (``MarkPredictionEnabled``) tells whether
    :meth:`~MarksEndpoints.predict_marks` works.
    """

    subject: Item
    marks: Tuple[Mark, ...] = ()
    average_text: str = ""
    average: Optional[float] = None
    temporary_mark: str = ""
    temporary_mark_note: str = ""
    subject_note: str = ""
    points_only: bool = False
    prediction_enabled: bool = False
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Any, *, validate: bool = True) -> "SubjectMarks":
        """Parses a subject object; with ``validate`` (default) one without its ``Subject`` object or its ``Marks``
        list raises :class:`BakalariContractError`. A non-object always does."""
        if validate:
            check_shape(data, "subject entry", lists=("Marks",), objects_=("Subject",))
        data = require_mapping(data, "subject entry")
        average_text = text(data.get("AverageText"))
        return cls(
            subject=Item.from_json(mapping(data.get("Subject"))),
            marks=tuple(Mark.from_json(mark) for mark in objects(data.get("Marks"))),
            average_text=average_text,
            average=_finite(to_float(average_text)),
            temporary_mark=text(data.get("TemporaryMark")),
            temporary_mark_note=text(data.get("TemporaryMarkNote")),
            subject_note=text(data.get("SubjectNote")),
            points_only=to_bool(data.get("PointsOnly")),
            prediction_enabled=to_bool(data.get("MarkPredictionEnabled")),
            raw=dict(data),
        )

    @property
    def new_marks(self) -> List[Mark]:
        """The marks the server flags as new (``IsNew``)."""
        return [mark for mark in self.marks if mark.is_new]

    @property
    def unconfirmed_marks(self) -> List[Mark]:
        """The marks that wait for a parent's confirmation."""
        return [mark for mark in self.marks if mark.is_unconfirmed]

    def format_summary(self) -> str:
        """One readable line: subject abbreviation and name, average, number of marks and the temporary mark."""
        name = " ".join(part for part in (self.subject.abbrev, self.subject.name) if part) or self.subject.id.strip()
        line = f"{name}: average {self.average_text or '-'}, {len(self.marks)} mark(s)"
        return line + (f", temporary mark {self.temporary_mark}" if self.temporary_mark else "")

    def format(self) -> str:
        """The summary line followed by one indented line per mark (see :meth:`Mark.format`)."""
        return "\n".join([self.format_summary()] + ["    " + mark.format() for mark in self.marks])


@dataclass(frozen=True)
class Marks(Model):
    """The marks of the current school year by subject (``GET /api/3/marks``) and the school's mark options."""

    subjects: Tuple[SubjectMarks, ...] = ()
    mark_options: Tuple[Item, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Any, *, validate: bool = True) -> "Marks":
        """Parses a marks payload. With ``validate`` (default) a payload without the ``Subjects`` list, or with a
        subject that lacks its ``Subject`` object or ``Marks`` list, raises :class:`BakalariContractError` listing
        every problem; without it such entries parse with defaults. A non-object always raises."""
        if validate:
            _check_nested(data, "marks response", "Subjects", lists=("Marks",), objects_=("Subject",))
        data = require_mapping(data, "marks response")
        return cls(
            subjects=tuple(SubjectMarks.from_json(entry, validate=False) for entry in objects(data.get("Subjects"))),
            mark_options=tuple(Item.from_json(option) for option in objects(data.get("MarkOptions"))),
            raw=dict(data),
        )

    @property
    def all_marks(self) -> List[Mark]:
        """Every mark, subject by subject in the server's order."""
        return [mark for subject in self.subjects for mark in subject.marks]

    @property
    def new_marks(self) -> List[Mark]:
        """The marks the server flags as new (``IsNew``)."""
        return [mark for mark in self.all_marks if mark.is_new]

    @property
    def unconfirmed_marks(self) -> List[Mark]:
        """The marks that wait for a parent's confirmation (see :meth:`MarksEndpoints.confirm_marks`)."""
        return [mark for mark in self.all_marks if mark.is_unconfirmed]

    def subject(self, key: Union[str, Item]) -> Optional[SubjectMarks]:
        """The subject with the given id (exact, or without the padding: ``"4"`` finds ``" 4"``), abbreviation or
        name (ignoring case), or else ``None``. An :class:`Item`, such as a timetable lesson's subject, matches by its
        id first and then by its abbreviation and name."""
        return _find(self.subjects, lambda entry: entry.subject, key)

    def mark_option(self, mark: Union[Mark, str]) -> Optional[Item]:
        """The mark option of a mark or a mark text (its ``name`` describes the mark), or ``None``."""
        wanted = mark.text if isinstance(mark, Mark) else text(mark)
        if not wanted:
            return None
        for option in self.mark_options:
            if option.id.strip() == wanted:
                return option
        return next((option for option in self.mark_options if option.abbrev == wanted), None)

    def format(self) -> str:
        """Readable marks: per subject a summary line followed by its marks (see :meth:`SubjectMarks.format`)."""
        return "\n".join(subject.format() for subject in self.subjects)


@dataclass(frozen=True)
class FinalMark(Model):
    """A mark on a certificate. ``subject`` is resolved from the term's subject list (``None`` if it is not there);
    ``date`` is when the mark was entered."""

    id: str
    subject_id: str
    text: str
    subject: Optional[Item] = None
    date: Optional[dt.datetime] = None
    edit_date: Optional[dt.datetime] = None
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any], subjects: Optional[Mapping[str, Item]] = None) -> "FinalMark":
        """Parses one entry of a term's ``FinalMarks``; ``subjects`` maps the term's subject ids to their items."""
        subject_id = ident(data.get("SubjectId"))
        index, wanted = subjects or {}, subject_id.strip()
        subject = index.get(subject_id) if wanted else None
        if wanted and subject is None:
            subject = next((item for key, item in index.items() if key.strip() == wanted), None)
        return cls(
            id=ident(data.get("Id")),
            subject_id=subject_id,
            text=text(data.get("MarkText")),
            subject=subject,
            date=parse_datetime(data.get("MarkDate")),
            edit_date=parse_datetime(data.get("EditDate")),
            raw=dict(data),
        )

    @property
    def numeric_value(self) -> Optional[float]:
        """The value of a classic mark (``"1"`` to ``"5"``), ``None`` for marks such as ``"N"`` (not graded)."""
        return _classic_value(self.text)


@dataclass(frozen=True)
class CertificateTerm(Model):
    """The certificate of one term (``GET /api/3/marks/final``): its final marks, the overall result
    (``achievement_text``, e.g. "prospěl s vyznamenáním"), the average and the absence."""

    school_year: str
    semester: str
    semester_name: str = ""
    grade: Optional[int] = None
    grade_name: str = ""
    year_in_school: Optional[int] = None
    final_marks: Tuple[FinalMark, ...] = ()
    subjects: Tuple[Item, ...] = ()
    achievement_text: str = ""
    marks_average: Optional[float] = None
    absent_hours: Optional[int] = None
    not_excused_hours: Optional[int] = None
    certificate_date: Optional[dt.date] = None
    repeated: bool = False
    closed: bool = False
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "CertificateTerm":
        """Parses one entry of ``CertificateTerms``, resolving each final mark's subject."""
        subjects = tuple(Item.from_json(subject) for subject in objects(data.get("Subjects")))
        index = {subject.id: subject for subject in subjects}
        return cls(
            school_year=text(data.get("SchoolYear")),
            semester=text(data.get("Semester")),
            semester_name=text(data.get("SemesterName")),
            grade=to_int(data.get("Grade")),
            grade_name=text(data.get("GradeName")),
            year_in_school=to_int(data.get("YearInSchool")),
            final_marks=tuple(FinalMark.from_json(mark, index) for mark in objects(data.get("FinalMarks"))),
            subjects=subjects,
            achievement_text=text(data.get("AchievementText")),
            marks_average=_finite(to_float(data.get("MarksAverage"))),
            absent_hours=to_int(data.get("AbsentHours")),
            not_excused_hours=to_int(data.get("NotExcusedHours")),
            certificate_date=parse_date(data.get("CertificateDate")),
            repeated=to_bool(data.get("Repeated")),
            closed=to_bool(data.get("Closed")),
            raw=dict(data),
        )

    def final_mark(self, key: Union[str, Item]) -> Optional[FinalMark]:
        """The final mark of the subject with the given id, abbreviation or name (as :meth:`Marks.subject`), or
        ``None``."""
        return _find(self.final_marks, lambda mark: mark.subject or Item(mark.subject_id, "", ""), key)

    def format(self) -> str:
        """Readable certificate: a summary line followed by one indented line per final mark."""
        details = [self.achievement_text] if self.achievement_text else []
        if self.marks_average is not None:
            details.append(f"average {self.marks_average:.2f}")
        if self.absent_hours is not None:
            unexcused = f" ({self.not_excused_hours} unexcused)" if self.not_excused_hours is not None else ""
            details.append(f"absent {self.absent_hours} h{unexcused}")
        head = " ".join(_term_parts(self.school_year, self.semester))
        if self.certificate_date:
            head += f" ({self.certificate_date.isoformat()})"
        lines = [head + (": " + ", ".join(details) if details else "")]
        for mark in self.final_marks:
            subject = mark.subject
            label = " ".join(part for part in (subject.abbrev, subject.name) if part) if subject else ""
            lines.append(f"    {label or mark.subject_id.strip()}: {mark.text or '-'}")
        return "\n".join(lines)


@dataclass(frozen=True)
class PedagogicalMeasure(Model):
    """A praise or a reprimand (``GET /api/3/marks/measures``). ``type_id`` is the school's code (e.g. ``dTU``),
    ``type_label`` its name and ``text`` the reason, decoded from the HTML entities the server sends."""

    date: Optional[dt.date]
    type_id: str
    type_label: str
    text: str
    school_year: str = ""
    semester: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "PedagogicalMeasure":
        """Parses one entry of ``PedagogicalMeasures``."""
        return cls(
            date=parse_date(data.get("Date")),
            type_id=ident(data.get("TypeId")),
            type_label=text(data.get("TypeLabel")),
            text=text(html.unescape(text(data.get("Text")))),
            school_year=text(data.get("SchoolYear")),
            semester=text(data.get("Semester")),
            raw=dict(data),
        )

    def format(self) -> str:
        """One readable line: date, type, text, school year and semester."""
        date = self.date.isoformat() if self.date else "-"
        line = f"{date} {self.type_label or self.type_id}".rstrip() + (f": {_one_line(self.text)}" if self.text else "")
        term = ", ".join(_term_parts(self.school_year, self.semester))
        return line + (f" ({term})" if term else "")


def parse_final_marks(data: Any, *, validate: bool = True) -> List[CertificateTerm]:
    """Parses a ``GET /api/3/marks/final`` payload into its certificate terms. With ``validate`` (default) a payload
    without the ``CertificateTerms`` list, or with a term that lacks its ``FinalMarks`` or ``Subjects`` list, raises
    :class:`BakalariContractError` listing every problem. A non-object always raises."""
    if validate:
        _check_nested(data, "final marks response", "CertificateTerms", lists=("FinalMarks", "Subjects"))
    data = require_mapping(data, "final marks response")
    return [CertificateTerm.from_json(term) for term in objects(data.get("CertificateTerms"))]


def parse_pedagogical_measures(data: Any, *, validate: bool = True) -> List[PedagogicalMeasure]:
    """Parses a ``GET /api/3/marks/measures`` payload. With ``validate`` (default) a payload without the
    ``PedagogicalMeasures`` list raises :class:`BakalariContractError`. A non-object always raises."""
    if validate:
        check_shape(data, "pedagogical measures response", lists=("PedagogicalMeasures",))
    data = require_mapping(data, "pedagogical measures response")
    return [PedagogicalMeasure.from_json(measure) for measure in objects(data.get("PedagogicalMeasures"))]


def _what_if_objects(marks: Any) -> List[Dict[str, Any]]:
    if isinstance(marks, (str, bytes, abc.Mapping)) or not isinstance(marks, abc.Iterable):
        raise TypeError("what_if() expects a sequence of {Id, MarkText, Weight, MaxPoints, SubjectId} objects")
    body = []
    for entry in marks:
        if not isinstance(entry, abc.Mapping):
            raise TypeError(f"A what-if mark must be a mapping, got {type(entry).__name__}")
        body.append(dict(entry))
    return body


def _hypothetical_pairs(hypothetical: Any) -> List[Tuple[str, int]]:
    """The validated ``(mark_text, weight)`` pairs, read once, so that a generator works too."""
    if isinstance(hypothetical, (str, bytes, abc.Mapping)) or not isinstance(hypothetical, abc.Iterable):
        raise TypeError("The hypothetical marks must be an iterable of (mark_text, weight) pairs")
    pairs = []
    for pair in hypothetical:
        if isinstance(pair, (str, bytes)) or not isinstance(pair, abc.Sequence) or len(pair) != 2:
            raise TypeError(f"A hypothetical mark must be a (mark_text, weight) pair, got {pair!r}")
        mark_text, weight = pair
        if not isinstance(mark_text, str) or not mark_text.strip():
            raise ValueError(f"A hypothetical mark needs a mark text such as '1' or '2-', got {mark_text!r}")
        if isinstance(weight, bool) or not isinstance(weight, int):
            raise TypeError(f"The weight of a hypothetical mark must be an integer, got {weight!r}")
        pairs.append((mark_text.strip(), weight))
    return pairs


def _mark_ids(marks: Any) -> List[str]:
    if isinstance(marks, (str, Mark)):
        marks = [marks]
    if isinstance(marks, (bytes, abc.Mapping)) or not isinstance(marks, abc.Iterable):
        raise TypeError("confirm_marks() expects mark ids or Mark objects")
    ids = []
    for mark in marks:
        mark_id = mark.id if isinstance(mark, Mark) else mark
        if not isinstance(mark_id, str) or not mark_id.strip():
            raise ValueError(f"Not a mark id: {mark_id!r}")
        ids.append(mark_id)
    return list(dict.fromkeys(ids))


class MarksEndpoints(ClientCore):
    """Marks endpoints of :class:`~bakalari.BakalariClient`."""

    def marks(self, *, since: Optional[DateLike] = None, validate: bool = True) -> Marks:
        """``GET /api/3/marks``: the subjects of the current school year with their marks and averages, and the
        school's mark options. With ``since`` (``?from=YYYY-MM-DD``) the server returns only the marks from that day
        on."""
        data = self.get_json(api_path("marks"), {"from": format_date(since)})
        return Marks.from_json(data, validate=validate)

    def new_marks_count(self) -> int:
        """``GET /api/3/marks/count-new``: the server's counter of new marks. It is often 0 even when marks are
        flagged new (presumably it counts marks not yet announced by a push notification); :attr:`Marks.new_marks`
        lists the marks flagged ``IsNew``."""
        return require_int(self.get_json(api_path("marks", "count-new")), "new marks count")

    def final_marks(self, *, validate: bool = True) -> List[CertificateTerm]:
        """``GET /api/3/marks/final``: the certificates of every term since the start of the studies, oldest first,
        each with its final marks."""
        return parse_final_marks(self.get_json(api_path("marks", "final")), validate=validate)

    def pedagogical_measures(self, *, validate: bool = True) -> List[PedagogicalMeasure]:
        """``GET /api/3/marks/measures``: the praises and reprimands of the whole study."""
        return parse_pedagogical_measures(self.get_json(api_path("marks", "measures")), validate=validate)

    def what_if(self, marks: Sequence[Mapping[str, Any]], *, validate: bool = True) -> SubjectMarks:
        """``POST /api/3/marks/what-if``: recomputes one subject for a JSON list of ``{Id, MarkText, Weight,
        MaxPoints, SubjectId}`` objects, its current marks plus hypothetical ones with ``Id`` null (see
        :meth:`Mark.what_if_entry` and :meth:`predict_marks`). HTTP 403 when prediction is disabled for the subject."""
        data = self.post_json(api_path("marks", "what-if"), json_body=_what_if_objects(marks))
        return SubjectMarks.from_json(data, validate=validate)

    def predict_marks(
        self,
        subject: Union[SubjectMarks, Item, str],
        hypothetical: Iterable[Tuple[str, int]],
        *,
        marks: Optional[Marks] = None,
        validate: bool = True,
    ) -> SubjectMarks:
        """``POST /api/3/marks/what-if``: the subject as it would be with additional hypothetical classic marks, given
        as ``(mark_text, weight)`` pairs such as ``[("1", 3), ("2-", 5)]``; ``average`` is the predicted average.

        ``subject`` is a :class:`SubjectMarks`, or an :class:`~bakalari.Item` or a subject id, abbreviation or name
        looked up in ``marks`` (fetched with :meth:`marks` when not given). The server computes the average from the
        marks sent, so use marks fetched without ``since``. The request carries the subject's current marks and the
        hypothetical ones (``Id`` null, ``MaxPoints`` 0; send hypothetical point marks with :meth:`what_if`). The
        server answers HTTP 403 (:class:`~bakalari.BakalariPermissionError`) when prediction is disabled for the
        subject (``prediction_enabled``) or the account lacks the right ``PredictMarks``.
        """
        pairs = _hypothetical_pairs(hypothetical)  # rejects bad input before any request
        if isinstance(subject, SubjectMarks):
            target = subject
        else:
            found = (marks if marks is not None else self.marks(validate=validate)).subject(subject)
            if found is None:
                raise ValueError(f"No subject {subject!r} among the marks")
            target = found
        subject_id = target.subject.id or next((mark.subject_id for mark in target.marks if mark.subject_id), "")
        body = [mark.what_if_entry() for mark in target.marks]
        body += [
            {"Id": None, "MarkText": mark_text, "Weight": weight, "MaxPoints": 0, "SubjectId": subject_id}
            for mark_text, weight in pairs
        ]
        return self.what_if(body, validate=validate)

    def confirm_marks(self, mark_ids: Union[str, Mark, Iterable[Union[str, Mark]]]) -> bool:
        """``POST /api/3/marks/SetClassificationConfirmation``: confirms (signs) marks as a parent, given as mark ids
        or :class:`Mark` objects (e.g. :attr:`Marks.unconfirmed_marks`). Returns True when the server confirmed them
        (HTTP 200) and False when there was nothing to confirm (HTTP 204, or no ids: then no request is sent). Needs
        the right ``CanConfirmClassification``."""
        ids = _mark_ids(mark_ids)
        if not ids:
            return False
        path = api_path("marks", "SetClassificationConfirmation")
        return self.request("POST", path, json_body=ids, expected_status=(200, 204)).status == 200
