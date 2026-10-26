"""Command line interface: the ``bakalari`` console script and ``python -m bakalari``.

``bakalari [global options] COMMAND [options]``: ``bakalari --help`` lists the commands by area and
``bakalari COMMAND --help`` describes one. The school's address comes from ``--base-url`` or ``BAKALARI_URL`` and the
login of the Bakaláři web from ``BAKALARI_USERNAME`` and ``BAKALARI_PASSWORD``; a session kept with ``--session-file``
makes the password unnecessary while its refresh token is valid. Text output strips control characters from server
strings; ``--json`` prints the data as JSON. Errors go to standard error as ``bakalari: error: ...`` and never contain
a token or a password.

Exit status: 0 success, 1 a Bakaláři API, connection or contract error, 2 a usage or configuration error.
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import datetime as dt
import html
import http
import json
import logging
import os
import re
import secrets
import shlex
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

from ._version import __version__
from .absence import Absence
from .client import (
    BASE_URL_ENV,
    PASSWORD_ENV,
    TOKEN_PATH,
    USERNAME_ENV,
    BakalariClient,
    HttpResponse,
    SessionState,
    normalize_base_url,
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
)
from .events import Event
from .gdpr import Commissioner, Consent
from .homeworks import Homework
from .komens import Message, MessageTypes, Recipient
from .marks import Mark, Marks, SubjectMarks
from .models import AttachmentInfo, Item
from .payments import ClassFundPaymentInfo
from .public_timetable import PublicTarget
from .schools import DEFAULT_MAX_REQUESTS, SchoolDirectory
from .subjects import SubjectInfo, Theme, find_subject
from .teacher import ClassBookDay, ClassBookRecord
from .timetable import CZECH_DAY_ABBREVIATIONS, Lesson, Timetable, week_of
from .user import UserProfile

__all__ = [
    "DEFAULT_RETRIES",
    "DEFAULT_TIMEOUT",
    "EXIT_ERROR",
    "EXIT_INTERRUPTED",
    "EXIT_OK",
    "EXIT_USAGE",
    "SESSION_FILE_ENV",
    "ClientFactory",
    "DirectoryFactory",
    "build_parser",
    "default_client_factory",
    "default_directory_factory",
    "main",
]

SESSION_FILE_ENV = "BAKALARI_SESSION_FILE"
DEFAULT_TIMEOUT = 30.0
DEFAULT_RETRIES = 2

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130

# Creates the client of a command from the parsed arguments; the flag tells whether the command needs a login.
ClientFactory = Callable[[argparse.Namespace, bool], BakalariClient]
# Creates the public school directory client of the ``schools`` command.
DirectoryFactory = Callable[[argparse.Namespace], SchoolDirectory]

# C0 and C1 control characters except tab and line feed: a server string (a title, a name, an HTML body, a file name)
# must not move the cursor, recolour or retitle the terminal.
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
# json.dumps escapes the C0 controls itself, but with ensure_ascii=False it leaves DEL and the C1 controls raw.
_RAW_IN_JSON = re.compile(r"[\x7f-\x9f]")
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_DIGITS = re.compile(r"[0-9]+")
_CHARSET = re.compile(r"charset=[\"']?([\w.-]+)", re.IGNORECASE)
_RELATIVE_DAYS = {"yesterday": -1, "today": 0, "tomorrow": 1}
_API_METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH")
_API_SUCCESS = (200, 201, 202, 204)
_PERMISSION_HINT = "the module or right this needs is not enabled for the account or the school"
_TEACHER_HINT = "this is available to teacher accounts only"
_ABSENCE_LABELS = {
    "unsolved": "unsolved",
    "ok": "excused",
    "missed": "unexcused",
    "late": "late",
    "soon": "left early",
    "school": "school activity",
    "distance_teaching": "distance teaching",
}
_WEEK_LABELS = {"actual": "this week", "permanent": "permanent timetable", "next": "next week"}
_EPILOG = """\
environment variables:
  BAKALARI_URL           the school's Bakaláři address, e.g. https://skola.bakalari.cz
  BAKALARI_USERNAME      the username of the Bakaláři web (see --username-env)
  BAKALARI_PASSWORD      its password (see --password-env)
  BAKALARI_SESSION_FILE  the session file (see --session-file)

exit status: 0 success, 1 Bakaláři API or connection error, 2 usage or configuration error"""


class _UsageError(Exception):
    """A command line that cannot be carried out as given (exit status 2)."""


# --- Output ------------------------------------------------------------------------------------------------------


def _clean(text: str) -> str:
    return _CONTROL_CHARACTERS.sub("", text)


def _say(text: str = "") -> None:
    print(_clean(text))


def _say_json(data: Any) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    print(_RAW_IN_JSON.sub(lambda match: f"\\u{ord(match.group()):04x}", text))


def _say_value(value: Any, as_json: bool) -> None:
    if as_json:
        _say_json(value)
    else:
        _say(str(value))


def _tell(message: str, kind: str = "") -> None:
    """A message on standard error: ``bakalari: <kind>: <message>``."""
    print(f"bakalari: {kind + ': ' if kind else ''}{_clean(message)}", file=sys.stderr)


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _shown_id(value: str) -> str:
    """An id as it must be typed in a shell: quoted when it is empty or holds spaces or shell characters."""
    return shlex.quote(value)


def _item_label(item: Optional[Item]) -> str:
    if item is None:
        return ""
    return item.abbrev or item.name or item.id.strip()


def _date_text(value: Optional[dt.date]) -> str:
    return value.isoformat() if value else "-"


def _when(value: Optional[dt.datetime]) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else "-"


def _period(start: Optional[dt.date], end: Optional[dt.date]) -> str:
    return f"{start.isoformat() if start else '?'} - {end.isoformat() if end else '?'}"


def _clock(value: dt.time) -> str:
    return f"{value.hour}:{value.minute:02d}"


def _local_time(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).astimezone().isoformat(sep=" ", timespec="seconds")


def _columns(rows: Sequence[Sequence[str]]) -> List[str]:
    """Rows of cells as lines with aligned columns; the last cell of a row is not padded."""
    if not rows:
        return []
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]) - 1)]
    return ["  ".join([cell.ljust(width) for cell, width in zip(row, widths)] + [row[-1]]).rstrip() for row in rows]


def _attachment_text(info: AttachmentInfo) -> str:
    details = [f"id {_shown_id(info.id)}"]
    if info.size is not None:
        details.append(f"{info.size} bytes")
    if info.content_type:
        details.append(info.content_type)
    return f"{info.name or '-'} ({', '.join(details)})"


# --- Argument types ----------------------------------------------------------------------------------------------


def _date(value: str) -> dt.date:
    """A date argument: ``YYYY-MM-DD``, ``today``, ``yesterday`` or ``tomorrow``."""
    text = value.strip().lower()
    if text in _RELATIVE_DAYS:
        return dt.date.today() + dt.timedelta(days=_RELATIVE_DAYS[text])
    if _ISO_DATE.fullmatch(text):
        with contextlib.suppress(ValueError):
            return dt.date.fromisoformat(text)
    raise argparse.ArgumentTypeError(f"invalid date {value!r}: use YYYY-MM-DD, today, yesterday or tomorrow")


def _positive_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError:
        number = 0.0
    if not 0 < number < float("inf"):
        raise argparse.ArgumentTypeError(f"not a positive number: {value!r}")
    return number


def _count(value: str) -> int:
    if not _DIGITS.fullmatch(value.strip()):
        raise argparse.ArgumentTypeError(f"not a whole number of zero or more: {value!r}")
    return int(value)


def _positive_int(value: str) -> int:
    number = _count(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"not a positive whole number: {value!r}")
    return number


def _hypothetical_mark(value: str) -> Tuple[str, int]:
    """A ``MARK:WEIGHT`` argument of ``predict``, e.g. ``2-:5``."""
    mark, separator, weight = value.rpartition(":")
    if not separator or not mark.strip() or not _DIGITS.fullmatch(weight.strip()) or int(weight) < 1:
        raise argparse.ArgumentTypeError(f"invalid mark {value!r}: use MARK:WEIGHT, e.g. 1:3 or 2-:5")
    return mark.strip(), int(weight)


# --- Session file ------------------------------------------------------------------------------------------------


class _SessionFile:
    """The JSON file of ``--session-file``: :meth:`SessionState.to_dict` data, readable by its owner only."""

    def __init__(self, path: str) -> None:
        self.path = Path(os.path.expanduser(path))

    def read(self) -> Optional[SessionState]:
        """The stored session, ``None`` when the file does not exist; a file that cannot be read or is not a session
        raises :class:`BakalariConfigError`."""
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as error:  # ValueError: not UTF-8
            raise BakalariConfigError(f"Cannot read the session file {self.path}: {_reason(error)}") from None
        try:
            state = SessionState.from_dict(json.loads(text))
            normalize_base_url(state.base_url)
        except (ValueError, TypeError, BakalariConfigError):
            raise BakalariConfigError(
                f"The session file {self.path} is not a Bakaláři session (it is corrupt or belongs to another "
                "program): delete it or pass another --session-file."
            ) from None
        return state

    def load(self) -> Optional[SessionState]:
        """Like :meth:`read`, and limits a file other users can read to its owner (POSIX)."""
        state = self.read()
        if state is not None and os.name == "posix":
            with contextlib.suppress(OSError):
                if stat.S_IMODE(self.path.stat().st_mode) & 0o077:
                    os.chmod(self.path, 0o600)
                    _tell(f"the session file {self.path} was readable by other users; its mode is now 0600", "warning")
        return state

    def save(self, state: SessionState) -> None:
        """Writes the session atomically: a new file created with mode 0600 replaces the old one."""
        text = json.dumps(state.to_dict(), indent=2) + "\n"
        temporary = self.path.with_name(f".{self.path.name}.{secrets.token_hex(8)}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
            with open(descriptor, "w", encoding="utf-8") as file:
                if os.name == "posix":
                    os.fchmod(file.fileno(), 0o600)  # exactly 0600, whatever the umask
                file.write(text)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        except OSError as error:
            with contextlib.suppress(OSError):
                temporary.unlink()
            raise BakalariConfigError(f"Cannot write the session file {self.path}: {_reason(error)}") from None

    def delete(self) -> bool:
        """Deletes the file after checking that it holds a session; False when there is none."""
        if self.read() is None:
            return False
        try:
            self.path.unlink()
        except FileNotFoundError:
            return False
        except OSError as error:
            raise BakalariConfigError(f"Cannot delete the session file {self.path}: {_reason(error)}") from None
        return True


def _reason(error: Exception) -> str:
    return (error.strerror if isinstance(error, OSError) else None) or str(error)


# --- Factories ---------------------------------------------------------------------------------------------------


def default_client_factory(args: argparse.Namespace, needs_login: bool) -> BakalariClient:
    """Creates the client of a command: the address from ``--base-url``, ``$BAKALARI_URL`` or the session loaded from
    the session file (``args.session``), the login from the environment variables named by ``--username-env`` and
    ``--password-env``, and the ``--timeout`` and ``--retries`` options.

    A command that ``needs_login`` requires the login variables unless a session was loaded; with a session they only
    serve as the fallback when its refresh token is no longer accepted. Missing values raise
    :class:`BakalariConfigError`.
    """
    session: Optional[SessionState] = getattr(args, "session", None)
    username_env = getattr(args, "username_env", USERNAME_ENV)
    password_env = getattr(args, "password_env", PASSWORD_ENV)
    base_url = getattr(args, "base_url", None) or os.environ.get(BASE_URL_ENV) or (session.base_url if session else "")
    username = os.environ.get(username_env) or None
    password = os.environ.get(password_env) or None
    missing = [] if base_url else [BASE_URL_ENV]
    if needs_login and session is None:
        missing += [name for name, value in ((username_env, username), (password_env, password)) if not value]
    if missing:
        raise BakalariConfigError(
            f"Missing environment variable(s): {', '.join(missing)}. Set the school's Bakaláři address "
            f"({BASE_URL_ENV} or --base-url) and the login of the Bakaláři web, or resume a stored session with "
            "--session-file."
        )
    return BakalariClient(
        base_url,
        username,
        password,
        timeout=getattr(args, "timeout", DEFAULT_TIMEOUT),
        retries=getattr(args, "retries", DEFAULT_RETRIES),
    )


def default_directory_factory(args: argparse.Namespace) -> SchoolDirectory:
    """Creates the client of the public school directory for the ``schools`` command."""
    return SchoolDirectory(timeout=getattr(args, "timeout", DEFAULT_TIMEOUT))


# --- One run of a command ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Command:
    name: str
    handler: Callable[["_Run"], None]
    school: bool = True  # talks to the school's installation
    login: bool = True  # needs a login (the login variables or a stored session)
    hint: str = ""  # explains an HTTP 403 of this command


class _Run:
    """The state of one command: the arguments, the client and the session file."""

    def __init__(self, args: argparse.Namespace, directory_factory: DirectoryFactory) -> None:
        self.args = args
        self.spec: _Command = args.spec
        path = args.session_file if args.session_file is not None else os.environ.get(SESSION_FILE_ENV)
        self.session = _SessionFile(path) if path else None
        self.loaded: Optional[SessionState] = None
        self.resumed = False
        self._directory_factory = directory_factory
        self._client: Optional[BakalariClient] = None
        self._watching = False
        self._stored: Optional[SessionState] = None  # what the session file holds

    @property
    def client(self) -> BakalariClient:
        if self._client is None:
            raise RuntimeError(f"the command {self.spec.name} has no client")
        return self._client

    def directory(self) -> SchoolDirectory:
        return self._directory_factory(self.args)

    def execute(self, client_factory: ClientFactory) -> None:
        self._client_factory = client_factory
        needs_login = self.spec.login and not getattr(self.args, "no_auth", False)
        if self.spec.school:
            self._connect(client_factory, needs_login)
        try:
            self.spec.handler(self)
        except BaseException:
            self.save_session(quiet=True)  # a renewed refresh token must survive a failed command
            raise
        self.save_session()

    def _connect(self, client_factory: ClientFactory, needs_login: bool) -> None:
        configured = getattr(self.args, "base_url", None) or os.environ.get(BASE_URL_ENV)
        if self.session is not None and (needs_login or not configured):
            self.loaded = self._stored = self.session.load()
        self.args.session = self.loaded
        client = client_factory(self.args, needs_login)
        self._client = client
        if not needs_login or self.session is None:
            return
        if self.loaded is not None:
            try:
                client.import_session(self.loaded)
            except BakalariConfigError:
                raise BakalariConfigError(
                    f"The session file {self.session.path} belongs to {self.loaded.base_url}, not to "
                    f"{client.base_url}: pass the matching --base-url or another --session-file, or delete it with "
                    "'bakalari logout'."
                ) from None
            self.resumed = True
        previous = client.on_session_update

        def update(state: SessionState) -> None:
            self._store(state)
            if previous is not None:
                previous(state)

        client.on_session_update = update
        self._watching = True

    def save_session(self, *, quiet: bool = False) -> None:
        """Saves the client's session unless the session file holds it already. Logins and renewals save it at once;
        an unchanged session is not rewritten, so that a concurrent command's renewal is not overwritten."""
        if not self._watching or self._client is None:
            return
        try:
            state = self._client.export_session()
        except BakalariError:  # never logged in
            return
        # The refresh token changes with every login and renewal; only an expired access token, which the import
        # drops, differs otherwise.
        if self._stored is not None and state.refresh_token == self._stored.refresh_token:
            return
        try:
            self._store(state)
        except BakalariConfigError:
            if not quiet:
                raise

    def _store(self, state: SessionState) -> None:
        if self.session is not None:
            self.session.save(state)
            self._stored = state

    def hint(self, error: BakalariError) -> str:
        """A hint for an error, or an empty string."""
        if isinstance(error, BakalariPermissionError):
            if "IsTeacher" in error.message:
                return _TEACHER_HINT
            return self.spec.hint or _PERMISSION_HINT
        if isinstance(error, BakalariAuthError) and error.path == TOKEN_PATH:
            if self.resumed and not (os.environ.get(self.args.username_env) and os.environ.get(self.args.password_env)):
                return "the stored session is no longer accepted: set the login variables and run 'bakalari login'"
            return f"check the login in {self.args.username_env} and {self.args.password_env}"
        if isinstance(error, BakalariConnectionError):
            if not self.spec.school:
                return "check the network connection"
            return f"check the school's address ({BASE_URL_ENV} or --base-url) and the network connection"
        if isinstance(error, BakalariNotFoundError) and error.path == TOKEN_PATH:
            return f"check the school's address ({BASE_URL_ENV} or --base-url)"
        return ""


