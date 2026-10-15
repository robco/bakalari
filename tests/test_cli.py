"""Tests of the command line interface: every command and option through an injected client factory and a scripted
transport, the session file, the exit codes and the sanitising of server strings."""
import argparse
import contextlib
import copy
import datetime as dt
import io
import json
import logging
import os
import re
import stat
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List
from unittest import mock

from bakalari import BakalariClient, BakalariConfigError, BakalariConnectionError, HttpResponse, SessionState
from bakalari._version import __version__
from bakalari.cli import (
    SESSION_FILE_ENV,
    build_parser,
    default_client_factory,
    default_directory_factory,
    main,
)
from bakalari.schools import DIRECTORY_URL, SchoolDirectory
from bakalari.timetable import week_of

from .support import (
    BASE_URL,
    FORBIDDEN,
    INVALID_GRANT,
    NOT_TEACHER,
    PASSWORD,
    USERNAME,
    FakeClock,
    FakeTransport,
    binary_response,
    empty_response,
    json_response,
    load_fixture,
    load_text_fixture,
    text_response,
    token_response,
)

DIRECTORY = "https://directory.example/api/v1"
POSIX = os.name == "posix"
VERSION = {"ApiVersion": "3.52.1", "ApplicationVersion": "2.2.1009.7", "BaseUrl": "api/3"}
NOW = 1_000_000.0  # the FakeClock's time
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
COMMANDS = {
    "integrations": ["mcp"],
    "public data (no login)": ["version", "schools", "public-timetable"],
    "account and session": ["login", "logout", "profile (whoami)", "modules", "web-login", "web-modules", "at-school"],
    "timetable and events": ["timetable", "substitutions", "events"],
    "marks": ["marks", "final-marks", "measures", "predict", "confirm-marks"],
    "absence, subjects and homeworks": ["absence", "subjects", "homeworks", "homework-done"],
    "Komens messages": ["messages", "message", "message-types", "send-message", "reply", "confirm-message",
                        "hide-message", "delete-message", "attachment"],
    "GDPR and payments": ["consents", "commissioners", "class-fund"],
    "teacher accounts": ["classbook", "lesson-tags", "marking"],
    "raw access": ["api"],
}


def fixture(name, status=200):
    return json_response(status, load_fixture(name))


def page(name, url=""):
    return text_response(200, load_text_fixture(name), url=url)


def payload(name, key):
    return json_response(200, load_fixture(name)[key])


def expiry(epoch):
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).astimezone().isoformat(sep=" ", timespec="seconds")


@contextlib.contextmanager
def clean_environment(**variables):
    """``os.environ`` without this package's variables, so that the developer's own login never reaches a test."""
    with mock.patch.dict(os.environ):
        for name in [name for name in os.environ if name.startswith(("BAKALARI_", "BAK_")) or name == "FORCE_COLOR"]:
            del os.environ[name]
        os.environ.update({"PYTHON_COLORS": "0", **variables})  # plain argparse help on Python 3.14
        yield


@dataclass
class Result:
    code: int
    out: str
    err: str
    transport: FakeTransport

    @property
    def lines(self) -> List[str]:
        return self.out.splitlines()

    @property
    def data(self) -> Any:
        return json.loads(self.out)

    @property
    def calls(self):
        """The requests without those to the token endpoint."""
        return self.transport.api_calls


def run(argv, *responses, login=True, env=None, factory=None):
    """Runs the command line with a client (with or without the login) and a school directory on a scripted
    transport; any request beyond the scripted responses fails the test."""
    transport = FakeTransport(*responses)

    def client_factory(args, needs_login):
        credentials = (USERNAME, PASSWORD) if login else (None, None)
        return BakalariClient(BASE_URL, *credentials, transport=transport, clock=FakeClock())

    def directory_factory(args):
        return SchoolDirectory(DIRECTORY, transport=transport)

    out, err = io.StringIO(), io.StringIO()
    with clean_environment(**(env or {})), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv, client_factory=factory or client_factory, directory_factory=directory_factory)
    return Result(code, out.getvalue(), err.getvalue(), transport)


def run_without_client(argv, env=None):
    out, err = io.StringIO(), io.StringIO()
    with clean_environment(**(env or {})), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return Result(code, out.getvalue(), err.getvalue(), FakeTransport())


def write_session(path, *, access_token="access-1", expires_at=NOW + 3600, refresh_token="refresh-1",
                  base_url=BASE_URL, mode=0o600):
    state = SessionState(base_url=base_url, refresh_token=refresh_token, access_token=access_token,
                         expires_at=expires_at, user_id="U1", scope="offline_access bakalari_api",
                         api_version="3.52.1")
    path.write_text(json.dumps(state.to_dict()), encoding="utf-8")
    os.chmod(path, mode)
    return state


def read_session(path):
    return json.loads(path.read_text(encoding="utf-8"))


def file_mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


class CliTestCase(unittest.TestCase):
    def assertClean(self, text):
        self.assertIsNone(CONTROL.search(text), f"control character in {text!r}")

    def assertNoSecrets(self, result):
        for secret in (PASSWORD, "access-1", "refresh-1", "access-2", "refresh-2"):
            self.assertNotIn(secret, result.out + result.err)


class ParserTest(CliTestCase):
    def test_version_option(self):
        result = run_without_client(["--version"])
        self.assertEqual((result.code, result.out), (0, f"bakalari-api {__version__}\n"))

    def test_help_lists_every_command_by_area(self):
        result = run_without_client(["--help"])
        self.assertEqual(result.code, 0)
        block = result.out.split("commands:\n", 1)[1].split("\n\n", 1)[0].splitlines()
        groups = [line.strip().rstrip(":") for line in block if not line.startswith("    ")]
        names = [re.split(r"\s{2,}", line.strip())[0] for line in block if line.startswith("    ")]
        self.assertEqual(groups, list(COMMANDS))
        self.assertEqual(names, [name for entries in COMMANDS.values() for name in entries])
        self.assertIn("send-message      send a message [changes data]", result.out)
        self.assertIn("BAKALARI_SESSION_FILE", result.out)
        self.assertIn("exit status: 0 success, 1 Bakaláři API or connection error, 2 usage or configuration error",
                      result.out)

    def test_every_command_is_listed_and_has_help(self):
        action = next(item for item in build_parser()._actions if isinstance(item, argparse._SubParsersAction))
        listed = {name.split()[0] for entries in COMMANDS.values() for name in entries}
        self.assertEqual(set(action.choices), listed | {"whoami"})
        for name in sorted(action.choices):
            with self.subTest(name):
                result = run_without_client([name, "--help"])
                self.assertEqual(result.code, 0)
                self.assertTrue(result.out.startswith(f"usage: bakalari {'profile' if name == 'whoami' else name}"))

    def test_usage_errors_exit_2(self):
        for argv in ([], ["nonsense"], ["timetable", "--date", "15.10.2026"], ["timetable", "--date", "2026-02-30"],
                     ["--timeout", "0", "version"], ["--timeout", "nan", "version"], ["--timeout", "abc", "version"],
                     ["--retries", "-1", "version"],
                     ["schools", "--max-requests", "0"], ["predict", "M", "1"], ["predict", "M", "1:0"],
                     ["predict", "M", ":3"], ["predict", "M"], ["api", "FETCH", "/api/3"], ["marks", "--json", "x"],
                     ["public-timetable"], ["public-timetable", "--class", "1A", "--room", "R1"],
                     ["send-message", "--type", "OBECNA", "--recipient-type", "U"], ["message"],
                     ["timetable", "--week", "1", "--permanent"], ["-v", "marks", "--unknown"]):
            with self.subTest(argv):
                result = run_without_client(argv)
                self.assertEqual(result.code, 2)
                self.assertIn("error:", result.err)
                self.assertEqual(result.out, "")

    def test_invalid_date_names_the_accepted_forms(self):
        result = run_without_client(["timetable", "--date", "15.10.2026"])
        self.assertIn("invalid date '15.10.2026': use YYYY-MM-DD, today, yesterday or tomorrow", result.err)

    def test_relative_dates(self):
        result = run(["homeworks", "--since", "yesterday", "--until", "TOMORROW"], token_response(),
                     json_response(200, {"Homeworks": []}))
        today = dt.date.today()
        self.assertEqual(result.calls[0].query, {"from": (today - dt.timedelta(days=1)).isoformat(),
                                                 "to": (today + dt.timedelta(days=1)).isoformat()})
        result = run(["events", "--since", "today"], token_response(), json_response(200, {"Events": []}))
        self.assertEqual(result.calls[0].query, {"from": dt.date.today().isoformat()})


class GlobalOptionsTest(CliTestCase):
    def test_default_factory_passes_the_options_and_the_named_login_variables(self):
        args = build_parser().parse_args(["--base-url", "skola.example/bakaweb/login", "--username-env", "MY_USER",
                                          "--password-env", "MY_PASS", "--timeout", "5", "--retries", "0", "marks"])
        with clean_environment(MY_USER="jan", MY_PASS="tajne"), mock.patch("bakalari.cli.BakalariClient") as created:
            default_client_factory(args, True)
        created.assert_called_once_with("skola.example/bakaweb/login", "jan", "tajne", timeout=5.0, retries=0)
        with clean_environment():
            client = default_client_factory(build_parser().parse_args(["--base-url", BASE_URL, "version"]), False)
        self.assertEqual((client.base_url, client.timeout, client.retries), (BASE_URL, 30.0, 2))
        self.assertFalse(client.is_authenticated)

    def test_default_factory_reads_the_address_from_the_environment(self):
        args = build_parser().parse_args(["marks"])
        with clean_environment(BAKALARI_URL=BASE_URL, BAKALARI_USERNAME="u", BAKALARI_PASSWORD="p"):
            self.assertEqual(default_client_factory(args, True).base_url, BASE_URL)

    def test_default_factory_names_the_missing_variables(self):
        args = build_parser().parse_args(["--username-env", "BAKALARI_TEST_UNSET_USER", "--password-env",
                                          "BAKALARI_TEST_UNSET_PASS", "marks"])
        with clean_environment(), self.assertRaises(BakalariConfigError) as raised:
            default_client_factory(args, True)
        self.assertIn("Missing environment variable(s): BAKALARI_URL, BAKALARI_TEST_UNSET_USER, "
                      "BAKALARI_TEST_UNSET_PASS.", str(raised.exception))
        with clean_environment(BAKALARI_URL=BASE_URL, BAKALARI_TEST_UNSET_USER="u"), \
                self.assertRaises(BakalariConfigError) as raised:
            default_client_factory(args, True)
        self.assertIn("Missing environment variable(s): BAKALARI_TEST_UNSET_PASS.", str(raised.exception))

    def test_default_factory_with_a_session_needs_no_login(self):
        args = build_parser().parse_args(["marks"])
        args.session = SessionState(base_url="https://other.example/bakaweb", refresh_token="r")
        with clean_environment(), mock.patch("bakalari.cli.BakalariClient") as created:
            default_client_factory(args, True)
        created.assert_called_once_with("https://other.example/bakaweb", None, None, timeout=30.0, retries=2)

    def test_default_factory_works_with_a_partial_namespace(self):
        args = argparse.Namespace(username_env="BAKALARI_TEST_UNSET_USER", password_env="BAKALARI_TEST_UNSET_PASS",
                                  base_url=BASE_URL)
        with clean_environment():
            self.assertFalse(default_client_factory(args, needs_login=False).is_authenticated)

    def test_missing_login_variables_exit_2(self):
        result = run_without_client(["--base-url", BASE_URL, "--username-env", "BAKALARI_TEST_UNSET_USER",
                                     "--password-env", "BAKALARI_TEST_UNSET_PASS", "modules"])
        self.assertEqual((result.code, result.out), (2, ""))
        self.assertIn("bakalari: error: Missing environment variable(s): BAKALARI_TEST_UNSET_USER, "
                      "BAKALARI_TEST_UNSET_PASS.", result.err)

    def test_default_directory_factory(self):
        directory = default_directory_factory(build_parser().parse_args(["--timeout", "7.5", "schools"]))
        self.assertEqual((directory.base_url, directory.timeout), (DIRECTORY_URL, 7.5))

    def test_verbose_logs_each_request_without_secrets(self):
        logger = logging.getLogger("bakalari")
        handlers, level = list(logger.handlers), logger.level
        result = run(["-v", "modules"], token_response(), json_response(200, {"EnabledModules": []}))
        self.assertEqual(result.code, 0)
        self.assertIn("DEBUG bakalari.client: POST /api/login -> HTTP 200", result.err)
        self.assertIn("DEBUG bakalari.client: GET /api/3/user -> HTTP 200", result.err)
        self.assertIn("INFO bakalari.client: Logged in to the Bakaláři API as user U1", result.err)
        self.assertNoSecrets(result)
        self.assertEqual((logger.handlers, logger.level), (handlers, level))  # restored after the command

    def test_quiet_without_verbose(self):
        result = run(["modules"], token_response(), json_response(200, {"EnabledModules": [{"Module": "Marks"}]}))
        self.assertEqual((result.code, result.out, result.err), (0, "Marks\n", ""))


