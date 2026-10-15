"""The account: profile, enabled modules and rights, presence at school, web modules and web login tokens.

``GET /api/3/user`` describes the logged-in account: its type (``parents``, ``student`` or ``teacher``), names,
class and school, the students of a parent account, the enabled modules with the account's rights in each, and the
module settings (``SettingModules``), which also carry the current semester and school year. A one-time token from
``GET /api/3/logintoken`` opens the Bakaláři web already logged in (``/api/3/login/<token>?returnUrl=...``).
"""
from __future__ import annotations

import datetime as dt
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional, Tuple

from ._core import ClientCore, api_path
from ._parse import (
    check_shape,
    ident,
    mapping,
    objects,
    parse_date,
    quote_segment,
    require_mapping,
    shape_problems,
    strings,
    text,
    to_int,
)
from .errors import BakalariContractError
from .models import Item, Model

__all__ = [
    "ModuleRights",
    "SchoolYear",
    "Semester",
    "StudentInfo",
    "UserEndpoints",
    "UserProfile",
    "WebModule",
    "WebModules",
]


@dataclass(frozen=True)
class ModuleRights(Model):
    """A module enabled for the account (``Komens``, ``Marks``, ...) with the account's rights in it, e.g.
    ``SendMessages`` or ``CanConfirmClassification``."""

    module: str
    rights: Tuple[str, ...] = ()

    def allows(self, right: str) -> bool:
        """True when the module grants ``right`` (compared case-insensitively)."""
        wanted = right.strip().casefold()
        return any(own.casefold() == wanted for own in self.rights)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "ModuleRights":
        """Parses an ``EnabledModules`` entry (``{"Module": ..., "Rights": [...]}``)."""
        rights = (text(right) for right in strings(data.get("Rights")))
        return cls(module=text(data.get("Module")), rights=tuple(right for right in rights if right))


@dataclass(frozen=True)
class Semester(Model):
    """The current semester (pololetí) from ``SettingModules.Common.ActualSemester``: ``id`` is ``"1"`` or ``"2"``,
    ``start`` and ``end`` are its first and last day."""

    id: str
    start: Optional[dt.date] = None
    end: Optional[dt.date] = None

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "Semester":
        """Parses ``{"SemesterId", "From", "To"}``."""
        return cls(id=ident(data.get("SemesterId")), start=parse_date(data.get("From")), end=parse_date(data.get("To")))

    @classmethod
    def optional(cls, data: Any) -> Optional["Semester"]:
        """Parses an object that may be missing or ``null`` (the server may leave the semester out during the
        summer holidays); an object without an id and dates is ``None`` too."""
        if not isinstance(data, Mapping):
            return None
        semester = cls.from_json(data)
        return semester if (semester.id.strip() or semester.start or semester.end) else None


@dataclass(frozen=True)
class SchoolYear(Model):
    """The current school year from ``SettingModules.Common.ActualSchoolYear``: ``name`` such as ``"2026/27"``,
    ``start`` and ``end`` its effective first and last day."""

    id: str
    name: str = ""
    start: Optional[dt.date] = None
    end: Optional[dt.date] = None

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "SchoolYear":
        """Parses ``{"Id", "Name", "EffectiveStartDate", "EffectiveEndDate"}``."""
        return cls(
            id=ident(data.get("Id")),
            name=text(data.get("Name")),
            start=parse_date(data.get("EffectiveStartDate")),
            end=parse_date(data.get("EffectiveEndDate")),
        )

    @classmethod
    def optional(cls, data: Any) -> Optional["SchoolYear"]:
        """Parses an object that may be missing or ``null`` (older servers do not send it); an object without an id,
        a name and dates is ``None`` too."""
        if not isinstance(data, Mapping):
            return None
        year = cls.from_json(data)
        return year if (year.id.strip() or year.name or year.start or year.end) else None


@dataclass(frozen=True)
class StudentInfo(Model):
    """A student of a parent account (``Students``). A parent with several children has one login per child."""

    full_name: str
    school_class: Optional[Item] = None
    school_type: str = ""
    study_year: Optional[int] = None
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "StudentInfo":
        """Parses a ``Students`` entry (``FullName``, ``Class``, ``SchoolType``, ``StudyYear``)."""
        return cls(
            full_name=text(data.get("FullName")),
            school_class=Item.optional(data.get("Class")),
            school_type=text(data.get("SchoolType")),
            study_year=to_int(data.get("StudyYear")),
            raw=dict(data),
        )