def _describe(error: BakalariError) -> str:
    """The error message for the terminal: the request, the status and the server's own message."""
    if not isinstance(error, BakalariHTTPError):
        return str(error)
    body = error.body
    if error.path == TOKEN_PATH and isinstance(body, Mapping) and body.get("error"):
        description = body.get("error_description")
        return f"the login was refused ({body['error']}{': ' + str(description) if description else ''})"
    try:
        status = f"HTTP {error.status} {http.HTTPStatus(error.status).phrase}"
    except ValueError:
        status = f"HTTP {error.status}"
    detail = _one_line(error.message)
    return f"{error.method} {error.path} answered {status}" + (f": {detail}" if detail else "")


# --- Public data -------------------------------------------------------------------------------------------------


def _version(run: _Run) -> None:
    client = run.client
    version = client.api_version()
    if run.args.json:
        _say_json(version)
        return
    _say(
        f"Bakaláři REST API {version.get('ApiVersion')} (application {version.get('ApplicationVersion')}) "
        f"at {client.base_url}/{version.get('BaseUrl')}"
    )


def _schools(run: _Run) -> None:
    args = run.args
    if args.query is not None and args.municipality is not None:
        raise _UsageError("pass either QUERY or --municipality, not both")
    directory = run.directory()
    if args.query is None and args.municipality is None:
        municipalities = directory.municipalities()
        if args.json:
            _say_json([municipality.to_dict() for municipality in municipalities])
            return
        for municipality in municipalities:
            _say(f"{municipality.name or '(no name)'}\t{municipality.school_count}")
        if not municipalities:
            _say("No municipalities.")
        return
    if args.municipality is not None:
        schools = directory.schools(args.municipality)
    else:
        schools = directory.find(args.query, max_requests=args.max_requests)
    if args.json:
        _say_json([school.to_dict() for school in schools])
        return
    for school in schools:
        _say(f"{school.name}\t{school.base_url or '-'}")
    if not schools:
        _say("No schools found.")


def _public_timetable(run: _Run) -> None:
    args, client = run.args, run.client
    if args.list:
        if args.permanent or args.next:
            raise _UsageError("--permanent and --next need --class, --teacher or --room")
        targets = client.public_timetable_targets()
        if args.json:
            _say_json(targets.to_dict())
            return
        rows = [(target.kind, _shown_id(target.id), target.name) for target in targets.all_targets]
        _say("\n".join(_columns(rows)) or "No public timetables.")
        return
    kind, key = next(
        (kind, value)
        for kind, value in (("class", args.class_id), ("teacher", args.teacher), ("room", args.room))
        if value is not None
    )
    week = "permanent" if args.permanent else "next" if args.next else "actual"
    found = _public_target(run, kind, key)
    timetable = client.public_timetable(kind, found if found is not None else key, week=week)
    if args.json:
        _say_json(timetable.to_dict())
        return
    name = found.name if found is not None and found.name else key
    _say(f"Public timetable of {kind} {name}, {_WEEK_LABELS[week]}")
    _say(timetable.format() or "No lessons.")


def _public_target(run: _Run, kind: str, key: str) -> Optional[PublicTarget]:
    """The published target that ``key`` names (an id, or a name ignoring case and spaces), else ``None``."""
    try:
        return run.client.public_timetable_targets().find(key, kind)
    except BakalariContractError:  # a page without target lists: the id is tried as given
        return None


# --- Account and session -----------------------------------------------------------------------------------------


def _login(run: _Run) -> None:
    client = run.client
    try:
        info = client.login()
        renewed = False
    except BakalariConfigError:  # no login variables: renew the stored session with its refresh token
        if not run.resumed:
            raise
        info = client.refresh()
        renewed = True
    expires = _local_time(info.expires_at)
    session_file = str(run.session.path) if run.session is not None else None
    if run.args.json:
        _say_json({
            "base_url": client.base_url, "user_id": info.user_id, "api_version": info.api_version,
            "token_type": info.token_type, "scope": info.scope, "expires_in": info.expires_in, "expires_at": expires,
            "renewed": renewed, "session_file": session_file,
        })
    else:
        action = "Renewed the session of user" if renewed else "Logged in as user"
        _say(f"{action} {info.user_id or '-'} at {client.base_url} (API {info.api_version or '-'}); "
             f"the access token expires at {expires}.")
        if session_file is not None:
            _say(f"Saved the session to {session_file}.")
    if session_file is None:
        _tell(f"the session is not kept: pass --session-file PATH (or set {SESSION_FILE_ENV}) to keep it", "note")