class SessionFileTest(CliTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.path = self.directory / "session.json"

    def test_login_stores_the_session_with_mode_0600(self):
        result = run(["--session-file", str(self.path), "login"], token_response())
        self.assertEqual(result.code, 0)
        self.assertEqual(result.lines, [
            f"Logged in as user U1 at {BASE_URL} (API 3.52.1); the access token expires at {expiry(NOW + 3600)}.",
            f"Saved the session to {self.path}.",
        ])
        self.assertEqual(result.err, "")
        self.assertEqual(result.transport.calls[0].form["grant_type"], "password")
        stored = read_session(self.path)
        self.assertEqual((stored["base_url"], stored["refresh_token"], stored["access_token"], stored["user_id"]),
                         (BASE_URL, "refresh-1", "access-1", "U1"))
        self.assertEqual(SessionState.from_dict(stored).expires_at, NOW + 3600)
        if POSIX:
            self.assertEqual(file_mode(self.path), 0o600)
        self.assertEqual(sorted(path.name for path in self.directory.iterdir()), ["session.json"])  # no temporary
        self.assertNoSecrets(result)

    def test_the_session_file_replaces_the_password(self):
        run(["--session-file", str(self.path), "login"], token_response())
        before = (self.path.read_bytes(), os.stat(self.path).st_mtime_ns)
        result = run(["--session-file", str(self.path), "marks", "--count-new"], json_response(200, 0), login=False)
        self.assertEqual((result.code, result.out), (0, "0\n"))
        self.assertEqual(len(result.transport.calls), 1)  # no login: the stored access token is still valid
        self.assertEqual(result.transport.calls[0].headers["Authorization"], "Bearer access-1")
        self.assertEqual((self.path.read_bytes(), os.stat(self.path).st_mtime_ns), before)  # unchanged, not rewritten

    def test_a_refresh_token_alone_starts_the_session_and_the_renewed_one_is_saved(self):
        write_session(self.path, access_token="", expires_at=0.0, mode=0o600)
        result = run(["--session-file", str(self.path), "homeworks", "--count"],
                     token_response("access-2", "refresh-2"), json_response(200, 2), login=False)
        self.assertEqual((result.code, result.out), (0, "2\n"))
        renewal, request = result.transport.calls
        self.assertEqual(renewal.form,
                         {"client_id": "ANDR", "grant_type": "refresh_token", "refresh_token": "refresh-1"})
        self.assertEqual(request.headers["Authorization"], "Bearer access-2")
        stored = read_session(self.path)
        self.assertEqual((stored["refresh_token"], stored["access_token"]), ("refresh-2", "access-2"))
        if POSIX:
            self.assertEqual(file_mode(self.path), 0o600)
        self.assertNoSecrets(result)

    def test_the_session_file_can_come_from_the_environment(self):
        write_session(self.path, access_token="", expires_at=0.0)
        result = run(["modules"], token_response("access-2", "refresh-2"), json_response(200, {"EnabledModules": []}),
                     login=False, env={SESSION_FILE_ENV: str(self.path)})
        self.assertEqual((result.code, result.out), (0, "No modules.\n"))
        self.assertEqual(read_session(self.path)["refresh_token"], "refresh-2")

    def test_a_session_file_alone_works_with_the_default_factory(self):
        write_session(self.path)
        transport = FakeTransport(json_response(200, 1))

        def client_class(*args, **kwargs):
            return BakalariClient(*args, transport=transport, clock=FakeClock(), **kwargs)

        out = io.StringIO()
        with clean_environment(), contextlib.redirect_stdout(out), \
                mock.patch("bakalari.cli.BakalariClient", side_effect=client_class) as created:
            code = main(["--session-file", str(self.path), "messages", "--count"])
        self.assertEqual((code, out.getvalue()), (0, "1\n"))
        created.assert_called_once_with(BASE_URL, None, None, timeout=30.0, retries=2)
        self.assertEqual(transport.calls[0].headers["Authorization"], "Bearer access-1")

    def test_commands_without_login_take_the_address_from_the_session_file(self):
        state = write_session(self.path)
        seen = []

        def factory(args, needs_login):
            seen.append((args.session, needs_login))
            return BakalariClient(BASE_URL, transport=FakeTransport(json_response(200, VERSION)))

        self.assertEqual(run(["--session-file", str(self.path), "version"], factory=factory).code, 0)
        self.assertEqual(run(["--session-file", str(self.path), "version"], factory=factory,
                             env={"BAKALARI_URL": BASE_URL}).code, 0)
        self.assertEqual(seen, [(state, False), (None, False)])  # read only when no address is configured

    def test_a_dead_refresh_token_without_login_variables(self):
        write_session(self.path, access_token="", expires_at=0.0)
        before = self.path.read_bytes()
        result = run(["--session-file", str(self.path), "absence"], INVALID_GRANT, login=False)
        self.assertEqual((result.code, result.out), (1, ""))
        self.assertEqual(result.err.splitlines(), [
            "bakalari: error: the login was refused (invalid_grant: Špatný login nebo heslo)",
            "bakalari: hint: the stored session is no longer accepted: set the login variables and run "
            "'bakalari login'",
        ])
        self.assertEqual(self.path.read_bytes(), before)

    def test_the_login_variables_are_the_fallback_for_a_dead_refresh_token(self):
        write_session(self.path, access_token="", expires_at=0.0)
        result = run(["--session-file", str(self.path), "homeworks", "--count"], INVALID_GRANT,
                     token_response("access-3", "refresh-3"), json_response(200, 0))
        self.assertEqual(result.code, 0)
        refresh, login, _ = result.transport.calls
        self.assertEqual((refresh.form["grant_type"], login.form["grant_type"]), ("refresh_token", "password"))
        self.assertEqual(login.form["username"], USERNAME)
        self.assertEqual(read_session(self.path)["refresh_token"], "refresh-3")

    def test_a_renewed_session_is_saved_even_when_the_command_fails(self):
        write_session(self.path, access_token="", expires_at=0.0)
        result = run(["--session-file", str(self.path), "absence"], token_response("access-2", "refresh-2"),
                     FORBIDDEN, login=False)
        self.assertEqual(result.code, 1)
        self.assertEqual(read_session(self.path)["refresh_token"], "refresh-2")

    def test_login_renews_a_stored_session_without_the_login_variables(self):
        write_session(self.path)
        result = run(["--session-file", str(self.path), "login"], token_response("access-2", "refresh-2"), login=False)
        self.assertEqual(result.code, 0)
        self.assertTrue(result.lines[0].startswith(f"Renewed the session of user U1 at {BASE_URL} (API 3.52.1)"))
        self.assertEqual(result.transport.calls[0].form["grant_type"], "refresh_token")
        self.assertEqual(read_session(self.path)["refresh_token"], "refresh-2")

    def test_login_with_the_login_variables_logs_in_again(self):
        write_session(self.path)
        result = run(["--session-file", str(self.path), "login", "--json"], token_response("access-2", "refresh-2"))
        self.assertEqual(result.code, 0)
        self.assertEqual(result.transport.calls[0].form["grant_type"], "password")
        data = result.data
        self.assertEqual({key: data[key] for key in ("base_url", "user_id", "api_version", "expires_in", "renewed",
                                                       "session_file")},
                         {"base_url": BASE_URL, "user_id": "U1", "api_version": "3.52.1", "expires_in": 3600,
                          "renewed": False, "session_file": str(self.path)})
        self.assertEqual(data["expires_at"], expiry(NOW + 3600))
        self.assertNoSecrets(result)

    def test_login_without_a_session_file_says_that_nothing_is_kept(self):
        result = run(["login"], token_response())
        self.assertEqual(result.code, 0)
        self.assertEqual(len(result.lines), 1)
        self.assertEqual(result.err, "bakalari: note: the session is not kept: pass --session-file PATH (or set "
                                     "BAKALARI_SESSION_FILE) to keep it\n")

    def test_a_missing_directory_is_created(self):
        path = self.directory / "config" / "bakalari" / "session.json"
        self.assertEqual(run(["--session-file", str(path), "login"], token_response()).code, 0)
        self.assertEqual(read_session(path)["refresh_token"], "refresh-1")

    def test_a_session_file_that_cannot_be_written_is_a_configuration_error(self):
        blocker = self.directory / "file.txt"
        blocker.write_text("not a directory", encoding="utf-8")
        result = run(["--session-file", str(blocker / "session.json"), "login"], token_response())
        self.assertEqual(result.code, 2)
        self.assertIn("the session file", result.err.lower())

    def test_a_failed_write_leaves_no_temporary_file(self):
        with mock.patch("bakalari.cli.os.replace", side_effect=OSError(28, "No space left on device")):
            result = run(["--session-file", str(self.path), "login"], token_response())
        self.assertEqual(result.code, 2)
        self.assertIn(f"Cannot write the session file {self.path}: No space left on device", result.err)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_a_failed_login_creates_no_session_file(self):
        result = run(["--session-file", str(self.path), "marks"], INVALID_GRANT)
        self.assertEqual(result.code, 1)
        self.assertFalse(self.path.exists())

    def test_login_without_a_login_or_a_session(self):
        result = run(["login"], login=False)
        self.assertEqual((result.code, result.transport.calls), (2, []))
        self.assertIn("No Bakaláři login", result.err)

    def test_the_factory_s_own_session_callback_is_kept(self):
        updates = []

        def factory(args, needs_login):
            return BakalariClient(BASE_URL, USERNAME, PASSWORD, transport=FakeTransport(token_response()),
                                  clock=FakeClock(), on_session_update=updates.append)

        self.assertEqual(run(["--session-file", str(self.path), "login"], factory=factory).code, 0)
        self.assertEqual([state.refresh_token for state in updates], ["refresh-1"])
        self.assertEqual(read_session(self.path)["refresh_token"], "refresh-1")

    def test_a_session_the_factory_started_is_saved_after_the_command(self):
        transport = FakeTransport(token_response("access-7", "refresh-7"), json_response(200, 0))

        def factory(args, needs_login):
            client = BakalariClient(BASE_URL, USERNAME, PASSWORD, transport=transport, clock=FakeClock())
            client.login()  # before the CLI watches the session
            return client

        self.assertEqual(run(["--session-file", str(self.path), "marks", "--count-new"], factory=factory).code, 0)
        self.assertEqual(read_session(self.path)["refresh_token"], "refresh-7")

    def test_corrupt_and_foreign_session_files_are_configuration_errors(self):
        contents = {"not json": b"{not json", "a list": b"[1, 2]", "no refresh token": b'{"base_url": "x"}',
                    "an invalid address": b'{"base_url": "https://[bad", "refresh_token": "r"}'}
        for what, content in contents.items():
            with self.subTest(what):
                self.path.write_bytes(content)
                result = run(["--session-file", str(self.path), "marks"])
                self.assertEqual((result.code, result.out), (2, ""))
                self.assertEqual(result.err, f"bakalari: error: The session file {self.path} is not a Bakaláři "
                                             "session (it is corrupt or belongs to another program): delete it or "
                                             "pass another --session-file.\n")
                self.assertEqual(result.transport.calls, [])
        self.path.write_bytes(b"\xff\xfe\x00")
        result = run(["--session-file", str(self.path), "marks"])
        self.assertEqual(result.code, 2)
        self.assertIn(f"Cannot read the session file {self.path}", result.err)

    def test_a_session_of_another_school_is_a_configuration_error(self):
        write_session(self.path, base_url="https://other.example/bakaweb")
        result = run(["--session-file", str(self.path), "marks"])
        self.assertEqual(result.code, 2)
        self.assertIn(f"The session file {self.path} belongs to https://other.example/bakaweb, not to {BASE_URL}",
                      result.err)
        self.assertEqual(result.transport.calls, [])

    @unittest.skipUnless(POSIX, "file modes are POSIX")
    def test_a_session_file_readable_by_others_is_restricted(self):
        write_session(self.path, mode=0o644)
        result = run(["--session-file", str(self.path), "marks", "--count-new"], json_response(200, 0), login=False)
        self.assertEqual(result.code, 0)
        self.assertEqual(file_mode(self.path), 0o600)
        self.assertIn("warning: the session file", result.err)

    def test_logout_deletes_the_session_file(self):
        write_session(self.path)
        result = run(["--session-file", str(self.path), "logout"])
        self.assertEqual((result.code, result.out), (0, f"Deleted the session file {self.path}.\n"))
        self.assertFalse(self.path.exists())
        self.assertEqual(result.transport.calls, [])
        result = run(["--session-file", str(self.path), "logout"])
        self.assertEqual((result.code, result.out), (0, f"There is no session file {self.path}.\n"))

    def test_logout_reports_a_file_it_cannot_delete(self):
        write_session(self.path)
        with mock.patch.object(Path, "unlink", side_effect=PermissionError(13, "Permission denied")):
            result = run(["--session-file", str(self.path), "logout"])
        self.assertEqual(result.code, 2)
        self.assertIn(f"Cannot delete the session file {self.path}: Permission denied", result.err)
        self.assertTrue(self.path.exists())

    def test_logout_needs_a_session_file(self):
        result = run(["logout"])
        self.assertEqual((result.code, result.out), (2, ""))
        self.assertIn("logout needs a session file: pass --session-file PATH or set BAKALARI_SESSION_FILE",
                      result.err)

    def test_logout_never_deletes_a_file_that_is_not_a_session(self):
        self.path.write_text("my notes", encoding="utf-8")
        result = run(["--session-file", str(self.path), "logout"])
        self.assertEqual(result.code, 2)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "my notes")