@dataclass(frozen=True)
class UserProfile(Model):
    """The logged-in account (``GET /api/3/user``); it holds personal data such as names, class and school.

    ``user_type`` is ``parents``, ``student`` or ``teacher`` (``user_type_text`` is the Czech label). For a parent
    account ``full_name`` is the student's name with the class, as in ``students``, and ``full_user_name`` the
    account holder's name (newer servers). ``modules`` lists the enabled modules with their rights, ``semester`` and
    ``school_year`` come from ``SettingModules.Common``, and ``settings`` keeps the whole ``SettingModules`` object
    (Komens, Marking, Timetable, Homeworks, ClassBook, Emergency, ... settings, each with a ``$type``).
    ``teacher_classes`` lists the ``TeacherClasses`` of a teacher account (``null`` for other accounts).
    """

    uid: str
    full_name: str = ""
    full_user_name: str = ""
    user_type: str = ""
    user_type_text: str = ""
    school_name: str = ""
    school_type: str = ""
    study_year: Optional[int] = None
    school_class: Optional[Item] = None
    teacher_classes: Tuple[Item, ...] = ()
    students: Tuple[StudentInfo, ...] = ()
    modules: Tuple[ModuleRights, ...] = ()
    semester: Optional[Semester] = None
    school_year: Optional[SchoolYear] = None
    campaign_category_code: str = ""
    settings: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Any, *, validate: bool = True) -> "UserProfile":
        """Parses a ``GET /api/3/user`` payload. With ``validate`` (default) a profile without a ``UserType`` string,
        or whose ``Class``, ``SettingModules``, ``EnabledModules`` or ``Students`` has the wrong JSON type, raises
        :class:`BakalariContractError`; missing optional parts (the semester and even the modules may be left out
        during the summer holidays) get defaults."""
        if validate:
            problems = shape_problems(
                data,
                "user profile",
                lists=[name for name in ("EnabledModules", "Students") if _present(data, name)],
                objects_=[name for name in ("Class", "SettingModules") if _present(data, name)],
            )
            if isinstance(data, Mapping) and not isinstance(data.get("UserType"), str):
                problems.append("Missing string 'UserType'")
            if problems:
                raise BakalariContractError(problems, "user profile")
        data = require_mapping(data, "user profile")
        settings = mapping(data.get("SettingModules"))
        common = mapping(settings.get("Common"))
        teacher_classes = (Item.optional(entry) for entry in objects(data.get("TeacherClasses")))
        return cls(
            uid=ident(data.get("UserUID")),
            full_name=text(data.get("FullName")),
            full_user_name=text(data.get("FullUserName")),
            user_type=text(data.get("UserType")),
            user_type_text=text(data.get("UserTypeText")),
            school_name=text(data.get("SchoolOrganizationName")),
            school_type=text(data.get("SchoolType")),
            study_year=to_int(data.get("StudyYear")),
            school_class=Item.optional(data.get("Class")),
            teacher_classes=tuple(item for item in teacher_classes if item is not None),
            students=tuple(StudentInfo.from_json(entry) for entry in objects(data.get("Students"))),
            modules=tuple(ModuleRights.from_json(entry) for entry in objects(data.get("EnabledModules"))),
            semester=Semester.optional(common.get("ActualSemester")),
            school_year=SchoolYear.optional(common.get("ActualSchoolYear")),
            campaign_category_code=ident(data.get("CampaignCategoryCode")),
            settings=dict(settings),
            raw=dict(data),
        )

    @property
    def is_parent(self) -> bool:
        """True for a parent account (``UserType`` ``parents``)."""
        return self.user_type.lower() == "parents"

    @property
    def is_student(self) -> bool:
        """True for a student account (``UserType`` ``student``)."""
        return self.user_type.lower() == "student"

    @property
    def is_teacher(self) -> bool:
        """True for a teacher account (``UserType`` ``teacher``)."""
        return self.user_type.lower() == "teacher"

    @property
    def module_names(self) -> List[str]:
        """Names of the enabled modules in the server's order, e.g. ``["Komens", "Absence", ...]``."""
        return [module.module for module in self.modules]

    def has_module(self, name: str) -> bool:
        """True when the module ``name`` (e.g. ``"Komens"``, compared case-insensitively) is enabled."""
        return self._module(name) is not None

    def rights_of(self, module: str) -> Tuple[str, ...]:
        """The account's rights in ``module`` (compared case-insensitively); empty when it is not enabled."""
        found = self._module(module)
        return found.rights if found else ()

    def has_right(self, module: str, right: str) -> bool:
        """True when ``module`` is enabled with ``right``, e.g. ``has_right("Marks", "PredictMarks")``."""
        found = self._module(module)
        return found.allows(right) if found else False

    def _module(self, name: str) -> Optional[ModuleRights]:
        wanted = name.strip().casefold()
        return next((module for module in self.modules if module.module.casefold() == wanted), None)


@dataclass(frozen=True)
class WebModule(Model):
    """A page of the Bakaláři web that the app links to: ``url`` is relative to the installation root (e.g.
    ``next/dokumentyPrehled.aspx``), so open it logged in with ``web_login_url(module.url)``. ``submenu`` is the
    server's ``SubMenu`` list as sent, or ``None``."""

    name: str
    url: str
    icon_id: str = ""
    submenu: Optional[Tuple[Any, ...]] = field(default=None, compare=False)
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "WebModule":
        """Parses a ``WebModules`` entry or the ``Dashboard`` (``IconId``, ``SubMenu``, ``Url``, ``Name``)."""
        submenu = data.get("SubMenu")
        return cls(
            name=text(data.get("Name")),
            url=text(data.get("Url")),
            icon_id=text(data.get("IconId")),
            submenu=tuple(submenu) if isinstance(submenu, list) else None,
            raw=dict(data),
        )