def _logout(run: _Run) -> None:
    if run.session is None:
        raise _UsageError(f"logout needs a session file: pass --session-file PATH or set {SESSION_FILE_ENV}")
    if run.session.delete():
        _say(f"Deleted the session file {run.session.path}.")
    else:
        _say(f"There is no session file {run.session.path}.")


def _profile(run: _Run) -> None:
    profile = run.client.user_profile()
    if run.args.json:
        _say_json(profile.to_dict())
        return
    _say("\n".join(_profile_lines(profile)))


def _profile_lines(profile: UserProfile) -> List[str]:
    kind = profile.user_type_text or profile.user_type or "-"
    if profile.user_type_text and profile.user_type:
        kind = f"{profile.user_type_text} ({profile.user_type})"
    lines = [f"User type: {kind}", f"Name: {profile.full_name or '-'}"]
    if profile.full_user_name and profile.full_user_name != profile.full_name:
        lines.append(f"Account holder: {profile.full_user_name}")
    if profile.school_class is not None:
        lines.append(f"Class: {_item_label(profile.school_class)}")
    if profile.teacher_classes:
        lines.append("Classes: " + ", ".join(_item_label(item) for item in profile.teacher_classes))
    if profile.study_year is not None:
        lines.append(f"Study year: {profile.study_year}")
    if profile.school_name:
        lines.append(f"School: {profile.school_name}")
    if profile.school_type:
        lines.append(f"School type: {profile.school_type}")
    year = profile.school_year
    if year is not None:
        lines.append(f"School year: {year.name or year.id} ({_period(year.start, year.end)})")
    semester = profile.semester
    if semester is not None:
        lines.append(f"Semester: {semester.id.strip() or '-'} ({_period(semester.start, semester.end)})")
    if profile.students:
        lines.append("Students:")
        for student in profile.students:
            label = _item_label(student.school_class)
            known = not label or student.full_name.endswith(label)
            lines.append(f"    {student.full_name or '-'}" + ("" if known else f" ({label})"))
    return lines


def _modules(run: _Run) -> None:
    modules = run.client.user_profile(validate=False).modules
    if run.args.json:
        _say_json([module.to_dict() for module in modules])
        return
    for module in modules:
        _say(f"{module.module}: {', '.join(module.rights) or '-'}" if run.args.rights else module.module)
    if not modules:
        _say("No modules.")


def _web_login(run: _Run) -> None:
    args, client = run.args, run.client
    return_url: Optional[str] = args.return_url
    if args.module is not None:
        modules = client.web_modules(validate=False).modules
        wanted = args.module.strip().casefold()
        found = next((module for module in modules if module.name.casefold() == wanted), None)
        if found is None:
            names = ", ".join(module.name for module in modules if module.name) or "none"
            raise _UsageError(f"no web module {args.module!r} (the account has: {names})")
        return_url = found.url
    _say(client.web_login_url() if return_url is None else client.web_login_url(return_url))
    _tell("the link logs anyone who opens it in to the Bakaláři web as you; it works once, so do not share it",
          "warning")


def _web_modules(run: _Run) -> None:
    modules = run.client.web_modules(validate=False)
    if run.args.json:
        _say_json(modules.to_dict())
        return
    for module in modules.modules:
        _say(f"{module.name or '-'}\t{module.url}")
    if modules.dashboard is not None:
        _say(f"(dashboard)\t{modules.dashboard.url}")
    if not modules.modules and modules.dashboard is None:
        _say("No web modules.")


def _at_school(run: _Run) -> None:
    present = run.client.student_at_school()
    if run.args.json:
        _say_json(present)
    else:
        _say("at school" if present else "not at school")


# --- Timetable and events ----------------------------------------------------------------------------------------


def _timetable(run: _Run) -> None:
    args, client = run.args, run.client
    class_id: Optional[str] = None
    label = ""
    if args.class_id is not None:
        if args.class_id.strip():
            class_id = args.class_id
        else:
            own = client.user_profile(validate=False).school_class
            if own is None:
                raise _UsageError("the account has no class of its own: pass --class ID")
            class_id, label = own.id, _item_label(own)
    if args.permanent:
        if class_id is None:
            timetable = client.permanent_timetable()
        else:
            timetable = client.class_timetable(class_id, permanent=True)
        when = ""
    else:
        date = args.date or dt.date.today() + dt.timedelta(weeks=args.week or 0)
        timetable = client.actual_timetable(date) if class_id is None else client.class_timetable(class_id, date)
        monday, sunday = week_of(date)
        when = f"week {monday.isoformat()} - {sunday.isoformat()}"
    if args.day:
        lessons = timetable.lessons_on(args.day)
        if args.json:
            _say_json([lesson.to_dict() for lesson in lessons])
            return
        lines = [line for lesson in lessons for line in _lesson_lines(lesson, args.details, with_date=True)]
        _say("\n".join(lines) or "No lessons.")
        return
    if args.json:
        _say_json(timetable.to_dict())
        return
    if class_id is None:
        title = "Permanent timetable" if args.permanent else f"Actual timetable, {when}"
    else:
        label = label or _class_label(timetable, class_id)
        title = f"Permanent class timetable {label}" if args.permanent else f"Class timetable {label}, {when}"
    _say(title)
    _say(_format_timetable(timetable, args.details))


def _class_label(timetable: Timetable, class_id: str) -> str:
    item = timetable.classes.get(class_id)
    return _item_label(item) if item is not None else class_id.strip()


def _format_timetable(timetable: Timetable, details: bool) -> str:
    if not details:
        return timetable.format()
    lines: List[str] = []
    for day in timetable.days:
        lines.append(day.format_summary())
        for lesson in day.lessons:
            lines.extend("    " + line for line in _lesson_lines(lesson, details, with_date=False))
    return "\n".join(lines)


def _lesson_lines(lesson: Lesson, details: bool, *, with_date: bool) -> List[str]:
    lines = [lesson.format(with_date=with_date)]
    if details:
        notes = [("theme", lesson.theme), ("notice", lesson.notice)]
        notes += [("homework", homework.text) for homework in lesson.homeworks]
        lines.extend(f"    {label}: {_one_line(value)}" for label, value in notes if value)
    return lines


def _substitutions(run: _Run) -> None:
    args = run.args
    substitutions = run.client.substitutions(args.since or args.day)  # the 14 days from --day include it
    if args.day:
        changes = substitutions.on(args.day)
        if args.json:
            _say_json([change.to_dict() for change in changes])
            return
        _say(f"Substitutions on {args.day.isoformat()}")
        _say("\n".join(change.format(with_date=False) for change in changes) or "No changes.")
        return
    if args.json:
        _say_json(substitutions.to_dict())
        return
    _say(f"Substitutions {_period(substitutions.start, substitutions.end)}")
    _say(substitutions.format() or "No changes.")


def _events(run: _Run) -> None:
    args = run.args
    scope = "my" if args.my else "public" if args.public else "all"
    events = run.client.events(args.since, scope=scope)
    if args.json:
        _say_json([event.to_dict() for event in events])
        return
    for event in events:
        _say(_event_line(event))
        if args.details:
            for line in event.description.splitlines():
                _say(f"    {line}".rstrip())
            if event.note:
                _say(f"    note: {_one_line(event.note)}")
    if not events:
        _say("No events.")


def _event_line(event: Event) -> str:
    dates, start, end = event.dates, event.start, event.end
    if event.whole_day and dates:
        when = dates[0].isoformat() if len(dates) == 1 else f"{dates[0].isoformat()}..{dates[-1].isoformat()}"
    elif start is not None:
        when = f"{start:%Y-%m-%d %H:%M}"
        if end is not None:
            when += f"-{end:%H:%M}" if end.date() == start.date() else f" - {end:%Y-%m-%d %H:%M}"
    else:
        when = "-"
    line = f"{when} {_one_line(event.title) or '(no title)'}"
    if event.event_type is not None:
        line += f" [{event.event_type.name or event.event_type.abbrev}]"
    for items in (event.classes, event.rooms):
        if items:
            line += " | " + ", ".join(_item_label(item) for item in items)
    return line


# --- Marks -------------------------------------------------------------------------------------------------------


def _marks(run: _Run) -> None:
    args, client = run.args, run.client
    if args.count_new:
        if args.subject is not None or args.new or args.unconfirmed or args.since:
            raise _UsageError("--count-new prints the server's counter of new marks and takes no other option")
        _say_value(client.new_marks_count(), args.json)
        return
    data = client.marks(since=args.since)
    subjects = list(data.subjects)
    chosen: Optional[SubjectMarks] = None
    if args.subject is not None:
        chosen = _subject_of(data, args.subject)
        subjects = [chosen]
    if not (args.new or args.unconfirmed):
        if args.json:
            _say_json(chosen.to_dict() if chosen is not None else data.to_dict())
        else:
            _say("\n".join(subject.format() for subject in subjects) or "No marks.")
        return
    selected = [(subject, [mark for mark in subject.marks if _selected(mark, args)]) for subject in subjects]
    selected = [(subject, marks) for subject, marks in selected if marks]
    if args.json:
        _say_json([{**subject.to_dict(), "marks": [mark.to_dict() for mark in marks]} for subject, marks in selected])
        return
    lines = [line for subject, marks in selected for line in [subject.format_summary()] + _indented(marks)]
    kinds = " ".join(name for name, on in (("new", args.new), ("unconfirmed", args.unconfirmed)) if on)
    _say("\n".join(lines) or f"No {kinds} marks.")


def _selected(mark: Mark, args: argparse.Namespace) -> bool:
    return (mark.is_new or not args.new) and (mark.is_unconfirmed or not args.unconfirmed)


def _indented(marks: Sequence[Mark]) -> List[str]:
    return ["    " + mark.format() for mark in marks]


def _subject_of(data: Marks, key: str) -> SubjectMarks:
    found = data.subject(key)
    if found is None:
        known = ", ".join(_item_label(subject.subject) for subject in data.subjects) or "none"
        raise _UsageError(f"no subject {key!r} among the marks (subjects: {known})")
    return found


def _final_marks(run: _Run) -> None:
    terms = run.client.final_marks()
    if run.args.json:
        _say_json([term.to_dict() for term in terms])
        return
    _say("\n".join(term.format() for term in terms) or "No final marks.")