class PublicCommandsTest(CliTestCase):
    def test_version(self):
        result = run(["version"], json_response(200, VERSION))
        self.assertEqual((result.code, result.out),
                         (0, f"Bakaláři REST API 3.52.1 (application 2.2.1009.7) at {BASE_URL}/api/3\n"))
        self.assertEqual(len(result.transport.calls), 1)  # no login
        self.assertNotIn("Authorization", result.transport.calls[0].headers)
        self.assertEqual(run(["version", "--json"], json_response(200, VERSION)).data, VERSION)

    def test_schools_lists_the_municipalities(self):
        result = run(["schools"], fixture("schools_municipalities.json"))
        self.assertEqual(result.code, 0)
        self.assertEqual(result.lines[:3], ["(no name)\t3", "Čertovice\t1", "Kocourkov\t2"])
        self.assertEqual(result.transport.calls[0].url, DIRECTORY + "/municipality")
        data = run(["schools", "--json"], fixture("schools_municipalities.json")).data
        self.assertEqual(data[2], {"name": "Kocourkov", "school_count": 2})

    def test_schools_without_municipalities(self):
        self.assertEqual(run(["schools"], json_response(200, [])).out, "No municipalities.\n")

    def test_schools_matching_a_query(self):
        result = run(["schools", "certovice"], fixture("schools_municipalities.json"),
                     fixture("schools_kocourkov.json"))
        self.assertEqual(result.code, 0)
        self.assertEqual(result.transport.calls[1].url, DIRECTORY + "/municipality/%C4%8Certovice")
        self.assertEqual(result.lines[:2], ["Základní škola Kocourkov, Mlýnská 7\thttps://zs-kocourkov.school.example",
                                            "Gymnázium Kocourkov\thttps://gym-kocourkov.school.example/bakaweb"])
        result = run(["schools", "praha"], fixture("schools_municipalities.json"))
        self.assertEqual((result.code, result.out), (0, "No schools found.\n"))

    def test_schools_of_a_municipality(self):
        result = run(["schools", "--municipality", "Kocourkov", "--json"], fixture("schools_kocourkov.json"))
        self.assertEqual(result.transport.calls[0].url, DIRECTORY + "/municipality/Kocourkov")
        self.assertEqual(result.data[1], {"id": "SYKCAAAAAB", "name": "Gymnázium Kocourkov",
                                          "url": "https://gym-kocourkov.school.example/bakaweb"})

    def test_schools_usage_errors(self):
        result = run(["schools", "kocourkov", "--max-requests", "1"], fixture("schools_municipalities.json"))
        self.assertEqual(result.code, 2)
        self.assertIn("(max_requests=1): use a more specific name", result.err)
        self.assertEqual(len(result.transport.calls), 1)
        result = run(["schools", "x", "--municipality", "y"])
        self.assertEqual((result.code, result.transport.calls), (2, []))
        self.assertIn("pass either QUERY or --municipality, not both", result.err)

    def test_schools_unknown_municipality(self):
        result = run(["schools", "--municipality", "Atlantida"], json_response(404, {"Message": "Not found"}))
        self.assertEqual(result.code, 1)
        self.assertIn(f"GET {DIRECTORY}/municipality/Atlantida answered HTTP 404 Not Found: Not found", result.err)

    def test_public_timetable_list(self):
        result = run(["public-timetable", "--list"], page("public_timetable_index.html"))
        self.assertEqual(result.code, 0)
        self.assertEqual(result.lines[0], "class    2B        2.B")
        self.assertIn("teacher  'U  19'   Vzorový Karel", result.lines)
        self.assertIn("room     'G 7'     14", result.lines)
        self.assertNotIn("Authorization", result.transport.calls[0].headers)
        data = run(["public-timetable", "--list", "--json"], page("public_timetable_index.html")).data
        self.assertEqual(data["teachers"][1], {"kind": "teacher", "id": "U  19", "name": "Vzorový Karel"})

    def test_public_timetable_of_a_target_named_by_its_name(self):
        result = run(["public-timetable", "--teacher", "vzorový karel", "--next"], page("public_timetable_index.html"),
                     page("public_timetable_actual.html"))
        self.assertEqual(result.code, 0)
        self.assertEqual(result.transport.calls[1].path, "/bakaweb/Timetable/Public/Next/Teacher/U%20%2019")
        self.assertEqual(result.lines[:3], [
            "Public timetable of teacher Vzorový Karel, next week",
            "po 16.11. (2026-11-16): 5 lesson(s)",
            "     1.  8:00-8:45  Anglický jazyk | Ing. Karel Vzorový | 14 | Aj1",
        ])
        self.assertEqual(len(result.transport.calls), 2)  # no login

    def test_public_timetable_permanent_json_and_unlisted_ids(self):
        result = run(["public-timetable", "--class", "2B", "--permanent", "--json"],
                     page("public_timetable_index.html"), page("public_timetable_permanent.html"))
        self.assertEqual(result.transport.calls[1].path, "/bakaweb/Timetable/Public/Permanent/Class/2B")
        self.assertEqual(result.data["week"], "permanent")
        result = run(["public-timetable", "--room", "X9"], page("public_timetable_index.html"),
                     page("public_timetable_actual.html"))
        self.assertEqual(result.transport.calls[1].path, "/bakaweb/Timetable/Public/Actual/Room/X9")
        self.assertEqual(result.lines[0], "Public timetable of room X9, this week")

    def test_public_timetable_without_target_lists_tries_the_id(self):
        result = run(["public-timetable", "--class", "2B"], text_response(200, "<html><body>nic</body></html>"),
                     page("public_timetable_actual.html"))
        self.assertEqual(result.code, 0)
        self.assertEqual(result.lines[0], "Public timetable of class 2B, this week")

    def test_a_school_that_does_not_publish_the_timetable(self):
        url = BASE_URL + "/next/errinfo.aspx?e=K+po%c5%beadovan%c3%a9+str%c3%a1nce+nem%c3%a1te+p%c5%99%c3%adstup."
        result = run(["public-timetable", "--class", "2B"], page("public_timetable_index.html"),
                     page("public_timetable_errinfo.html", url=url))
        self.assertEqual((result.code, result.out), (1, ""))
        self.assertEqual(result.err.splitlines(), [
            "bakalari: error: GET /Timetable/Public/Actual/Class/2B answered HTTP 403 Forbidden: K požadované stránce "
            "nemáte přístup.",
            "bakalari: hint: the school does not publish this timetable",
        ])

    def test_public_timetable_week_options_need_a_target(self):
        result = run(["public-timetable", "--list", "--next"])
        self.assertEqual((result.code, result.transport.calls), (2, []))
        self.assertIn("--permanent and --next need --class, --teacher or --room", result.err)


class AccountCommandsTest(CliTestCase):
    def test_profile(self):
        result = run(["profile"], token_response(), fixture("user_parent.json"))
        self.assertEqual(result.code, 0)
        self.assertEqual(result.lines, [
            "User type: rodič (parents)",
            "Name: Kocourek Vilém, 6.E",
            "Account holder: Kocourková Bára",
            "Class: 6.E",
            "Study year: 6",
            "School: Základní škola Kocourkov, Mlýnská 7",
            "School year: 2026/27 (2026-09-01 - 2027-08-31)",
            "Semester: 1 (2026-09-01 - 2027-01-31)",
            "Students:",
            "    Kocourek Vilém, 6.E",
        ])

    def test_profile_of_a_teacher_and_a_student_without_the_class_in_the_name(self):
        profile = {"UserType": "teacher", "UserTypeText": "učitel", "FullName": "Mgr. Ivana Mlynářová",
                   "SchoolType": "ZŠ",
                   "TeacherClasses": [{"Id": "1A", "Abbrev": "1.A", "Name": "1. A"}],
                   "Students": [{"FullName": "Jan Novák", "Class": {"Id": "2B", "Abbrev": "2.B", "Name": ""}}]}
        result = run(["profile"], token_response(), json_response(200, profile))
        self.assertEqual(result.lines, ["User type: učitel (teacher)", "Name: Mgr. Ivana Mlynářová", "Classes: 1.A",
                                        "School type: ZŠ", "Students:", "    Jan Novák (2.B)"])

    def test_whoami_json(self):
        result = run(["whoami", "--json"], token_response(), fixture("user_parent.json"))
        data = result.data
        self.assertEqual((data["full_name"], data["user_type"]), ("Kocourek Vilém, 6.E", "parents"))
        self.assertNotIn("settings", data)

    def test_modules(self):
        profile = {"EnabledModules": [{"Module": "Timetable"},
                                      {"Module": "Marks", "Rights": ["ShowMarks", "PredictMarks"]}]}
        result = run(["modules"], token_response(), json_response(200, profile))
        self.assertEqual((result.code, result.out.split()), (0, ["Timetable", "Marks"]))
        result = run(["modules", "--rights"], token_response(), json_response(200, profile))
        self.assertEqual(result.lines, ["Timetable: -", "Marks: ShowMarks, PredictMarks"])
        result = run(["modules", "--json"], token_response(), json_response(200, profile))
        self.assertEqual(result.data, [{"module": "Timetable", "rights": []},
                                       {"module": "Marks", "rights": ["ShowMarks", "PredictMarks"]}])

    def test_web_login_prints_the_link_and_warns_that_it_is_a_credential(self):
        result = run(["web-login"], token_response(), json_response(200, "tok/en"))
        self.assertEqual(result.out, f"{BASE_URL}/api/3/login/tok%2Fen?returnUrl=next/dash.aspx\n")
        self.assertIn("bakalari: warning: the link logs anyone who opens it in to the Bakaláři web as you", result.err)
        result = run(["web-login", "--return-url", "next/prubzna.aspx"], token_response(), json_response(200, "t"))
        self.assertEqual(result.out, f"{BASE_URL}/api/3/login/t?returnUrl=next/prubzna.aspx\n")

    def test_web_login_into_a_web_module(self):
        result = run(["web-login", "--module", "DOKUMENTY"], token_response(), fixture("webmodule.json"),
                     json_response(200, "t"))
        self.assertEqual(result.out, f"{BASE_URL}/api/3/login/t?returnUrl=next/dokumentyPrehled.aspx\n")
        result = run(["web-login", "--module", "Rozvrh"], token_response(), fixture("webmodule.json"))
        self.assertEqual(result.code, 2)
        self.assertIn("no web module 'Rozvrh' (the account has: Ankety, Dokumenty)", result.err)

    def test_web_modules(self):
        result = run(["web-modules"], token_response(), fixture("webmodule.json"))
        self.assertEqual(result.lines, ["Ankety\tnext/ankety.aspx", "Dokumenty\tnext/dokumentyPrehled.aspx",
                                        "(dashboard)\tnext/dash.aspx"])
        data = run(["web-modules", "--json"], token_response(), fixture("webmodule.json")).data
        self.assertEqual(data["dashboard"]["url"], "next/dash.aspx")
        result = run(["web-modules"], token_response(), json_response(200, {"WebModules": None}))
        self.assertEqual(result.out, "No web modules.\n")

    def test_at_school(self):
        self.assertEqual(run(["at-school"], token_response(), json_response(200, True)).out, "at school\n")
        self.assertEqual(run(["at-school"], token_response(), json_response(200, False)).out, "not at school\n")
        self.assertEqual(run(["at-school", "--json"], token_response(), json_response(200, True)).data, True)
        result = run(["at-school"], token_response(), FORBIDDEN)
        self.assertEqual(result.code, 1)
        self.assertIn("bakalari: hint: the AccessSystem module (right CanShowStudentPresentAtSchool) is not enabled",
                      result.err)


