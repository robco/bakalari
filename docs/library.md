# Library guide

This guide describes the Python API of `bakalari`: the client and its configuration, the conventions every
model follows, every `BakalariClient` method grouped by area with its parameters and the model it returns, and the
plumbing underneath (errors, threading, timeouts, retries, transports and logging). The
[README](../README.md) gives a shorter tour, the [endpoint coverage](endpoints.md) lists the HTTP endpoint behind
each method with its verification status, and the [command line reference](cli.md) describes the `bakalari`
command built on these methods. The [MCP user guide](mcp.md) explains how to expose them to an AI application,
including host configuration, account setup and read/write examples.

Signatures are written as in Python, without the type annotations; the code carries the full type hints (the
package ships `py.typed`). The models live in the module of their area (`bakalari.marks.Mark`,
`bakalari.komens.Message`, ...), and the examples import them from there. The package itself exports the client,
the errors, every model class and the main helpers too (`from bakalari import Mark, Message`); the other helpers,
such as `bakalari.payments.account_to_iban()` and the `parse_...()` functions of most modules, are imported from
their modules.

## Contents

- [The client](#the-client): creating it, authentication, sessions
- [Conventions of the models](#conventions-of-the-models)
- [Errors](#errors)
- Areas: [account](#account), [timetable](#timetable), [substitutions](#substitutions), [marks](#marks),
  [absence](#absence), [subjects](#subjects), [homeworks](#homeworks), [Komens messages](#komens-messages),
  [events](#events), [GDPR](#gdpr), [payments](#payments), [teachers](#teachers),
  [public timetable](#public-timetable), [school directory](#school-directory)
- [Raw requests](#raw-requests)
- [MCP server integration](#mcp-server-integration)
- [Threading](#threading), [timeouts and retries](#timeouts-and-retries), [transports](#transports),
  [logging](#logging), [testing your code](#testing-your-code)

## The client

### Creating a client

`BakalariClient` combines the endpoint methods of every area on one client core. It needs the address of the
school's Bakaláři installation and either the login of the Bakaláři web or a saved session.

```text
BakalariClient(base_url, username=None, password=None, *, refresh_token=None, client_id="ANDR", timeout=30.0,
               renew_margin=60.0, retries=0, retry_backoff=0.5, ssl_context=None, transport=None, clock=time.time,
               sleep=time.sleep, on_session_update=None, user_agent=USER_AGENT)
```

| Parameter | Default | Meaning |
|---|---|---|
| `base_url` | required | The installation root that serves the web and the API, e.g. `https://skola.bakalari.cz` or `https://www.skola.cz/bakaweb`. A URL copied from the browser works: `https://` is added when the scheme is missing, and a query, a trailing slash and a page path such as `/login` or `/next/dash.aspx` are dropped (see `normalize_base_url()`). An empty address raises `BakalariConfigError`. |
| `username`, `password` | `None` | The login of the Bakaláři web. They are needed only to log in, so a client that resumes a session can do without them. |
| `refresh_token` | `None` | Starts from a refresh token instead of a login (see [sessions](#sessions)). |
| `client_id` | `"ANDR"` | The OAuth client id, that of the official mobile app. |
| `timeout` | `30.0` | Seconds a request may wait for the server (see [timeouts and retries](#timeouts-and-retries)). |
| `renew_margin` | `60.0` | How many seconds before its expiry the access token is renewed. |
| `retries` | `0` | How many times a `GET`, `PUT` or `DELETE` request is repeated after a connection error or HTTP 502, 503 or 504. |
| `retry_backoff` | `0.5` | Seconds before the first retry; each further retry waits twice as long. |
| `ssl_context` | `None` | An `ssl.SSLContext` for the default transport, e.g. with a company CA. |
| `transport` | `None` | A function that sends the requests instead of `urllib` (see [transports](#transports)). |
| `clock`, `sleep` | `time.time`, `time.sleep` | The time source and the wait between retries; meant for tests. |
| `on_session_update` | `None` | Called with a new `SessionState` after every login and renewal (see [sessions](#sessions)). |
| `user_agent` | `bakalari-python/<version>` | The `User-Agent` header. |

The configuration stays available as the attributes `base_url` (normalized), `client_id`, `timeout`,
`renew_margin`, `retries`, `retry_backoff`, `user_agent` and `on_session_update`; changing one affects the
following requests. `repr(client)` shows only the address and whether the client holds a token.

`from_env()` creates the client from environment variables:

```text
BakalariClient.from_env(*, username_env="BAKALARI_USERNAME", password_env="BAKALARI_PASSWORD", base_url=None,
                        environ=None, **kwargs)
```

It reads the address from `base_url` or `BAKALARI_URL` and the login from the two variables (another child's
login, for instance, from other variable names), and raises `BakalariConfigError` naming every missing variable.
`environ` is a mapping to read instead of `os.environ`; any other keyword goes to the constructor.

```python
from bakalari import BakalariClient

client = BakalariClient.from_env(timeout=10, retries=2)
with BakalariClient.from_env() as scoped:          # logout() when the block ends
    print(scoped.api_version()["ApiVersion"])
```

The package also exports the constants `API_PATH` (`"/api/3"`), `TOKEN_PATH` (`"/api/login"`),
`DEFAULT_CLIENT_ID` (`"ANDR"`), `BASE_URL_ENV`, `USERNAME_ENV`, `PASSWORD_ENV` and `__version__`.

### Authentication

The client authenticates like the official mobile app: OAuth2 on `POST /api/login` with the password grant, which
returns a Bearer access token valid for an hour and a refresh token, and the refresh-token grant, which returns new
tokens without the password. Everything happens on its own:

- The first request that needs a token logs in, or renews a stored refresh token.
- The access token is renewed `renew_margin` seconds before it expires.
- When the server refuses a token anyway (HTTP 401), the client renews it and repeats the request once.
- When the refresh token is rejected and the client knows the password, it logs in again.

| Method or property | Returns | What it does |
|---|---|---|
| `login(username=None, password=None)` | `TokenInfo` | Logs in with the password grant, by default with the client's login, and stores the tokens. A wrong login raises `BakalariAuthError` and keeps the previous tokens; no login at all raises `BakalariConfigError`. |
| `refresh()` | `TokenInfo` | Renews the tokens with the refresh-token grant; `BakalariError` when no refresh token is stored. |
| `ensure_token()` | `TokenInfo` | Logs in or renews as needed and returns the current token info. |
| `logout()` | `None` | Forgets the tokens. The API has no revocation endpoint, so this ends nothing on the server. |
| `is_authenticated` | `bool` | True while the client holds an access token (it may still need renewing). |
| `token_info` | `TokenInfo` or `None` | The non-secret part of the current token; `None` before the first login. |

`TokenInfo` holds `user_id` (the server's `bak:UserId`), `token_type`, `expires_in` (seconds), `scope`,
`api_version` and `expires_at` (the expiry in epoch seconds); its property `scopes` splits `scope`. It never holds
a token.

Bakaláři counts failed logins per account and shows them to the account owner at the next web login. Never try
passwords and never test error handling with a real username and a wrong password.

### Sessions

A session is what it takes to continue without the password: the refresh token (valid until it goes unused for
about a month; each renewal issues a new one) and the current access token.

| Method | Returns | What it does |
|---|---|---|
| `export_session()` | `SessionState` | The current tokens and their metadata; `BakalariError` when no refresh token is stored (before the first login or after `logout()`). |
| `import_session(state)` | `None` | Resumes a `SessionState` or its `to_dict()` data. A still valid access token is reused; otherwise the next request renews the tokens. A session of another installation raises `BakalariConfigError`. |

`SessionState` has the fields `base_url`, `refresh_token`, `access_token`, `expires_at`, `user_id`, `scope`,
`api_version` and `token_type`. `to_dict()` returns them all as JSON data, the tokens included, and
`SessionState.from_dict(data)` reads them back (it needs at least `base_url` and `refresh_token`, else
`BakalariConfigError`). The tokens are left out of `repr()`. Treat a session like a password: store it in a file
only you can read and never commit or share it.

`on_session_update` is called with `export_session()` after every login and renewal, the automatic ones included,
so an application can always store the newest refresh token. It runs on the thread whose request needed the new
token, possibly while the client holds its token lock: keep it short and don't wait in it for other threads that
use the same client. An exception it raises propagates to that request; the new tokens are stored already.

```python
import json
import os

from bakalari import BakalariClient, SessionState

def save_session(state: SessionState) -> None:
    descriptor = os.open("bakalari.session.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with open(descriptor, "w", encoding="utf-8") as file:
        json.dump(state.to_dict(), file)

client = BakalariClient.from_env(on_session_update=save_session)
client.login()                                     # writes the file

with open("bakalari.session.json", encoding="utf-8") as file:
    state = SessionState.from_dict(json.load(file))
resumed = BakalariClient(state.base_url, on_session_update=save_session)   # no password
resumed.import_session(state)
```

[examples/persistent_session.py](../examples/persistent_session.py) adds the atomic replacement of the file and
the fallback to the password when the refresh token has expired.

## Conventions of the models

**Dataclasses.** The parsed responses are dataclasses that inherit `Model` (`TokenInfo` and `SessionState` are
plain dataclasses). All of them are frozen except `Timetable`. Collections are tuples (the helper properties
such as `Marks.new_marks` return lists), and nested objects are models too.

**`raw`.** Top-level and entity models end with a `raw` field holding the server's object as a dict, for the keys
the model does not map. It is left out of `repr()` and `to_dict()`.

**`to_dict()`.** Returns JSON-ready data of the fields `repr()` shows: nested models become dicts, dates and
datetimes ISO strings and tuples lists. A few models have their own form: `Lesson.to_dict()` is flat (subject,
teacher and room as abbreviations and names, the change type and description), `Day.to_dict()` and
`Timetable.to_dict()` use it for their lessons, and `AttachmentFile.to_dict()` adds the `size` instead of the
content. `SessionState.to_dict()` (not a model) contains the tokens.

**Ids** are kept exactly as the server sends them, never stripped: `" 2"` and `"2"` are different ids, and they
are percent-encoded when they go into a URL path (`%202`). Methods that take an id usually take the model that
carries it too (a `Message`, a `Homework`, an `AttachmentInfo`, ...); the teacher methods take plain ids. The
lookups made for user input, such as `Marks.subject()`, `find_subject()`, `PublicTargets.find()` and
`MessageTypes.message_type()`, also accept an id without its padding and, where the model has them, an
abbreviation or a name, compared case-insensitively.

**Display strings** are trimmed (the server pads abbreviations and averages: `"ČJL "`, `"2,57 "`), and `null`
becomes `""`.

**Timestamps** are `datetime` objects with the offset the server sends (`2026-10-12T08:00:00+02:00`), so they are
timezone-aware; nothing is converted to another zone, and a value without an offset would stay naive. Values that
mean a calendar day are `datetime.date` objects: `Day.date`, `Mark.date`, `Homework.start` and `Homework.end`,
`Substitutions.start`, `AbsenceDay.date`, `Consent.valid_from`, ... A few timestamps keep their time although
only the day matters, e.g. `FinalMark.date` and `MarkingMark.mark_date`. The server's "no date" (`0001-01-01`) and
unparseable values become `None`.

**Numbers and flags.** Numbers are `int` or `float`; decimal commas are accepted (`"2,86"` is 2.86), and a
missing value or one that is not a finite number becomes `None`, or 0 for counters and amounts of money. `null`
booleans are `False`. Missing optional fields get these defaults, so parsing is lenient.

**`Item`.** The `{Id, Abbrev, Name}` objects of the API (classes, groups, subjects, teachers, rooms, week cycles,
event types) become `Item(id, abbrev, name)`; `str(item)` is the name, else the abbreviation, else the id. An
optional item is `None` when the server sends `null` or an object whose fields are all empty.

**Dates in requests** are `DateLike`: a `datetime.date`, a `datetime.datetime` or an ISO string such as
`"2026-10-22"`. A string goes to the server unchanged, which answers an invalid one with HTTP 400. Since `from` is
a Python keyword, the parameters are called `since` and `until`.

**Validation.** Methods with a `validate` parameter check the essential shape of the payload first (the lists and
objects every answer has) and raise `BakalariContractError`, whose `problems` lists every violation, when it does
not match. With `validate=False` they parse what they can: unknown references become `None` and malformed entries
are skipped. A payload of the wrong JSON type (a list where an object belongs) always raises
`BakalariContractError`, and so does a body that is not JSON at all, such as an HTML error page with HTTP 200. The
timetable raises the subclass `TimetableContractError`. Counters (`new_marks_count()`, `unread_messages_count()`,
...) must be numbers.

**Offline parsing.** Most models have a `from_json()` class method (`Timetable.from_json()`, `Marks.from_json()`,
`Absence.from_json()`, ...), and the modules have functions for their list payloads: `parse_subjects()`,
`parse_homeworks()`, `parse_events()`, `parse_messages()`, `parse_message()`, `parse_consents()`,
`parse_commissioners()`, `parse_class_fund_payments()`, `parse_final_marks()`, `parse_pedagogical_measures()`,
`parse_public_targets()` and `parse_public_timetable()`. They take the decoded JSON (or the HTML page) and,
except `parse_public_targets()`, the same `validate` argument.

**Readable output.** Models that are often printed have `format()` (and `format_summary()`) methods that return
one readable line per item, in English with the Czech texts of the server as they are.

**Wrong arguments** raise `ValueError` or `TypeError` before any request: an empty id, an unknown folder, scope,
kind or sort order, an empty search text, a malformed hypothetical mark.

## Errors

```text
BakalariError
├── BakalariConfigError        missing address or login, invalid session, session of another installation
├── BakalariConnectionError    DNS, TLS, refused connection, timeout
├── BakalariHTTPError          an unexpected HTTP status
│   ├── BakalariAuthError      login or refresh token rejected (HTTP 400 invalid_grant), token refused (HTTP 401)
│   ├── BakalariPermissionError  HTTP 403: module or right not enabled, teacher-only, unpublished public timetable
│   └── BakalariNotFoundError  HTTP 404: unknown endpoint or object
└── BakalariContractError      the answer is not JSON or does not have the expected structure
    └── TimetableContractError the timetable payload does not have the expected structure
```

`BakalariError` itself is raised for a few conditions found by the client: a homework the server refused to tick,
a token answer without tokens, `refresh()` or `export_session()` without a session, no way to reply to a message.

`BakalariHTTPError` and its subclasses have the attributes `method`, `path`, `status`, `expected` (the status or
statuses that were accepted) and `body` (the error body of an HTTP 4xx or 5xx answer: the decoded JSON, the title
of an HTML page or the start of the text; else `None`), and the property `message`, the server's own error text.
The `path` attribute and diagnostic messages omit query strings and fragments.
A 403 says `An error has occurred.` when a module or right is missing, and
`Some privilege is missing (IsTeacher).` for a teacher endpoint. `BakalariContractError` has `problems`.
Messages never contain tokens or passwords.

```python
from bakalari import BakalariContractError, BakalariError, BakalariPermissionError

try:
    absence = client.absence()
except BakalariPermissionError as error:
    print("Not available for this account:", error.message)
except BakalariContractError as error:
    print("Unexpected answer:", *error.problems, sep="\n- ")
except BakalariError as error:
    print("Bakaláři error:", error)
```

## Account

Module `bakalari.user`.

| Method | Returns | Notes |
|---|---|---|
| `user_profile(*, validate=True)` | `UserProfile` | `GET /api/3/user`: the account, its modules and rights, the current semester and school year. |
| `enabled_modules()` | `List[str]` | The module names of the profile (parsed without validation). |
| `student_at_school()` | `bool` | `GET /api/3/user/student-at-school`: whether the school's access system registers the student at school now. Module AccessSystem. |
| `web_modules(*, validate=True)` | `WebModules` | `GET /api/3/webmodule`: the pages of the Bakaláři web the app links to. |
| `login_token()` | `str` | `GET /api/3/logintoken`: a one-time token for the web login. A credential until it is used. |
| `web_login_url(return_url="next/dash.aspx")` | `str` | `<base_url>/api/3/login/<token>?returnUrl=<return_url>` with a fresh token: opened in a browser, it logs in to the web and goes to `return_url` (a path such as a `WebModule.url`). An empty `return_url` leaves out the query. A credential until it is used. |
| `register_notification(token)` | `None` | `POST /api/3/register-notification?token=`: registers a push token. The server expects the official app's Firebase token, so a third-party token receives no pushes; poll the counters instead. Changes data. |

- **`UserProfile`**: `uid`; `full_name` (for a parent account the student's name with the class); `full_user_name`
  (the account holder, newer servers); `user_type` (`"parents"`, `"student"` or `"teacher"`) and `user_type_text`
  (the Czech label); `school_name`, `school_type`, `study_year`; `school_class` (an `Item` or `None`);
  `teacher_classes` (`Item` tuple, teachers only); `students` (`StudentInfo` tuple, parent accounts);
  `modules` (`ModuleRights` tuple); `semester` (`Semester` or `None`); `school_year` (`SchoolYear` or `None`);
  `campaign_category_code`; `settings` (the server's `SettingModules` object, left out of `repr()` and
  `to_dict()`); `raw`. Properties `is_parent`, `is_student`, `is_teacher` and `module_names`; methods
  `has_module(name)`, `rights_of(module)` and `has_right(module, right)`, which compare names case-insensitively.
- **`StudentInfo`**: `full_name`, `school_class`, `school_type`, `study_year`, `raw`. A parent with several
  children has one login per child.
- **`ModuleRights`**: `module` (`"Komens"`, `"Marks"`, ...) and `rights` (e.g. `"SendMessages"`); method
  `allows(right)`.
- **`Semester`**: `id` (`"1"` or `"2"`), `start`, `end`. **`SchoolYear`**: `id`, `name` (`"2026/27"`), `start`,
  `end`. The server may leave out the semester during the summer holidays, and older servers the school year.
- **`WebModules`**: `modules` (`WebModule` tuple), `dashboard` (`WebModule` or `None`), `raw`.
  **`WebModule`**: `name`, `url` (relative, e.g. `"next/dokumentyPrehled.aspx"`), `icon_id`, `submenu` (the
  server's list as a tuple, or `None`), `raw`.

```python
profile = client.user_profile()
if profile.is_parent:
    print([student.full_name for student in profile.students])
if profile.has_right("Komens", "SendMessages"):
    print("may send messages")
documents = next((module for module in client.web_modules().modules if module.name == "Dokumenty"), None)
if documents is not None:
    link = client.web_login_url(documents.url)     # a credential: open it, don't share it
```

## Timetable

Module `bakalari.timetable`.

| Method | Returns | Notes |
|---|---|---|
| `actual_timetable(date=None, *, validate=True)` | `Timetable` | `GET /api/3/timetable/actual?date=`: the Monday-Friday week that contains `date` (default today) with its substitutions, cancellations and events. A weekend date returns its own week; holidays are days without lessons. |
| `permanent_timetable(*, validate=True)` | `Timetable` | `GET /api/3/timetable/permanent`: the regular timetable; a lesson of some weeks lists its `cycles`. |
| `class_timetable(class_id, date=None, *, permanent=False, validate=True)` | `Timetable` | The timetable of a whole class with the lessons of all its groups. `class_id` is an id or an `Item` such as the profile's `school_class`; with `permanent=True` the permanent one (`date` does not apply). Verified for the account's own class; another class may be refused. |
| `timetable_json(kind="actual", date=None, *, class_id=None)` | `Dict[str, Any]` | The raw payload; `kind` is `"actual"` or `"permanent"`. |

- **`Timetable`** (the one mutable model): `hours` (`Hour` tuple), `days` (`Day` tuple), the lookup dicts
  `classes`, `groups`, `subjects`, `teachers`, `rooms` and `cycles` (`Item` values keyed by the raw ids), `raw`.
  Properties `lessons`, `taught_lessons` (without the events that replace lessons), `changed_lessons` and `dates`;
  methods `day(date)`, `lessons_on(date)`, `covers_week_of(date)`, `format()` and `to_dict()`; class method
  `from_json(data, *, validate=True)`.
- **`Day`**: `date`, `day_of_week` (1 is Monday), `day_type` (one of `DAY_TYPES`: `WorkDay`, `Weekend`,
  `Celebration`, `Holiday`, `DirectorDay`, `Undefined`), `description` (names a holiday), `lessons`, `raw`.
  Property `is_work_day`; methods `format_summary()` and `to_dict()`.
- **`Lesson`**: `date`, `day_of_week`, `hour` (an `Hour`); `subject`, `teacher` and `room` (`Item` or `None`;
  an event that replaces a lesson has none of them); `groups` and `cycles` (`Item` tuples); `theme`; `change` (a
  `Change` or `None`); `homeworks` (`LessonHomework` tuple: `id`, `text`) and `homework_ids`; `notice`;
  `week_theme`; `is_last_room_lesson`; `start` and `duration` (minutes after midnight and length, newer servers);
  `raw`. Properties `changed`, `is_taught`, `has_homework` and `title` (the subject name, or the change's type name
  for an event); methods `format(*, with_date=True)` and `to_dict()`, a flat dict with the keys `"date"`,
  `"day_of_week"`, `"hour"`, `"begin"`, `"end"`, `"subject_abbrev"`, `"subject"`, `"teacher_abbrev"`,
  `"teacher"`, `"room"`, `"room_name"`, `"groups"`, `"cycles"`, `"theme"`, `"changed"`, `"change_type"`,
  `"change_description"`, `"notice"`, `"week_theme"` and `"homeworks"` (unset values are empty strings).
- **`Hour`**: `id` (an int), `caption` (the lesson number, `"1"`), `begin` and `end` (`"8:00"`), `start` and
  `duration` (minutes, newer servers).
- **`Change`**: `change_type` (one of `CHANGE_TYPES`: `Canceled`, `Added`, `Removed`, `RoomChanged`,
  `Substitution`, `Absence`), `description`, `type_name`, `type_abbrev`, `time` (`"8:00 - 8:45"`), `day`,
  `hours` (`"1. hod"`), `display_type`, `atom_type`, `change_subject`, `begin_time`, `end_time`, `lesson_info` (a
  `ChangeLessonInfo` or `None`), `start`, `duration`, `raw`; method `format(*, with_date=True)`. The timetable fills
  `start` and `duration`, the substitutions list `day`, `begin_time`, `end_time` and `lesson_info`.
- **`ChangeLessonInfo`**: `class_abbrev`, `group_abbrev`, `is_class_group`, `subject_abbrev`, `room_abbrev`;
  `str()` joins the group (or class), subject and room.
- Functions: `contract_problems(data)` lists the contract violations of a timetable payload and
  `validate_timetable(data)` raises `TimetableContractError` for them; `to_date(value)` and `week_of(value)` (the
  Monday and Sunday of a week) convert `DateLike` values.

```python
import datetime as dt

week = client.actual_timetable(dt.date.today() + dt.timedelta(weeks=1))
for lesson in week.changed_lessons:
    print(lesson.format())
monday = week.day(week.dates[0]) if week.dates else None
print(week.covers_week_of(dt.date.today() + dt.timedelta(weeks=1)), monday.is_work_day if monday else None)
```

## Substitutions

Module `bakalari.substitutions`.

| Method | Returns | Notes |
|---|---|---|
| `substitutions(since=None, *, validate=True)` | `Substitutions` | `GET /api/3/substitutions?from=`: the changes of the timetable for 14 days from `since`; without it from Monday of the current week. Module Substitutions. |

- **`Substitutions`**: `start` and `end` (dates; `end` is 14 days after `start`), `changes` (a tuple of the
  timetable's `Change` model, each with its `day`), `raw`. Property `dates` (the days with a change); methods
  `on(date)`, `by_day()` (a dict of the changes per day) and `format()`.

## Marks

Module `bakalari.marks`.

| Method | Returns | Notes |
|---|---|---|
| `marks(*, since=None, validate=True)` | `Marks` | `GET /api/3/marks`: the subjects of the current school year with their marks and averages, and the school's mark options. With `since`, only the marks from that day on. |
| `new_marks_count()` | `int` | `GET /api/3/marks/count-new`: the server's counter, which is often 0 even when marks are flagged new; `Marks.new_marks` lists the flagged marks. |
| `final_marks(*, validate=True)` | `List[CertificateTerm]` | `GET /api/3/marks/final`: the certificates of every term, oldest first. |
| `pedagogical_measures(*, validate=True)` | `List[PedagogicalMeasure]` | `GET /api/3/marks/measures`: praises and reprimands. |
| `predict_marks(subject, hypothetical, *, marks=None, validate=True)` | `SubjectMarks` | `POST /api/3/marks/what-if`: the subject as it would be with additional marks. `subject` is a `SubjectMarks`, or an `Item`, id, abbreviation or name looked up in `marks` (fetched when not given; `ValueError` when it is not there). `hypothetical` is an iterable of `(mark_text, weight)` pairs such as `[("1", 3), ("2-", 5)]`. Computes only; HTTP 403 when prediction is disabled for the subject. |
| `what_if(marks, *, validate=True)` | `SubjectMarks` | The same request with your own list of `{Id, MarkText, Weight, MaxPoints, SubjectId}` objects (`Mark.what_if_entry()` builds one), e.g. for hypothetical point marks. |
| `confirm_marks(mark_ids)` | `bool` | `POST /api/3/marks/SetClassificationConfirmation`: confirms (signs) marks as a parent; mark ids or `Mark` objects, one or many. True when the server confirmed them, False when there was nothing to confirm (also for an empty list, which sends nothing). Right `CanConfirmClassification`. Changes data. |

- **`Marks`**: `subjects` (`SubjectMarks` tuple), `mark_options` (`Item` tuple: the mark values the school uses;
  an option's id is a mark text and its name describes it), `raw`. Properties `all_marks`, `new_marks` and
  `unconfirmed_marks`; methods `subject(key)` (by id, id without padding, abbreviation or name; `None` when there
  is no such subject), `mark_option(mark)` and `format()`.
- **`SubjectMarks`**: `subject` (an `Item`), `marks` (`Mark` tuple), `average_text` (as the server formats it,
  `"2,57"`), `average` (a float or `None`), `temporary_mark`, `temporary_mark_note`, `subject_note`,
  `points_only`, `prediction_enabled`, `raw`. Properties `new_marks` and `unconfirmed_marks`; methods
  `format_summary()` and `format()`.
- **`Mark`**: `id`, `subject_id`, `text` (the mark as shown: `"1"`, `"2-"`, `"N"`, or points), `caption`,
  `theme`, `date` (a date), `edit_date` (a datetime), `teacher_id`, `type`, `type_note`, `weight` (`None` for a
  point mark), `is_new`, `is_points`, `points_text`, `max_points`, `calculated_text`, `class_rank_text`,
  `verbal_evaluation`, `is_invalid_date`, `confirmation_state` (`"Confirmed"`, `"Unconfirmed"` or empty),
  `confirmed_at`, `confirmed_by`, `raw`. Properties `is_confirmed`, `is_unconfirmed`, `is_hypothetical` (a mark of
  a prediction, without an id) and `numeric_value` (`"1"` to `"5"`, a trailing `-` adding 0.5; `None` for point
  marks and marks such as `"N"`); methods `what_if_entry()` and `format()`.
- **`CertificateTerm`**: `school_year`, `semester`, `semester_name`, `grade`, `grade_name`, `year_in_school`,
  `final_marks` (`FinalMark` tuple), `subjects` (`Item` tuple), `achievement_text` (e.g. "prospěl s
  vyznamenáním"), `marks_average`, `absent_hours`, `not_excused_hours`, `certificate_date`, `repeated`, `closed`,
  `raw`; methods `final_mark(key)` and `format()`.
- **`FinalMark`**: `id`, `subject_id`, `text`, `subject` (the term's `Item` or `None`), `date`, `edit_date`,
  `raw`; property `numeric_value`.
- **`PedagogicalMeasure`**: `date`, `type_id`, `type_label`, `text` (HTML entities decoded), `school_year`,
  `semester`, `raw`; method `format()`.

```python
marks = client.marks()
for subject in marks.subjects:
    if subject.new_marks:
        print(subject.format_summary())
        for mark in subject.new_marks:
            print("   ", mark.format())
czech = marks.subject("ČJL")
if czech is not None and czech.prediction_enabled:
    print(client.predict_marks(czech, [("1", 2)]).average_text)
```

## Absence

Module `bakalari.absence`.

| Method | Returns | Notes |
|---|---|---|
| `absence(*, validate=True)` | `Absence` | `GET /api/3/absence/student`: the absence per day and per subject. Module Absence; the per-subject list is empty without the right `ShowAbsencePercentage`. |

- **`Absence`**: `percentage_threshold` (the share of missed lessons from which the school highlights a subject,
  a fraction such as `0.25`; `None` when not sent, 0 when not set), `days` (`AbsenceDay` tuple), `subjects`
  (`SubjectAbsence` tuple), `raw`. Property `subjects_over_threshold`; methods `totals()` (the day counters summed
  over all days), `day(date)` and `subject(name)`.
- **`AbsenceDay`**: `date` and the lesson counts `unsolved` (not yet excused), `ok` (excused), `missed`
  (unexcused), `late`, `soon` (early leavings), `school` (absent for a school activity) and `distance_teaching`,
  `raw`. Property `total`; method `counts()` (a dict in the order of `DAY_COUNTERS`).
- **`SubjectAbsence`**: `subject_name` (may be empty), `lessons_count`, `base` (missed lessons), `late`, `soon`,
  `school`, `distance_teaching`, `percentage_threshold` (the payload's threshold, left out of `repr()` and
  `to_dict()`), `raw`. Properties `percentage` (`base / lessons_count`, `None` before the first lesson) and
  `over_threshold` (the percentage has reached a threshold above 0).

## Subjects

Module `bakalari.subjects`.

| Method | Returns | Notes |
|---|---|---|
| `subjects(*, validate=True)` | `List[SubjectInfo]` | `GET /api/3/subjects`: the student's subjects with their teachers. |
| `subject_themes(subject_id, *, validate=True)` | `SubjectThemes` | `GET /api/3/subjects/themes/{id}`: the lessons of a subject with their class-book themes. `subject_id` is an id exactly as sent, a `SubjectInfo` or an `Item`; an id a URL path cannot carry (e.g. with a backslash) is sent as `GET /api/3/subjects/themes/get?subjectid=`, which answers the same. Right `ShowSubjectThemes`. |

- **`SubjectInfo`**: `id`, `name`, `abbrev`, `teacher` (an `Item` or `None`), `teacher_email`, `teacher_web`,
  `teacher_school_phone`, `teacher_home_phone`, `teacher_mobile_phone` (empty unless the school publishes them),
  `raw`.
- **`SubjectThemes`**: `subject` (an `Item`), `themes` (`Theme` tuple), `raw`.
- **`Theme`**: `date`, `theme`, `note`, `hour_caption` (`"1. hod"`), `lesson_label` (the lesson's number in the
  subject), `start`, `duration` (minutes), `raw`; properties `start_time` and `end_time` (`datetime.time` or
  `None`).
- Functions: `find_subject(subjects, key)` finds a subject by exact id, id without padding, abbreviation or name;
  `parse_subjects(data, *, validate=True)`.

## Homeworks

Module `bakalari.homeworks`.

| Method | Returns | Notes |
|---|---|---|
| `homeworks(since=None, until=None, *, validate=True)` | `List[Homework]` | `GET /api/3/homeworks?from=&to=`: the homeworks given or due in the interval; without it the server returns 14 days back and one day ahead. |
| `active_homeworks_count()` | `int` | `GET /api/3/homeworks/count-actual`: the homeworks that are not closed. |
| `set_homework_done(homework_id, done=True)` | `None` | `PUT /api/3/homeworks/{id}/student-done/{true\|false}`: ticks the student's `finished` flag, or clears it with `done=False`. An id or a `Homework`. An explicit refusal of the server raises `BakalariError`. Changes data. |

- **`Homework`**: `id`, `start` (the day it was given), `end` (the day it is due), `content`, `notice`, `done`
  (the teacher's flag: handed in), `closed` (no longer current), `finished` (the student's own tick),
  `electronic` (handed in on the web), `hour` (the lesson number), `school_class`, `group`, `subject`, `teacher`
  (`Item` or `None`), `attachments` (`AttachmentInfo` tuple, downloaded with `download_attachment()`), `raw`.
  Property `is_active` (not closed).
- Function: `parse_homeworks(data, *, validate=True)`.

Electronic submission works on the web only; open it with `web_login_url()`.

## Komens messages

Module `bakalari.komens`. Module Komens; sending needs the right `SendMessages`, uploading `SendAttachments`.

| Method | Returns | Notes |
|---|---|---|
| `messages(folder="received", *, since=None, validate=True)` | `List[Message]` | `POST /api/3/komens/messages/{folder}`: the folder `"received"`, `"sent"` or `"noticeboard"`, or `"apology"` and `"rating"`, which need extra rights. With `since`, only the messages from that day on. |
| `message(message_id, folder="received", *, validate=True)` | `Message` | `GET /api/3/komens/messages/{received\|sent}/{id}`: the detail; pass `"sent"` for a sent message, whose detail adds the recipients and persons. Reading the detail does not mark the message as read. |
| `unread_messages_count(folder="received")` | `int` | The unread messages of `"received"` or `"noticeboard"`. |
| `mark_message_read(message_id)` | `None` | `PUT .../mark-as-read`. Changes data. |
| `confirm_message(message_id)` | `None` | `PUT .../mark-as-confirmed`: confirms that a message was read; allowed when `Message.can_confirm`. Changes data. |
| `hide_message(message_id)` | `None` | `PUT .../mark-as-hidden`; allowed when `Message.can_hide`. Changes data. |
| `unhide_message(message_id)` | `None` | `PUT .../mark-as-unhidden`: shows a hidden message again. Changes data. |
| `delete_message(message_id)` | `None` | `DELETE /api/3/komens/message/{id}`; allowed when `Message.can_delete`. Changes data. |
| `message_types(*, reply_to=None, validate=True)` | `MessageTypes` | What the account may send; with `reply_to` (a message or its id) what a reply to it allows. |
| `send_message(...)` | `None` | `POST /api/3/komens/message`; see below. Changes data. |
| `reply_to_message(message, text, *, title=None, attachments=(), require_confirmation=False)` | `None` | Replies with the first message type and recipient type that `message_types(reply_to=message)` offers, to the original sender when the recipient type needs recipients; `title` defaults to `"Re: "` plus the original title when the type has a title. A `Message` or an id (then the detail is fetched first). Changes data. |
| `download_attachment(attachment_id)` | `AttachmentFile` | `GET /api/3/komens/attachment/{id}`: an attachment of a message or a homework (an id or an `AttachmentInfo`). Only attachments of the user's own messages. |
| `upload_attachment(source, *, filename=None, content_type=None)` | `str` | `POST /api/3/komens/attachment`: uploads a file for `send_message()` and returns its id. `source` is a path, a binary file object or bytes (then `filename` is required); the content type defaults to the one the file name suggests. |
| `rating_templates()` | `Any` | The rating templates as raw JSON (teacher accounts). |

```text
send_message(*, message_type, text, recipient_type, recipients=(), title="", previous_message_id=None,
             attachments=(), require_confirmation=False, email_notification=False, copy_for_class_teacher=False,
             copy_for_parent=False, send_as_director=False, lifetime=None, date_from=None, date_to=None,
             type_of_rating_id=None, scale=None, extra=None)
```

The arguments map to the keys of the JSON body: `message_type` (a code such as `"OBECNA"` or a `MessageType`) to
`MessageType`, `recipient_type` (a code or a `RecipientType`) to `RecipientType`, `recipients` (codes or
`Recipient` objects; none for the selection `"ZERO"`) to `Recipients`, `text` (HTML, as the web editor writes it)
to `Text`, `title` to `Title`, `attachments` (ids from `upload_attachment()`) to `Attachments`,
`previous_message_id` to `PreviousMessageId`, `require_confirmation`, `email_notification`,
`copy_for_class_teacher`, `copy_for_parent` and `send_as_director` to `RequireConfirmation`, `EmailNotification`,
`CopyForClassTeacher`, `CopyForParent` and `SendAsDirector`, `lifetime` to `Lifetime`, `date_from` and `date_to`
(ISO strings) to `DateFrom` and `DateTo`, `type_of_rating_id` to `TypeOfRatingId` and `scale` to `Scale`.
`DraftDate` is sent as `null`, and `extra` adds or overrides any key. An empty code or attachment id raises
`ValueError` before the request; any status but HTTP 200 raises `BakalariHTTPError`.

- **`Message`**: `id`; `kind` (the server's `$type`, e.g. `"GeneralMessageReceived"`); `title`; `text` (the HTML
  body); `sent`; `sender` (a `Sender`); `attachments` (`AttachmentInfo` tuple); `read`, `confirmed`,
  `can_confirm`, `can_answer`, `can_hide`, `can_delete`, `hidden`; `life_time` (`"ToRead"` or `"ToConfirm"`);
  `date_from` and `date_to` (for a message about a period, such as an excuse); `message_type` (`"OBECNA"`,
  `"OMLUVENKA"`, ...); `relevant_name` and `relevant_person_type` (the other party as the web lists it);
  `recipients_count`, `recipients_processed_count` and `attachments_count` (the sent list; `None` elsewhere);
  `recipients` and `recipients_processed` (`MessageRecipient` tuples) and `persons` (`MessagePerson` tuple) of the
  detail of a sent message; `raw`. Properties `plain_text` (the body as readable text: paragraphs and line breaks
  kept, list items with `- `, link targets after their text, embedded images and control characters dropped) and
  `needs_confirmation` (`can_confirm` and not yet `confirmed`); method `person(person_id)`. `repr()` shortens a
  long `text`.
- **`Sender`**: `id`, `type` (`"teacher"`, `"administrator"`, `"parents"`, `"student"`), `name`.
- **`MessageRecipient`**: `id`, `user_type`, `action_date`, `parent_persons`, `raw`. **`MessagePerson`**: `id`,
  `user_type`, `person_id`, `first_name`, `middle_name`, `last_name`, `degree`, `degree_behind`,
  `class_abbreviation`, `raw`; property `full_name`.
- **`MessageTypes`**: `types` (`MessageType` tuple), `recipients` (`Recipient` tuple: every recipient of the
  school), `raw`; methods `message_type(key)` and `recipient(key)`.
- **`MessageType`**: `code` (`"OBECNA"`, ...), `name`, `has_title`, `show_email_notification`,
  `show_confirmation`, `super_type`, `recipient_types` (`RecipientType` tuple), `raw`; method
  `recipient_type(key)`.
- **`RecipientType`**: `code` (e.g. `"U"`), `name`, `selection` (`"ONE"`, `"MULTI"` or `"ZERO"`),
  `show_copy_for_class_teacher`, `show_copy_for_director`, `show_copy_for_parent`, `show_copy_for_student`,
  `recipients` (`Recipient` tuple), `raw`. Properties `needs_recipients` (false for `"ZERO"`) and
  `default_recipients`; method `recipient(key)`.
- **`Recipient`**: `code` (what the recipients of `send_message()` take), `name`, `display_name`, `abbreviation`,
  `is_default`, `raw`.
- **`AttachmentInfo`** (module `bakalari.models`): `id`, `name`, `content_type`, `size`, `raw`.
- **`AttachmentFile`**: `filename` (as the server names it), `content_type`, `content` (bytes, left out of
  `repr()`), `id`. Properties `size` and `safe_filename` (without directory parts, control characters, characters
  Windows forbids and Windows device names, never a hidden file, at most 255 bytes); method
  `save(target, overwrite=False)`, which writes into `target` (a directory gets the file under `safe_filename`)
  and returns the path written; an existing file is never replaced unless `overwrite` is true
  (`FileExistsError`). `to_dict()` gives the `size` instead of the content.
- Functions: `parse_messages(data, *, validate=True)` and `parse_message(data, *, validate=True)`; constants
  `MESSAGE_FOLDERS`, `DETAIL_FOLDERS` and `UNREAD_FOLDERS`.

```python
types = client.message_types()
general = types.message_type("OBECNA")
if general is not None:
    teacher = general.recipient_type("U")
    if teacher is not None and teacher.needs_recipients and teacher.recipients:
        print("could send to", teacher.recipients[0].display_name)
```

## Events

Module `bakalari.events`.

| Method | Returns | Notes |
|---|---|---|
| `events(since=None, *, scope="all", validate=True)` | `List[Event]` | `GET /api/3/events`, `/events/my` or `/events/public` (`scope` `"all"`, `"my"` or `"public"`): the events from `since` on, or of the whole school year without it. Module Events. |

- **`Event`**: `id`, `title`, `description`, `note`, `event_type` (an `Item` or `None`), `times` (`EventTime`
  tuple, one entry per day), `classes`, `class_sets`, `teachers`, `teacher_sets`, `rooms`, `room_sets` and
  `students` (`Item` tuples), `changed` (when the school last edited it), `raw`. Properties `start` (the earliest
  start), `end` (the latest end), `whole_day` and `dates`.
- **`EventTime`**: `whole_day`, `start` and `end` (00:00 and 23:59 for a whole-day entry), `interval_start` and
  `interval_end` (the times entered for that day, `None` when the day has none), `interval_date`; property `date`.
- Function: `parse_events(data, *, validate=True)`; constant `EVENT_SCOPES`.

## GDPR

Module `bakalari.gdpr`.

| Method | Returns | Notes |
|---|---|---|
| `gdpr_commissioners(*, validate=True)` | `List[Commissioner]` | `GET /api/3/gdpr/commissioners`: the school's data protection officers; empty when the school has entered none. |
| `consents(*, validate=True)` | `List[Consent]` | `GET /api/3/gdpr/consents/person`: the consents of the logged-in person. |
| `child_consents(*, validate=True)` | `List[Consent]` | `GET /api/3/gdpr/consents/person/child`: the consents concerning the children of a parent account. |
| `new_consents_count()` | `int` | `GET /api/3/gdpr/consents/person/new`. |

- **`Commissioner`**: `id`, `name`, `mobile`, `phone`, `email`, `web`, `data_box` (the id of the Czech data box),
  `raw`.
- **`Consent`**: `id`, `person_type`, `person_id`, `created`, `title`, `personal_data` (what is processed),
  `usage_purpose` (why), `body`, `validity`, `valid_from`, `valid_to`, `valid_years`, `state` (e.g. `"Agreed"`),
  `can_agree`, `can_disagree`, `can_revoke_request`, `raw`; property `is_agreed`. Answering a consent is not
  supported (the request is undocumented).
- Functions: `parse_commissioners(data, *, validate=True)` and `parse_consents(data, *, validate=True)`.

## Payments

Module `bakalari.payments`. Module Payments; amounts are in CZK.

| Method | Returns | Notes |
|---|---|---|
| `class_fund_summary()` | `ClassFundSummary` | `GET /api/3/payments/classfund/summary`. |
| `class_fund_payments(*, sort="desc", search=None, validate=True)` | `List[ClassFundMonth]` | `GET /api/3/payments/classfund`: the movements by month, newest first (`"desc"`) or oldest first (`"asc"`), optionally only those matching `search` (an empty search raises `ValueError`). |
| `class_fund_payment_info()` | `ClassFundPaymentInfo` | `GET /api/3/payments/classfund/paymentsinfo`: how to pay into the fund. |
| `regular_payments_summary()` | `Any` | The regular payments summary as raw JSON (the payload is undocumented). |

- **`ClassFundSummary`**: `student_name_with_class`, `balance`, `spent` (a negative number), `raw`.
- **`ClassFundMonth`**: `month` (its first day), `balance` (the month's income and expenses), `items`
  (`ClassFundItem` tuple), `raw`. **`ClassFundItem`**: `description`, `date`, `amount` (positive for income,
  negative for an expense), `raw`.
- **`ClassFundPaymentInfo`**: `instructions`, `bank_account` (Czech format `prefix-number/bank`),
  `variable_symbol`, `specific_symbol` (`""` when there is none), `amount` (0 when not set), `message`, `raw`.
  Properties `iban` and `formatted_iban` (`None` when the account cannot be converted); method
  `qr_payment(*, amount=None, message=None)`.
- Functions: `account_to_iban(account)` (a Czech account number to its IBAN, or `None`), `format_iban(iban)`
  (groups of four characters) and `parse_class_fund_payments(data, *, validate=True)`; constant
  `CLASS_FUND_SORTS`.

`qr_payment()` returns the Czech QR payment ("QR Platba", SPAYD 1.0) string
`SPD*1.0*ACC:<IBAN>*AM:<amount>*CC:CZK*X-VS:<vs>*X-SS:<ss>*MSG:<message>` without the empty parts; draw it as a QR
code with any QR library. `amount` and `message` replace the server's values; an amount that rounds to 0.00 is left
out, so the payer fills it in, and a negative or excessive one raises `ValueError`. The message becomes plain ASCII
(letters lose their diacritics, `*` and `%` are percent-encoded) cut to 60 characters. It returns `None` when the
account has no IBAN or a symbol is not a number of at most 10 digits.

```python
from bakalari.payments import account_to_iban, format_iban

iban = account_to_iban("19-2000145399/0800")
print(iban, format_iban(iban) if iban else None)   # CZ6508000000192000145399 CZ65 0800 0000 1920 0014 5399
```

## Teachers

Module `bakalari.teacher`. Teacher accounts only; others get `BakalariPermissionError`. No teacher account was
available to verify these models against a live server, so each keeps the server's object in `raw`.

| Method | Returns | Notes |
|---|---|---|
| `classbook(since, until, *, validate=True)` | `ClassBook` | `GET /api/3/classbook?from=&to=`: a date covers the whole day; a datetime is sent as its wall-clock time with milliseconds and without an offset (`format_classbook_time()`). |
| `save_classbook_record(record, *, validate=True)` | `ClassBook` | `POST /api/3/classbook/{Id}`: writes a record and returns the saved day (with empty `hours`). `record` is a `ClassBookRecord` or the JSON body that `ClassBookRecord.request_body()` builds. Changes data. |
| `lesson_tags()` | `List[LessonTag]` | `GET /api/3/classbook/lessonTags`. |
| `lesson_absence(lesson_id)` | `Dict[str, Any]` | `GET /api/3/lesson/{lessonId}/absence`: the attendance of a lesson as raw JSON. `lesson_id` is a record's `lesson_id`, not its `id`. |
| `lesson_past(lesson_id)` | `LessonPast` | `GET /api/3/lesson/{lessonId}/past`: the last theme and the label of the next record. |
| `lesson_students_timetable(lesson_id)` | `Dict[str, Any]` | `GET /api/3/lesson/{lessonId}/studentsTimetable` as raw JSON. |
| `marking_atoms(*, validate=True)` | `List[MarkingAtom]` | `GET /api/3/marking/atoms`: the subjects and groups the teacher gives marks in. |
| `marking_marks(atom_id, *, validate=True)` | `MarkingSheet` | `GET /api/3/marking/marks/{atomId}`. |
| `emergency_configuration()` | `Any` | The emergency (crisis alarm) configuration as raw JSON. |

- **`ClassBook`**: `days` (`ClassBookDay` tuple), `hours` (`Hour` tuple), `raw`. Property `records`; methods
  `record(key)` (by record id or lesson id) and `hour(hour_id)`.
- **`ClassBookDay`**: `date`, `day_of_week`, `day_type`, `description`, `records` (`ClassBookRecord` tuple), `raw`.
- **`ClassBookRecord`**: `id`, `lesson_id`, `label` (the lesson's number in the subject), `theme`, `notice`,
  `private_notice`, `week_theme`, `tags` (tag ids), `level`, `hour_id`, `date`, `start`, `duration`,
  `hour_caption`, `hour_time`, `subject` (an `Item` or `None`), `groups` (`ClassBookGroup` tuple: an `Item` with a
  `class_id`), `editable_groups`, `change_text`, `supervision`, `raw`. Property `is_written`; method
  `request_body(*, theme=None, notice=None, private_notice=None, week_theme=None, label=None, tags=None)`, the body
  to save with the given changes (a record that is not written yet needs the `LessonPast.next_label` of
  `lesson_past()`).
- **`LessonTag`**: `id`, `abbreviation`, `title`, `raw`. **`LessonPast`**: `lesson_id`, `last_theme`,
  `next_label`, `raw`.
- **`MarkingAtom`**: `id`, `name`, `subject`, `disabled`, `disabled_text`, `raw`.
- **`MarkingSheet`**: `mark_options` (`Item` tuple), `marks` (`MarkingMark` tuple), `students`
  (`MarkingStudent` tuple), `teachers` (`Item` tuple), `raw`; methods `student(student_id)` and
  `marks_of(student)`.
- **`MarkingMark`**: `id`, `mark_date`, `edit_date`, `teacher_id`, `header_id` (groups the marks of one test),
  `mark_value`, `theme`, `student_id`, `read_only`, `read_only_description`, `publish_date`, `confirmed_at`,
  `confirmed_by`, `confirmation_state`, `raw`; property `is_confirmed`.
- **`MarkingStudent`**: `id`, `name`, `class_id`, `first_name`, `middle_name`, `last_name`,
  `registration_number`, `average_text1`, `average_text2`, `released`, `raw`.
- Functions: `format_classbook_time(value, *, end_of_day=False)` and `classbook_problems(data)`.

## Public timetable

Module `bakalari.public_timetable`. These are HTML pages of the Bakaláři web that need no login, so a client
without a login works: `BakalariClient("https://skola.bakalari.cz")`.

| Method | Returns | Notes |
|---|---|---|
| `public_timetable_targets()` | `PublicTargets` | `GET /Timetable/Public`: the classes, teachers and rooms the school publishes. |
| `public_timetable(kind, target_id, *, week="actual", validate=True)` | `PublicTimetable` | The timetable of a `kind` (`"class"`, `"teacher"` or `"room"`) for the `week` `"actual"`, `"permanent"` or `"next"`; `target_id` is a target id or a `PublicTarget`. A timetable the school does not publish raises `BakalariPermissionError` (its `message` is the reason the page gives). |
| `public_timetable_url(kind, target_id, *, week="actual")` | `str` | The browser address of that page. |

- **`PublicTargets`**: `classes`, `teachers` and `rooms` (`PublicTarget` tuples); property `all_targets`; methods
  `of_kind(kind)` and `find(key, kind=None)` (by exact id, else by name or id ignoring case and spaces).
- **`PublicTarget`**: `kind`, `id` (may contain spaces, e.g. `"U  19"`), `name`.
- **`PublicTimetable`**: `kind`, `target_id`, `week`, `hours` (`Hour` tuple), `days` (`PublicDay` tuple), `raw`
  (the embedded JSON of newer servers). Properties `lessons` and `changed_lessons`; methods `day(key)` (by Czech
  weekday abbreviation or date), `hour_of(lesson)` and `format()`.
- **`PublicDay`**: `day_abbrev` (`"po"` ... `"ne"`), `date_text` (`"12.10."`), `date` (only when the page
  reveals the year), `day_off`, `day_off_name`, `lessons`, `raw`; property `day_of_week`; method
  `format_summary()`.
- **`PublicLesson`**: `hour_index`, `begin`, `end`, `subject`, `subject_abbrev`, `teacher`, `teacher_abbrev`,
  `room`, `room_name`, `group`, `theme`, `notice`, `change_info`, `changed`, `absent_info`, `hour_caption`,
  `group_name`, `change_type`, `cycle`, `atom_type`, `raw`; properties `removed` and `title`; method `format()`.
- Functions for saved pages: `parse_public_targets(html)`,
  `parse_public_timetable(html, *, kind="", target_id="", week="", validate=True)` and
  `public_timetable_path(kind, target_id, *, week="actual")`; constants `PUBLIC_KINDS`, `PUBLIC_WEEKS` and
  `PUBLIC_TIMETABLE_PATH`.

## School directory

Module `bakalari.schools`. The public directory of schools that use Bakaláři, `https://sluzby.bakalari.cz/api/v1`
(`DIRECTORY_URL`), needs no login and is not part of a school's installation, so it has its own small client:

```text
SchoolDirectory(base_url=DIRECTORY_URL, *, timeout=30.0, transport=None)
```

| Method | Returns | Notes |
|---|---|---|
| `municipalities(*, validate=True)` | `List[Municipality]` | `GET /municipality`: every municipality with its number of schools, one of them without a name. |
| `schools(municipality, *, validate=True)` | `List[School]` | `GET /municipality/{name}`: the schools of a municipality (a name or a `Municipality`). The service matches the name as a case-insensitive prefix, so `"Brno"` also returns the schools of `"Brno - Bystrc"`. An unknown name raises `BakalariNotFoundError`, an empty one `ValueError`. |
| `find(text, *, max_requests=15, validate=True)` | `List[School]` | The schools of every municipality whose name contains `text`, ignoring case, diacritics and the spacing around dashes. A text that would need more than `max_requests` requests (`DEFAULT_MAX_REQUESTS`) raises `ValueError` before it sends them; so does an empty one. |

The module-level functions `municipalities()`, `schools(name)` and `find(text)` use a default `SchoolDirectory`.

- **`Municipality`**: `name`, `school_count`, `raw`.
- **`School`**: `id`, `name`, `url` (the address as listed), `raw`; property `base_url` (normalized the way the
  client normalizes its address; pass it to `BakalariClient`).

## Raw requests

These methods of the client core reach any endpoint, for one without a typed method or the full payload of one
that has it.

| Method | Returns | Notes |
|---|---|---|
| `api_version()` | `Dict[str, Any]` | `GET /api/3` (no login): `ApiVersion`, `ApplicationVersion`, `BaseUrl`. |
| `available_api_versions()` | `List[Dict[str, Any]]` | `GET /api` (no login). |
| `request(method, path, *, params=None, form=None, json_body=None, data=None, headers=None, authorized=True, access_token=None, expected_status=200)` | `HttpResponse` | Sends a request and returns the response. |
| `get_json(path, params=None, *, authorized=True)` | `Any` | `GET` and decode the JSON body (`None` for an empty body). |
| `post_json(path, *, params=None, form=None, json_body=None, expected_status=200)` | `Any` | An authorized `POST`, decoded the same way. |

`request()` details:

- `method` is `GET`, `POST`, `PUT`, `DELETE` or `PATCH`; `path` is relative to `base_url` (`/api/3/user`).
- `params` become the query string (`None` values are left out; a list repeats the key). Pass at most one body:
  `form` (form-encoded), `json_body` (JSON) or `data` (raw bytes, with their `Content-Type` in `headers`).
- Every request sends `Accept: application/json`, `Accept-Language: cs` (some installations answer HTTP 500
  without it) and the `User-Agent`; `headers` add or replace headers.
- `authorized=True` sends the managed Bearer token, logging in or renewing it first, and renews and repeats the
  request once after HTTP 401. `authorized=False` is for the public endpoints, and `access_token` sends that token
  instead of the managed one, without renewing it.
- A status not in `expected_status` (an int, a collection of ints, or `None` for any) raises
  `BakalariAuthError` (HTTP 401, and HTTP 400 of the token endpoint), `BakalariPermissionError` (403),
  `BakalariNotFoundError` (404) or `BakalariHTTPError`.

`get_json()` and `post_json()` raise `BakalariContractError` when the body is not JSON. Ids that go into a path must
be percent-encoded: `urllib.parse.quote(value, safe="")`.

**`HttpResponse`** (exported by `bakalari`): `status`, `headers`, `body` (bytes, left out of `repr()`), `url` (the
final URL after redirects, when the transport knows it); property `text` (the body decoded as UTF-8) and
`content_type` (the media type without parameters, lower-cased); methods `json()` (`None` for an empty body) and
`header(name, default=None)` (case-insensitive).

```python
from urllib.parse import quote

summary = client.get_json("/api/3/payments/regularpayments/summary")
response = client.request("GET", "/api/3/subjects/themes/" + quote(" 2", safe=""), expected_status=(200, 404))
print(response.status, response.json() if response.content_type == "application/json" else response.text[:80])
```

## MCP server integration

`bakalari.mcp.MCPServer` wraps a client in the local stdio MCP server. The class is imported from
`bakalari.mcp`, rather than from the package root:

```python
from bakalari import BakalariClient
from bakalari.mcp import MCPServer

client = BakalariClient.from_env()
MCPServer(client, allow_writes=False).serve()
```

`serve()` owns stdin/stdout until EOF; only protocol messages may go to stdout while it runs. Use stderr for
application diagnostics. Set `allow_writes=True` only when the integration should expose the 11 write tools
alongside the 50 read tools. Account permissions still apply. This flag is fixed when the server is constructed.

| API | Use |
|---|---|
| `MCPServer(client=None, *, allow_writes=False, client_provider=None, directory_provider=None)` | Pass an existing client, or a zero-argument provider for lazy creation; do not pass both. A directory provider returns a `SchoolDirectory`. |
| `server.serve(input_stream=None, output_stream=None)` | Serve a single serial connection. Optional streams are binary; defaults are `sys.stdin.buffer` and `sys.stdout.buffer`. |
| `server.handle(message)` | Handle one decoded JSON-RPC object and return its response, or `None` for a notification. Initialization is required before tool calls. |

Without a supplied client/provider, school tools lazily read the standard URL and credential environment
variables. Direct embedding does not load `BAKALARI_SESSION_FILE`: import the session into your client and
configure `on_session_update` yourself, following [Sessions](#sessions). The `bakalari mcp` command handles
session-file loading and atomic persistence for you.

The MCP catalog is an explicit subset of the Python interface: no arbitrary `request()`, credentials,
one-time web login links or local file access. Tools accept JSON-friendly arguments and return `{"data": ...}`.
An attachment is transferred as base64, whereas the Python API can also work with local paths and file objects.
Calls run serially, and an in-flight synchronous school request cannot be interrupted by an MCP cancellation.

See the [complete MCP user guide](mcp.md) for all tools, [workflow examples](mcp.md#everyday-workflows),
[protocol details](mcp.md#protocol-and-lifecycle), and a
[Python MCP client example](mcp.md#connect-from-a-python-mcp-client). The regular Python client remains useful
when your application needs direct access to models and endpoints rather than a subprocess protocol.

## Threading

One client can be shared between threads. A lock guards the tokens, so only one thread logs in or renews at a time
while the others wait for the new token; the HTTP requests themselves run in parallel. The models are immutable
(except `Timetable`, which the client never changes after parsing), so they can be shared too. A
`SchoolDirectory` keeps no state.

`on_session_update` runs on the thread that triggered the login or renewal, possibly while the lock is held:
don't wait in it for other threads that use the same client.

## Timeouts and retries

`timeout` (30 seconds) goes to the transport with every request. The default transport passes it to
`urllib.request.urlopen()`, where it limits each blocking step (connecting, each read), not the whole request. A
timeout or another network failure raises `BakalariConnectionError`.

`retries` (0 in the library, 2 in the command line) repeats the idempotent `GET`, `PUT` and `DELETE` requests
after a `BakalariConnectionError` or an HTTP 502, 503 or 504 answer. It waits
`retry_backoff` seconds (0.5) before the first retry and twice as long before each further one. `POST` requests,
including logins, are never repeated. When the last attempt still fails, the error (or the HTTP error of the last
answer) is raised as usual.

## Transports

A transport sends one request. It is any function with the signature

```text
transport(method, url, headers, body, timeout) -> HttpResponse
```

(`bakalari.http.Transport`). It returns HTTP error statuses as responses and raises `BakalariConnectionError` when
the server cannot be reached. The default, `urllib_transport(ssl_context=None)`, uses `urllib.request` without a
cookie jar (the API is stateless) and honours the usual proxy variables such as `HTTPS_PROXY`. It follows HTTP(S)
redirects, but never downgrades HTTPS to HTTP. Requests with an Authorization header or body (including login
requests) can only redirect within the original origin: the same scheme, host and effective port. A refused
redirect is returned as its original HTTP status; the client raises `BakalariHTTPError` unless that status was
explicitly accepted. Public requests without a body can redirect to another host.

For a company CA or other TLS settings, pass an `ssl.SSLContext`:

```python
import ssl

from bakalari import BakalariClient

context = ssl.create_default_context()             # e.g. ssl.create_default_context(cafile="company-ca.pem")
client = BakalariClient.from_env(ssl_context=context)
```

A custom transport can measure, record or route the requests through another HTTP library. It sees the
`Authorization` header and the login form with the password, so it must never log headers or bodies:

```python
import time

from bakalari import BakalariClient, HttpResponse, urllib_transport

default_transport = urllib_transport()

def timed_transport(method, url, headers, body, timeout) -> HttpResponse:
    started = time.monotonic()
    response = default_transport(method, url, headers, body, timeout)
    print(f"{method} HTTP {response.status} in {time.monotonic() - started:.2f} s")   # no URL, headers or body
    return response

client = BakalariClient.from_env(transport=timed_transport)
```

The public timetable recognizes an unpublished timetable by its redirect to an error or login page, so a transport
must either follow redirects and set `HttpResponse.url` to the final address, or return the redirect answer with
its `Location` header. `SchoolDirectory` takes a `transport` too.

## Logging

The client logs through the standard `logging` module, by default nowhere (Python shows only warnings and errors
of unconfigured loggers):

| Logger | Level | Records |
|---|---|---|
| `bakalari.client` | `DEBUG` | Every request: method, path (without the query) and HTTP status. |
| `bakalari.client` | `INFO` | Logins (with the user id and API version), renewals, a refused token that is renewed, retries. |
| `bakalari.schools` | `DEBUG` | Every request to the school directory: URL and HTTP status. |

Passwords, tokens, query strings and bodies are never logged. Messages and attachments do not appear either, but
paths contain ids, so treat debug logs as private.

```python
import logging

logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("bakalari").setLevel(logging.DEBUG)    # bakalari.client and bakalari.schools
```

## Testing your code

A transport that returns canned answers lets you test code that uses the client without a network or an account
(the package's own tests do this with the helpers in `unittests/support.py` of the source distribution):

```python
import json

from bakalari import BakalariClient, HttpResponse

def fake_transport(method, url, headers, body, timeout) -> HttpResponse:
    if url.endswith("/api/login"):
        payload = {"access_token": "access", "refresh_token": "refresh", "token_type": "Bearer", "expires_in": 3600}
    elif url.endswith("/api/3/marks/count-new"):
        payload = 2
    else:
        return HttpResponse(404, {"Content-Type": "application/json"}, b'{"Message": "Not found"}')
    return HttpResponse(200, {"Content-Type": "application/json"}, json.dumps(payload).encode("utf-8"))

test_client = BakalariClient("https://school.example", "user", "password", transport=fake_transport)
assert test_client.new_marks_count() == 2
```

Use synthetic data in tests and fixtures, never captured answers of a real account.