def _measures(run: _Run) -> None:
    measures = run.client.pedagogical_measures()
    if run.args.json:
        _say_json([measure.to_dict() for measure in measures])
        return
    _say("\n".join(measure.format() for measure in measures) or "No pedagogical measures.")


def _predict(run: _Run) -> None:
    args, client = run.args, run.client
    data = client.marks()  # without since=: the server averages exactly the marks it is sent
    current = _subject_of(data, args.subject)
    pairs: List[Tuple[str, int]] = args.marks
    if data.mark_options:
        unknown = [mark for mark, _ in pairs if data.mark_option(mark) is None]
        if unknown:
            known = ", ".join(option.abbrev or option.id.strip() for option in data.mark_options)
            raise _UsageError(f"unknown mark(s) {', '.join(unknown)}: the school uses {known}")
    result = client.predict_marks(current, pairs)
    if args.json:
        _say_json(result.to_dict())
        return
    added = ", ".join(f"{mark} (weight {weight})" for mark, weight in pairs)
    _say(current.format_summary())
    _say(f"Predicted average with {added}: {result.average_text or '-'}")


def _confirm_marks(run: _Run) -> None:
    args, client = run.args, run.client
    if args.all_unconfirmed == bool(args.ids):
        raise _UsageError("pass the ids of the marks to confirm or --all-unconfirmed")
    if args.all_unconfirmed:
        pending = [(subject, mark) for subject in client.marks().subjects for mark in subject.unconfirmed_marks]
        ids = [mark.id for _, mark in pending]
        shown = _columns([
            (_item_label(subject.subject), dataclasses.replace(mark, confirmation_state="Confirmed").format())
            for subject, mark in pending
        ])
    else:
        ids = list(dict.fromkeys(args.ids))
        shown = [_shown_id(mark_id) for mark_id in ids]
    if not ids or not client.confirm_marks(ids):
        _say("Nothing to confirm.")
        return
    _say(f"Confirmed {len(ids)} mark(s):")
    _say("\n".join("    " + line for line in shown))


# --- Absence, subjects and homeworks -----------------------------------------------------------------------------


def _absence(run: _Run) -> None:
    absence = run.client.absence()
    if run.args.json:
        _say_json(absence.to_dict())
        return
    _say("\n".join(_absence_lines(absence, run.args.days)))


def _absence_lines(absence: Absence, days: bool) -> List[str]:
    lines = []
    if absence.percentage_threshold:
        lines.append(f"Threshold: {absence.percentage_threshold:.0%} of the lessons")
    for subject in absence.subjects:
        share = f"{subject.percentage:.1%}" if subject.percentage is not None else "-"
        name = subject.subject_name or "(no subject)"
        line = f"{name}: missed {subject.base} of {subject.lessons_count} lessons ({share})"
        counters = (("late", subject.late), ("left early", subject.soon), ("school activity", subject.school),
                    ("distance teaching", subject.distance_teaching))
        line += "".join(f", {label} {count}" for label, count in counters if count)
        lines.append(line + (" [over the threshold]" if subject.over_threshold else ""))
    if not absence.subjects:
        lines.append("No absence per subject.")
    if days:
        for day in absence.days:
            counts = ", ".join(f"{_ABSENCE_LABELS[name]} {count}" for name, count in day.counts().items() if count)
            lines.append(f"{_date_text(day.date)}: {counts or 'none'} (total {day.total})")
    totals = ", ".join(f"{_ABSENCE_LABELS[name]} {count}" for name, count in absence.totals().items() if count)
    lines.append(f"Total: {totals or 'no absence'}")
    return lines


def _subjects(run: _Run) -> None:
    args, client = run.args, run.client
    if args.themes is not None:
        _themes(run, args.themes)
        return
    subjects = client.subjects()
    if args.json:
        _say_json([subject.to_dict() for subject in subjects])
        return
    rows = [(subject.id.strip() or "-", subject.abbrev or "-", _subject_text(subject)) for subject in subjects]
    _say("\n".join(_columns(rows)) or "No subjects.")


def _subject_text(subject: SubjectInfo) -> str:
    """The name of a subject with its teacher and the teacher's contacts."""
    details = [subject.teacher.name or subject.teacher.abbrev] if subject.teacher is not None else []
    contacts = (("", subject.teacher_email), ("", subject.teacher_web), ("school phone ", subject.teacher_school_phone),
                ("mobile ", subject.teacher_mobile_phone), ("home phone ", subject.teacher_home_phone))
    details += [label + value for label, value in contacts if value]
    return (subject.name or "-") + "".join(f" | {detail}" for detail in details if detail)


def _themes(run: _Run, key: str) -> None:
    client = run.client
    try:
        found = find_subject(client.subjects(), key)  # "2", "Čj" or the name, not only the padded id " 2"
    except BakalariPermissionError:
        found = None
    themes = client.subject_themes(found if found is not None else key)
    if run.args.json:
        _say_json(themes.to_dict())
        return
    _say(" ".join(part for part in (themes.subject.abbrev, themes.subject.name) if part) or key)
    _say("\n".join(_theme_line(theme) for theme in themes.themes) or "No themes.")


def _theme_line(theme: Theme) -> str:
    parts = [_date_text(theme.date), theme.hour_caption]
    start, end = theme.start_time, theme.end_time
    if start is not None:
        parts.append(_clock(start) + (f"-{_clock(end)}" if end is not None else ""))
    text = theme.theme or "(no theme)"
    parts.append(f"{theme.lesson_label}. {text}" if theme.lesson_label else text)
    line = "  ".join(part for part in parts if part)
    return line + (f" ({_one_line(theme.note)})" if theme.note else "")


def _homeworks(run: _Run) -> None:
    args, client = run.args, run.client
    if args.count:
        if args.since or args.until or args.open:
            raise _UsageError("--count prints the server's counter of open homeworks and takes no other option")
        _say_value(client.active_homeworks_count(), args.json)
        return
    homeworks = client.homeworks(args.since, args.until)
    if args.open:
        homeworks = [homework for homework in homeworks if homework.is_active]
    if args.json:
        _say_json([homework.to_dict() for homework in homeworks])
        return
    _say("\n".join(line for homework in homeworks for line in _homework_lines(homework)) or "No homeworks.")


def _homework_lines(homework: Homework) -> List[str]:
    flags = [name for name, on in (("done", homework.done), ("finished", homework.finished),
                                   ("closed", homework.closed), ("electronic", homework.electronic)) if on]
    head = [f"due {_date_text(homework.end)}", _item_label(homework.subject)]
    if flags:
        head.append(f"[{', '.join(flags)}]")
    head.append(f"id {_shown_id(homework.id)}")
    lines = ["  ".join(part for part in head if part)]
    lines += [f"    {line}".rstrip() for line in homework.content.splitlines()]
    if homework.notice:
        lines.append(f"    notice: {_one_line(homework.notice)}")
    lines += [f"    attachment: {_attachment_text(info)}" for info in homework.attachments]
    return lines


def _homework_done(run: _Run) -> None:
    args = run.args
    run.client.set_homework_done(args.id, done=not args.undo)
    _say(f"Marked homework {_shown_id(args.id)} as {'not finished' if args.undo else 'finished'}.")


# --- Komens messages ---------------------------------------------------------------------------------------------


def _messages(run: _Run) -> None:
    args, client = run.args, run.client
    folder = "sent" if args.sent else "noticeboard" if args.noticeboard else "received"
    if args.count:
        if args.since or args.unread:
            raise _UsageError("--count prints the number of unread messages and takes no filter")
        count = len(client.messages(folder)) if folder == "sent" else client.unread_messages_count(folder)
        _say_value(count, args.json)
        return
    messages = client.messages(folder, since=args.since)
    if args.unread:
        messages = [message for message in messages if not message.read]
    if args.json:
        _say_json([message.to_dict() for message in messages])
        return
    _say("\n".join(_message_line(message, folder) for message in messages) or "No messages.")


def _message_flags(message: Message) -> List[str]:
    flags = [name for name, on in (("unread", not message.read), ("to confirm", message.needs_confirmation),
                                   ("hidden", message.hidden)) if on]
    count = len(message.attachments) or message.attachments_count or 0
    if count:
        flags.append(f"{count} attachment{'s' if count > 1 else ''}")
    return flags


def _message_line(message: Message, folder: str) -> str:
    if folder == "sent":
        count = message.recipients_count
        who = "to " + (message.relevant_name or (f"{count} recipient(s)" if count else "-"))
    else:
        who = message.sender.name or message.relevant_name or message.sender.id or "-"
    line = f"{_shown_id(message.id)}  {_when(message.sent)}  {who}: {_one_line(message.title) or '(no title)'}"
    flags = _message_flags(message)
    return line + (f"  [{', '.join(flags)}]" if flags else "")


def _message(run: _Run) -> None:
    args, client = run.args, run.client
    if args.mark_read and args.sent:
        raise _UsageError("--mark-read applies to received messages, not to --sent")
    if args.noticeboard:  # the noticeboard has no detail endpoint, but its list carries whole messages
        message = next((item for item in client.messages("noticeboard") if item.id == args.id), None)
        if message is None:
            raise _UsageError(f"no noticeboard message {args.id!r}")
    else:
        message = client.message(args.id, "sent" if args.sent else "received")
    if args.json:
        _say_json(message.to_dict())
    else:
        _say("\n".join(_message_lines(message, args.html)))
    if args.mark_read:
        if message.read:
            _tell(f"message {_shown_id(message.id)} was already read")
        else:
            client.mark_message_read(message.id)
            _tell(f"marked message {_shown_id(message.id)} as read")


def _message_lines(message: Message, raw_html: bool) -> List[str]:
    sender = message.sender
    lines = [
        f"Title: {_one_line(message.title) or '-'}",
        f"From: {sender.name or sender.id or '-'}" + (f" ({sender.type})" if sender.type else ""),
    ]
    if message.recipients:
        processed = {recipient.id: recipient for recipient in message.recipients_processed}
        lines.append("To:")
        for recipient in message.recipients:
            person = message.person(recipient.id)
            line = f"    {person.full_name if person is not None and person.full_name else recipient.id}"
            line += f" ({recipient.user_type})" if recipient.user_type else ""
            done = processed.get(recipient.id)
            if done is not None and done.action_date is not None:
                line += f", processed {_when(done.action_date)}"
            lines.append(line)
    elif message.kind.startswith("Sent") and message.relevant_name:
        lines.append(f"To: {message.relevant_name}")
    lines.append(f"Date: {_when(message.sent)}")
    kind = ", ".join(value for value in (message.message_type, message.life_time) if value)
    if kind:
        lines.append(f"Type: {kind}")
    if message.date_from is not None or message.date_to is not None:
        lines.append(f"Period: {_when(message.date_from)} - {_when(message.date_to)}")
    flags = [flag for flag in _message_flags(message) if "attachment" not in flag]
    if flags:
        lines.append(f"Flags: {', '.join(flags)}")
    lines += ["", (message.text if raw_html else message.plain_text) or "(no text)"]
    if message.attachments:
        lines += ["", "Attachments:"] + [f"    {_attachment_text(info)}" for info in message.attachments]
    return lines