class TimetableCommandsTest(CliTestCase):
    def test_timetable_text(self):
        result = run(["timetable", "--date", "2026-10-15"], token_response(), fixture("actual.json"))
        self.assertEqual(result.code, 0)
        self.assertEqual(result.calls[0].query, {"date": "2026-10-15"})
        lines = result.lines
        self.assertEqual(lines[0], "Actual timetable, week 2026-10-12 - 2026-10-18")
        self.assertEqual(lines[1], "2026-10-12 po WorkDay: 2 lesson(s)")
        self.assertIn("Matematika | RNDr. Petr Dvořák | 105 | 1.A [RoomChanged: Změna učebny: 105]", result.out)

    def test_timetable_json_of_one_day(self):
        result = run(["timetable", "--day", "2026-10-12", "--json"], token_response(), fixture("actual.json"))
        self.assertEqual(result.code, 0)
        self.assertEqual([lesson["subject"] for lesson in result.data], ["", "Český jazyk a literatura"])

    def test_timetable_lessons_of_one_day(self):
        result = run(["timetable", "--day", "2026-10-13"], token_response(), fixture("actual.json"))
        self.assertEqual(result.lines, ["2026-10-13  1.  8:00-8:45  Matematika | RNDr. Petr Dvořák | 105 | 1.A "
                                        "[RoomChanged: Změna učebny: 105]"])
        result = run(["timetable", "--day", "2026-10-14"], token_response(), fixture("actual.json"))
        self.assertEqual(result.out, "No lessons.\n")

    def test_permanent_timetable_json(self):
        result = run(["timetable", "--permanent", "--json"], token_response(), fixture("permanent.json"))
        self.assertEqual(result.code, 0)
        self.assertEqual(result.calls[0].path, "/bakaweb/api/3/timetable/permanent")
        self.assertEqual(len(result.data["days"]), 2)
        result = run(["timetable", "--permanent"], token_response(), fixture("permanent.json"))
        self.assertEqual(result.lines[0], "Permanent timetable")

    def test_timetable_of_another_week(self):
        result = run(["timetable", "--week", "-1"], token_response(), fixture("actual.json"))
        last_week = dt.date.today() - dt.timedelta(weeks=1)
        self.assertEqual(result.calls[0].query, {"date": last_week.isoformat()})
        monday, sunday = week_of(last_week)
        self.assertEqual(result.lines[0], f"Actual timetable, week {monday.isoformat()} - {sunday.isoformat()}")

    def test_timetable_of_the_own_class_with_details(self):
        result = run(["timetable", "--class", "--details", "--date", "2026-10-19"], token_response(),
                     fixture("user_parent.json"), fixture("timetable_class.json"))
        self.assertEqual(result.code, 0)
        self.assertEqual([call.api_path for call in result.calls], ["/api/3/user", "/api/3/timetable/actual/class/2E"])
        self.assertEqual(result.lines[:9], [
            "Class timetable 6.E, week 2026-10-19 - 2026-10-25",
            "2026-10-19 po WorkDay: 4 lesson(s)",
            "     1.  8:00-8:45  Tělesná výchova | Bc. Tomáš Malý | TV1 | 1.B Chl",
            "        theme: Atletika",
            "     1.  8:00-8:45  Tělesná výchova | Mgr. Lucie Bílá | TV2 | 1.B Dív",
            "        theme: Gymnastika",
            "     2.  8:55-9:40  Matematika | Mgr. Eva Horáková | 031 | 1.B",
            "        theme: Lineární rovnice",
            "        notice: Přineste si kalkulačku.",
        ])
        self.assertEqual(result.lines[9], "        homework: Pracovní sešit str. 12, cvičení 3 a 4")

    def test_timetable_of_a_class_by_id(self):
        result = run(["timetable", "--class", "1B", "--permanent"], token_response(), fixture("timetable_class.json"))
        self.assertEqual(result.calls[0].api_path, "/api/3/timetable/permanent/class/1B")
        self.assertEqual(result.lines[0], "Permanent class timetable 1.B")
        result = run(["timetable", "--class", "XY", "--date", "2026-10-19", "--day", "2026-10-19", "--details"],
                     token_response(), fixture("timetable_class.json"))
        self.assertEqual(result.calls[0].query, {"date": "2026-10-19"})
        self.assertEqual(result.lines[1], "    theme: Atletika")
        result = run(["timetable", "--class", "XY", "--date", "2026-10-19"], token_response(),
                     fixture("timetable_class.json"))
        self.assertEqual(result.lines[0], "Class timetable XY, week 2026-10-19 - 2026-10-25")

    def test_timetable_of_the_own_class_needs_one(self):
        result = run(["timetable", "--class"], token_response(), json_response(200, {"UserType": "teacher"}))
        self.assertEqual(result.code, 2)
        self.assertIn("the account has no class of its own: pass --class ID", result.err)

    def test_substitutions(self):
        result = run(["substitutions"], token_response(), fixture("substitutions.json"))
        self.assertEqual(result.calls[0].query, {})
        self.assertEqual(result.lines[:3], [
            "Substitutions 2026-10-12 - 2026-10-26",
            "2026-10-12 1. hod (8:00 - 8:45) Absence: Třídnická hodina: Horáková Eva",
            "2026-10-14 3. hod (10:00 - 10:45) Substitution: Suplování: Veselý Karel | 1.B, F, 031",
        ])
        result = run(["substitutions", "--since", "2026-10-12", "--json"], token_response(),
                     fixture("substitutions.json"))
        self.assertEqual(result.calls[0].query, {"from": "2026-10-12"})
        self.assertEqual(len(result.data["changes"]), 6)
        result = run(["substitutions"], token_response(), json_response(200, {"Changes": []}))
        self.assertEqual(result.lines, ["Substitutions ? - ?", "No changes."])

    def test_substitutions_of_one_day(self):
        result = run(["substitutions", "--day", "2026-10-14"], token_response(), fixture("substitutions.json"))
        self.assertEqual(result.calls[0].query, {"from": "2026-10-14"})  # its 14 days include the day
        self.assertEqual(result.lines, [
            "Substitutions on 2026-10-14",
            "3. hod (10:00 - 10:45) Substitution: Suplování: Veselý Karel | 1.B, F, 031",
            "4. hod (10:55 - 11:40) RoomChanged: Změna učebny: 105 | AjS2, Aj, 105",
        ])
        result = run(["substitutions", "--day", "2026-10-15", "--json"], token_response(),
                     fixture("substitutions.json"))
        self.assertEqual(result.data, [])
        result = run(["substitutions", "--day", "2026-10-13"], token_response(), fixture("substitutions.json"))
        self.assertEqual(result.lines[1], "No changes.")

    def test_substitutions_module_disabled(self):
        result = run(["substitutions"], token_response(), FORBIDDEN)
        self.assertEqual(result.err.splitlines(), [
            "bakalari: error: GET /api/3/substitutions answered HTTP 403 Forbidden: An error has occurred.",
            "bakalari: hint: the module or right this needs is not enabled for the account or the school",
        ])

    def test_events(self):
        result = run(["events", "--details"], token_response(), fixture("events.json"))
        self.assertEqual(result.calls[0].api_path, "/api/3/events")
        self.assertEqual(result.lines, [
            "2026-10-20 08:00-12:30 Exkurze do hvězdárny [školní akce] | 2.B (celá)",
            "    Sraz v 7:40 před školou.",
            "    S sebou svačinu a pití.",
            "2027-01-11..2027-01-13 Lyžařský výcvikový kurz [kurz] | 1.A (celá), 1.B (celá)",
            "2027-02-12 19:00 - 2027-02-13 01:30 Školní ples [společenská akce] | TV1",
            "    Vstupenky prodává kancelář školy.",
            "    note: Pořádá spolek rodičů.",
            "2026-11-05 16:00-18:00 Konzultace s rodiči [konzultace] | 2.B (celá) | 105",
            "    Individuální konzultace podle rozpisu.",
        ])
        result = run(["events"], token_response(), fixture("events.json"))
        self.assertEqual(len(result.lines), 4)

    def test_event_scopes_since_and_json(self):
        result = run(["events", "--my", "--since", "2026-10-01"], token_response(), json_response(200, {"Events": []}))
        self.assertEqual((result.calls[0].api_path, result.calls[0].query),
                         ("/api/3/events/my", {"from": "2026-10-01"}))
        self.assertEqual(result.out, "No events.\n")
        result = run(["events", "--public", "--json"], token_response(), fixture("events.json"))
        self.assertEqual(result.calls[0].api_path, "/api/3/events/public")
        self.assertEqual([event["id"] for event in result.data], ["QW3RT", "ZX8CV", "PL4NB", "MT5KL"])

    def test_events_without_times_or_type(self):
        events = {"Events": [{"Id": "1", "Title": "Den otevřených dveří", "Times": []},
                             {"Id": "3", "Title": "Sbírka", "Times": [{"StartTime": "2026-12-02T10:00:00+01:00"}]},
                             {"Id": "2", "Title": "", "Times": [{"WholeDay": True,
                                                                  "StartTime": "2026-12-01T00:00:00+01:00",
                                                                  "IntervalDate": "2026-12-01T00:00:00+01:00"}]}]}
        result = run(["events"], token_response(), json_response(200, events))
        self.assertEqual(result.lines, ["- Den otevřených dveří", "2026-12-02 10:00 Sbírka", "2026-12-01 (no title)"])


class MarksCommandsTest(CliTestCase):
    def test_marks(self):
        result = run(["marks"], token_response(), fixture("marks.json"))
        self.assertEqual(result.code, 0)
        self.assertEqual(result.calls[0].query, {})
        self.assertEqual(result.lines[:3], [
            "ČJL Český jazyk a literatura: average 2,57, 3 mark(s)",
            "    2026-09-14  1       weight 2  Diktát 1: Vyjmenovaná slova po B (diktát)",
            "    2026-10-05  3-      weight 4  Slohová práce (písemná práce) [new, unconfirmed]",
        ])
        self.assertIn("F Fyzika: average 0,67, 2 mark(s)", result.lines)
        self.assertEqual(len(result.lines), 10)

    def test_marks_of_one_subject_since_a_date(self):
        result = run(["marks", "--subject", "m", "--since", "2026-09-01"], token_response(), fixture("marks.json"))
        self.assertEqual(result.calls[0].query, {"from": "2026-09-01"})
        self.assertEqual(result.lines, ["M Matematika: average 1,50, 2 mark(s)",
                                        "    2026-09-22  1-      weight 3  Zlomky: Sčítání zlomků (písemná práce)",
                                        "    2026-10-01  N       weight 1  Test (test)"])
        data = run(["marks", "--subject", "12", "--json"], token_response(), fixture("marks.json")).data
        self.assertEqual((data["subject"]["name"], data["average"]), ("Matematika", 1.5))

    def test_marks_of_an_unknown_subject(self):
        result = run(["marks", "--subject", "dějepis"], token_response(), fixture("marks.json"))
        self.assertEqual((result.code, result.out), (2, ""))
        self.assertIn("no subject 'dějepis' among the marks (subjects: ČJL, M, F)", result.err)

    def test_new_and_unconfirmed_marks(self):
        result = run(["marks", "--new"], token_response(), fixture("marks.json"))
        self.assertEqual(result.lines, [
            "ČJL Český jazyk a literatura: average 2,57, 3 mark(s)",
            "    2026-10-05  3-      weight 4  Slohová práce (písemná práce) [new, unconfirmed]",
            "F Fyzika: average 0,67, 2 mark(s)",
            "    2026-10-09  5/20              Laboratorní práce (laboratorní práce) [new, unconfirmed]",
        ])
        result = run(["marks", "--unconfirmed", "--subject", "čjl"], token_response(), fixture("marks.json"))
        self.assertEqual(len(result.lines), 3)
        result = run(["marks", "--new", "--unconfirmed", "--subject", "M"], token_response(), fixture("marks.json"))
        self.assertEqual(result.out, "No new unconfirmed marks.\n")
        data = run(["marks", "--unconfirmed", "--json"], token_response(), fixture("marks.json")).data
        self.assertEqual([(subject["subject"]["abbrev"], len(subject["marks"])) for subject in data],
                         [("ČJL", 2), ("F", 1)])

    def test_marks_json_and_empty(self):
        data = run(["marks", "--json"], token_response(), fixture("marks.json")).data
        self.assertEqual(len(data["subjects"]), 3)
        self.assertEqual(data["mark_options"][0], {"id": "1", "abbrev": "1", "name": "1"})
        result = run(["marks"], token_response(), json_response(200, {"Subjects": []}))
        self.assertEqual(result.out, "No marks.\n")

    def test_new_marks_counter(self):
        result = run(["marks", "--count-new"], token_response(), json_response(200, 2))
        self.assertEqual((result.code, result.out, result.calls[0].api_path), (0, "2\n", "/api/3/marks/count-new"))
        self.assertEqual(run(["marks", "--count-new", "--json"], token_response(), json_response(200, 0)).data, 0)
        result = run(["marks", "--count-new", "--new"])
        self.assertEqual((result.code, result.transport.calls), (2, []))

    def test_final_marks_and_measures(self):
        result = run(["final-marks"], token_response(), fixture("marks_final.json"))
        self.assertEqual(result.lines[0], "2024/25 semester 2 (2025-06-27): prospěl s vyznamenáním, average 1.33, "
                                          "absent 31 h (0 unexcused)")
        self.assertEqual(result.lines[1], "    Chv Chování: 1")
        self.assertEqual(len(run(["final-marks", "--json"], token_response(), fixture("marks_final.json")).data), 2)
        result = run(["final-marks"], token_response(), json_response(200, {"CertificateTerms": []}))
        self.assertEqual(result.out, "No final marks.\n")
        result = run(["measures"], token_response(), fixture("marks_measures.json"))
        self.assertEqual(result.lines[0], "2025-12-18 pochvala třídního učitele: za reprezentaci školy v matematické "
                                          "olympiádě & ve sběru papíru (2025/26, semester 1)")
        data = run(["measures", "--json"], token_response(), fixture("marks_measures.json")).data
        self.assertEqual(data[1]["type_id"], "nTU")
        result = run(["measures"], token_response(), json_response(200, {"PedagogicalMeasures": []}))
        self.assertEqual(result.out, "No pedagogical measures.\n")

    def test_predict(self):
        result = run(["predict", "ČJL", "1:3", "2-:1"], token_response(), fixture("marks.json"),
                     fixture("marks_what_if.json"))
        self.assertEqual(result.code, 0)
        marks, what_if = result.calls
        self.assertEqual(marks.query, {})  # all marks: the server averages what it is sent
        self.assertEqual((what_if.method, what_if.api_path), ("POST", "/api/3/marks/what-if"))
        self.assertEqual([entry["Id"] for entry in what_if.json],
                         ["QX7K0A{1}B", "QX7K0A(2)C", "QX7K0B:3/D", None, None])
        self.assertEqual(what_if.json[3:], [
            {"Id": None, "MarkText": "1", "Weight": 3, "MaxPoints": 0, "SubjectId": " 4"},
            {"Id": None, "MarkText": "2-", "Weight": 1, "MaxPoints": 0, "SubjectId": " 4"},
        ])
        self.assertEqual(result.lines, ["ČJL Český jazyk a literatura: average 2,57, 3 mark(s)",
                                        "Predicted average with 1 (weight 3), 2- (weight 1): 2,10"])
        data = run(["predict", "4", "1:3", "--json"], token_response(), fixture("marks.json"),
                   fixture("marks_what_if.json")).data
        self.assertEqual(data["average"], 2.1)

    def test_predict_refuses_unknown_subjects_and_marks_before_computing(self):
        result = run(["predict", "ČJL", "Z:3"], token_response(), fixture("marks.json"))
        self.assertEqual((result.code, len(result.calls)), (2, 1))
        self.assertIn("unknown mark(s) Z: the school uses 1, 1-, 2, 2-, 3, 3-, 4, 4-, 5, N, X, ?, A, P, U", result.err)
        result = run(["predict", "Dějepis", "1:1"], token_response(), fixture("marks.json"))
        self.assertEqual((result.code, len(result.calls)), (2, 1))

    def test_predict_disabled_for_the_subject(self):
        result = run(["predict", "M", "1:1"], token_response(), fixture("marks.json"), FORBIDDEN)
        self.assertEqual(result.code, 1)
        self.assertIn("bakalari: hint: mark prediction is disabled for this subject, or the account lacks the right "
                      "PredictMarks", result.err)

    def test_confirm_every_unconfirmed_mark(self):
        result = run(["confirm-marks", "--all-unconfirmed"], token_response(), fixture("marks.json"),
                     empty_response(200))
        self.assertEqual(result.code, 0)
        confirmation = result.calls[1]
        self.assertEqual((confirmation.method, confirmation.api_path),
                         ("POST", "/api/3/marks/SetClassificationConfirmation"))
        self.assertEqual(confirmation.json, ["QX7K0A(2)C", "QX7K0B:3/D", "JT5R2J=7;L"])
        self.assertEqual(result.lines, [
            "Confirmed 3 mark(s):",
            "    ČJL  2026-10-05  3-      weight 4  Slohová práce (písemná práce) [new]",
            "    ČJL  2026-10-08  2       weight 1  Interpunkce (ústní zkoušení) - Pěkná práce, pozor na čárky.",
            "    F    2026-10-09  5/20              Laboratorní práce (laboratorní práce) [new]",
        ])

    def test_confirm_marks_by_id(self):
        result = run(["confirm-marks", "QX7K0A(2)C", "U 1", "QX7K0A(2)C"], token_response(), empty_response(200))
        self.assertEqual(result.calls[0].json, ["QX7K0A(2)C", "U 1"])
        self.assertEqual(result.lines, ["Confirmed 2 mark(s):", "    'QX7K0A(2)C'", "    'U 1'"])
        result = run(["confirm-marks", "QX7K0A(2)C"], token_response(), empty_response(204))
        self.assertEqual((result.code, result.out), (0, "Nothing to confirm.\n"))

    def test_confirm_marks_with_nothing_pending_sends_no_confirmation(self):
        data = copy.deepcopy(load_fixture("marks.json"))
        for subject in data["Subjects"]:
            for mark in subject["Marks"]:
                mark["MarkConfirmationState"] = "Confirmed"
        result = run(["confirm-marks", "--all-unconfirmed"], token_response(), json_response(200, data))
        self.assertEqual((result.code, result.out, len(result.calls)), (0, "Nothing to confirm.\n", 1))

    def test_confirm_marks_needs_ids_or_all(self):
        for argv in (["confirm-marks"], ["confirm-marks", "X", "--all-unconfirmed"]):
            result = run(argv)
            self.assertEqual((result.code, result.transport.calls), (2, []))
            self.assertIn("pass the ids of the marks to confirm or --all-unconfirmed", result.err)
        result = run(["confirm-marks", "X"], token_response(), FORBIDDEN)
        self.assertIn("hint: the account lacks the right CanConfirmClassification", result.err)


