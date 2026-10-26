# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-10-26

Initial release of the `bakalari` distribution: an unofficial Python client, CLI and MCP server for
Bakaláři REST API v3, using only the standard library and supporting Python 3.9 through 3.14.

### Added

- MCP server mode through `bakalari mcp`, `bakalari-mcp` and `python -m bakalari.mcp`, with no new runtime
  dependencies and Python 3.9 support. The stdio server provides 50 read tools across the API modules and school
  directory, plus 11 opt-in write tools with `--allow-writes`.
- Explicit tool schemas and validation, protocol/version negotiation, structured results, redacted errors,
  bounded stdio frames, base64 attachment transfers, and automatic CLI session renewal/persistence.
- MCP setup and tool reference in `docs/mcp.md`, including macOS/Linux and Windows setup, multiple accounts,
  read/write workflows, attachment examples, troubleshooting, an offline connection check and Python integration.
  README, CLI and library guides link to the full usage guide.
- Offline MCP protocol/integration tests and a CI interoperability check using the official MCP Python client.

#### Client

- `BakalariClient` logs in like the official mobile app (the OAuth2 password grant on `POST /api/login`, client id
  `ANDR`) on the first request that needs a token, renews the access token with the refresh token `renew_margin`
  seconds (60) before it expires, renews and retries once after HTTP 401, and logs in again with the password when
  the refresh token is rejected. `login()`, `refresh()`, `ensure_token()`, `logout()`, `token_info` (`TokenInfo`:
  user id, scope, API version, expiry; never a token) and `is_authenticated` give explicit control, and a `with`
  block logs out at its end.