def _message_types(run: _Run) -> None:
    args, client = run.args, run.client
    types = client.message_types() if args.reply_to is None else client.message_types(reply_to=args.reply_to)
    if args.json:
        _say_json(types.to_dict())
        return
    _say("\n".join(_message_type_lines(types)) or "No message types.")


def _message_type_lines(types: MessageTypes) -> List[str]:
    lines = []
    for message_type in types.types:
        options = [name for name, on in (("title", message_type.has_title),
                                         ("confirmation", message_type.show_confirmation),
                                         ("e-mail notification", message_type.show_email_notification)) if on]
        line = f"{_shown_id(message_type.code)}  {message_type.name}"
        lines.append(line + (f"  [{', '.join(options)}]" if options else ""))
        for recipient_type in message_type.recipient_types:
            copies = [name for name, on in (("copy for class teacher", recipient_type.show_copy_for_class_teacher),
                                            ("copy for parent", recipient_type.show_copy_for_parent)) if on]
            line = f"    {_shown_id(recipient_type.code)}  {recipient_type.name}  {recipient_type.selection or '-'}"
            lines.append(line + (f"  [{', '.join(copies)}]" if copies else ""))
            if recipient_type.needs_recipients:
                for recipient in recipient_type.recipients:
                    default = " (default)" if recipient.is_default else ""
                    lines.append(f"        {_shown_id(recipient.code)}  {recipient}{default}")
    return lines


def _message_text(args: argparse.Namespace) -> str:
    """The body of a message from ``--text`` or ``--text-file`` (``-`` for standard input), as HTML: plain text is
    escaped and its line breaks become ``<br>``, unless ``--html`` says it is HTML already."""
    if args.text_file is not None:
        try:
            if args.text_file == "-":
                text = sys.stdin.read()
            else:
                text = Path(args.text_file).read_text(encoding="utf-8")
        except (OSError, ValueError) as error:
            raise _UsageError(f"cannot read {args.text_file}: {_reason(error)}") from None
    else:
        text = args.text
    if not text.strip():
        raise _UsageError("the message text is empty")
    if args.html:
        return str(text)
    return html.escape(text.strip("\r\n"), quote=False).replace("\r\n", "\n").replace("\n", "<br>")


def _uploaded(run: _Run, paths: Optional[List[str]]) -> List[str]:
    """Uploads the ``--attach`` files (all of them must exist first) and returns their attachment ids."""
    paths = paths or []
    missing = [path for path in paths if not os.path.isfile(path)]
    if missing:
        raise _UsageError(f"no such file: {', '.join(missing)}")
    return [run.client.upload_attachment(path) for path in paths]


def _send_message(run: _Run) -> None:
    args, client = run.args, run.client
    types = client.message_types()
    message_type = types.message_type(args.message_type)
    if message_type is None:
        codes = ", ".join(item.code for item in types.types) or "none"
        raise _UsageError(f"the account cannot send the message type {args.message_type!r} (it can send: {codes})")
    recipient_type = message_type.recipient_type(args.recipient_type)
    if recipient_type is None:
        codes = ", ".join(item.code for item in message_type.recipient_types) or "none"
        raise _UsageError(f"{message_type.code} has no recipient type {args.recipient_type!r} (it has: {codes})")
    wanted: List[str] = args.recipients or []
    recipients: List[Recipient] = []
    if not recipient_type.needs_recipients:
        if wanted:
            raise _UsageError(f"the recipient type {recipient_type.code} implies its recipients: leave out --to")
    elif not wanted:
        raise _UsageError(f"the recipient type {recipient_type.code} needs --to CODE (see 'bakalari message-types')")
    elif recipient_type.selection.upper() == "ONE" and len(wanted) > 1:
        raise _UsageError(f"the recipient type {recipient_type.code} takes one recipient")
    for code in wanted:
        recipient = recipient_type.recipient(code)
        if recipient is None:
            raise _UsageError(f"{recipient_type.code} has no recipient {code!r} (see 'bakalari message-types')")
        recipients.append(recipient)
    offered = (("--require-confirmation", args.require_confirmation, message_type.show_confirmation),
               ("--email-notification", args.email_notification, message_type.show_email_notification),
               ("--copy-for-class-teacher", args.copy_for_class_teacher, recipient_type.show_copy_for_class_teacher),
               ("--copy-for-parent", args.copy_for_parent, recipient_type.show_copy_for_parent))
    refused = [option for option, wanted_option, allowed in offered if wanted_option and not allowed]
    if refused:
        raise _UsageError(f"{message_type.code} to {recipient_type.code} does not offer {', '.join(refused)}")
    if message_type.has_title and not (args.title or "").strip():
        raise _UsageError(f"the message type {message_type.code} needs --title")
    if not message_type.has_title and args.title:
        raise _UsageError(f"the message type {message_type.code} has no title: leave out --title")
    text = _message_text(args)
    attachments = _uploaded(run, args.attach)
    client.send_message(
        message_type=message_type, text=text, recipient_type=recipient_type, recipients=recipients,
        title=args.title or "", attachments=attachments, require_confirmation=args.require_confirmation,
        email_notification=args.email_notification, copy_for_class_teacher=args.copy_for_class_teacher,
        copy_for_parent=args.copy_for_parent,
    )
    to = ", ".join(f"{recipient} ({_shown_id(recipient.code)})" for recipient in recipients) or recipient_type.name
    title = f' "{_one_line(args.title)}"' if args.title else ""
    files = f" with {len(attachments)} attachment(s)" if attachments else ""
    _say(f"Sent the {message_type.code} message{title} to {to}{files}.")


def _reply(run: _Run) -> None:
    args, client = run.args, run.client
    text = _message_text(args)
    original = client.message(args.id)
    attachments = _uploaded(run, args.attach)
    client.reply_to_message(original, text, title=args.title, attachments=attachments,
                            require_confirmation=args.require_confirmation)
    sender = original.sender.name or original.sender.id or "-"
    _say(f'Replied to message {_shown_id(original.id)} "{_one_line(original.title)}" from {sender}.')


def _confirm_message(run: _Run) -> None:
    run.client.confirm_message(run.args.id)
    _say(f"Confirmed message {_shown_id(run.args.id)}.")


def _hide_message(run: _Run) -> None:
    args = run.args
    if args.undo:
        run.client.unhide_message(args.id)
        _say(f"Message {_shown_id(args.id)} is shown again.")
    else:
        run.client.hide_message(args.id)
        _say(f"Hid message {_shown_id(args.id)}.")


def _delete_message(run: _Run) -> None:
    run.client.delete_message(run.args.id)
    _say(f"Deleted message {_shown_id(run.args.id)}.")


def _attachment(run: _Run) -> None:
    args = run.args
    attachment = run.client.download_attachment(args.id)
    target = args.output or os.curdir
    try:
        path = attachment.save(target, overwrite=args.force)
    except FileExistsError as error:
        raise _UsageError(f"{error.filename} already exists: pass --force to overwrite it") from None
    except OSError as error:
        raise _UsageError(f"cannot save the attachment to {error.filename or target}: {_reason(error)}") from None
    kind = f", {attachment.content_type}" if attachment.content_type else ""
    _say(f"Saved {os.path.abspath(path)} ({attachment.size} bytes{kind}).")


# --- GDPR and payments -------------------------------------------------------------------------------------------


def _consents(run: _Run) -> None:
    args, client = run.args, run.client
    if args.count:
        if args.child:
            raise _UsageError("--count counts the new consents of the account itself and takes no --child")
        _say_value(client.new_consents_count(), args.json)
        return
    consents = client.child_consents() if args.child else client.consents()
    if args.json:
        _say_json([consent.to_dict() for consent in consents])
        return
    _say("\n".join(_consent_line(consent) for consent in consents) or "No consents.")


def _consent_line(consent: Consent) -> str:
    details = []
    if consent.valid_from is not None:
        details.append(f"from {consent.valid_from.isoformat()}")
    if consent.valid_to is not None:
        details.append(f"until {consent.valid_to.isoformat()}")
    validity = consent.validity or (f"{consent.valid_years} year(s)" if consent.valid_years else "")
    if validity:
        details.append(f"validity {validity}")
    answers = [name for name, on in (("can agree", consent.can_agree), ("can disagree", consent.can_disagree),
                                     ("can request revocation", consent.can_revoke_request)) if on]
    line = f"{consent.state or '-'}  {_one_line(consent.title) or '(no title)'}"
    return line + (f" ({', '.join(details)})" if details else "") + (f" [{', '.join(answers)}]" if answers else "")


def _commissioners(run: _Run) -> None:
    commissioners = run.client.gdpr_commissioners()
    if run.args.json:
        _say_json([commissioner.to_dict() for commissioner in commissioners])
        return
    _say("\n".join(_commissioner_line(item) for item in commissioners) or "No data protection officer is listed.")


def _commissioner_line(commissioner: Commissioner) -> str:
    parts = (commissioner.name or "-", commissioner.email,
             f"mobile {commissioner.mobile}" if commissioner.mobile else "",
             f"phone {commissioner.phone}" if commissioner.phone else "", commissioner.web,
             f"data box {commissioner.data_box}" if commissioner.data_box else "")
    return " | ".join(part for part in parts if part)