class SchoolWorkCommandsTest(CliTestCase):
    def test_absence(self):
        result = run(["absence", "--days"], token_response(), fixture("absence.json"))
        self.assertEqual(result.lines, [
            "Threshold: 25% of the lessons",
            "Český jazyk a literatura: missed 5 of 20 lessons (25.0%), late 1 [over the threshold]",
            "Matematika: missed 2 of 21 lessons (9.5%), left early 1",
            "Fyzika: missed 3 of 8 lessons (37.5%), school activity 1, distance teaching 1 [over the threshold]",
            "(no subject): missed 0 of 4 lessons (0.0%), school activity 2",
            "2026-09-14: excused 5 (total 5)",
            "2026-09-22: unsolved 2, unexcused 1, late 1 (total 4)",
            "2026-10-06: left early 1, school activity 3, distance teaching 1 (total 5)",
            "Total: unsolved 2, excused 5, unexcused 1, late 1, left early 1, school activity 3, distance teaching 1",
        ])
        result = run(["absence"], token_response(), fixture("absence.json"))
        self.assertEqual(len(result.lines), 6)

    def test_absence_without_data_and_json(self):
        empty = {"PercentageThreshold": None, "Absences": [],
                 "AbsencesPerSubject": [{"SubjectName": "Hudební výchova"}]}
        result = run(["absence"], token_response(), json_response(200, empty))
        self.assertEqual(result.lines, ["Hudební výchova: missed 0 of 0 lessons (-)", "Total: no absence"])
        result = run(["absence"], token_response(), json_response(200, {"Absences": [], "AbsencesPerSubject": []}))
        self.assertEqual(result.lines, ["No absence per subject.", "Total: no absence"])
        data = run(["absence", "--json"], token_response(), fixture("absence.json")).data
        self.assertEqual((data["percentage_threshold"], len(data["days"])), (0.25, 3))

    def test_subjects(self):
        result = run(["subjects"], token_response(), fixture("subjects.json"))
        self.assertEqual(result.lines, [
            "2   Čj  Český jazyk a literatura | Mgr. Jana Nováková",
            "10  M   Matematika | Ing. Petr Svoboda",
            "TV  TV  Tělesná výchova | Bc. Eva Dvořáková | eva.dvorakova@school.example | school phone "
            "+420 100 010 203 | mobile +420 100 040 506",
        ])
        data = run(["subjects", "--json"], token_response(), fixture("subjects.json")).data
        self.assertEqual(data[0]["id"], " 2")
        result = run(["subjects"], token_response(), json_response(200, {"Subjects": []}))
        self.assertEqual(result.out, "No subjects.\n")

    def test_themes_of_a_subject_named_by_abbreviation(self):
        result = run(["subjects", "--themes", "čj"], token_response(), fixture("subjects.json"),
                     fixture("subjects_themes.json"))
        self.assertEqual(result.calls[1].path, "/bakaweb/api/3/subjects/themes/%202")
        self.assertEqual(result.lines, [
            "Čj Český jazyk a literatura",
            "2026-09-01  1. hod  8:00-8:45  1. Opakování učiva 6. ročníku",
            "2026-09-03  3. hod  10:00-10:45  2. Slovní druhy",
            "2026-10-13  2. hod  8:55-9:40  12. Diktát: vyjmenovaná slova po B",
        ])

    def test_themes_fall_back_to_the_id_as_given(self):
        themes = {"Subject": {"Id": "X/1", "Abbrev": "", "Name": ""},
                  "Themes": [{"Date": None, "Theme": "", "Note": "doplnit", "HourCaption": "", "Start": 0,
                              "Duration": 0, "LessonLabel": ""}]}
        result = run(["subjects", "--themes", "X/1", "--json"], token_response(), fixture("subjects.json"),
                     json_response(200, themes))
        self.assertEqual((result.calls[1].api_path, result.calls[1].query),
                         ("/api/3/subjects/themes/get", {"subjectid": "X/1"}))
        self.assertEqual(result.data["themes"][0]["note"], "doplnit")
        result = run(["subjects", "--themes", "X/1"], token_response(), FORBIDDEN, json_response(200, themes))
        self.assertEqual(result.lines, ["X/1", "-  (no theme) (doplnit)"])
        empty = {"Subject": {"Id": "10", "Abbrev": "M", "Name": "Matematika"}, "Themes": []}
        result = run(["subjects", "--themes", "10"], token_response(), fixture("subjects.json"),
                     json_response(200, empty))
        self.assertEqual(result.lines, ["M Matematika", "No themes."])

    def test_homeworks(self):
        result = run(["homeworks", "--since", "2026-09-01", "--until", "2026-10-31"], token_response(),
                     fixture("homeworks.json"))
        self.assertEqual(result.calls[0].query, {"from": "2026-09-01", "to": "2026-10-31"})
        self.assertEqual(result.lines, [
            "due 2026-10-07  Čj  [finished]  id HW0A1B2C3D",
            "    Pracovní sešit str. 12, cvičení 3 a 4.",
            "due 2026-10-15  M  [electronic]  id HW0A1B2C4E",
            "    Vypracujte úlohy z přiloženého listu.",
            "    Postup najdete na https://school.example/ukoly/zlomky",
            "    attachment: zlomky.pdf (id 'UAB  3XYZQ', 48213 bytes, application/pdf)",
            "    attachment: obrázek.jpg (id 'UAB  3XYZR', 0 bytes, image/jpeg)",
            "due 2026-09-24  Čj  [done, finished, closed]  id HW0A1B2B9F",
            "    Naučit se básničku nazpaměť.",
        ])

    def test_open_homeworks_json_and_empty(self):
        result = run(["homeworks", "--open", "--json"], token_response(), fixture("homeworks.json"))
        self.assertEqual(result.calls[0].query, {})
        self.assertEqual([homework["id"] for homework in result.data], ["HW0A1B2C3D", "HW0A1B2C4E"])
        homework = {"ID": "H 1", "Notice": "x", "Attachments": [{"Id": "A1", "Name": "list.txt"}]}
        result = run(["homeworks"], token_response(), json_response(200, {"Homeworks": [homework]}))
        self.assertEqual(result.lines, ["due -  id 'H 1'", "    notice: x", "    attachment: list.txt (id A1)"])
        result = run(["homeworks", "--open"], token_response(), json_response(200, {"Homeworks": []}))
        self.assertEqual(result.out, "No homeworks.\n")

    def test_open_homeworks_counter(self):
        result = run(["homeworks", "--count"], token_response(), json_response(200, 2))
        self.assertEqual((result.out, result.calls[0].api_path), ("2\n", "/api/3/homeworks/count-actual"))
        result = run(["homeworks", "--count", "--open"])
        self.assertEqual((result.code, result.transport.calls), (2, []))

    def test_homework_done_and_undone(self):
        result = run(["homework-done", "HW0A1B2C4E"], token_response(), text_response(200, "true", "application/json"))
        call = result.calls[0]
        self.assertEqual((call.method, call.api_path, call.body),
                         ("PUT", "/api/3/homeworks/HW0A1B2C4E/student-done/true", None))
        self.assertEqual(result.out, "Marked homework HW0A1B2C4E as finished.\n")
        result = run(["homework-done", "H 1", "--undo"], token_response(), empty_response(204))
        self.assertEqual(result.calls[0].api_path, "/api/3/homeworks/H%201/student-done/false")
        self.assertEqual(result.out, "Marked homework 'H 1' as not finished.\n")

    def test_homework_done_refused_by_the_server(self):
        result = run(["homework-done", "HW1"], token_response(), text_response(200, "false", "application/json"))
        self.assertEqual((result.code, result.out), (1, ""))
        self.assertIn("answered false: the homework was not marked finished", result.err)
        result = run(["homework-done", ""])
        self.assertEqual(result.code, 2)
        self.assertIn("needs a homework id", result.err)


