"""Absence of the student: per day and per subject.

``GET /api/3/absence/student`` returns ``PercentageThreshold`` (the share of missed lessons from which the school
highlights a subject, a fraction such as ``0.25``), ``Absences`` (the days with absence, each counted in lessons by
kind) and ``AbsencesPerSubject`` (lessons taught and missed per subject). The per-subject list is empty without the
``ShowAbsencePercentage`` right and may contain an entry without a subject name.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ._core import ClientCore, api_path
from ._parse import DateLike, check_shape, objects, parse_date, require_mapping, text, to_date, to_float, to_int
from .models import Model

__all__ = ["DAY_COUNTERS", "Absence", "AbsenceDay", "AbsenceEndpoints", "SubjectAbsence"]

# The lesson counters of a day, named like the AbsenceDay fields, in the server's order.
DAY_COUNTERS = ("unsolved", "ok", "missed", "late", "soon", "school", "distance_teaching")


def _count(value: Any) -> int:
    """A lesson counter; a missing, ``null`` or unparseable value counts as 0."""
    return to_int(value) or 0


@dataclass(frozen=True)
class AbsenceDay(Model):
    """The absence of one day in lessons by kind: ``unsolved`` (not yet excused or refused), ``ok`` (excused),
    ``missed`` (unexcused), ``late`` (late arrivals), ``soon`` (early leavings), ``school`` (absent for a school
    activity) and ``distance_teaching`` (missed distance lessons)."""

    date: Optional[dt.date]
    unsolved: int = 0
    ok: int = 0
    missed: int = 0
    late: int = 0
    soon: int = 0
    school: int = 0
    distance_teaching: int = 0
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "AbsenceDay":
        """Parses one entry of ``Absences``."""
        return cls(
            date=parse_date(data.get("Date")),
            unsolved=_count(data.get("Unsolved")),
            ok=_count(data.get("Ok")),
            missed=_count(data.get("Missed")),
            late=_count(data.get("Late")),
            soon=_count(data.get("Soon")),
            school=_count(data.get("School")),
            distance_teaching=_count(data.get("DistanceTeaching")),
            raw=dict(data),
        )

    def counts(self) -> Dict[str, int]:
        """The counters by name (see :data:`DAY_COUNTERS`), e.g. ``{"unsolved": 0, "ok": 5, ...}``."""
        return {name: getattr(self, name) for name in DAY_COUNTERS}

    @property
    def total(self) -> int:
        """Every absence record of the day: the sum of all counters."""
        return sum(self.counts().values())


@dataclass(frozen=True)
class SubjectAbsence(Model):
    """The absence in one subject: of ``lessons_count`` lessons taught so far the student missed ``base``;
    ``late``, ``soon``, ``school`` and ``distance_teaching`` count late arrivals, early leavings, absences for a
    school activity and missed distance lessons. ``subject_name`` may be empty (the server can list an entry without
    a subject name). ``percentage_threshold`` is the school's threshold of the whole payload, kept here for
    :attr:`over_threshold` and hidden from ``repr()`` and ``to_dict()``."""

    subject_name: str
    lessons_count: int = 0
    base: int = 0
    late: int = 0
    soon: int = 0
    school: int = 0
    distance_teaching: int = 0
    percentage_threshold: Optional[float] = field(default=None, compare=False, repr=False)
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any], percentage_threshold: Optional[float] = None) -> "SubjectAbsence":
        """Parses one entry of ``AbsencesPerSubject``; ``percentage_threshold`` is the payload's
        ``PercentageThreshold``."""
        return cls(
            subject_name=text(data.get("SubjectName")),
            lessons_count=_count(data.get("LessonsCount")),
            base=_count(data.get("Base")),
            late=_count(data.get("Late")),
            soon=_count(data.get("Soon")),
            school=_count(data.get("School")),
            distance_teaching=_count(data.get("DistanceTeaching")),
            percentage_threshold=percentage_threshold,
            raw=dict(data),
        )

    @property
    def percentage(self) -> Optional[float]:
        """The share of missed lessons, ``base / lessons_count`` (``0.25`` is 25 %), or ``None`` before the first
        lesson."""
        return self.base / self.lessons_count if self.lessons_count > 0 else None

    @property
    def over_threshold(self) -> bool:
        """True when :attr:`percentage` has reached the school's ``percentage_threshold``; False when either is
        unknown or the threshold is 0 (not set)."""
        percentage, threshold = self.percentage, self.percentage_threshold
        return percentage is not None and threshold is not None and threshold > 0 and percentage >= threshold


@dataclass(frozen=True)
class Absence(Model):
    """The student's absence (``GET /api/3/absence/student``): ``percentage_threshold`` is the share of missed
    lessons from which the school highlights a subject (a fraction, ``0.25`` is 25 %; ``None`` when not sent),
    ``days`` lists the days with absence and ``subjects`` the absence per subject, both in the server's order."""

    percentage_threshold: Optional[float]
    days: Tuple[AbsenceDay, ...] = ()
    subjects: Tuple[SubjectAbsence, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Any, *, validate: bool = True) -> "Absence":
        """Parses the payload. With ``validate`` (default) a payload without the ``Absences`` and
        ``AbsencesPerSubject`` lists of objects raises :class:`~bakalari.BakalariContractError`; without it, missing
        parts stay empty. A payload that is not a JSON object is always an error."""
        if validate:
            check_shape(data, "absence", lists=("Absences", "AbsencesPerSubject"))
        payload = require_mapping(data, "absence")
        threshold = to_float(payload.get("PercentageThreshold"))
        return cls(
            percentage_threshold=threshold,
            days=tuple(AbsenceDay.from_json(day) for day in objects(payload.get("Absences"))),
            subjects=tuple(
                SubjectAbsence.from_json(subject, threshold) for subject in objects(payload.get("AbsencesPerSubject"))
            ),
            raw=dict(payload),
        )

    def totals(self) -> Dict[str, int]:
        """The day counters summed over all days, keyed like the :class:`AbsenceDay` fields (``unsolved``, ``ok``,
        ``missed``, ``late``, ``soon``, ``school``, ``distance_teaching``)."""
        totals = dict.fromkeys(DAY_COUNTERS, 0)
        for day in self.days:
            for name, count in day.counts().items():
                totals[name] += count
        return totals

    def day(self, date: DateLike) -> Optional[AbsenceDay]:
        """The absence on ``date`` (a date, datetime or ISO string), or ``None`` for a day without absence; a string
        that is not an ISO date raises ``ValueError``."""
        wanted = to_date(date)
        return next((day for day in self.days if day.date == wanted), None)

    def subject(self, name: str) -> Optional[SubjectAbsence]:
        """The absence in the subject called ``name`` (case-insensitive, surrounding spaces ignored), or ``None``."""
        wanted = text(name).casefold()
        return next((subject for subject in self.subjects if subject.subject_name.casefold() == wanted), None)

    @property
    def subjects_over_threshold(self) -> List[SubjectAbsence]:
        """The subjects whose share of missed lessons has reached the threshold (see
        :attr:`SubjectAbsence.over_threshold`)."""
        return [subject for subject in self.subjects if subject.over_threshold]


class AbsenceEndpoints(ClientCore):
    """Absence endpoints of :class:`~bakalari.BakalariClient`."""

    def absence(self, *, validate: bool = True) -> Absence:
        """``GET /api/3/absence/student``: the student's absence per day and per subject with the school's
        percentage threshold (module Absence, right ``ShowAbsence``; the per-subject list is empty without the
        ``ShowAbsencePercentage`` right)."""
        return Absence.from_json(self.get_json(api_path("absence", "student")), validate=validate)