def _class_fund(run: _Run) -> None:
    args, client = run.args, run.client
    payments = args.payments or args.asc or args.search is not None
    # The payments first: an empty --search is refused before any request.
    months = client.class_fund_payments(sort="asc" if args.asc else "desc", search=args.search) if payments else []
    summary = client.class_fund_summary()
    info = client.class_fund_payment_info() if args.info else None
    regular = client.regular_payments_summary() if args.regular else None
    if args.json:
        data: Dict[str, Any] = {"summary": summary.to_dict()}
        if payments:
            data["payments"] = [month.to_dict() for month in months]
        if info is not None:
            data["info"] = {**info.to_dict(), "iban": info.iban, "qr_payment": info.qr_payment()}
        if args.regular:
            data["regular"] = regular
        _say_json(data)
        return
    name = summary.student_name_with_class or "-"
    lines = [f"{name}: balance {summary.balance:.2f} CZK, spent {summary.spent:.2f} CZK"]
    if payments:
        lines.append("Payments:")
        for month in months:
            lines.append(f"    {month.month.strftime('%Y-%m') if month.month else '-'}  {month.balance:.2f} CZK")
            lines += [f"        {_date_text(item.date)}  {item.amount:>10.2f}  {_one_line(item.description)}"
                      for item in month.items]
        if not months:
            lines.append("    No payments.")
    if info is not None:
        lines += ["Payment details:"] + ["    " + line for line in _payment_info_lines(info)]
    if args.regular:
        lines += ["Regular payments:", json.dumps(regular, ensure_ascii=False, indent=2)]
    _say("\n".join(lines))


def _payment_info_lines(info: ClassFundPaymentInfo) -> List[str]:
    lines = [f"Instructions: {_one_line(info.instructions)}"] if info.instructions else []
    lines += [f"Account: {info.bank_account or '-'}", f"IBAN: {info.formatted_iban or '-'}"]
    if info.variable_symbol:
        lines.append(f"Variable symbol: {info.variable_symbol}")
    if info.specific_symbol:
        lines.append(f"Specific symbol: {info.specific_symbol}")
    if info.amount > 0:
        lines.append(f"Amount: {info.amount:.2f} CZK")
    if info.message:
        lines.append(f"Message: {_one_line(info.message)}")
    payment = info.qr_payment()
    lines.append(f"QR payment: {payment}" if payment else "QR payment: not available (no IBAN or invalid symbols)")
    return lines


# --- Teacher accounts --------------------------------------------------------------------------------------------


def _classbook(run: _Run) -> None:
    args = run.args
    monday, sunday = week_of(dt.date.today())
    since: dt.date = args.since or (args.until - dt.timedelta(days=6) if args.until else monday)
    until: dt.date = args.until or (since + dt.timedelta(days=6) if args.since else sunday)
    if until < since:
        raise _UsageError("--until is before --since")
    book = run.client.classbook(since, until)
    if args.json:
        _say_json(book.to_dict())
        return
    lines: List[str] = []
    for day in book.days:
        lines.append(_classbook_day(day))
        lines += ["    " + line for line in _columns([_record_cells(record) for record in day.records])]
    _say("\n".join(lines) or "No class-book days.")


def _classbook_day(day: ClassBookDay) -> str:
    weekday = CZECH_DAY_ABBREVIATIONS[day.date.weekday()] if day.date else ""
    description = f" ({day.description})" if day.description else ""
    head = " ".join(part for part in (_date_text(day.date), weekday, day.day_type) if part)
    return f"{head}{description}: {len(day.records)} record(s)"


def _record_cells(record: ClassBookRecord) -> Tuple[str, str, str, str, str]:
    """A class-book record as cells: the lesson number, its time, the subject, the groups and the numbered theme."""
    text = record.theme or "(no theme)"
    text = f"{record.label}. {text}" if record.label else text
    text += f" [{_one_line(record.change_text)}]" if record.change_text else ""
    caption = f"{record.hour_caption}." if record.hour_caption else ""
    groups = ", ".join(_item_label(group) for group in record.groups)
    return caption, record.hour_time, _item_label(record.subject), groups, text


def _lesson_tags(run: _Run) -> None:
    tags = run.client.lesson_tags()
    if run.args.json:
        _say_json([tag.to_dict() for tag in tags])
        return
    rows = [(_shown_id(tag.id), tag.abbreviation or "-", tag.title or "-") for tag in tags]
    _say("\n".join(_columns(rows)) or "No lesson tags.")


def _marking(run: _Run) -> None:
    args, client = run.args, run.client
    if args.atom is None:
        atoms = client.marking_atoms()
        if args.json:
            _say_json([atom.to_dict() for atom in atoms])
            return
        rows = []
        for atom in atoms:
            text = (atom.name or "-") + (f" [{_item_label(atom.subject)}]" if atom.subject is not None else "")
            if atom.disabled:
                text += " (disabled" + (f": {atom.disabled_text}" if atom.disabled_text else "") + ")"
            rows.append((_shown_id(atom.id), text))
        _say("\n".join(_columns(rows)) or "No marking units.")
        return
    sheet = client.marking_marks(args.atom)
    if args.json:
        _say_json(sheet.to_dict())
        return
    lines = []
    for student in sheet.students:
        values = ", ".join(mark.mark_value for mark in sheet.marks_of(student) if mark.mark_value) or "-"
        line = f"{student.name or student.id}: {values}"
        line += f" (average {student.average_text1})" if student.average_text1 else ""
        lines.append(line + (" [released]" if student.released else ""))
    _say("\n".join(lines) or "No students.")


# --- Raw access --------------------------------------------------------------------------------------------------


def _key_values(values: Optional[List[str]], option: str) -> Dict[str, Any]:
    """``KEY=VALUE`` arguments as a mapping; a repeated key collects its values in a list."""
    result: Dict[str, Any] = {}
    for item in values or []:
        key, separator, value = item.partition("=")
        if not separator or not key:
            raise _UsageError(f"{option} needs KEY=VALUE, got {item!r}")
        if key in result:
            previous = result[key]
            result[key] = (previous if isinstance(previous, list) else [previous]) + [value]
        else:
            result[key] = value
    return result


def _api(run: _Run) -> None:
    args = run.args
    path = args.path.strip()
    if "://" in path:
        raise _UsageError("PATH is relative to the school's address, e.g. /api/3/marks")
    params = _key_values(args.param, "--param")
    form = _key_values(args.form, "--form") if args.form else None
    data: Optional[bytes] = None
    headers: Optional[Dict[str, str]] = None
    if args.body is not None:
        try:
            json.loads(args.body)
        except ValueError as error:
            raise _UsageError(f"--body is not valid JSON: {error}") from None
        data, headers = args.body.encode("utf-8"), {"Content-Type": "application/json; charset=utf-8"}
    response = run.client.request(
        args.method, path, params=params or None, form=form, data=data, headers=headers,
        authorized=not args.no_auth, expected_status=_API_SUCCESS,
    )
    _say_response(response)


def _say_response(response: HttpResponse) -> None:
    if not response.body:
        _say(f"HTTP {response.status} (no content)")
        return
    try:
        data = response.json()
    except ValueError:  # not JSON
        pass
    else:
        _say_json(data)
        return
    content_type = response.content_type
    if content_type.startswith("text/") or content_type.endswith(("xml", "javascript")):
        charset = _CHARSET.search(response.header("Content-Type") or "")
        try:
            text = response.body.decode(charset.group(1) if charset else "utf-8", errors="replace")
        except LookupError:
            text = response.text
        _say(text)
        return
    _say(f"HTTP {response.status}: {content_type or 'no content type'}, {len(response.body)} bytes (not shown)")


def _mcp(run: _Run) -> None:
    """Start a lazy MCP connection, retaining the CLI's session persistence callbacks."""
    from .mcp import MCPServer

    def client() -> BakalariClient:
        if run._client is None:
            # A public tool needs no login, but any saved session must still be imported and watched.
            try:
                run._connect(lambda args, needs_login: run._client_factory(args, False), needs_login=True)
            except Exception:
                run._client = None  # A failed import must not bypass the school/session check on the next call.
                raise
        return run.client

    MCPServer(client_provider=client, directory_provider=run.directory, allow_writes=run.args.allow_writes).serve()


# --- Parser ------------------------------------------------------------------------------------------------------


def _json_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")


def _text_options(parser: argparse.ArgumentParser) -> None:
    text = parser.add_mutually_exclusive_group(required=True)
    text.add_argument("--text", metavar="TEXT", help="the text of the message")
    text.add_argument("--text-file", metavar="PATH", help="read the text from a UTF-8 file ('-' for standard input)")
    parser.add_argument("--html", action="store_true", help="the text is HTML (default: plain text, line breaks kept)")
    parser.add_argument("--attach", metavar="PATH", action="append", help="upload and attach a file (repeatable)")


