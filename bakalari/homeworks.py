"""Homeworks: listing, the open-homework counter and marking a homework done.

``GET /api/3/homeworks`` lists the homeworks given or due between ``from`` and ``to`` (by default the server uses 14
days back to one day ahead). ``Done`` is the teacher's flag (the homework was handed in), ``Finished`` the student's
own tick, which ``PUT /api/3/homeworks/{id}/student-done/{true|false}`` sets, and ``Closed`` marks a homework that is
no longer current. Attachments are downloaded with
:meth:`BakalariClient.download_attachment <bakalari.BakalariClient.download_attachment>`.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional, Tuple, Union

from ._core import ClientCore, api_path
from ._parse import (
    DateLike,
    check_shape,
    compact,
    format_date,
    ident,
    objects,
    parse_date,
    quote_segment,
    require_int,
    require_mapping,
    text,
    to_bool,
    to_int,
)
from .errors import BakalariError
from .models import AttachmentInfo, Item, Model

__all__ = ["Homework", "HomeworksEndpoints", "parse_homeworks"]


@dataclass(frozen=True)
class Homework(Model):
    """A homework (an entry of ``GET /api/3/homeworks``): ``start`` is the day it was given (``DateStart``), ``end``
    the day it is due (``DateEnd``) and ``hour`` its lesson number. ``done`` is set by the teacher once it is handed
    in, ``finished`` by the student (:meth:`~HomeworksEndpoints.set_homework_done`), ``closed`` when it is no longer
    current and ``electronic`` for a homework handed in electronically (on the web). ``school_class``, ``group``,
    ``subject`` and ``teacher`` are ``None`` when the server leaves them out."""

    id: str
    start: Optional[dt.date] = None
    end: Optional[dt.date] = None
    content: str = ""
    notice: str = ""
    done: bool = False
    closed: bool = False
    finished: bool = False
    electronic: bool = False
    hour: Optional[int] = None
    school_class: Optional[Item] = None
    group: Optional[Item] = None
    subject: Optional[Item] = None
    teacher: Optional[Item] = None
    attachments: Tuple[AttachmentInfo, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "Homework":
        """Parses one entry of ``Homeworks``; servers before API 3.14 send no ``Finished`` (it stays False)."""
        return cls(
            id=ident(data.get("ID")),
            start=parse_date(data.get("DateStart")),
            end=parse_date(data.get("DateEnd")),
            content=text(data.get("Content")),
            notice=text(data.get("Notice")),
            done=to_bool(data.get("Done")),
            closed=to_bool(data.get("Closed")),
            finished=to_bool(data.get("Finished")),
            electronic=to_bool(data.get("Electronic")),
            hour=to_int(data.get("Hour")),
            school_class=Item.optional(data.get("Class")),
            group=Item.optional(data.get("Group")),
            subject=Item.optional(data.get("Subject")),
            teacher=Item.optional(data.get("Teacher")),
            attachments=tuple(AttachmentInfo.from_json(item) for item in objects(data.get("Attachments"))),
            raw=dict(data),
        )

    @property
    def is_active(self) -> bool:
        """True while the homework is not closed; :meth:`~HomeworksEndpoints.active_homeworks_count` counts these."""
        return not self.closed


def parse_homeworks(data: Any, *, validate: bool = True) -> List[Homework]:
    """Parses a ``GET /api/3/homeworks`` payload into the homeworks in the server's order. With ``validate``
    (default) a payload without a ``Homeworks`` list of objects raises :class:`~bakalari.BakalariContractError`; a
    payload that is not a JSON object always does."""
    if validate:
        check_shape(data, "homework list", lists=("Homeworks",))
    payload = require_mapping(data, "homework list")
    return [Homework.from_json(homework) for homework in objects(payload.get("Homeworks"))]


class HomeworksEndpoints(ClientCore):
    """Homework endpoints of :class:`~bakalari.BakalariClient`."""

    def homeworks(
        self, since: Optional[DateLike] = None, until: Optional[DateLike] = None, *, validate: bool = True
    ) -> List[Homework]:
        """``GET /api/3/homeworks?from=&to=``: the homeworks given or due between ``since`` and ``until`` (dates,
        datetimes or ISO strings; the server defaults to 14 days back and one day ahead). An invalid date string
        answers HTTP 400 (:class:`~bakalari.BakalariHTTPError`). Module Homeworks, right ``ShowHomeworks``."""
        params = compact({"from": format_date(since), "to": format_date(until)})
        return parse_homeworks(self.get_json(api_path("homeworks"), params), validate=validate)

    def active_homeworks_count(self) -> int:
        """``GET /api/3/homeworks/count-actual``: the number of current homeworks (those not closed)."""
        return require_int(self.get_json(api_path("homeworks", "count-actual")), "active homework count")

    def set_homework_done(self, homework_id: Union[str, Homework], done: bool = True) -> None:
        """``PUT /api/3/homeworks/{id}/student-done/{true|false}``: ticks a homework as finished by the student, or
        unticks it with ``done=False``; this is its ``finished`` flag (``done`` stays the teacher's). ``homework_id``
        is an id or a :class:`Homework`. The request has no body; the server answers HTTP 200 with the text ``true``
        (HTTP 204 is accepted too), which is not decoded as JSON. An explicit ``false`` answer means the change was
        not made and raises :class:`~bakalari.BakalariError`. An id that contains a backslash cannot be addressed:
        IIS answers HTTP 404 (:class:`~bakalari.BakalariNotFoundError`), and other characters IIS refuses in a URL
        path (see :meth:`~bakalari.BakalariClient.subject_themes`) fail alike; homework ids no longer contain such
        characters since server version 26.0.429.0."""
        key = homework_id.id if isinstance(homework_id, Homework) else ident(homework_id)
        if not key:
            raise ValueError("set_homework_done() needs a homework id")
        path = api_path("homeworks", quote_segment(key), "student-done", "true" if done else "false")
        response = self.request("PUT", path, expected_status=(200, 204))
        if response.text.lstrip("\ufeff").strip().strip('"').strip().lower() == "false":
            state = "finished" if done else "not finished"
            raise BakalariError(f"Bakaláři API PUT {path} answered false: the homework was not marked {state}")