class KomensCommandsTest(CliTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def test_received_messages(self):
        result = run(["messages"], token_response(), fixture("komens_received.json"))
        call = result.calls[0]
        self.assertEqual((call.method, call.api_path, call.form), ("POST", "/api/3/komens/messages/received", {}))
        self.assertEqual(result.lines, [
            "400101  2026-10-12 09:15  Mgr. Petra Ukázková: Třídní schůzky  [1 attachment]",
            "400099  2026-10-05 14:02  Jan Vzorový (ředitelství): Souhlas s exkurzí  [unread, to confirm]",
            "400087  2026-09-28 07:30  Ing. Tomáš Vzorník: Rozvrh  [hidden, 1 attachment]",
        ])
        result = run(["messages", "--unread", "--since", "2026-10-01"], token_response(),
                     fixture("komens_received.json"))
        self.assertEqual(result.calls[0].form, {"dateFrom": "2026-10-01"})
        self.assertEqual(len(result.lines), 1)

    def test_sent_and_noticeboard_messages(self):
        result = run(["messages", "--sent"], token_response(), fixture("komens_sent.json"))
        self.assertEqual(result.lines, [
            "400120  2026-10-14 07:41  to Mgr. Petra Ukázková: Dotaz k domácímu úkolu  [1 attachment]",
            "400108  2026-10-10 18:20  to 2 recipient(s): omluvenka: Adam Příkladný, 6.B",
        ])
        result = run(["messages", "--noticeboard", "--json"], token_response(), fixture("komens_received.json"))
        self.assertEqual(result.calls[0].api_path, "/api/3/komens/messages/noticeboard")
        self.assertEqual(result.data[0]["title"], "Třídní schůzky")
        result = run(["messages", "--noticeboard"], token_response(), json_response(200, {"Messages": []}))
        self.assertEqual(result.out, "No messages.\n")

    def test_message_counters(self):
        result = run(["messages", "--count"], token_response(), json_response(200, 3))
        self.assertEqual((result.out, result.calls[0].api_path), ("3\n", "/api/3/komens/messages/received/unread"))
        result = run(["messages", "--count", "--noticeboard", "--json"], token_response(), json_response(200, 0))
        self.assertEqual((result.data, result.calls[0].api_path), (0, "/api/3/komens/messages/noticeboard/unread"))
        result = run(["messages", "--count", "--sent"], token_response(), fixture("komens_sent.json"))
        self.assertEqual(result.out, "2\n")
        result = run(["messages", "--count", "--unread"])
        self.assertEqual((result.code, result.transport.calls), (2, []))

    def test_received_message(self):
        result = run(["message", "400095"], token_response(), fixture("komens_received_detail.json"))
        self.assertEqual(result.calls[0].api_path, "/api/3/komens/messages/received/400095")
        self.assertEqual(result.lines, [
            "Title: Sběr papíru",
            "From: Jan Vzorový (ředitelství) (administrator)",
            "Date: 2026-10-01 11:45",
            "Type: OBECNA, ToRead",
            "",
            "Ve středu proběhne sběr papíru.",
            "Děkujeme.",
        ])
        data = run(["message", "400095", "--json"], token_response(), fixture("komens_received_detail.json")).data
        self.assertEqual(data["text"], "<p>Ve středu proběhne sběr papíru.<br>Děkujeme.</p>")

    def test_sent_message_with_its_recipients(self):
        result = run(["message", "400120", "--sent"], token_response(), fixture("komens_sent_detail.json"))
        self.assertEqual(result.calls[0].api_path, "/api/3/komens/messages/sent/400120")
        self.assertEqual(result.lines[:6], [
            "Title: Dotaz k domácímu úkolu",
            "From: Eva Příkladná (parents)",
            "To:",
            "    Mgr. Petra Ukázková (teacher), processed 2026-10-14 07:41",
            "    Ing. Tomáš Vzorník, Ph.D. (teacher)",
            "Date: 2026-10-14 07:41",
        ])

    def test_sent_message_of_the_list_names_its_recipient(self):
        message = copy.deepcopy(load_fixture("komens_sent.json")["Messages"][0])
        message.update({"Type": None, "LifeTime": None})
        result = run(["message", "400120", "--sent"], token_response(), json_response(200, {"Message": message}))
        self.assertEqual(result.lines[:4], ["Title: Dotaz k domácímu úkolu", "From: Eva Příkladná (parents)",
                                            "To: Mgr. Petra Ukázková", "Date: 2026-10-14 07:41"])
        self.assertEqual(result.lines[4], "")  # no type line

    def test_message_flags_period_and_attachments(self):
        message = copy.deepcopy(load_fixture("komens_sent.json")["Messages"][1])
        message.update({"Read": False, "CanConfirm": True, "Hidden": True, "Text": ""})
        message["Attachments"] = [{"Id": "A 1", "Name": "zpráva.pdf", "Type": "application/pdf", "Size": 10}]
        message["$type"] = "SentMessageWithRecipients"
        result = run(["message", "400108", "--sent"], token_response(), json_response(200, {"Message": message}))
        self.assertEqual(result.lines[2:], [
            "Date: 2026-10-10 18:20",
            "Type: OMLUVENKA, ToConfirm",
            "Period: 2026-10-07 00:00 - 2026-10-09 23:59",
            "Flags: unread, to confirm, hidden",
            "",
            "(no text)",
            "",
            "Attachments:",
            "    zpráva.pdf (id 'A 1', 10 bytes, application/pdf)",
        ])

    def test_noticeboard_message_as_html_marked_as_read(self):
        notices = copy.deepcopy(load_fixture("komens_received.json"))
        result = run(["message", "400099", "--noticeboard", "--html", "--mark-read"], token_response(),
                     json_response(200, notices), empty_response(204))
        listing, marking = result.calls
        self.assertEqual(listing.api_path, "/api/3/komens/messages/noticeboard")
        self.assertEqual((marking.method, marking.api_path), ("PUT", "/api/3/komens/message/400099/mark-as-read"))
        self.assertIn("<p>Prosíme o potvrzení účasti na exkurzi do planetária.</p>", result.lines)
        self.assertEqual(result.err, "bakalari: marked message 400099 as read\n")

    def test_mark_read_only_when_unread(self):
        result = run(["message", "400095", "--mark-read", "--json"], token_response(),
                     fixture("komens_received_detail.json"))
        self.assertEqual(len(result.calls), 1)
        self.assertEqual(result.data["id"], "400095")
        self.assertEqual(result.err, "bakalari: message 400095 was already read\n")

    def test_message_usage_errors(self):
        result = run(["message", "400120", "--sent", "--mark-read"])
        self.assertEqual((result.code, result.transport.calls), (2, []))
        self.assertIn("--mark-read applies to received messages, not to --sent", result.err)
        result = run(["message", "1", "--noticeboard"], token_response(), fixture("komens_received.json"))
        self.assertEqual(result.code, 2)
        self.assertIn("no noticeboard message '1'", result.err)

    def test_message_types(self):
        result = run(["message-types"], token_response(), fixture("komens_message_types.json"))
        self.assertEqual(result.calls[0].api_path, "/api/3/komens/message-types")
        self.assertEqual(result.lines[:9], [
            "OBECNA  Obecná zpráva  [title, confirmation, e-mail notification]",
            "    U  učitel  ONE  [copy for parent]",
            "        UQX7K  Ukázková Petra, Mgr.",
            "        T8M4W  Vzorník Tomáš, Ing., Ph.D.",
            "        ' 9KX'  Zkušební Alena",
            "    UV  učitelé - všichni  ZERO",
            "    VS  vedení školy  MULTI  [copy for class teacher]",
            "        RS  ředitel školy (default)",
            "        ZR  zástupce ředitele",
        ])
        self.assertEqual(result.lines[9], "OMLUVENKA  Omluvení absence")
        result = run(["message-types", "--reply-to", "400101", "--json"], token_response(),
                     fixture("komens_message_types_reply.json"))
        self.assertEqual(result.calls[0].api_path, "/api/3/komens/message-types/reply/400101")
        self.assertEqual(result.data["types"][0]["recipient_types"][0]["code"], "OD")
        result = run(["message-types"], token_response(), json_response(200, {"MessageTypes": []}))
        self.assertEqual(result.out, "No message types.\n")

    def test_send_message(self):
        result = run(["send-message", "--type", "obecna", "--recipient-type", "U", "--to", "9kx", "--title", "Dotaz",
                      "--text", "Dobrý den,\n<prosím> o radu & pomoc.\n", "--require-confirmation",
                      "--copy-for-parent"], token_response(), fixture("komens_message_types.json"),
                     json_response(200, {"Message": ""}))
        self.assertEqual(result.code, 0)
        send = result.calls[1]
        self.assertEqual((send.method, send.api_path), ("POST", "/api/3/komens/message"))
        body = send.json
        self.assertEqual({key: body[key] for key in ("MessageType", "RecipientType", "Recipients", "Title", "Text",
                                                     "RequireConfirmation", "CopyForParent", "EmailNotification",
                                                     "Attachments")},
                         {"MessageType": "OBECNA", "RecipientType": "U", "Recipients": [" 9KX"], "Title": "Dotaz",
                          "Text": "Dobrý den,<br>&lt;prosím&gt; o radu &amp; pomoc.", "RequireConfirmation": True,
                          "CopyForParent": True, "EmailNotification": False, "Attachments": []})
        self.assertEqual(result.out, "Sent the OBECNA message \"Dotaz\" to Zkušební Alena (' 9KX').\n")

    def test_send_message_to_implied_recipients_with_html_from_a_file_and_attachments(self):
        text = self.directory / "zprava.html"
        text.write_text("<p>Dobrý den</p>", encoding="utf-8")
        attachment = self.directory / "omluvenka.pdf"
        attachment.write_bytes(b"%PDF-1.7")
        result = run(["send-message", "--type", "OBECNA", "--recipient-type", "uv", "--title", "Oznámení",
                      "--text-file", str(text), "--html", "--attach", str(attachment)], token_response(),
                     fixture("komens_message_types.json"), json_response(200, "att-1"),
                     json_response(200, {"Message": ""}))
        self.assertEqual(result.code, 0)
        _, upload, send = result.calls
        self.assertEqual((upload.method, upload.api_path), ("POST", "/api/3/komens/attachment"))
        self.assertIn(b'filename="omluvenka.pdf"', upload.body)
        self.assertEqual((send.json["Recipients"], send.json["Text"], send.json["Attachments"]),
                         ([], "<p>Dobrý den</p>", ["att-1"]))
        self.assertEqual(result.out, 'Sent the OBECNA message "Oznámení" to učitelé - všichni with 1 attachment(s).\n')

    def test_send_message_to_several_recipients_with_copies_and_notifications(self):
        result = run(["send-message", "--type", "OBECNA", "--recipient-type", "VS", "--to", "RS", "--to",
                      "zástupce ředitele", "--title", "Žádost", "--text", "Text", "--email-notification",
                      "--copy-for-class-teacher"], token_response(), fixture("komens_message_types.json"),
                     json_response(200, {"Message": ""}))
        self.assertEqual(result.code, 0)
        body = result.calls[1].json
        self.assertEqual({key: body[key] for key in ("RecipientType", "Recipients", "EmailNotification",
                                                     "CopyForClassTeacher", "CopyForParent", "RequireConfirmation")},
                         {"RecipientType": "VS", "Recipients": ["RS", "ZR"], "EmailNotification": True,
                          "CopyForClassTeacher": True, "CopyForParent": False, "RequireConfirmation": False})
        self.assertEqual(result.out,
                         'Sent the OBECNA message "Žádost" to ředitel školy (RS), zástupce ředitele (ZR).\n')

    def test_send_message_text_from_standard_input(self):
        with mock.patch("sys.stdin", io.StringIO("Omlouvám syna.\r\nDěkuji")):
            result = run(["send-message", "--type", "OMLUVENKA", "--recipient-type", "U", "--to", "UQX7K",
                          "--text-file", "-"], token_response(), fixture("komens_message_types.json"),
                         json_response(200, {"Message": ""}))
        self.assertEqual(result.calls[1].json["Text"], "Omlouvám syna.<br>Děkuji")
        self.assertEqual(result.out, "Sent the OMLUVENKA message to Ukázková Petra, Mgr. (UQX7K).\n")

    def test_send_message_is_validated_before_anything_is_sent(self):
        base = ["send-message", "--type", "OBECNA", "--recipient-type", "U", "--to", "UQX7K", "--title", "T"]
        cases = {
            "the account cannot send the message type 'X' (it can send: OBECNA, OMLUVENKA)":
                ["send-message", "--type", "X", "--recipient-type", "U", "--text", "t"],
            "OBECNA has no recipient type 'Q' (it has: U, UV, VS)":
                ["send-message", "--type", "OBECNA", "--recipient-type", "Q", "--text", "t"],
            "the recipient type UV implies its recipients: leave out --to":
                ["send-message", "--type", "OBECNA", "--recipient-type", "UV", "--to", "X", "--text", "t"],
            "the recipient type U needs --to CODE":
                ["send-message", "--type", "OBECNA", "--recipient-type", "U", "--text", "t"],
            "the recipient type U takes one recipient": base + ["--to", "T8M4W", "--text", "t"],
            "U has no recipient 'nikdo'":
                ["send-message", "--type", "OBECNA", "--recipient-type", "U", "--to", "nikdo", "--text", "t"],
            "OBECNA to U does not offer --copy-for-class-teacher": base + ["--copy-for-class-teacher", "--text", "t"],
            "OMLUVENKA to U does not offer --require-confirmation, --email-notification":
                ["send-message", "--type", "OMLUVENKA", "--recipient-type", "U", "--to", "UQX7K",
                 "--require-confirmation", "--email-notification", "--text", "t"],
            "the message type OBECNA needs --title":
                ["send-message", "--type", "OBECNA", "--recipient-type", "VS", "--to", "RS", "--text", "t"],
            "the message type OMLUVENKA has no title: leave out --title":
                ["send-message", "--type", "OMLUVENKA", "--recipient-type", "U", "--to", "UQX7K", "--title", "T",
                 "--text", "t"],
            "the message text is empty": base + ["--text", " \n"],
            "cannot read": base + ["--text-file", str(self.directory / "missing.txt")],
            "no such file": base + ["--text", "t", "--attach", str(self.directory / "missing.pdf")],
        }
        for message, argv in cases.items():
            with self.subTest(message):
                result = run(argv, token_response(), fixture("komens_message_types.json"))
                self.assertEqual((result.code, result.out), (2, ""))
                self.assertIn(message, result.err)
                self.assertEqual([call.api_path for call in result.calls], ["/api/3/komens/message-types"])

    def test_reply(self):
        result = run(["reply", "400095", "--text", "Děkuji, přijdeme."], token_response(),
                     fixture("komens_received_detail.json"), fixture("komens_message_types_reply.json"),
                     json_response(200, {"Message": ""}))
        self.assertEqual(result.code, 0)
        detail, types, send = result.calls
        self.assertEqual((detail.api_path, types.api_path, send.api_path),
                         ("/api/3/komens/messages/received/400095", "/api/3/komens/message-types/reply/400095",
                          "/api/3/komens/message"))
        self.assertEqual({key: send.json[key] for key in ("MessageType", "RecipientType", "Recipients", "Title",
                                                          "PreviousMessageId", "Text")},
                         {"MessageType": "OBECNA", "RecipientType": "OD", "Recipients": [], "Title": "Re: Sběr papíru",
                          "PreviousMessageId": "400095", "Text": "Děkuji, přijdeme."})
        self.assertEqual(result.out, 'Replied to message 400095 "Sběr papíru" from Jan Vzorový (ředitelství).\n')

    def test_reply_with_a_title_an_attachment_and_a_confirmation(self):
        attachment = self.directory / "potvrzeni.txt"
        attachment.write_text("ano", encoding="utf-8")
        result = run(["reply", "400095", "--title", "Odpověď", "--text", "Ano", "--attach", str(attachment),
                      "--require-confirmation"], token_response(), fixture("komens_received_detail.json"),
                     json_response(200, "att-9"), fixture("komens_message_types_reply.json"),
                     json_response(200, {"Message": ""}))
        self.assertEqual(result.code, 0)
        self.assertEqual([call.api_path for call in result.calls], [
            "/api/3/komens/messages/received/400095", "/api/3/komens/attachment",
            "/api/3/komens/message-types/reply/400095", "/api/3/komens/message",
        ])
        body = result.calls[3].json
        self.assertEqual((body["Title"], body["Attachments"], body["RequireConfirmation"]),
                         ("Odpověď", ["att-9"], True))

    def test_reply_text_is_checked_before_any_request(self):
        result = run(["reply", "400095", "--text", " "])
        self.assertEqual((result.code, result.transport.calls), (2, []))
        self.assertIn("the message text is empty", result.err)

    def test_message_actions(self):
        cases = [
            (["confirm-message", "400099"], "PUT", "/api/3/komens/message/400099/mark-as-confirmed",
             "Confirmed message 400099."),
            (["hide-message", "400099"], "PUT", "/api/3/komens/message/400099/mark-as-hidden", "Hid message 400099."),
            (["hide-message", "400099", "--undo"], "PUT", "/api/3/komens/message/400099/mark-as-unhidden",
             "Message 400099 is shown again."),
            (["delete-message", "40 01"], "DELETE", "/api/3/komens/message/40%2001", "Deleted message '40 01'."),
        ]
        for argv, method, path, output in cases:
            with self.subTest(argv):
                result = run(argv, token_response(), empty_response(204))
                self.assertEqual((result.code, result.out), (0, output + "\n"))
                self.assertEqual((result.calls[0].method, result.calls[0].api_path), (method, path))

    def test_message_actions_the_message_does_not_allow(self):
        for argv, hint in ((["confirm-message", "1"], "the message does not ask for a confirmation"),
                           (["hide-message", "1"], "the message cannot be hidden"),
                           (["delete-message", "1"], "the message cannot be deleted")):
            result = run(argv, token_response(), FORBIDDEN)
            self.assertEqual(result.code, 1)
            self.assertIn(f"bakalari: hint: {hint}", result.err)

    def test_attachment_into_a_directory(self):
        headers = {"Content-Type": "application/pdf", "Content-Disposition": "attachment; filename=\"Pozvánka.pdf\""}
        result = run(["attachment", "ATT 1", "-o", str(self.directory)], token_response(),
                     binary_response(b"%PDF-1.7", headers))
        self.assertEqual(result.calls[0].api_path, "/api/3/komens/attachment/ATT%201")
        target = self.directory / "Pozvánka.pdf"
        self.assertEqual(target.read_bytes(), b"%PDF-1.7")
        self.assertEqual(result.out, f"Saved {os.path.abspath(target)} (8 bytes, application/pdf).\n")

    def test_attachment_into_the_current_directory(self):
        previous = os.getcwd()
        os.chdir(self.directory)
        self.addCleanup(os.chdir, previous)
        result = run(["attachment", "a1"], token_response(), binary_response(b"data"))
        self.assertEqual(result.code, 0)
        self.assertEqual((self.directory / "attachment-a1").read_bytes(), b"data")
        self.assertIn("(4 bytes, application/octet-stream)", result.out)

    def test_attachment_never_overwrites_without_force(self):
        target = self.directory / "ukol.pdf"
        target.write_bytes(b"mine")
        result = run(["attachment", "a1", "-o", str(target)], token_response(), binary_response(b"new"))
        self.assertEqual((result.code, result.out), (2, ""))
        self.assertIn(f"{target} already exists: pass --force to overwrite it", result.err)
        self.assertEqual(target.read_bytes(), b"mine")
        result = run(["attachment", "a1", "-o", str(target), "--force"], token_response(), binary_response(b"new"))
        self.assertEqual(result.code, 0)
        self.assertEqual(target.read_bytes(), b"new")

    def test_attachment_into_a_missing_directory(self):
        result = run(["attachment", "a1", "-o", str(self.directory / "missing" / "x.pdf")], token_response(),
                     binary_response(b"new"))
        self.assertEqual(result.code, 2)
        self.assertIn("cannot save the attachment to", result.err)


class GdprAndPaymentsCommandsTest(CliTestCase):
    def test_consents(self):
        result = run(["consents"], token_response(), fixture("gdpr_consents.json"))
        self.assertEqual(result.calls[0].api_path, "/api/3/gdpr/consents/person")
        self.assertEqual(result.lines, [
            "Agreed  Souhlas zákonného zástupce se zasíláním informací o činnosti a akcích školy na jeho e-mailovou "
            "adresu a telefon (from 2025-09-02, validity 5 let) [can disagree, can request revocation]",
        ])
        result = run(["consents", "--child"], token_response(), fixture("gdpr_child_consents.json"))
        self.assertEqual(result.calls[0].api_path, "/api/3/gdpr/consents/person/child")
        self.assertEqual(result.lines[1], "Agreed  Zveřejnění jména žáka ve výsledcích soutěží (from 2025-09-01, "
                                          "validity 5 year(s)) [can disagree, can request revocation]")
        self.assertEqual(result.lines[2], "Agreed  Účast na preventivním programu (from 2026-09-01, validity 1 rok)")
        data = run(["consents", "--json"], token_response(), fixture("gdpr_consents.json")).data
        self.assertEqual((data[0]["id"], data[0]["state"]), ("4711", "Agreed"))
        result = run(["consents"], token_response(),
                     json_response(200, {"PersonConsents": [{"Id": 1, "ValidTo": "2027-01-01"}]}))
        self.assertEqual(result.out, "-  (no title) (until 2027-01-01)\n")
        result = run(["consents"], token_response(), json_response(200, {"PersonConsents": []}))
        self.assertEqual(result.out, "No consents.\n")

    def test_new_consents_counter(self):
        result = run(["consents", "--count"], token_response(), json_response(200, 1))
        self.assertEqual((result.out, result.calls[0].api_path), ("1\n", "/api/3/gdpr/consents/person/new"))
        result = run(["consents", "--count", "--child"])
        self.assertEqual((result.code, result.transport.calls), (2, []))

    def test_commissioners(self):
        result = run(["commissioners"], token_response(), fixture("gdpr_commissioners.json"))
        self.assertEqual(result.out, "Mgr. Ludmila Pokorná | poverenec@skola.example | mobile +420 799 000 111 | "
                                     "https://poverenec.example | data box x7k2mpq\n")
        data = run(["commissioners", "--json"], token_response(), fixture("gdpr_commissioners.json")).data
        self.assertEqual(data[0]["data_box"], "x7k2mpq")
        result = run(["commissioners"], token_response(), json_response(200, {"Commissioners": []}))
        self.assertEqual(result.out, "No data protection officer is listed.\n")
        result = run(["commissioners"], token_response(),
                     json_response(200, {"Commissioners": [{"Id": "1", "Name": "", "Phone": "+420 1"}]}))
        self.assertEqual(result.out, "- | phone +420 1\n")

    def test_class_fund(self):
        result = run(["class-fund"], token_response(), fixture("payments_summary.json"))
        self.assertEqual(result.out, "Kolářová Eliška (2.B): balance 1250.50 CZK, spent -3870.25 CZK\n")
        result = run(["class-fund", "--payments", "--info", "--regular"], token_response(),
                     fixture("payments_classfund.json"), fixture("payments_summary.json"),
                     fixture("payments_info.json"), json_response(200, {"Total": 1500}))
        self.assertEqual([call.api_path for call in result.calls], [
            "/api/3/payments/classfund", "/api/3/payments/classfund/summary", "/api/3/payments/classfund/paymentsinfo",
            "/api/3/payments/regularpayments/summary",
        ])
        self.assertEqual(result.calls[0].query, {"sort": "desc"})
        self.assertEqual(result.lines, [
            "Kolářová Eliška (2.B): balance 1250.50 CZK, spent -3870.25 CZK",
            "Payments:",
            "    2026-10  160.00 CZK",
            "        2026-10-08      -90.00  Divadlo 2.B",
            "        2026-10-02      250.00  Příjem z banky (Kolářová Eliška)",
            "    2026-09  -49.50 CZK",
            "        2026-09-21     -399.50  Pracovní sešit Fyzika 2",
            "        2026-09-03      350.00  Příjem z banky (Kolářová Eliška)",
            "    2026-08  0.00 CZK",
            "Payment details:",
            "    Instructions: Pro platbu do třídního fondu použijte níže uvedený bankovní účet, specifický a "
            "variabilní symbol.",
            "    Account: 35-1234567899/0100",
            "    IBAN: CZ59 0100 0000 3512 3456 7899",
            "    Variable symbol: 2026001234",
            "    Specific symbol: 2222",
            "    Message: 2.B Kolářová Eliška třídní fond",
            "    QR payment: SPD*1.0*ACC:CZ5901000000351234567899*CC:CZK*X-VS:2026001234*X-SS:2222*MSG:2.B Kolarova "
            "Eliska tridni fond",
            "Regular payments:",
            "{",
            '  "Total": 1500',
            "}",
        ])

    def test_class_fund_search_order_and_json(self):
        info = {"BankAccount": "nesmysl", "Amount": 300, "VariableSymbol": None}
        result = run(["class-fund", "--search", "Divadlo", "--asc", "--info", "--json"], token_response(),
                     fixture("payments_classfund.json"), fixture("payments_summary.json"), json_response(200, info))
        self.assertEqual(result.calls[0].query, {"sort": "asc", "search": "Divadlo"})
        data = result.data
        self.assertEqual(set(data), {"summary", "payments", "info"})
        self.assertEqual(data["summary"]["balance"], 1250.5)
        self.assertEqual(data["payments"][0]["items"][0]["amount"], -90.0)
        self.assertEqual((data["info"]["iban"], data["info"]["qr_payment"], data["info"]["amount"]),
                         (None, None, 300.0))
        result = run(["class-fund", "--info"], token_response(), fixture("payments_summary.json"),
                     json_response(200, info))
        self.assertEqual(result.lines[2:], ["    Account: nesmysl", "    IBAN: -", "    Amount: 300.00 CZK",
                                            "    QR payment: not available (no IBAN or invalid symbols)"])
        result = run(["class-fund", "--payments"], token_response(), json_response(200, {"MonthlyData": []}),
                     fixture("payments_summary.json"))
        self.assertEqual(result.lines[1:], ["Payments:", "    No payments."])

    def test_class_fund_errors(self):
        result = run(["class-fund", "--search", " "])
        self.assertEqual((result.code, result.transport.calls), (2, []))
        self.assertIn("The class fund search text must not be empty", result.err)
        result = run(["class-fund"], token_response(), FORBIDDEN)
        self.assertEqual(result.code, 1)
        self.assertIn("bakalari: hint: the Payments module is not enabled for the school", result.err)


class TeacherCommandsTest(CliTestCase):
    def test_classbook(self):
        result = run(["classbook", "--since", "2026-09-21"], token_response(), fixture("teacher_classbook.json"))
        self.assertEqual(result.calls[0].query, {"from": "2026-09-21T00:00:00.000", "to": "2026-09-27T23:59:59.999"})
        self.assertEqual(result.lines, [
            "2026-09-21 po WorkDay: 3 record(s)",
            "    1.  8:00 - 8:45  M   2.B               14. Pythagorova věta",
            "                     Fy  1.A sk1, 1.B sk1  1. Ukázkové téma",
            "                                           (no theme) [Suplování za: Fiktivní Oto]",
            "2026-09-28 po Celebration (Den české státnosti): 0 record(s)",
        ])

    def test_classbook_periods_and_json(self):
        monday, sunday = week_of(dt.date.today())
        result = run(["classbook", "--json"], token_response(), fixture("teacher_classbook.json"))
        self.assertEqual(result.calls[0].query, {"from": f"{monday.isoformat()}T00:00:00.000",
                                                 "to": f"{sunday.isoformat()}T23:59:59.999"})
        self.assertEqual(len(result.data["days"]), 2)
        result = run(["classbook", "--until", "2026-09-27"], token_response(), json_response(200, {"Days": []}))
        self.assertEqual(result.calls[0].query, {"from": "2026-09-21T00:00:00.000", "to": "2026-09-27T23:59:59.999"})
        self.assertEqual(result.out, "No class-book days.\n")
        result = run(["classbook", "--since", "2026-09-28", "--until", "2026-09-27"])
        self.assertEqual((result.code, result.transport.calls), (2, []))

    def test_teacher_accounts_only(self):
        for argv in (["classbook"], ["lesson-tags"], ["marking"], ["marking", "A1"]):
            with self.subTest(argv):
                result = run(argv, token_response(), NOT_TEACHER)
                self.assertEqual(result.code, 1)
                self.assertIn("answered HTTP 403 Forbidden: Some privilege is missing (IsTeacher).", result.err)
                self.assertIn("bakalari: hint: this is available to teacher accounts only", result.err)

    def test_lesson_tags(self):
        result = run(["lesson-tags"], token_response(), payload("teacher_lesson.json", "lessonTags"))
        self.assertEqual(result.calls[0].api_path, "/api/3/classbook/lessonTags")
        self.assertEqual(result.lines, ["T1     EC1  Projekt", "'T 2'  EXK  Exkurze", "T3     -    -"])
        data = run(["lesson-tags", "--json"], token_response(), payload("teacher_lesson.json", "lessonTags")).data
        self.assertEqual(data[1], {"id": "T 2", "abbreviation": "EXK", "title": "Exkurze"})
        self.assertEqual(run(["lesson-tags"], token_response(), json_response(200, [])).out, "No lesson tags.\n")

    def test_marking(self):
        result = run(["marking"], token_response(), payload("teacher_marking.json", "atoms"))
        self.assertEqual(result.calls[0].api_path, "/api/3/marking/atoms")
        self.assertEqual(result.lines, ["A1B2C3  2.B Matematika [M]",
                                        "A1B2C4  1.A Fyzika sk1 [Fy] (disabled: Klasifikace je uzavřena)",
                                        "'A[9]'  Seminář"])
        result = run(["marking", "A[9]"], token_response(), payload("teacher_marking.json", "marks"))
        self.assertEqual(result.calls[0].api_path, "/api/3/marking/marks/A%5B9%5D")
        self.assertEqual(result.lines, ["Pokusný Adam: 1, N (average 1,00)",
                                        "Zkušební Bára Marie: 2- (average 2,50) [released]"])
        data = run(["marking", "A1", "--json"], token_response(), payload("teacher_marking.json", "marks")).data
        self.assertEqual(len(data["marks"]), 3)
        self.assertEqual(run(["marking", "--json"], token_response(), json_response(200, {"Atoms": []})).data, [])
        self.assertEqual(run(["marking"], token_response(), json_response(200, {"Atoms": []})).out,
                         "No marking units.\n")
        self.assertEqual(run(["marking", "A1"], token_response(), json_response(200, {"Marks": []})).out,
                         "No students.\n")


class ApiCommandTest(CliTestCase):
    def test_verbose_raw_request_hides_query_and_fragment_in_errors(self):
        path = "/api/3/register-notification?token=query-secret#fragment-secret"
        result = run(["-v", "api", "POST", path], token_response(), json_response(400, {"Message": "bad request"}))
        self.assertEqual(result.code, 1)
        self.assertIn("/api/3/register-notification", result.err)
        self.assertNotIn("query-secret", result.err + result.out)
        self.assertNotIn("fragment-secret", result.err + result.out)
        self.assertEqual(result.calls[0].url, BASE_URL + path)

    def test_get_with_parameters(self):
        result = run(["api", "get", "/api/3/marks", "-p", "from=2026-10-01", "-p", "a=1", "-p", "a=2=3"],
                     token_response(), json_response(200, {"Subjects": [], "Name": "Žák"}))
        call = result.calls[0]
        self.assertEqual((call.method, call.api_path), ("GET", "/api/3/marks"))
        self.assertEqual(call.url.split("?", 1)[1], "from=2026-10-01&a=1&a=2%3D3")
        self.assertEqual(call.headers["Authorization"], "Bearer access-1")
        self.assertEqual(result.out, '{\n  "Subjects": [],\n  "Name": "Žák"\n}\n')

    def test_post_form_and_json_bodies(self):
        result = run(["api", "POST", "api/3/komens/messages/received", "--form", "dateFrom=2026-10-01"],
                     token_response(), fixture("komens_received.json"))
        call = result.calls[0]
        self.assertEqual((call.api_path, call.form), ("/api/3/komens/messages/received", {"dateFrom": "2026-10-01"}))
        self.assertEqual(call.headers["Content-Type"], "application/x-www-form-urlencoded")
        self.assertEqual(len(result.data["Messages"]), 3)
        result = run(["api", "POST", "/api/3/register-notification", "-p", "token=abc", "--body", "null"],
                     token_response(), empty_response(204))
        call = result.calls[0]
        self.assertEqual((call.body, call.query, call.headers["Content-Type"]),
                         (b"null", {"token": "abc"}, "application/json; charset=utf-8"))
        self.assertEqual(result.out, "HTTP 204 (no content)\n")

    def test_public_endpoint_without_login(self):
        page_bytes = "<p>Žák</p>".encode("cp1250")
        response = HttpResponse(200, {"Content-Type": "text/html; charset=windows-1250"}, page_bytes)
        result = run(["api", "GET", "/Timetable/Public", "--no-auth"], response)
        self.assertEqual(len(result.transport.calls), 1)
        self.assertNotIn("Authorization", result.transport.calls[0].headers)
        self.assertEqual(result.out, "<p>Žák</p>\n")

    def test_binary_answer_is_not_printed(self):
        result = run(["api", "GET", "/api/3/komens/attachment/1"], token_response(),
                     binary_response(b"%PDF", {"Content-Type": "application/pdf"}))
        self.assertEqual(result.out, "HTTP 200: application/pdf, 4 bytes (not shown)\n")
        result = run(["api", "GET", "/x"], token_response(), text_response(200, "plain", "text/plain; charset=nope"))
        self.assertEqual(result.out, "plain\n")

    def test_error_status(self):
        result = run(["api", "GET", "/api/3/nothing"], token_response(),
                     json_response(404, {"Message": "No HTTP resource was found."}))
        self.assertEqual((result.code, result.out), (1, ""))
        self.assertEqual(result.err, "bakalari: error: GET /api/3/nothing answered HTTP 404 Not Found: No HTTP "
                                     "resource was found.\n")

    def test_usage_errors(self):
        for argv, message in ((["api", "GET", "https://evil.example/api"], "PATH is relative to the school's address"),
                              (["api", "POST", "/x", "--body", "{x"], "--body is not valid JSON"),
                              (["api", "GET", "/x", "-p", "novalue"], "--param needs KEY=VALUE, got 'novalue'"),
                              (["api", "POST", "/x", "--form", "=1"], "--form needs KEY=VALUE, got '=1'")):
            with self.subTest(argv):
                result = run(argv, token_response())
                self.assertEqual((result.code, result.out), (2, ""))
                self.assertIn(message, result.err)
                self.assertEqual(result.calls, [])


class ErrorHandlingTest(CliTestCase):
    def test_rejected_login_exits_1_without_secrets(self):
        result = run(["modules"], INVALID_GRANT)
        self.assertEqual((result.code, result.out), (1, ""))
        self.assertEqual(result.err.splitlines(), [
            "bakalari: error: the login was refused (invalid_grant: Špatný login nebo heslo)",
            "bakalari: hint: check the login in BAKALARI_USERNAME and BAKALARI_PASSWORD",
        ])
        self.assertNoSecrets(result)

    def test_connection_error(self):
        error = BakalariConnectionError("POST https://school.example/bakaweb/api/login failed: timed out")
        result = run(["marks"], error)
        self.assertEqual(result.code, 1)
        self.assertEqual(result.err.splitlines(), [
            "bakalari: error: POST https://school.example/bakaweb/api/login failed: timed out",
            "bakalari: hint: check the school's address (BAKALARI_URL or --base-url) and the network connection",
        ])
        result = run(["schools"], BakalariConnectionError("GET https://directory.example failed: refused"))
        self.assertEqual(result.err.splitlines()[1], "bakalari: hint: check the network connection")

    def test_wrong_address(self):
        result = run(["marks"], text_response(404, "<html><head><title>404 - Soubor nenalezen</title></head></html>"))
        self.assertEqual(result.code, 1)
        self.assertEqual(result.err.splitlines(), [
            "bakalari: error: POST /api/login answered HTTP 404 Not Found: 404 - Soubor nenalezen",
            "bakalari: hint: check the school's address (BAKALARI_URL or --base-url)",
        ])

    def test_contract_error(self):
        result = run(["marks"], token_response(), json_response(200, {"Subjects": None}))
        self.assertEqual(result.code, 1)
        self.assertEqual(result.err, "bakalari: error: The Bakaláři marks response violates its contract:\n"
                                     "- Missing list 'Subjects'\n")

    def test_server_error_with_an_unknown_status(self):
        result = run(["marks"], token_response(), json_response(599, {"Message": "Chyba"}))
        self.assertEqual(result.err, "bakalari: error: GET /api/3/marks answered HTTP 599: Chyba\n")

    def test_interrupted(self):
        result = run(["marks"], KeyboardInterrupt())
        self.assertEqual((result.code, result.out, result.err), (130, "", "bakalari: interrupted\n"))

    def test_unexpected_operating_system_error(self):
        result = run(["marks"], OSError(5, "Input/output error"))
        self.assertEqual((result.code, result.err), (1, "bakalari: error: Input/output error\n"))

    def test_text_the_output_encoding_cannot_hold_is_escaped(self):
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding="ascii")

        def factory(args, needs_login):
            return BakalariClient(BASE_URL, transport=FakeTransport(json_response(200, VERSION)))

        with clean_environment(), contextlib.redirect_stdout(stream):
            code = main(["version"], client_factory=factory)
            stream.flush()
        self.assertEqual(code, 0)
        self.assertTrue(buffer.getvalue().startswith(b"Bakal\\xe1\\u0159i REST API 3.52.1"))

    def test_broken_pipe_points_standard_output_at_the_null_device(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        descriptor = os.open(os.path.join(directory.name, "out.txt"), os.O_WRONLY | os.O_CREAT)
        self.addCleanup(os.close, descriptor)

        class BrokenPipe(io.StringIO):
            def write(self, text):
                raise BrokenPipeError(32, "Broken pipe")

            def fileno(self):
                return descriptor

        def factory(args, needs_login):
            return BakalariClient(BASE_URL, transport=FakeTransport(json_response(200, VERSION)))

        with clean_environment(), contextlib.redirect_stdout(BrokenPipe()):
            code = main(["version"], client_factory=factory)
        self.assertEqual(code, 1)
        os.write(descriptor, b"lost")  # now the null device
        self.assertEqual(os.path.getsize(os.path.join(directory.name, "out.txt")), 0)

    def test_closed_standard_output(self):
        class ClosedPipe(io.StringIO):
            def write(self, text):
                raise BrokenPipeError(32, "Broken pipe")

        transport = FakeTransport(json_response(200, VERSION))

        def factory(args, needs_login):
            return BakalariClient(BASE_URL, transport=transport)

        err = io.StringIO()
        with clean_environment(), contextlib.redirect_stdout(ClosedPipe()), contextlib.redirect_stderr(err):
            code = main(["version"], client_factory=factory)
        self.assertEqual((code, err.getvalue()), (1, ""))


class SanitisingTest(CliTestCase):
    """Server strings never reach the terminal with control characters (terminal escape sequences)."""

    ESCAPE = "\x1b]0;owned\x07\x1b[31m"

    def message(self, **changes):
        message = copy.deepcopy(load_fixture("komens_received_detail.json"))
        message["Message"].update(changes)
        return json_response(200, message)

    def test_message_title_sender_and_text(self):
        response = self.message(Title=f"Výlet{self.ESCAPE}\x9b2J", Text=f"<p>Ahoj{self.ESCAPE}\x08</p>",
                                Sender={"Id": "U1", "Type": "teacher", "Name": f"Jana\x00\x85 Nová{self.ESCAPE}"},
                                Attachments=[{"Id": "a\x1b1", "Name": "x\x1b.pdf", "Type": "", "Size": 1}])
        result = run(["message", "1"], token_response(), response)
        self.assertEqual(result.code, 0)
        self.assertClean(result.out)
        self.assertIn("Title: Výlet]0;owned[31m2J", result.out)
        self.assertIn("From: Jana Nová]0;owned[31m (teacher)", result.out)

    def test_message_html(self):
        result = run(["message", "1", "--html"], token_response(), self.message(Text=f"<p>A{self.ESCAPE}\r\nB</p>"))
        self.assertClean(result.out)
        self.assertIn("<p>A]0;owned[31m\nB</p>", result.out)

    def test_json_output_escapes_control_characters(self):
        result = run(["message", "1", "--json"], token_response(), self.message(Title="A\x1b[31m\x9bB\x7f"))
        self.assertClean(result.out)
        self.assertIn('"title": "A\\u001b[31m\\u009bB\\u007f"', result.out)
        self.assertEqual(result.data["title"], "A\x1b[31m\x9bB\x7f")  # the data itself is unchanged

    def test_lists_and_errors(self):
        messages = {"Messages": [{"Id": "1", "Title": f"T{self.ESCAPE}", "Sender": {"Name": "\x1bS"}, "Read": True}]}
        result = run(["messages"], token_response(), json_response(200, messages))
        self.assertClean(result.out)
        result = run(["marks"], token_response(), json_response(403, {"Message": f"Zakázáno{self.ESCAPE}"}))
        self.assertClean(result.err)
        self.assertIn("Zakázáno]0;owned[31m", result.err)

    def test_attachment_file_name(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        headers = {"Content-Type": "text/plain\x1b[31m",
                   "Content-Disposition": "attachment; filename=\"a\x1b[2Jb.txt\""}
        result = run(["attachment", "1", "-o", directory.name], token_response(), binary_response(b"x", headers))
        self.assertEqual(result.code, 0)
        self.assertClean(result.out)
        self.assertEqual(os.listdir(directory.name), ["a_[2Jb.txt"])

    def test_tabs_and_line_breaks_are_kept(self):
        homeworks = {"Homeworks": [{"ID": "H1", "Content": "1.\tcvičení\n2.\tcvičení\x1b[K"}]}
        result = run(["homeworks"], token_response(), json_response(200, homeworks))
        self.assertEqual(result.lines, ["due -  id H1", "    1.\tcvičení", "    2.\tcvičení[K"])


if __name__ == "__main__":
    unittest.main()