def build_parser() -> argparse.ArgumentParser:
    """The argument parser of the command line; ``bakalari --help`` lists its commands by area."""
    parser = argparse.ArgumentParser(prog="bakalari", formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog=_EPILOG)
    parser.add_argument("--version", action="version", version=f"bakalari {__version__}",
                        help="print the package version and exit")
    parser.add_argument("--base-url", metavar="URL",
                        help=f"the school's Bakaláři address (default: ${BASE_URL_ENV}, else the session file's)")
    parser.add_argument("--username-env", metavar="NAME", default=USERNAME_ENV,
                        help="the environment variable with the username (default: %(default)s)")
    parser.add_argument("--password-env", metavar="NAME", default=PASSWORD_ENV,
                        help="the environment variable with the password (default: %(default)s)")
    parser.add_argument("--session-file", metavar="PATH",
                        help="keep the session in this file (mode 0600), so that the password is needed only when it "
                             f"expires; use one file per account (default: ${SESSION_FILE_ENV})")
    parser.add_argument("--timeout", metavar="SECONDS", type=_positive_float, default=DEFAULT_TIMEOUT,
                        help="the timeout of each request (default: 30)")
    parser.add_argument("--retries", metavar="N", type=_count, default=DEFAULT_RETRIES,
                        help="retries of GET, PUT and DELETE requests after a connection error or HTTP 502, 503 or "
                             "504 (default: %(default)s)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="log every request (method, path, status; never tokens or passwords) to standard error")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True,
                                     help="the command to run (listed above)")
    groups: Dict[str, List[Tuple[str, str]]] = {}

    def command(group: str, name: str, summary: str, handler: Callable[[_Run], None], description: str, *,
                aliases: Sequence[str] = (), school: bool = True, login: bool = True,
                hint: str = "") -> argparse.ArgumentParser:
        sub = commands.add_parser(name, aliases=list(aliases), description=description)
        sub.set_defaults(spec=_Command(name, handler, school=school, login=login, hint=hint))
        groups.setdefault(group, []).append((name + (f" ({', '.join(aliases)})" if aliases else ""), summary))
        return sub

    sub = command("integrations", "mcp", "MCP server over stdio (read-only unless --allow-writes)", _mcp,
                  "Serve Model Context Protocol tools over standard input/output. Configure the school and login "
                  "with the usual global options or environment variables. Tool discovery needs no configuration. "
                  "Only JSON-RPC protocol messages are written to stdout.", school=False, login=False)
    sub.add_argument("--allow-writes", action="store_true",
                     help="expose tools that change school data, including sending and deleting messages")

    group = "public data (no login)"
    sub = command(group, "version", "API version of the school's installation", _version,
                  "Prints the REST API version of the school's installation (GET /api/3). No login is needed.",
                  login=False)
    _json_option(sub)
    sub = command(group, "schools", "find a school's Bakaláři address", _schools,
                  "Searches the public directory of schools that use Bakaláři: without QUERY the municipalities with "
                  "their number of schools, with QUERY the schools of the matching municipalities with the address to "
                  "use as BAKALARI_URL. No login is needed.", school=False, login=False)
    sub.add_argument("query", nargs="?", metavar="QUERY",
                     help="a part of a municipality name, ignoring case and diacritics")
    sub.add_argument("--municipality", metavar="NAME",
                     help="the schools of the municipality NAME (and of those whose names start with it)")
    sub.add_argument("--max-requests", metavar="N", type=_positive_int, default=DEFAULT_MAX_REQUESTS,
                     help="refuse a QUERY that needs more directory requests (default: %(default)s)")
    _json_option(sub)
    sub = command(group, "public-timetable", "timetables the school publishes", _public_timetable,
                  "Prints a timetable from the school's public timetable pages (/Timetable/Public), or with --list the "
                  "classes, teachers and rooms it publishes. ID is an id or a name from --list. No login is needed.",
                  login=False, hint="the school does not publish this timetable")
    target = sub.add_mutually_exclusive_group(required=True)
    target.add_argument("--list", action="store_true", help="list the published classes, teachers and rooms")
    target.add_argument("--class", dest="class_id", metavar="ID", help="the timetable of a class")
    target.add_argument("--teacher", metavar="ID", help="the timetable of a teacher")
    target.add_argument("--room", metavar="ID", help="the timetable of a room")
    week = sub.add_mutually_exclusive_group()
    week.add_argument("--permanent", action="store_true", help="the permanent timetable instead of this week")
    week.add_argument("--next", action="store_true", help="next week instead of this week")
    _json_option(sub)

    group = "account and session"
    sub = command(group, "login", "log in and store the session", _login,
                  "Logs in with the login variables, or renews the session of the session file without them, and "
                  "prints the user id, the API version and the expiry of the access token. With --session-file the "
                  "session is stored for later commands.")
    _json_option(sub)
    command(group, "logout", "delete the session file", _logout,
            "Deletes the session file. The API cannot revoke tokens: the last access token expires within an hour.",
            school=False, login=False)
    sub = command(group, "profile", "the account: type, name, class, school, students", _profile,
                  "Prints the account (GET /api/3/user): its type, name, class and school, the school year and "
                  "semester, and the students of a parent account.", aliases=("whoami",))
    _json_option(sub)
    sub = command(group, "modules", "modules enabled for the account", _modules,
                  "Lists the Bakaláři modules enabled for the account (Komens, Marks, ...).")
    sub.add_argument("--rights", action="store_true", help="also list the account's rights in each module")
    _json_option(sub)
    sub = command(group, "web-login", "one-time link that opens the Bakaláři web logged in", _web_login,
                  "Prints a one-time link (GET /api/3/logintoken) that opens the Bakaláři web logged in. The link is "
                  "a credential: anyone who opens it is logged in as you.")
    page = sub.add_mutually_exclusive_group()
    page.add_argument("--return-url", metavar="URL",
                      help="the page to open, relative to the school's address (default: next/dash.aspx)")
    page.add_argument("--module", metavar="NAME", help="open the web module NAME (see web-modules)")
    sub = command(group, "web-modules", "pages of the Bakaláři web the app links to", _web_modules,
                  "Lists the pages of the Bakaláři web that the official app links to (GET /api/3/webmodule).")
    _json_option(sub)
    sub = command(group, "at-school", "whether the student is registered at school now", _at_school,
                  "Tells whether the school's access system registers the student at school now "
                  "(GET /api/3/user/student-at-school).",
                  hint="the AccessSystem module (right CanShowStudentPresentAtSchool) is not enabled for the account")
    _json_option(sub)

    group = "timetable and events"
    sub = command(group, "timetable", "actual or permanent timetable", _timetable,
                  "Prints the actual timetable of a week with its changes, or the permanent timetable; with --class "
                  "the timetable of a whole class with all its groups.")
    when = sub.add_mutually_exclusive_group()
    when.add_argument("--date", type=_date, help="a day of the wanted week (YYYY-MM-DD; default today)")
    when.add_argument("--week", type=int, help="weeks from the current one, e.g. 1 = next week, -1 = last week")
    when.add_argument("--permanent", action="store_true", help="the permanent (regular) timetable")
    sub.add_argument("--day", type=_date, help="only the lessons of this day (YYYY-MM-DD)")
    sub.add_argument("--class", dest="class_id", metavar="ID", nargs="?", const="",
                     help="the timetable of a whole class (default: the account's own class)")
    sub.add_argument("--details", action="store_true", help="also print the themes, notices and homeworks")
    _json_option(sub)
    sub = command(group, "substitutions", "changes of the timetable for two weeks", _substitutions,
                  "Prints the changes of the timetable (substitutions, cancellations, room changes, ...) for 14 days "
                  "from Monday of this week or from --since (GET /api/3/substitutions).")
    start = sub.add_mutually_exclusive_group()
    start.add_argument("--since", type=_date, metavar="DATE", help="the first day of the 14 days")
    start.add_argument("--day", type=_date, metavar="DATE", help="only the changes of this day")
    _json_option(sub)
    sub = command(group, "events", "school events", _events,
                  "Lists the school's events (trips, exams, parents' evenings, ...) of the school year.")
    scope = sub.add_mutually_exclusive_group()
    scope.add_argument("--my", action="store_true", help="only the account's own events")
    scope.add_argument("--public", action="store_true", help="only the public events")
    sub.add_argument("--since", type=_date, metavar="DATE", help="only the events from DATE on")
    sub.add_argument("--details", action="store_true", help="also print the descriptions and notes")
    _json_option(sub)

    group = "marks"
    sub = command(group, "marks", "marks and averages per subject", _marks,
                  "Prints the marks of the school year per subject with the averages (GET /api/3/marks).")
    sub.add_argument("--subject", metavar="KEY", help="only the subject with this id, abbreviation or name")
    sub.add_argument("--new", action="store_true", help="only the marks flagged new")
    sub.add_argument("--unconfirmed", action="store_true", help="only the marks waiting for a parent's confirmation")
    sub.add_argument("--since", type=_date, metavar="DATE", help="only the marks from DATE on")
    sub.add_argument("--count-new", action="store_true",
                     help="print the server's counter of new marks (often 0; --new lists the new marks)")
    _json_option(sub)
    sub = command(group, "final-marks", "certificate marks of every term", _final_marks,
                  "Prints the certificates of every term with their final marks (GET /api/3/marks/final).")
    _json_option(sub)
    sub = command(group, "measures", "praises and reprimands", _measures,
                  "Prints the pedagogical measures, praises and reprimands (GET /api/3/marks/measures).")
    _json_option(sub)
    sub = command(group, "predict", "average with hypothetical marks", _predict,
                  "Computes the average of a subject with additional hypothetical marks on the server "
                  "(POST /api/3/marks/what-if, which changes nothing), e.g. 'predict M 1:3 2-:5'.",
                  hint="mark prediction is disabled for this subject, or the account lacks the right PredictMarks")
    sub.add_argument("subject", metavar="SUBJECT", help="the subject's id, abbreviation or name")
    sub.add_argument("marks", metavar="MARK:WEIGHT", nargs="+", type=_hypothetical_mark,
                     help="a hypothetical mark with its weight, e.g. 1:3 or 2-:5")
    _json_option(sub)
    sub = command(group, "confirm-marks", "confirm (sign) marks as a parent [changes data]", _confirm_marks,
                  "Confirms (signs) marks as a parent where the school asks for it "
                  "(POST /api/3/marks/SetClassificationConfirmation). This changes data on the server.",
                  hint="the account lacks the right CanConfirmClassification")
    sub.add_argument("ids", metavar="ID", nargs="*", help="the id of a mark to confirm")
    sub.add_argument("--all-unconfirmed", action="store_true", help="confirm every mark that waits for it")

    group = "absence, subjects and homeworks"
    sub = command(group, "absence", "absence per subject and day", _absence,
                  "Prints the absence per subject with the school's threshold, and with --days per day "
                  "(GET /api/3/absence/student).")
    sub.add_argument("--days", action="store_true", help="also list the days with absence")
    _json_option(sub)
    sub = command(group, "subjects", "subjects, teachers and lesson themes", _subjects,
                  "Lists the subjects with their teachers (GET /api/3/subjects), or with --themes the lesson themes "
                  "of one subject.")
    sub.add_argument("--themes", metavar="SUBJECT", help="the lesson themes of a subject (id, abbreviation or name)")
    _json_option(sub)
    sub = command(group, "homeworks", "homeworks", _homeworks,
                  "Lists the homeworks given or due in a period; the server's default is 14 days back to one day ahead "
                  "(GET /api/3/homeworks).")
    sub.add_argument("--since", type=_date, metavar="DATE", help="the start of the period")
    sub.add_argument("--until", type=_date, metavar="DATE", help="the end of the period")
    sub.add_argument("--open", action="store_true", help="only the homeworks that are not closed")
    sub.add_argument("--count", action="store_true", help="print the server's counter of open homeworks")
    _json_option(sub)
    sub = command(group, "homework-done", "tick or untick a homework as finished [changes data]", _homework_done,
                  "Ticks a homework as finished by the student (its 'finished' flag; 'done' is the teacher's), or "
                  "unticks it with --undo. Pass the id exactly as listed. This changes data on the server.")
    sub.add_argument("id", metavar="ID", help="the homework id (see homeworks)")
    sub.add_argument("--undo", action="store_true", help="untick the homework")

    group = "Komens messages"
    sub = command(group, "messages", "received, sent or noticeboard messages", _messages,
                  "Lists the received messages, or the sent or noticeboard ones: id, date, sender, title and flags.")
    folder = sub.add_mutually_exclusive_group()
    folder.add_argument("--sent", action="store_true", help="the sent messages")
    folder.add_argument("--noticeboard", action="store_true", help="the noticeboard")
    sub.add_argument("--since", type=_date, metavar="DATE", help="only the messages from DATE on")
    sub.add_argument("--unread", action="store_true", help="only the unread messages")
    sub.add_argument("--count", action="store_true",
                     help="print the number of unread messages (with --sent: of sent messages)")
    _json_option(sub)
    sub = command(group, "message", "one message with its attachments", _message,
                  "Prints one message as plain text (or HTML) with its attachments. Reading does not mark it as read; "
                  "--mark-read does (that changes data on the server).")
    sub.add_argument("id", metavar="ID", help="the message id (see messages)")
    folder = sub.add_mutually_exclusive_group()
    folder.add_argument("--sent", action="store_true", help="a sent message, with its recipients")
    folder.add_argument("--noticeboard", action="store_true", help="a noticeboard message")
    sub.add_argument("--html", action="store_true", help="print the text as HTML")
    sub.add_argument("--mark-read", action="store_true", help="mark the message as read")
    _json_option(sub)
    sub = command(group, "message-types", "message types and recipients for sending", _message_types,
                  "Lists the message types the account may send with their recipient types and recipients: the codes "
                  "for send-message.")
    sub.add_argument("--reply-to", metavar="ID", help="what a reply to the message ID allows")
    _json_option(sub)
    sub = command(group, "send-message", "send a message [changes data]", _send_message,
                  "Sends a Komens message (POST /api/3/komens/message). The codes come from message-types. This "
                  "changes data on the server.", hint="the account lacks the right SendMessages (or SendAttachments)")
    sub.add_argument("--type", dest="message_type", metavar="CODE", required=True, help="the message type, e.g. OBECNA")
    sub.add_argument("--recipient-type", metavar="CODE", required=True, help="the recipient type, e.g. U")
    sub.add_argument("--to", dest="recipients", metavar="CODE", action="append",
                     help="a recipient (repeatable); none for a recipient type with the selection ZERO")
    sub.add_argument("--title", metavar="TEXT", help="the title, for message types that have one")
    _text_options(sub)
    sub.add_argument("--require-confirmation", action="store_true", help="ask the recipients to confirm the message")
    sub.add_argument("--email-notification", action="store_true", help="notify the recipients by e-mail")
    sub.add_argument("--copy-for-class-teacher", action="store_true", help="send a copy to the class teacher")
    sub.add_argument("--copy-for-parent", action="store_true", help="send a copy to the parent")
    sub = command(group, "reply", "reply to a message [changes data]", _reply,
                  "Replies to a received message the way the server allows for it. This changes data on the server.",
                  hint="the account lacks the right SendMessages (or SendAttachments)")
    sub.add_argument("id", metavar="ID", help="the id of the received message")
    sub.add_argument("--title", metavar="TEXT", help="the title (default: 'Re: ' and the original title)")
    _text_options(sub)
    sub.add_argument("--require-confirmation", action="store_true", help="ask the recipient to confirm the reply")
    sub = command(group, "confirm-message", "confirm a message [changes data]", _confirm_message,
                  "Confirms that a message asking for it was read. This changes data on the server.",
                  hint="the message does not ask for a confirmation")
    sub.add_argument("id", metavar="ID", help="the message id")
    sub = command(group, "hide-message", "hide or unhide a message [changes data]", _hide_message,
                  "Hides a message, or shows it again with --undo. This changes data on the server.",
                  hint="the message cannot be hidden")
    sub.add_argument("id", metavar="ID", help="the message id")
    sub.add_argument("--undo", action="store_true", help="show the hidden message again")
    sub = command(group, "delete-message", "delete a message [changes data]", _delete_message,
                  "Deletes a message that allows it. This changes data on the server.",
                  hint="the message cannot be deleted")
    sub.add_argument("id", metavar="ID", help="the message id")
    sub = command(group, "attachment", "download a message or homework attachment", _attachment,
                  "Downloads an attachment of a message or a homework into a file or directory and prints the path. "
                  "An existing file is never overwritten without --force.")
    sub.add_argument("id", metavar="ID", help="the attachment id (see message and homeworks)")
    sub.add_argument("-o", "--output", metavar="PATH",
                     help="the file or the directory to save to (default: the current directory)")
    sub.add_argument("--force", action="store_true", help="overwrite an existing file")

    group = "GDPR and payments"
    sub = command(group, "consents", "GDPR consents", _consents,
                  "Lists the GDPR consents of the account or, with --child, of its children. Answering a consent is "
                  "possible on the Bakaláři web only.")
    sub.add_argument("--child", action="store_true", help="the consents of the children of a parent account")
    sub.add_argument("--count", action="store_true", help="print the number of new consents")
    _json_option(sub)
    sub = command(group, "commissioners", "data protection officers", _commissioners,
                  "Lists the school's data protection officers with their contacts.")
    _json_option(sub)
    sub = command(group, "class-fund", "class fund balance, payments and payment details", _class_fund,
                  "Prints the class fund balance and, with the options, its payments by month, how to pay into it "
                  "(the IBAN and the QR payment string) and the regular payments.",
                  hint="the Payments module is not enabled for the school")
    sub.add_argument("--payments", action="store_true", help="the income and expenses by month, newest first")
    sub.add_argument("--asc", action="store_true", help="oldest month first (implies --payments)")
    sub.add_argument("--search", metavar="TEXT", help="only the payments matching TEXT (implies --payments)")
    sub.add_argument("--info", action="store_true", help="how to pay into the fund, with the IBAN and the QR string")
    sub.add_argument("--regular", action="store_true", help="the summary of the regular payments (raw JSON)")
    _json_option(sub)

    group = "teacher accounts"
    sub = command(group, "classbook", "class-book records", _classbook,
                  "Prints the teacher's class-book records of a period, by default this week (GET /api/3/classbook).",
                  hint=_TEACHER_HINT)
    sub.add_argument("--since", type=_date, metavar="DATE", help="the first day (default: Monday of this week)")
    sub.add_argument("--until", type=_date, metavar="DATE", help="the last day (default: six days after the first)")
    _json_option(sub)
    sub = command(group, "lesson-tags", "tags of class-book records", _lesson_tags,
                  "Lists the tags a teacher can attach to class-book records.", hint=_TEACHER_HINT)
    _json_option(sub)
    sub = command(group, "marking", "marking units and their marks", _marking,
                  "Lists the units (subject and group) the teacher gives marks in, or with ATOM the students' marks "
                  "of one unit.", hint=_TEACHER_HINT)
    sub.add_argument("atom", metavar="ATOM", nargs="?", help="the id of a marking unit")
    _json_option(sub)

    group = "raw access"
    sub = command(group, "api", "raw request to any endpoint", _api,
                  "Sends a request to any endpoint with the account's token and prints the JSON answer (or the status "
                  "for an empty one), e.g. 'api GET /api/3/marks -p from=2026-10-01'. A non-GET request may change "
                  "data on the server.")
    sub.add_argument("method", metavar="METHOD", type=str.upper, choices=_API_METHODS,
                     help=f"the HTTP method: {', '.join(_API_METHODS)}")
    sub.add_argument("path", metavar="PATH", help="the path below the school's address, e.g. /api/3/marks")
    sub.add_argument("-p", "--param", metavar="KEY=VALUE", action="append", help="a query parameter (repeatable)")
    body = sub.add_mutually_exclusive_group()
    body.add_argument("--form", metavar="KEY=VALUE", action="append", help="a form field of the body (repeatable)")
    body.add_argument("--body", metavar="JSON", help="a JSON body")
    sub.add_argument("--no-auth", action="store_true", help="send the request without a login (public endpoints)")

    parser.description = _overview(groups)
    return parser


