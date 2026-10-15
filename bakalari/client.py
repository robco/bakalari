"""The Bakaláři REST API v3 client: :class:`BakalariClient` combines the endpoint modules on the client core.

Each module of this package (``marks``, ``komens``, ``timetable``, ...) holds the response models of one
Bakaláři module together with its endpoint methods; ``_core`` holds the configuration, the token lifecycle and
the request method they share.
"""
from __future__ import annotations

from ._core import (
    API_PATH,
    BASE_URL_ENV,
    DEFAULT_CLIENT_ID,
    PASSWORD_ENV,
    TOKEN_PATH,
    USERNAME_ENV,
    ClientCore,
    SessionState,
    TokenInfo,
    normalize_base_url,
)
from .absence import AbsenceEndpoints
from .events import EventsEndpoints
from .gdpr import GdprEndpoints
from .homeworks import HomeworksEndpoints
from .http import HttpResponse, Transport, urllib_transport
from .komens import KomensEndpoints
from .marks import MarksEndpoints
from .payments import PaymentsEndpoints
from .public_timetable import PublicTimetableEndpoints
from .subjects import SubjectsEndpoints
from .substitutions import SubstitutionsEndpoints
from .teacher import TeacherEndpoints
from .timetable import TimetableEndpoints
from .user import UserEndpoints

__all__ = [
    "API_PATH",
    "BASE_URL_ENV",
    "DEFAULT_CLIENT_ID",
    "PASSWORD_ENV",
    "TOKEN_PATH",
    "USERNAME_ENV",
    "BakalariClient",
    "HttpResponse",
    "SessionState",
    "TokenInfo",
    "Transport",
    "normalize_base_url",
    "urllib_transport",
]


class BakalariClient(
    UserEndpoints,
    TimetableEndpoints,
    MarksEndpoints,
    AbsenceEndpoints,
    SubjectsEndpoints,
    HomeworksEndpoints,
    EventsEndpoints,
    SubstitutionsEndpoints,
    KomensEndpoints,
    GdprEndpoints,
    PaymentsEndpoints,
    TeacherEndpoints,
    PublicTimetableEndpoints,
    ClientCore,
):
    """Client of one school's Bakaláři installation.

    >>> client = BakalariClient.from_env()          # BAKALARI_URL, BAKALARI_USERNAME, BAKALARI_PASSWORD
    >>> timetable = client.actual_timetable()        # logs in on the first authorized request
    >>> print(timetable.format())

    The typed endpoint methods come from the module of each Bakaláři area, which also defines the models they
    return: :mod:`~bakalari.user` (profile, modules and rights, presence at school, web login),
    :mod:`~bakalari.timetable`, :mod:`~bakalari.substitutions`, :mod:`~bakalari.marks`, :mod:`~bakalari.absence`,
    :mod:`~bakalari.subjects`, :mod:`~bakalari.homeworks`, :mod:`~bakalari.events`, :mod:`~bakalari.komens`
    (messages and attachments), :mod:`~bakalari.gdpr`, :mod:`~bakalari.payments`, :mod:`~bakalari.teacher` (teacher
    accounts only) and :mod:`~bakalari.public_timetable` (public pages, no login). An endpoint whose module or right
    the school has not enabled for the account raises :class:`~bakalari.BakalariPermissionError` (HTTP 403).

    See :class:`~bakalari._core.ClientCore` for the constructor arguments, the token handling and the generic
    :meth:`request`/:meth:`get_json` methods. The public school directory, which is not part of an installation,
    has its own client: :class:`~bakalari.SchoolDirectory`.
    """