@dataclass(frozen=True)
class WebModules(Model):
    """The pages of the Bakaláři web the app offers (``GET /api/3/webmodule``): ``modules`` such as documents or
    teaching resources, and the ``dashboard`` (``next/dash.aspx``, without a name or an icon)."""

    modules: Tuple[WebModule, ...] = ()
    dashboard: Optional[WebModule] = None
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_json(cls, data: Any, *, validate: bool = True) -> "WebModules":
        """Parses a ``GET /api/3/webmodule`` payload. With ``validate`` (default) a payload without the
        ``WebModules`` list of objects raises :class:`BakalariContractError`."""
        if validate:
            check_shape(data, "web module list", lists=("WebModules",))
        data = require_mapping(data, "web module list")
        dashboard = data.get("Dashboard")
        return cls(
            modules=tuple(WebModule.from_json(entry) for entry in objects(data.get("WebModules"))),
            dashboard=WebModule.from_json(dashboard) if isinstance(dashboard, Mapping) else None,
            raw=dict(data),
        )


def _present(data: Any, name: str) -> bool:
    return isinstance(data, Mapping) and data.get(name) is not None


def _require_bool(data: Any, what: str) -> bool:
    """A bare JSON boolean payload (the strings ``true`` and ``false`` are accepted too), or
    :class:`BakalariContractError`."""
    if isinstance(data, bool):
        return data
    if isinstance(data, str) and data.strip().lower() in ("true", "false"):
        return data.strip().lower() == "true"
    raise BakalariContractError([f"The {what} must be a JSON boolean, got {type(data).__name__}"], what)


def _require_text(data: Any, what: str) -> str:
    """A bare, non-empty JSON string payload exactly as sent, or :class:`BakalariContractError` (whose message never
    contains the value, which may be a credential)."""
    if not isinstance(data, str):
        raise BakalariContractError([f"The {what} must be a JSON string, got {type(data).__name__}"], what)
    if not data.strip():
        raise BakalariContractError([f"The {what} is empty"], what)
    return data


class UserEndpoints(ClientCore):
    """Account endpoints of :class:`~bakalari.BakalariClient`."""

    def user_profile(self, *, validate: bool = True) -> UserProfile:
        """``GET /api/3/user``: the account's type, names, class and school, the students of a parent account, the
        enabled modules with their rights and the module settings, including the current semester and school year."""
        return UserProfile.from_json(self.get_json(api_path("user")), validate=validate)

    def enabled_modules(self) -> List[str]:
        """Names of the modules enabled for the account (from ``GET /api/3/user``), e.g. Timetable, Substitutions,
        Marks, Komens."""
        return self.user_profile(validate=False).module_names

    def student_at_school(self) -> bool:
        """``GET /api/3/user/student-at-school``: whether the school's access system registers the student at
        school now. Needs the AccessSystem module (right ``CanShowStudentPresentAtSchool``); otherwise the server
        answers 403 (:class:`~bakalari.BakalariPermissionError`)."""
        return _require_bool(self.get_json(api_path("user", "student-at-school")), "student-at-school answer")

    def web_modules(self, *, validate: bool = True) -> WebModules:
        """``GET /api/3/webmodule``: the pages of the Bakaláři web the app links to (documents, teaching resources,
        ...) and the dashboard."""
        return WebModules.from_json(self.get_json(api_path("webmodule")), validate=validate)

    def login_token(self) -> str:
        """``GET /api/3/logintoken``: a one-time token that logs in to the Bakaláři web through
        ``/api/3/login/<token>`` (see :meth:`web_login_url`). Treat it like a password until it is used."""
        return _require_text(self.get_json(api_path("logintoken")), "login token")

    def web_login_url(self, return_url: str = "next/dash.aspx") -> str:
        """A one-time link ``<base_url>/api/3/login/<token>?returnUrl=<return_url>`` with a fresh token from
        ``GET /api/3/logintoken``: opened in a browser, it logs in to the Bakaláři web and redirects to ``return_url``,
        a path relative to the installation root such as a :class:`WebModule` ``url`` (a used or expired token
        redirects to the login page). Anyone who opens the link is logged in, so treat it like a password."""
        url = self.base_url + api_path("login", quote_segment(self.login_token()))
        return url + "?returnUrl=" + urllib.parse.quote(return_url, safe="/") if return_url else url

    def register_notification(self, token: str) -> None:
        """``POST /api/3/register-notification?token=<token>`` with the JSON body ``null``: registers a push
        notification token (HTTP 200 or 204). The server expects the official app's Firebase token, so a
        third-party token may be rejected and receives no pushes; poll the counters (unread messages, new marks)
        instead."""
        if not token:
            raise ValueError("register_notification needs a push notification token")
        self.request(
            "POST",
            api_path("register-notification"),
            params={"token": token},
            data=b"null",
            headers={"Content-Type": "application/json; charset=utf-8"},
            expected_status=(200, 204),
        )