def _overview(groups: Mapping[str, List[Tuple[str, str]]]) -> str:
    width = max(len(name) for entries in groups.values() for name, _ in entries) + 2
    lines = ["Command line client of the Bakaláři school information system (REST API v3).", "", "commands:"]
    for title, entries in groups.items():
        lines.append(f"  {title}:")
        lines.extend(f"    {name:<{width}}{summary}" for name, summary in entries)
    lines += ["", "Run 'bakalari COMMAND --help' for the options of a command."]
    return "\n".join(lines)


# --- Entry point -------------------------------------------------------------------------------------------------


@contextlib.contextmanager
def _request_logging(verbose: bool) -> Iterator[None]:
    """With ``verbose``, the package's log records (method, path and status of each request; never secrets) go to
    standard error while the command runs."""
    if not verbose:
        yield
        return
    logger = logging.getLogger("bakalari")
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield
    finally:
        logger.removeHandler(handler)
        logger.setLevel(level)


def _tolerate_unencodable_output() -> None:
    """Czech text written to a pipe or a file in a legacy encoding (Windows) is escaped instead of failing."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure) and getattr(stream, "errors", None) == "strict":
            with contextlib.suppress(Exception):
                reconfigure(errors="backslashreplace")


def _silence_stdout() -> None:
    """Points standard output at the null device after its reader went away (``bakalari messages | head``), so that
    Python's final flush does not complain once more."""
    try:
        descriptor = sys.stdout.fileno()
    except (AttributeError, OSError, ValueError):
        return
    with contextlib.suppress(OSError):
        null = os.open(os.devnull, os.O_WRONLY)
        os.dup2(null, descriptor)
        os.close(null)


def _exit_status(code: Any) -> int:
    if code is None:
        return EXIT_OK
    return code if isinstance(code, int) else EXIT_USAGE


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    client_factory: ClientFactory = default_client_factory,
    directory_factory: DirectoryFactory = default_directory_factory,
) -> int:
    """Runs the command line ``argv`` (default: ``sys.argv[1:]``) and returns the exit status: 0 success, 1 a Bakaláři
    API, connection or contract error, 2 a usage or configuration error. ``client_factory`` creates the client of a
    command (see :func:`default_client_factory`) and ``directory_factory`` the school directory of ``schools``."""
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exit_:  # --help, --version and usage errors
        return _exit_status(exit_.code)
    _tolerate_unencodable_output()
    run = _Run(args, directory_factory)
    with _request_logging(args.verbose):
        try:
            run.execute(client_factory)
        except (_UsageError, BakalariConfigError, ValueError) as error:  # ValueError: an argument the library refuses
            _tell(str(error), "error")
            return EXIT_USAGE
        except BakalariError as error:
            _tell(_describe(error), "error")
            hint = run.hint(error)
            if hint:
                _tell(hint, "hint")
            return EXIT_ERROR
        except BrokenPipeError:
            _silence_stdout()
            return EXIT_ERROR
        except OSError as error:
            _tell(f"{_reason(error)}{': ' + str(error.filename) if error.filename else ''}", "error")
            return EXIT_ERROR
        except KeyboardInterrupt:
            _tell("interrupted")
            return EXIT_INTERRUPTED
    return EXIT_OK