- `BakalariClient.from_env()` reads the address from `BAKALARI_URL` and the login from `BAKALARI_USERNAME` and
  `BAKALARI_PASSWORD`, or from other variables with `username_env=` and `password_env=` (e.g. another child's login).
- Sessions: `export_session()` and `import_session()` with `SessionState` (`to_dict()` and `from_dict()`), a client
  started from a `refresh_token` alone, and the `on_session_update` callback after every login and renewal, so that
  an application can keep the newest refresh token and continue without the password.
- Retries: `retries` (0 by default) repeats `GET`, `PUT` and `DELETE` requests after a connection error or HTTP 502,
  503 or 504, waiting `retry_backoff` (0.5 s) and twice as long before each further retry; `POST` requests, logins
  included, are never repeated. `timeout` (30 s) applies to every request.
- Transports: the default `urllib_transport()` (no cookie jar, the usual proxy variables, an optional `ssl_context`)
  or any function with the `Transport` signature that returns an `HttpResponse`, e.g. canned answers in tests.
- `normalize_base_url()` accepts an address copied from the browser: it adds `https://` and drops a page path, a
  query and a trailing slash. Every request sends `Accept-Language: cs`, without which some installations answer
  HTTP 500.
- Raw access with the same token handling: `request()` (any method, query parameters, a form, JSON or raw body,
  extra headers, an expected status or a set of them), `get_json()`, `post_json()`, `api_version()` and
  `available_api_versions()`.
- One client can be shared between threads: a lock guards the tokens.
- Logging through the `bakalari.client` and `bakalari.schools` loggers: the method, path and status of every
  request, the logins, renewals and retries.

#### Typed models and contract checks

- The responses become dataclasses based on `Model` (frozen, except `Timetable`), with `to_dict()` (JSON-ready data)
  and `raw` (the server's object, for the keys a model does not map). Ids are kept exactly as sent, space padding included, and
  percent-encoded in paths; display strings are trimmed; timestamps are timezone-aware `datetime` objects and
  calendar days `date` objects; decimal commas are understood; missing and `null` fields get defaults.
- `Item` for the `{Id, Abbrev, Name}` objects, `AttachmentInfo`, `format()` methods for readable one-line output, and
  `from_json()` class methods and `parse_...()` functions for offline parsing.
- Contract checks: the methods with a `validate` parameter (true by default) check the essential shape of each
  payload and raise `BakalariContractError` listing every problem (`TimetableContractError` for timetables). A body
  that is not JSON, such as an HTML error page with HTTP 200, is a contract error too, and counters must be numbers.
  `validate=False` parses leniently.
- Errors: `BakalariError` and its subclasses `BakalariConfigError`, `BakalariConnectionError`, `BakalariContractError`
  and `BakalariHTTPError`, which has `method`, `path`, `status`, `expected`, `body` and the server's `message`, and
  the subclasses `BakalariAuthError`, `BakalariPermissionError` (HTTP 403: a module or right is missing, or the
  endpoint is for teachers) and `BakalariNotFoundError` (HTTP 404). Wrong arguments raise `ValueError` or `TypeError`
  before any request.

#### Endpoints

Typed methods for 71 endpoints, one module per area. docs/endpoints.md lists every known endpoint with its
verification status: 41 of the 71 were verified against a live installation and 23 more by route and method.

- Account (`bakalari.user`): `user_profile()`, which returns a `UserProfile` (user type, names, class, school, school
  year and semester, the students of a parent account, the modules and rights with `has_module()` and
  `has_right()`), `enabled_modules()`, `student_at_school()`, `web_modules()`, `login_token()`, `web_login_url()` (a
  one-time link that opens the Bakaláři web logged in) and `register_notification()`.
- Timetable (`bakalari.timetable`): `actual_timetable()`, `permanent_timetable()`, `class_timetable()` (a whole
  class with all its groups) and `timetable_json()`, with the lessons' homeworks, notices, week themes and times.
- Substitutions (`bakalari.substitutions`): `substitutions()`, the changes of 14 days grouped by day.
- Marks (`bakalari.marks`): `marks()` (optionally only `since` a date), `new_marks_count()`, `final_marks()`,
  `pedagogical_measures()`, the what-if prediction of an average with `predict_marks()` and `what_if()`, and
  `confirm_marks()` for parents.
- Absence (`bakalari.absence`): `absence()` per day and per subject with the school's percentage threshold.
- Subjects (`bakalari.subjects`): `subjects()` with the teachers and their contacts, `subject_themes()` (with the
  alternative route for ids a URL path cannot carry) and `find_subject()`.
- Homeworks (`bakalari.homeworks`): `homeworks()`, `active_homeworks_count()` and `set_homework_done()`.
- Komens messages (`bakalari.komens`): `messages()` of the received, sent, noticeboard, apology and rating folders
  (optionally only `since` a date), `message()`, `unread_messages_count()`, `mark_message_read()`,
  `confirm_message()`, `hide_message()`, `unhide_message()`, `delete_message()`, `message_types()` (also for a
  reply), `send_message()`, `reply_to_message()`, `upload_attachment()`, `download_attachment()` with
  `AttachmentFile.save()`, and `rating_templates()`. `Message.plain_text` turns the HTML body into readable text.
- Events (`bakalari.events`): `events()` of the whole school, the user's own or the public ones.
- GDPR (`bakalari.gdpr`): `consents()`, `child_consents()`, `new_consents_count()` and `gdpr_commissioners()`.
- Payments (`bakalari.payments`): `class_fund_summary()`, `class_fund_payments()`, `class_fund_payment_info()` with
  the IBAN and the Czech QR payment (SPAYD) string, `regular_payments_summary()`, `account_to_iban()` and
  `format_iban()`.
- Teacher accounts (`bakalari.teacher`): `classbook()`, `save_classbook_record()`, `lesson_tags()`,
  `lesson_absence()`, `lesson_past()`, `lesson_students_timetable()`, `marking_atoms()`, `marking_marks()` and
  `emergency_configuration()`.
- Public timetables (`bakalari.public_timetable`, no login): `public_timetable_targets()`, `public_timetable()` and
  `public_timetable_url()` for classes, teachers and rooms, from the newer and the older page layouts, and
  `parse_public_targets()` and `parse_public_timetable()` for saved pages.
- School directory (`bakalari.schools`, no login): `SchoolDirectory` with `municipalities()`, `schools()` and
  `find()`, which ignores case and diacritics, to find a school's Bakaláři address.

#### Command line

- The `bakalari` command (also `python -m bakalari`) with 38 commands, grouped by area in `bakalari --help`: public
  data (`version`, `schools`, `public-timetable`), the account and the session (`login`, `logout`, `profile` with the
  alias `whoami`, `modules`, `web-login`, `web-modules`, `at-school`), `timetable`, `substitutions` and `events`,
  marks (`marks`, `final-marks`, `measures`, `predict`, `confirm-marks`), `absence`, `subjects`, `homeworks` and
  `homework-done`, Komens messages (`messages`, `message`, `message-types`, `send-message`, `reply`,
  `confirm-message`, `hide-message`, `delete-message`, `attachment`), `consents`, `commissioners` and `class-fund`,
  teacher accounts (`classbook`, `lesson-tags`, `marking`), and raw requests to any endpoint (`api`).
- Global options `--base-url`, `--username-env`, `--password-env`, `--session-file` (or `BAKALARI_SESSION_FILE`),
  `--timeout` (30 s), `--retries` (2), `-v` and `--version`. Most commands accept `--json` and then print JSON
  instead of text, and dates are `YYYY-MM-DD`, `today`, `yesterday` or `tomorrow`.
- The session file keeps the session between commands, so the password is needed only after the refresh token has
  expired. It works without the login variables, which then serve as the fallback for a rejected refresh token.
- The commands that change data are marked in the help, do exactly what the command line says and print what they
  did. `send-message` checks the command line against the account's message types before it uploads or sends
  anything.
- Exit status 0 on success, 1 for an API, connection or contract error, with a hint where the cause is likely (e.g.
  a module that is not enabled, or an endpoint for teacher accounts), 2 for a usage or configuration error and 130
  when interrupted. docs/cli.md is the complete reference.

#### Package and documentation

- The package exports the client, the errors, every model class and the main helpers from `bakalari`, ships
  `py.typed` and has no runtime dependencies.
- Documentation: the README, the library guide (docs/library.md, every method and model), the command line reference
  (docs/cli.md), the endpoint coverage (docs/endpoints.md) and runnable examples: the weekly timetable, new marks,
  unread messages with their attachments, homeworks as an iCalendar file, a persistent session, the class fund QR
  payment and the school search.
- An offline test suite with a scripted transport and synthetic fixtures, which CI runs on Python 3.9 to 3.14 on
  Linux and on Python 3.13 on macOS and Windows with at least 90 % coverage, and read-only live tests that run only
  when `BAKALARI_URL`, `BAKALARI_USERNAME` and `BAKALARI_PASSWORD` are set.

### Changed

- Rename the repository and Python distribution from `bakalari-api` to `bakalari`. Install with
  `python -m pip install bakalari`; the Python import and the `bakalari` and `bakalari-mcp` commands stay the same.
- Use `bakalari` in CLI version output, MCP server identity, release metadata, documentation and calendar exports,
  and `bakalari-python/<version>` in the default HTTP User-Agent.

- The login variables are `BAKALARI_USERNAME` and `BAKALARI_PASSWORD` instead of `BAK_PTRK_USERNAME` and
  `BAK_PTRK_PASSWORD`.
- The school's address is required: set `BAKALARI_URL` or pass `base_url` (`--base-url` on the command line). There
  is no default school any more.
- `user_profile()` returns a typed `UserProfile` instead of the raw dict; the server's object is its `raw` field.
- The timetable models `Timetable`, `Day`, `Lesson`, `Hour` and `Change` are `Model` dataclasses with new fields;
  the existing fields keep their meaning, and `Lesson.to_dict()` keeps its keys and adds `notice`, `week_theme` and
  `homeworks`.
- `request()` also sends `PUT`, `DELETE` and `PATCH` requests, JSON and raw bodies and extra headers, and accepts a
  set of expected statuses or `None` for any. HTTP 403 and 404 raise `BakalariPermissionError` and
  `BakalariNotFoundError`, which are `BakalariHTTPError` subclasses, so existing handlers keep working.
- The command line was rewritten; `timetable` keeps its options and output. `bakalari.cli.main()` returns the exit
  status 2 for a usage error instead of letting `SystemExit` escape, and `-v` configures only the package's loggers
  instead of the root logger.
- Split automation into **Python Package CI** (`python-package.yml`) and **Python Package Publish**
  (`python-publish.yml`), replacing the previous CI and tag-push publishing workflows. Publishing a GitHub
  release, or manually running the publish workflow from its matching tag, validates the release, runs reusable
  CI and publishes its checked distributions through the `pypi` environment using PyPI trusted publishing.
- Validate that the release tag matches the package version, the changelog has a dated, non-empty release
  section, and no changes remain under "Unreleased" before publishing.
- Collect both `unittests/` and `tests/` in CI with live tests explicitly disabled, including official MCP SDK
  interoperability and release-validation regression tests. Retain test and coverage reports for 30 days.
- Check wheel and source-distribution contents, typed-package metadata and installed command entry points;
  keep repository tooling, local state, caches and generated reports out of distributions.
- Update contributor documentation for the workflow migration, required checks, PyPI trusted-publisher setup
  and release validation.

### Fixed

- Fall back to the ordinary attachment filename when the server sends a malformed extended filename header.
- Remove duplicate legacy tests whose missing helper imports broke full test discovery.
- Pass the coverage configuration explicitly in CI so subprocesses running outside the checkout use the same
  branch-coverage settings and their results can be combined successfully.

### Security

- Block redirects to another origin for requests carrying an Authorization header or body, including login
  requests, and reject HTTPS downgrades. Public HTTP(S) redirects remain supported.
- Remove query strings and fragments from request paths in logs, HTTP errors and JSON contract errors, so raw
  request paths cannot expose query tokens in diagnostics.
- Reject malformed installation URLs and embedded URL credentials before they can appear in diagnostics.
- Redact known passwords and access/refresh tokens echoed in upstream HTTP error bodies, including nested values.
- Keep stored passwords and tokens in private attributes and exclude token payloads from `repr()`. Request logs
  omit query strings and bodies, and connection error messages omit query strings that can carry push tokens.
- TLS certificates are verified by default, and there is no cookie jar, because the API is stateless.
- The command line writes the session file atomically with mode 0600, restricts a session file that other users
  can read when it loads it (on POSIX systems), refuses a file that is not a Bakaláři session, and `logout`
  deletes nothing but a Bakaláři session file.
- Text output removes the C0 and C1 control characters from server strings (titles, names, message bodies, file
  names) and JSON output escapes them, so a server cannot send escape sequences to the terminal.
- `AttachmentFile.save()` and the `attachment` command sanitize the server's file name (no directory parts, control
  characters, Windows device names or hidden files) and never overwrite a file unless asked to.
- `web-login` warns that its one-time link is a credential. Reading a message never marks it as read. The live tests
  call no endpoint that changes data and never log in with a wrong password for a real user, because Bakaláři shows
  failed logins to the account owner.

### Known limitations

- The REST API is not officially documented and may change without notice.
- Not verified against a live server: the teacher endpoints (no teacher account was available), the payments
  payloads (the module was disabled at the test school), the timetable pages of a school that publishes them, and
  the write endpoints (sending, replying, confirming, hiding and deleting messages, uploading attachments,
  confirming marks, ticking homeworks, saving class-book records, registering a push token), which were checked by
  route and method only. Their models follow the community documentation, other clients and captured traffic, and
  keep the server's objects in `raw`.
- 17 known endpoints have no typed method, mostly because their requests are undocumented (Komens drafts, consent
  answers, emergency alarms, teacher payment prescriptions, class-book attendance writes, the student timetable);
  `request()` and `bakalari api` reach them. Consents can be answered and homeworks handed in electronically on the
  Bakaláři web only.
- `register_notification()` needs the official app's push token, so a third-party token receives no notifications;
  poll the counters instead. `new_marks_count()` is often 0 even when marks are flagged new.
- `predict_marks()` takes classic marks only; hypothetical point marks need `what_if()`.
- `send-message` and `reply` turn plain text into HTML (escaped, line breaks as `<br>`), assuming that the server
  stores messages as HTML like the web editor does; `--html` sends the text unchanged.
- `class_timetable()` was verified for the account's own class only; the timetable of another class may be refused.
- Two commands that renew the same session file at the same moment can race, because the file is not locked.

[Unreleased]: https://github.com/robco/bakalari/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/robco/bakalari/releases/tag/v1.0.0
