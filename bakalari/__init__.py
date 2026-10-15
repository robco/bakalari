"""Python client for the Bakaláři school information system REST API v3, built on the standard library only."""
from ._version import __version__
from .absence import Absence, AbsenceDay, SubjectAbsence
from .client import (
    API_PATH,
    BASE_URL_ENV,
    DEFAULT_CLIENT_ID,
    PASSWORD_ENV,
    TOKEN_PATH,
    USERNAME_ENV,
    BakalariClient,
    HttpResponse,
    SessionState,
    TokenInfo,
    Transport,
    normalize_base_url,
    urllib_transport,
)
from .errors import (
    BakalariAuthError,
    BakalariConfigError,
    BakalariConnectionError,
    BakalariContractError,
    BakalariError,
    BakalariHTTPError,
    BakalariNotFoundError,
    BakalariPermissionError,
    TimetableContractError,
)
from .events import Event, EventTime
from .gdpr import Commissioner, Consent
from .homeworks import Homework
from .komens import (
    AttachmentFile,
    Message,
    MessagePerson,
    MessageRecipient,
    MessageType,
    MessageTypes,
    Recipient,
    RecipientType,
    Sender,
)
from .marks import CertificateTerm, FinalMark, Mark, Marks, PedagogicalMeasure, SubjectMarks
from .models import AttachmentInfo, Item, Model
from .payments import ClassFundItem, ClassFundMonth, ClassFundPaymentInfo, ClassFundSummary
from .public_timetable import (
    PublicDay,
    PublicLesson,
    PublicTarget,
    PublicTargets,
    PublicTimetable,
    parse_public_targets,
    parse_public_timetable,
)
from .schools import DIRECTORY_URL, Municipality, School, SchoolDirectory
from .subjects import SubjectInfo, SubjectThemes, Theme, find_subject
from .substitutions import Substitutions
from .teacher import (
    ClassBook,
    ClassBookDay,
    ClassBookGroup,
    ClassBookRecord,
    LessonPast,
    LessonTag,
    MarkingAtom,
    MarkingMark,
    MarkingSheet,
    MarkingStudent,
)
from .timetable import (
    CHANGE_TYPES,
    DAY_TYPES,
    Change,
    ChangeLessonInfo,
    Day,
    Hour,
    Lesson,
    LessonHomework,
    Timetable,
    contract_problems,
    to_date,
    validate_timetable,
    week_of,
)
from .user import ModuleRights, SchoolYear, Semester, StudentInfo, UserProfile, WebModule, WebModules

__all__ = [
    "__version__",
    # The client, its configuration and the HTTP layer
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
    # Errors
    "BakalariAuthError",
    "BakalariConfigError",
    "BakalariConnectionError",
    "BakalariContractError",
    "BakalariError",
    "BakalariHTTPError",
    "BakalariNotFoundError",
    "BakalariPermissionError",
    "TimetableContractError",
    # Building blocks of the models
    "AttachmentInfo",
    "Item",
    "Model",
    # The account: profile, modules and rights, web modules (bakalari.user)
    "ModuleRights",
    "SchoolYear",
    "Semester",
    "StudentInfo",
    "UserProfile",
    "WebModule",
    "WebModules",
    # The public school directory, no login (bakalari.schools)
    "DIRECTORY_URL",
    "Municipality",
    "School",
    "SchoolDirectory",
    # Timetable (bakalari.timetable)
    "CHANGE_TYPES",
    "DAY_TYPES",
    "Change",
    "ChangeLessonInfo",
    "Day",
    "Hour",
    "Lesson",
    "LessonHomework",
    "Timetable",
    "contract_problems",
    "to_date",
    "validate_timetable",
    "week_of",
    # Substitutions (bakalari.substitutions)
    "Substitutions",
    # Marks (bakalari.marks)
    "CertificateTerm",
    "FinalMark",
    "Mark",
    "Marks",
    "PedagogicalMeasure",
    "SubjectMarks",
    # Absence (bakalari.absence)
    "Absence",
    "AbsenceDay",
    "SubjectAbsence",
    # Subjects and their themes (bakalari.subjects)
    "SubjectInfo",
    "SubjectThemes",
    "Theme",
    "find_subject",
    # Homeworks (bakalari.homeworks)
    "Homework",
    # Events (bakalari.events)
    "Event",
    "EventTime",
    # Komens messages (bakalari.komens)
    "AttachmentFile",
    "Message",
    "MessagePerson",
    "MessageRecipient",
    "MessageType",
    "MessageTypes",
    "Recipient",
    "RecipientType",
    "Sender",
    # GDPR (bakalari.gdpr)
    "Commissioner",
    "Consent",
    # Payments (bakalari.payments)
    "ClassFundItem",
    "ClassFundMonth",
    "ClassFundPaymentInfo",
    "ClassFundSummary",
    # Teacher accounts: class book, lessons, marking (bakalari.teacher)
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
    # The public timetable pages, no login (bakalari.public_timetable)
    "PublicDay",
    "PublicLesson",
    "PublicTarget",
    "PublicTargets",
    "PublicTimetable",
    "parse_public_targets",
    "parse_public_timetable",
]
