# Command line reference

`bakalari` is the package's command line client. It is installed with the package as a console script, and
`python -m bakalari` runs the same program. This page describes the global options, the environment variables, the
session file, the output and the exit status, and then every command with its options, an example and a sample of
its output. The [README](../README.md) gives a shorter overview, the [library guide](library.md) describes the
Python methods behind the commands, and the [endpoint coverage](endpoints.md) lists the HTTP endpoints.

The samples use synthetic data (invented names, ids and values) and the example address `https://skola.bakalari.cz`.
They were produced by the program itself; tab-separated columns are shown with the tabs expanded.

## Contents

- [Synopsis](#synopsis) and [getting started](#getting-started)
- [Configuration](#configuration): environment variables, the address, the login, several accounts
- [Global options](#global-options)
- [The session file](#the-session-file)
- [Output](#output), [exit status](#exit-status), [errors and hints](#errors-and-hints), [dates](#dates)
- [Commands that change data](#commands-that-change-data)
- [MCP server mode](#mcp-server-mode) (`mcp`)
- [Commands](#commands), by area:
  [public data](#public-data-no-login) (`version`, `schools`, `public-timetable`),
  [account and session](#account-and-session) (`login`, `logout`, `profile`, `modules`, `web-login`, `web-modules`,
  `at-school`),
  [timetable and events](#timetable-and-events) (`timetable`, `substitutions`, `events`),
  [marks](#marks) (`marks`, `final-marks`, `measures`, `predict`, `confirm-marks`),
  [absence, subjects and homeworks](#absence-subjects-and-homeworks) (`absence`, `subjects`, `homeworks`,
  `homework-done`),
  [Komens messages](#komens-messages) (`messages`, `message`, `message-types`, `send-message`, `reply`,
  `confirm-message`, `hide-message`, `delete-message`, `attachment`),
  [GDPR and payments](#gdpr-and-payments) (`consents`, `commissioners`, `class-fund`),
  [teacher accounts](#teacher-accounts) (`classbook`, `lesson-tags`, `marking`),
  [raw access](#raw-access) (`api`)
- [Endpoints without a command](#endpoints-without-a-command)

## Synopsis

```text
bakalari [global options] COMMAND [options]
python -m bakalari [global options] COMMAND [options]
```

The global options go before the command and the command's own options after it, for example
`bakalari --session-file ~/.bakalari.session.json marks --new`. `bakalari --help` lists the commands by area, and
`bakalari COMMAND --help` describes one command.

```text
usage: bakalari [-h] [--version] [--base-url URL] [--username-env NAME] [--password-env NAME]
                [--session-file PATH] [--timeout SECONDS] [--retries N] [-v]
                COMMAND ...
```

## Getting started

```console
$ export BAKALARI_URL=https://skola.bakalari.cz      # the address of your school's Bakaláři web
$ export BAKALARI_USERNAME=bara.kocourkova           # the login of the Bakaláři web
$ export BAKALARI_PASSWORD='...'
$ bakalari --session-file ~/.bakalari.session.json login
Logged in as user UQX7K3M at https://skola.bakalari.cz (API 3.52.1); the access token expires at 2026-10-15 08:30:00+02:00.
Saved the session to /home/bara/.bakalari.session.json.
$ export BAKALARI_SESSION_FILE=~/.bakalari.session.json
$ bakalari marks --new
ČJL Český jazyk a literatura: average 2,57, 3 mark(s)
    2026-10-05  3-      weight 4  Slohová práce (písemná práce) [new, unconfirmed]
F Fyzika: average 0,67, 2 mark(s)
    2026-10-09  5/20              Laboratorní práce (laboratorní práce) [new, unconfirmed]
```

Don't know your school's address? `bakalari schools <municipality>` finds it in the public school directory without
a login. From now on the commands use the session file and need no password while its refresh token is valid.

## Configuration

### Environment variables

| Variable | Meaning |
|---|---|
| `BAKALARI_URL` | The school's Bakaláři address, e.g. `https://skola.bakalari.cz` or `https://www.skola.cz/bakaweb`. `--base-url` takes precedence. |
| `BAKALARI_USERNAME` | The username of the Bakaláři web. `--username-env NAME` reads it from another variable. |
| `BAKALARI_PASSWORD` | The password of the Bakaláři web. `--password-env NAME` reads it from another variable. |
| `BAKALARI_SESSION_FILE` | The [session file](#the-session-file), used when `--session-file` is not given. |

Keep the password in your shell profile, a secret store or a password manager, not in scripts. Bakaláři counts
failed logins and shows them to the account owner at the next web login, so never try passwords.

### The school's address

The address comes from `--base-url`, else from `BAKALARI_URL`, else from the session file. It is the root of the
installation that serves the Bakaláři web; a URL copied from the browser works too: `https://` is added when the
scheme is missing, and a query, a trailing slash and a page such as `/login` or `/next/dash.aspx` are dropped.

### The login

What a command needs:

| Commands | School's address | Login |
|---|---|---|
| `schools`, `logout` | no | no |
| `version`, `public-timetable`, `api --no-auth` | yes | no |
| every other command | yes | the login variables or a session file |

A command that needs a login and has neither the login variables nor a stored session exits with status 2 and names
the missing variables:

```console
$ bakalari --base-url https://skola.bakalari.cz modules
bakalari: error: Missing environment variable(s): BAKALARI_USERNAME, BAKALARI_PASSWORD. Set the school's Bakaláři address (BAKALARI_URL or --base-url) and the login of the Bakaláři web, or resume a stored session with --session-file.
```

### Several accounts

A parent with several children has one login per child. Keep each login in its own pair of variables and each
session in its own file:

```bash
bakalari --username-env EMA_USERNAME --password-env EMA_PASSWORD --session-file ~/.bakalari-ema.session.json marks --new
bakalari --username-env OTA_USERNAME --password-env OTA_PASSWORD --session-file ~/.bakalari-ota.session.json marks --new
```

A shell alias per child keeps this short:

```bash
alias ema='bakalari --username-env EMA_USERNAME --password-env EMA_PASSWORD --session-file ~/.bakalari-ema.session.json'
ema marks --new
```

## Global options

| Option | Default | Meaning |
|---|---|---|
| `--base-url URL` | `$BAKALARI_URL`, else the session file's | The school's Bakaláři address. |
| `--username-env NAME` | `BAKALARI_USERNAME` | The environment variable with the username. |
| `--password-env NAME` | `BAKALARI_PASSWORD` | The environment variable with the password. |
| `--session-file PATH` | `$BAKALARI_SESSION_FILE` | Keep the session in this file (mode 0600), so that the password is needed only when it expires; use one file per account. See [the session file](#the-session-file). |
| `--timeout SECONDS` | 30 | The timeout of each request, a positive number. It limits each blocking step (connecting, each read), not the whole command. |
| `--retries N` | 2 | Retries of `GET`, `PUT` and `DELETE` requests after a connection error or HTTP 502, 503 or 504, waiting 0.5 s, then 1 s, 2 s, ... `0` turns them off. `POST` requests, the login included, are never repeated. |
| `-v`, `--verbose` | | Log every request (method, path, status; never tokens or passwords) to standard error, with the logins and renewals. |
| `--version` | | Print the package version (`bakalari 1.0.0`) and exit. |
| `-h`, `--help` | | Show the help and exit. |

`-v` writes the log records of the package to standard error; the query strings and bodies of the requests, the
tokens and the password never appear in them:

```console
$ bakalari -v marks --count-new
DEBUG bakalari.client: POST /api/login -> HTTP 200
INFO bakalari.client: Logged in to the Bakaláři API as user UQX7K3M (API 3.52.1)
DEBUG bakalari.client: GET /api/3/marks/count-new -> HTTP 200
0
```

## The session file

With `--session-file PATH` (or `BAKALARI_SESSION_FILE`) the command line keeps the session in a JSON file: the
school's address, the refresh token, the current access token and their metadata. Later commands resume it and need
no password while the refresh token is valid; it stays valid until it goes unused for about a month, and every
renewal issues a new one.

- **Creating it.** `bakalari login` logs in with the login variables and stores the session. Any other command that
  logs in with the login variables stores it as well.
- **Using it.** Every command that needs a login loads the file first. The access token, valid for an hour, is
  renewed with the refresh token when needed, and every login and renewal is saved at once, even when the command
  fails afterwards. After the command, the file is rewritten only when the session changed, so an unchanged session
  is not written again and a newer session that a concurrent command saved is not overwritten.
- **Without the password.** A session file works without the login variables. When they are set too, they are the
  fallback for a refresh token the server no longer accepts: the client logs in with the password and stores the new
  session. Without them, such a command exits with status 1 and the hint to set the login variables and run
  `bakalari login`.
- **`login` and `logout`.** With the login variables, `login` always logs in with the password, even when the file
  holds a session, so that a stored session of another account is never reused silently; without them it renews the
  stored session. `logout` deletes the file.
- **The address.** A session belongs to one school. Without `--base-url` and `BAKALARI_URL`, the file's address is
  used, also by the commands that need no login. A file of another school than the configured address is a
  configuration error (exit status 2).
- **Safe writing.** The file is replaced atomically by a new file created with mode 0600 (readable and writable by
  you only); a missing directory is created. On POSIX systems, a session file that other users can read is
  restricted to mode 0600 when it is loaded, with a warning.
- **Damaged files.** A file that cannot be read or does not hold a Bakaláři session (it is corrupt or belongs to
  another program) is a configuration error (exit status 2): delete it or pass another path. `logout` deletes only a
  file that holds a Bakaláři session, so a mistyped path never deletes another file.

The file contains the tokens and gives access to the account: keep it to yourself, never commit it (`.gitignore` the
name, as this repository does for `*.session.json`) and use one file per account. The API cannot revoke tokens, so
`logout` deletes the file, and an access token copied elsewhere stays valid until it expires within the hour. Two
commands that renew the same session at the same moment can still race, because the file is not locked.

The content is the library's `SessionState.to_dict()`, so a Python program can resume the same session with
`SessionState.from_dict()` and `BakalariClient.import_session()` (see the [library guide](library.md#sessions)):

```json
{
  "base_url": "https://skola.bakalari.cz",
  "refresh_token": "<secret>",
  "access_token": "<secret>",
  "expires_at": 1792045800.0,
  "user_id": "UQX7K3M",
  "scope": "offline_access bakalari_api timetable_widget",
  "api_version": "3.52.1",
  "token_type": "Bearer"
}
```

## Output

**Text.** The output is compact: one item per line, dates as `YYYY-MM-DD`, times as `HH:MM`, and the Czech texts
of the server as they are. Listings are aligned in columns. Ids are printed the way they must be typed in a shell:
quoted when they contain spaces or shell characters (`'U  19'`, `'QX7K0A(2)C'`), so they can be pasted into the next
command.

**Control characters.** Every line written to standard output and standard error has the C0 and C1 control
characters removed (except the tab and the line feed), so a title, a name or a message body from the server cannot
move the cursor, recolour or retitle the terminal.

**JSON.** Most commands accept `--json` and then print the data as indented JSON: the `to_dict()` data of the
library's models (without their `raw` field), a list for a list of items, a bare number for a counter and `true` or
`false` for a yes-or-no answer. Text is written as UTF-8 (`ensure_ascii` off); DEL and the C1 control characters are
escaped (`\u009b`). The commands without `--json` are `logout`, `web-login`, `confirm-marks`, `homework-done`,
`send-message`, `reply`, `confirm-message`, `hide-message`, `delete-message`, `attachment` and `api`, which prints
JSON whenever the answer is JSON.

**Standard error.** Messages start with `bakalari:`: `bakalari: error: ...` and `bakalari: hint: ...` for
failures, `bakalari: warning: ...` and `bakalari: note: ...` for advice, and a few confirmations such as
`bakalari: marked message 400099 as read`. They never contain a token or a password.

**Pipes and encodings.** A reader that closes the pipe early (`bakalari messages | head -1`) ends the command
quietly with exit status 1. On a console or in a file whose encoding cannot represent a character (Windows), the
character is written as a backslash escape instead of failing.

## Exit status

| Status | Meaning |
|---|---|
| 0 | Success, also for `--help` and `--version`. |
| 1 | A Bakaláři error: an unexpected HTTP status (a refused login, a missing module or right, an unknown id, ...), a connection error or timeout, an answer without the expected structure (a contract error), or another error of the operating system. |
| 2 | A usage or configuration error: an unknown command or option, an invalid value, missing environment variables, an unusable session file, an argument the library refuses (e.g. an empty search text), or a local file problem (an attachment that exists without `--force`, an unreadable `--text-file`, a missing `--attach` file). |
| 130 | Interrupted with Ctrl-C. |

## Errors and hints

An HTTP error names the request, the status and the server's own message; a refused login shows the error of the
token endpoint. A hint follows when the cause is likely:

```console
$ bakalari substitutions
bakalari: error: GET /api/3/substitutions answered HTTP 403 Forbidden: An error has occurred.
bakalari: hint: the module or right this needs is not enabled for the account or the school
$ bakalari modules
bakalari: error: the login was refused (invalid_grant: Špatný login nebo heslo)
bakalari: hint: check the login in BAKALARI_USERNAME and BAKALARI_PASSWORD
```

| Situation | Hint |
|---|---|
| HTTP 403 `Some privilege is missing (IsTeacher)` | this is available to teacher accounts only |
| Another HTTP 403 | The command's own hint (given with each command below), else: the module or right this needs is not enabled for the account or the school |
| The login was refused | check the login in BAKALARI_USERNAME and BAKALARI_PASSWORD (the variables `--username-env` and `--password-env` name) |
| The stored session was refused and no login variables are set | the stored session is no longer accepted: set the login variables and run 'bakalari login' |
| A connection error | check the school's address (BAKALARI_URL or --base-url) and the network connection (`schools`: check the network connection) |
| HTTP 404 from the token endpoint | check the school's address (BAKALARI_URL or --base-url) |

## Dates

Every `DATE` (and the `DAY` of `timetable --day`) is an ISO date `YYYY-MM-DD` or one of the words `today`,
`yesterday` and `tomorrow`, in any case. Anything else is a usage error.

## Commands that change data

Most commands only read. These change data on the server; `bakalari --help` marks the commands among them with
`[changes data]`, and the reference below marks them and `message --mark-read` with **Changes data on the server**:

| Command | What it changes |
|---|---|
| `confirm-marks` | Confirms (signs) marks as a parent. |
| `homework-done` | Ticks or unticks the student's "finished" flag of a homework. |
| `message ID --mark-read` | Marks a received message as read (reading it does not). |
| `send-message`, `reply` | Send a message, after uploading the `--attach` files. |
| `confirm-message`, `hide-message`, `delete-message` | Confirm, hide (or show again) and delete a message. |
| `api` with a method other than `GET` | Whatever the endpoint does. |

Each of them does exactly what its command line says and prints what it did. `predict` uses `POST` but only
computes, and `messages` uses `POST` because the API lists messages that way; neither changes anything.

## MCP server mode

```bash
bakalari --session-file /absolute/path/bakalari.session.json mcp
bakalari --session-file /absolute/path/bakalari.session.json mcp --allow-writes
```

`mcp` starts a local Model Context Protocol server over stdin/stdout. It uses the global configuration and session
options above. Discovery needs no credentials; school requests authenticate when needed. Standard output holds
JSON-RPC messages, and errors for tool calls are returned within the protocol instead of ending the process.
EOF stops the server. `--allow-writes` adds tools that change school data; without it all tools are read-only.

The installed `bakalari-mcp` command and `python -m bakalari.mcp` accept global options without the `mcp`
subcommand. Global options must precede `mcp`; for example:

```bash
bakalari --session-file /absolute/path/student.session.json --timeout 60 --retries 0 -v mcp
```

`mcp` does not accept `--json`, CLI date shortcuts such as `today`, or ordinary command filters such as
`--unread`. Its host calls named tools with the JSON arguments advertised by `tools/list`. A tool failure normally
returns an MCP error result while the process keeps running; it is not the exit status of a one-shot CLI command.
Write tools require both `--allow-writes` and the school's normal account rights.

The [MCP user guide](mcp.md) contains the extensive usage reference:

- [Installation and account setup](mcp.md#install-and-prepare-an-account), with macOS/Linux and PowerShell examples.
- [Host configurations](mcp.md#connect-an-mcp-host), [all settings](mcp.md#configuration-reference), and
  [separate accounts](mcp.md#use-multiple-accounts).
- [Everyday read workflows](mcp.md#everyday-workflows) and [write workflows](mcp.md#write-workflows), including
  messages, attachments, homework, marks and teacher records.
- [All 61 tools](mcp.md#tool-catalog), [results and limits](mcp.md#results-errors-and-limits),
  [an offline connection check](mcp.md#verify-the-connection-without-a-school-account), and
  [troubleshooting](mcp.md#troubleshooting).

## Commands

| Command | What it does | Login |
|---|---|---|
| [`mcp`](#mcp-server-mode) | MCP stdio server, with optional write tools | when a private tool is called |
| [`version`](#version) | API version of the school's installation | no |
| [`schools`](#schools) | find a school's Bakaláři address | no (no address either) |
| [`public-timetable`](#public-timetable) | timetables the school publishes | no |
| [`login`](#login) | log in and store the session | yes |
| [`logout`](#logout) | delete the session file | no (no address either) |
| [`profile`, `whoami`](#profile-whoami) | the account: type, name, class, school, students | yes |
| [`modules`](#modules) | modules enabled for the account | yes |
| [`web-login`](#web-login) | one-time link that opens the Bakaláři web logged in | yes |
| [`web-modules`](#web-modules) | pages of the Bakaláři web the app links to | yes |
| [`at-school`](#at-school) | whether the student is registered at school now | yes |
| [`timetable`](#timetable) | actual or permanent timetable | yes |
| [`substitutions`](#substitutions) | changes of the timetable for two weeks | yes |
| [`events`](#events) | school events | yes |
| [`marks`](#marks-1) | marks and averages per subject | yes |
| [`final-marks`](#final-marks) | certificate marks of every term | yes |
| [`measures`](#measures) | praises and reprimands | yes |
| [`predict`](#predict) | average with hypothetical marks | yes |
| [`confirm-marks`](#confirm-marks) | confirm (sign) marks as a parent [changes data] | yes |
| [`absence`](#absence) | absence per subject and day | yes |
| [`subjects`](#subjects) | subjects, teachers and lesson themes | yes |
| [`homeworks`](#homeworks) | homeworks | yes |
| [`homework-done`](#homework-done) | tick or untick a homework as finished [changes data] | yes |
| [`messages`](#messages) | received, sent or noticeboard messages | yes |
| [`message`](#message) | one message with its attachments | yes |
| [`message-types`](#message-types) | message types and recipients for sending | yes |
| [`send-message`](#send-message) | send a message [changes data] | yes |
| [`reply`](#reply) | reply to a message [changes data] | yes |
| [`confirm-message`](#confirm-message) | confirm a message [changes data] | yes |
| [`hide-message`](#hide-message) | hide or unhide a message [changes data] | yes |
| [`delete-message`](#delete-message) | delete a message [changes data] | yes |
| [`attachment`](#attachment) | download a message or homework attachment | yes |
| [`consents`](#consents) | GDPR consents | yes |
| [`commissioners`](#commissioners) | data protection officers | yes |
| [`class-fund`](#class-fund) | class fund balance, payments and payment details | yes |
| [`classbook`](#classbook) | class-book records | yes (teacher) |
| [`lesson-tags`](#lesson-tags) | tags of class-book records | yes (teacher) |
| [`marking`](#marking) | marking units and their marks | yes (teacher) |
| [`api`](#api) | raw request to any endpoint | yes, except with `--no-auth` |

Every area needs its Bakaláři module (and sometimes a right) to be enabled for the school and the account; otherwise
the server answers HTTP 403 and the command exits with status 1 and a hint.

## Public data (no login)

### `version`

Prints the REST API version of the school's installation (`GET /api/3`). No login is needed, only the address.

```text
bakalari version [--json]
```

```console
$ bakalari version
Bakaláři REST API 3.52.1 (application 2.2.1009.7) at https://skola.bakalari.cz/api/3
$ bakalari version --json
{
  "ApiVersion": "3.52.1",
  "ApplicationVersion": "2.2.1009.7",
  "BaseUrl": "api/3"
}
```

### `schools`

Searches the public directory of schools that use Bakaláři (`https://sluzby.bakalari.cz/api/v1`): without `QUERY`
the municipalities with their number of schools, with `QUERY` the schools of the matching municipalities with the
address to use as `BAKALARI_URL`. It needs neither a login nor the school's address.

```text
bakalari schools [--municipality NAME] [--max-requests N] [--json] [QUERY]
```

| Argument or option | Meaning |
|---|---|
| `QUERY` | A part of a municipality name, ignoring case and diacritics. |
| `--municipality NAME` | The schools of the municipality `NAME` (and of those whose names start with it). Not together with `QUERY`. |
| `--max-requests N` | Refuse a `QUERY` that needs more directory requests (default: 15): a broad query exits with status 2 and asks for a more specific name. |
| `--json` | Print JSON instead of text. |

The two columns are separated by a tab: the municipality and its number of schools (`(no name)` for the entry
without a name), or the school and its address (`-` when the directory lists none). An unknown `--municipality`
answers HTTP 404 (exit status 1).

```console
$ bakalari schools kocourkov
Základní škola Kocourkov, Mlýnská 7     https://zs-kocourkov.school.example
Gymnázium Kocourkov     https://gym-kocourkov.school.example/bakaweb
Mateřská škola Kocourkov - Dolní Konec  https://ms-dolni.school.example
Základní umělecká škola Horní Konec     https://zus-horni.school.example/bakalari
Střední odborná škola Horní Konec       https://sos-horni.school.example
Základní škola Kocourkovice     https://zs-kocourkovice.school.example
$ bakalari schools | head -4
(no name)       3
Čertovice       1
Kocourkov       2
Kocourkov - Dolní Konec 1
```

### `public-timetable`

Prints a timetable from the school's public timetable pages (`/Timetable/Public`), or with `--list` the classes,
teachers and rooms it publishes. No login is needed, only the address.

```text
bakalari public-timetable (--list | --class ID | --teacher ID | --room ID) [--permanent | --next] [--json]
```

| Option | Meaning |
|---|---|
| `--list` | List the published classes, teachers and rooms. |
| `--class ID` | The timetable of a class. |
| `--teacher ID` | The timetable of a teacher. |
| `--room ID` | The timetable of a room. |
| `--permanent` | The permanent timetable instead of this week. |
| `--next` | Next week instead of this week. |
| `--json` | Print JSON instead of text. |

`ID` is an id or a name from `--list`, compared ignoring case and spaces; the command looks it up in the published
list (one extra request) and otherwise tries it as an id. `--permanent` and `--next` need `--class`, `--teacher` or
`--room`. Schools choose what they publish: a timetable they do not publish ends with exit status 1, the reason the
page gives, and the hint "the school does not publish this timetable".

```console
$ bakalari public-timetable --list
class    2B        2.B
class    1A        1.A
class    ZQ        3.C
teacher  UQX01     Testová Ema
teacher  'U  19'   Vzorový Karel
teacher  'UZK(7)'  Ukázková Lucie
teacher  UFI02     Fiktivní Oto
room     R1        12
room     'G 7'     14
room     KL        Tělocvična
$ bakalari public-timetable --teacher 'Vzorový Karel' --next
Public timetable of teacher Vzorový Karel, next week
po 16.11. (2026-11-16): 5 lesson(s)
     1.  8:00-8:45  Anglický jazyk | Ing. Karel Vzorový | 14 | Aj1
     1.  8:00-8:45  Německý jazyk | Bc. Lucie Ukázková | 12 | Nj2
     1.  8:00-8:45  Odebráno z rozvrhu (Fy, Fiktivní Oto)
     2.  8:55-9:40  Fyzika | PaedDr. Oto Fiktivní | 14 [Změna místnosti: 14 (12)]
     3. 10:00-10:45 Matematika | Mgr. Ema Testová | 12
út 17.11. (2026-11-17): day off (státní svátek)
st 18.11. (2026-11-18): 1 lesson(s)
     2.  8:55-9:40  Český jazyk a literatura | PaedDr. Oto Fiktivní | 12 [Suplování: Fiktivní Oto - Testová Ema (nem)]
čt 19.11. (2026-11-19): 1 lesson(s)
     4. 10:55-11:40 Výtvarná výchova | Mgr. Ema Testová | KL
pá 20.11. (2026-11-20): 0 lesson(s)
$ bakalari public-timetable --class 2B
bakalari: error: GET /Timetable/Public/Actual/Class/2B answered HTTP 403 Forbidden: K požadované stránce nemáte přístup.
bakalari: hint: the school does not publish this timetable
```

## Account and session

### `login`

Logs in with the login variables, or renews the session of the session file without them, and prints the user id,
the API version and the expiry of the access token (in local time). With `--session-file` the session is stored for
later commands; without it, a note on standard error says that the session is not kept. See
[the session file](#the-session-file).

```text
bakalari login [--json]
```

`--json` prints `base_url`, `user_id`, `api_version`, `token_type`, `scope`, `expires_in`, `expires_at`, `renewed`
(true when the stored session was renewed) and `session_file` (`null` without one); never a token.

```console
$ bakalari --session-file ~/.bakalari.session.json login
Logged in as user UQX7K3M at https://skola.bakalari.cz (API 3.52.1); the access token expires at 2026-10-15 08:30:00+02:00.
Saved the session to /home/bara/.bakalari.session.json.
$ unset BAKALARI_USERNAME BAKALARI_PASSWORD
$ bakalari --session-file ~/.bakalari.session.json login
Renewed the session of user UQX7K3M at https://skola.bakalari.cz (API 3.52.1); the access token expires at 2026-10-15 08:30:00+02:00.
Saved the session to /home/bara/.bakalari.session.json.
$ bakalari login
Logged in as user UQX7K3M at https://skola.bakalari.cz (API 3.52.1); the access token expires at 2026-10-15 08:30:00+02:00.
bakalari: note: the session is not kept: pass --session-file PATH (or set BAKALARI_SESSION_FILE) to keep it
```

### `logout`

Deletes the session file. The API cannot revoke tokens: the last access token expires within an hour. No request is
sent, and neither the address nor the login is needed.

```text
bakalari logout
```

`logout` needs a session file (`--session-file` or `BAKALARI_SESSION_FILE`; without one it exits with status 2). It
deletes only a file that holds a Bakaláři session; a file that does not exist is reported with exit status 0.

```console
$ bakalari --session-file ~/.bakalari.session.json logout
Deleted the session file /home/bara/.bakalari.session.json.
$ bakalari --session-file ~/.bakalari.session.json logout
There is no session file /home/bara/.bakalari.session.json.
```

### `profile`, `whoami`

Prints the account (`GET /api/3/user`): its type, name, class and school, the school year and semester, and the
students of a parent account. `whoami` is another name for the command.

```text
bakalari profile [--json]
```

The lines appear when the server sends the value: `Account holder` (newer servers, for a parent account the parent's
name), `Classes` (teacher accounts), `School type` and `Students` (parent accounts). `--json` prints the profile with
its modules and rights, without the server's module settings.

```console
$ bakalari profile
User type: rodič (parents)
Name: Kocourek Vilém, 6.E
Account holder: Kocourková Bára
Class: 6.E
Study year: 6
School: Základní škola Kocourkov, Mlýnská 7
School year: 2026/27 (2026-09-01 - 2027-08-31)
Semester: 1 (2026-09-01 - 2027-01-31)
Students:
    Kocourek Vilém, 6.E
```

### `modules`

Lists the Bakaláři modules enabled for the account (Komens, Marks, ...).

```text
bakalari modules [--rights] [--json]
```

| Option | Meaning |
|---|---|
| `--rights` | Also list the account's rights in each module. |
| `--json` | Print JSON instead of text (a list of `module` and `rights`). |

```console
$ bakalari modules --rights
Komens: ShowReceivedMessages, ShowSentMessages, ShowNoticeBoardMessages, SaveConcept, ShowConcepts, SendMessages, ShowRatingDetails, SendAttachments
Absence: ShowAbsence, ShowAbsencePercentage
Events: ShowEvents
Marks: ShowFinalMarks, ShowManners, ShowMarks, PredictMarks, CanConfirmClassification
Timetable: ShowTimetable
Substitutions: ShowSubstitutions
Subjects: ShowSubjects, ShowSubjectThemes
Homeworks: ShowHomeworks
Gdpr: ShowOwnConsents, ShowChildConsents, ShowCommissioners
Campaign: ShowCampaign
AccessSystem: CanShowStudentPresentAtSchool
```

### `web-login`

Prints a one-time link (`GET /api/3/logintoken`) that opens the Bakaláři web logged in. The link is a credential:
anyone who opens it is logged in as you.

```text
bakalari web-login [--return-url URL | --module NAME]
```

| Option | Meaning |
|---|---|
| `--return-url URL` | The page to open, relative to the school's address (default: `next/dash.aspx`, the dashboard). |
| `--module NAME` | Open the web module `NAME` (see [`web-modules`](#web-modules)), compared ignoring case; an unknown name exits with status 2 and lists the account's modules. |

The link goes to standard output and the warning to standard error, so the link can be opened directly without
showing it, e.g. `open "$(bakalari web-login)"` on macOS or `xdg-open "$(bakalari web-login)"` on Linux. It works
once; a used link opens the login page.

```console
$ bakalari web-login --module Dokumenty
https://skola.bakalari.cz/api/3/login/Hc8sV2nQ5mKx0pZ7?returnUrl=next/dokumentyPrehled.aspx
bakalari: warning: the link logs anyone who opens it in to the Bakaláři web as you; it works once, so do not share it
```

### `web-modules`

Lists the pages of the Bakaláři web that the official app links to (`GET /api/3/webmodule`): the name and the URL
relative to the school's address, separated by a tab, and the dashboard. `--json` prints JSON instead of text.

```text
bakalari web-modules [--json]
```

```console
$ bakalari web-modules
Ankety  next/ankety.aspx
Dokumenty       next/dokumentyPrehled.aspx
(dashboard)     next/dash.aspx
```

### `at-school`

Tells whether the school's access system registers the student at school now (`GET /api/3/user/student-at-school`):
`at school` or `not at school` (`--json`: `true` or `false`).

```text
bakalari at-school [--json]
```

HTTP 403 hint: the AccessSystem module (right CanShowStudentPresentAtSchool) is not enabled for the account.

```console
$ bakalari at-school
at school
```

## Timetable and events

### `timetable`

Prints the actual timetable of a week with its changes, or the permanent timetable; with `--class` the timetable of a
whole class with all its groups.

```text
bakalari timetable [--date DATE | --week WEEK | --permanent] [--day DAY] [--class [ID]] [--details] [--json]
```

| Option | Meaning |
|---|---|
| `--date DATE` | A day of the wanted week (default: today). |
| `--week WEEK` | Weeks from the current one, e.g. `1` = next week, `-1` = last week. |
| `--permanent` | The permanent (regular) timetable; a lesson of some weeks only lists its week cycles. |
| `--day DAY` | Only the lessons of this day, each line with its date and without the title. The day must be in the week the command fetches: add `--date` or `--week` for a day outside the current week. |
| `--class [ID]` | The timetable of a whole class (default: the account's own class, which takes one more request). Verified for the account's own class; another class may be refused. |
| `--details` | Also print the themes, notices and homeworks under each lesson. |
| `--json` | Print JSON instead of text (with `--day`, a list of flat lesson objects). |

Each day has a summary line (date, Czech weekday, day type, the name of a holiday, the number of lessons) followed by
one line per lesson: the lesson number and time, the subject, teacher, room and groups, and a change in brackets
(its type and description). An event that replaces a lesson shows only its change.

```console
$ bakalari timetable --date 2026-10-15
Actual timetable, week 2026-10-12 - 2026-10-18
2026-10-12 po WorkDay: 2 lesson(s)
     1.  8:00-8:45  Třídnická hodina | 1.A [Absence: Třídnická hodina: Nováková Jana]
     2.  8:55-9:40  Český jazyk a literatura | Mgr. Jana Nováková | 205 | 1.A Chl
2026-10-13 út WorkDay: 1 lesson(s)
     1.  8:00-8:45  Matematika | RNDr. Petr Dvořák | 105 | 1.A [RoomChanged: Změna učebny: 105]
2026-10-14 st Holiday (podzimní prázdniny): 0 lesson(s)
$ bakalari timetable --date 2026-10-15 --day 2026-10-13
2026-10-13  1.  8:00-8:45  Matematika | RNDr. Petr Dvořák | 105 | 1.A [RoomChanged: Změna učebny: 105]
$ bakalari timetable --class 1B --details --date 2026-10-19
Class timetable 1.B, week 2026-10-19 - 2026-10-25
2026-10-19 po WorkDay: 4 lesson(s)
     1.  8:00-8:45  Tělesná výchova | Bc. Tomáš Malý | TV1 | 1.B Chl
        theme: Atletika
     1.  8:00-8:45  Tělesná výchova | Mgr. Lucie Bílá | TV2 | 1.B Dív
        theme: Gymnastika
     2.  8:55-9:40  Matematika | Mgr. Eva Horáková | 031 | 1.B
        theme: Lineární rovnice
        notice: Přineste si kalkulačku.
        homework: Pracovní sešit str. 12, cvičení 3 a 4
     3. 10:00-10:45 Fyzika | Mgr. Karel Veselý | 031 | 1.B [Substitution: Suplování: Veselý Karel]
2026-10-20 út WorkDay: 3 lesson(s)
     0.  7:10-7:55  Matematika | Mgr. Eva Horáková | 031 | 1.B [Added: Přidáno do rozvrhu: M, Horáková Eva, 031]
     1.  8:00-8:45  Exkurze | 1.B [Canceled: Exkurze: Technické muzeum]
     2.  8:55-9:40  Exkurze | 1.B [Canceled: Exkurze: Technické muzeum]
2026-10-21 st DirectorDay (Ředitelské volno): 0 lesson(s)
```

### `substitutions`

Prints the changes of the timetable (substitutions, cancellations, room changes, ...) for 14 days from Monday of this
week or from `--since` (`GET /api/3/substitutions`).

```text
bakalari substitutions [--since DATE | --day DATE] [--json]
```

| Option | Meaning |
|---|---|
| `--since DATE` | The first day of the 14 days. |
| `--day DATE` | Only the changes of this day. |
| `--json` | Print JSON instead of text. |

Each line has the date, the lessons and their time, the change type with its description, and the class or group,
subject and room. HTTP 403 means that the Substitutions module is not enabled.

```console
$ bakalari substitutions
Substitutions 2026-10-12 - 2026-10-26
2026-10-12 1. hod (8:00 - 8:45) Absence: Třídnická hodina: Horáková Eva
2026-10-14 3. hod (10:00 - 10:45) Substitution: Suplování: Veselý Karel | 1.B, F, 031
2026-10-14 4. hod (10:55 - 11:40) RoomChanged: Změna učebny: 105 | AjS2, Aj, 105
2026-10-16 1. - 3. hod (8:00 - 10:45) Canceled: Exkurze
2026-10-20 6. hod (12:45 - 13:30) Removed | Dív, Tv, 102
2026-10-21 7. hod (13:35 - 14:20) Added: Přidáno do rozvrhu: M, Horáková Eva, 031 | 1.B, M, 031
$ bakalari substitutions --day 2026-10-14
Substitutions on 2026-10-14
3. hod (10:00 - 10:45) Substitution: Suplování: Veselý Karel | 1.B, F, 031
4. hod (10:55 - 11:40) RoomChanged: Změna učebny: 105 | AjS2, Aj, 105
```

### `events`

Lists the school's events (trips, exams, parents' evenings, ...) of the school year.

```text
bakalari events [--my | --public] [--since DATE] [--details] [--json]
```

| Option | Meaning |
|---|---|
| `--my` | Only the account's own events. |
| `--public` | Only the public events. |
| `--since DATE` | Only the events from `DATE` on. |
| `--details` | Also print the descriptions and notes. |
| `--json` | Print JSON instead of text. |

One line per event in the server's order: its time (whole-day events as their first and last date), the title, the
type in brackets, and the classes and rooms.

```console
$ bakalari events --details
2026-10-20 08:00-12:30 Exkurze do hvězdárny [školní akce] | 2.B (celá)
    Sraz v 7:40 před školou.
    S sebou svačinu a pití.
2027-01-11..2027-01-13 Lyžařský výcvikový kurz [kurz] | 1.A (celá), 1.B (celá)
2027-02-12 19:00 - 2027-02-13 01:30 Školní ples [společenská akce] | TV1
    Vstupenky prodává kancelář školy.
    note: Pořádá spolek rodičů.
2026-11-05 16:00-18:00 Konzultace s rodiči [konzultace] | 2.B (celá) | 105
    Individuální konzultace podle rozpisu.
```

## Marks

### `marks`

Prints the marks of the school year per subject with the averages (`GET /api/3/marks`).

```text
bakalari marks [--subject KEY] [--new] [--unconfirmed] [--since DATE] [--count-new] [--json]
```

| Option | Meaning |
|---|---|
| `--subject KEY` | Only the subject with this id, abbreviation or name (compared ignoring case); an unknown subject exits with status 2 and lists the subjects. |
| `--new` | Only the marks flagged new. |
| `--unconfirmed` | Only the marks waiting for a parent's confirmation. |
| `--since DATE` | Only the marks from `DATE` on. |
| `--count-new` | Print the server's counter of new marks; it is often 0, and `--new` lists the new marks. It takes no other option. |
| `--json` | Print JSON instead of text. |

Each subject has a summary line with its average, number of marks and temporary mark (when the school sets one),
followed by one line per mark: the date, the mark (points as `42/50`, without a weight), the weight, the caption and
type, a verbal evaluation after ` - `, and the flags `new` and `unconfirmed`. The text output shows no mark ids; take
them from `--json`. `--new` and `--unconfirmed` leave out the subjects without such marks, and together they keep the
marks that are both.

```console
$ bakalari marks
ČJL Český jazyk a literatura: average 2,57, 3 mark(s)
    2026-09-14  1       weight 2  Diktát 1: Vyjmenovaná slova po B (diktát)
    2026-10-05  3-      weight 4  Slohová práce (písemná práce) [new, unconfirmed]
    2026-10-08  2       weight 1  Interpunkce (ústní zkoušení) - Pěkná práce, pozor na čárky. [unconfirmed]
M Matematika: average 1,50, 2 mark(s)
    2026-09-22  1-      weight 3  Zlomky: Sčítání zlomků (písemná práce)
    2026-10-01  N       weight 1  Test (test)
F Fyzika: average 0,67, 2 mark(s)
    2026-09-21  42/50             Kinematika: Pohyb rovnoměrný (test)
    2026-10-09  5/20              Laboratorní práce (laboratorní práce) [new, unconfirmed]
$ bakalari marks --subject M
M Matematika: average 1,50, 2 mark(s)
    2026-09-22  1-      weight 3  Zlomky: Sčítání zlomků (písemná práce)
    2026-10-01  N       weight 1  Test (test)
```

### `final-marks`

Prints the certificates of every term with their final marks (`GET /api/3/marks/final`), oldest first. `--json`
prints JSON instead of text.

```text
bakalari final-marks [--json]
```

```console
$ bakalari final-marks
2024/25 semester 2 (2025-06-27): prospěl s vyznamenáním, average 1.33, absent 31 h (0 unexcused)
    Chv Chování: 1
    ČJL Český jazyk a literatura: 2
    M Matematika: 1
2025/26 semester 1 (2026-01-29): prospěl, average 2.00, absent 12 h (2 unexcused)
    Chv Chování: 1
    ČJL Český jazyk a literatura: 3
    M Matematika: 2
```

### `measures`

Prints the pedagogical measures, praises and reprimands (`GET /api/3/marks/measures`). `--json` prints JSON instead
of text.

```text
bakalari measures [--json]
```

```console
$ bakalari measures
2025-12-18 pochvala třídního učitele: za reprezentaci školy v matematické olympiádě & ve sběru papíru (2025/26, semester 1)
2025-04-07 napomenutí třídního učitele: za opakované zapomínání pomůcek (2024/25, semester 2)
```

### `predict`

Computes the average of a subject with additional hypothetical marks on the server (`POST /api/3/marks/what-if`,
which changes nothing), e.g. `predict M 1:3 2-:5`.

```text
bakalari predict [--json] SUBJECT MARK:WEIGHT [MARK:WEIGHT ...]
```

| Argument or option | Meaning |
|---|---|
| `SUBJECT` | The subject's id, abbreviation or name. |
| `MARK:WEIGHT` | A hypothetical mark with its weight, e.g. `1:3` or `2-:5`; the weight is a whole number of at least 1. |
| `--json` | Print the predicted subject as JSON. |

The command fetches all marks of the school year (the server averages exactly the marks it is sent), checks the
marks against the ones the school uses (an unknown mark exits with status 2 and lists them) and then asks the server.
HTTP 403 hint: mark prediction is disabled for this subject, or the account lacks the right PredictMarks.

```console
$ bakalari predict ČJL 1:3 2-:1
ČJL Český jazyk a literatura: average 2,57, 3 mark(s)
Predicted average with 1 (weight 3), 2- (weight 1): 2,10
```

### `confirm-marks`

**Changes data on the server.** Confirms (signs) marks as a parent where the school asks for it
(`POST /api/3/marks/SetClassificationConfirmation`).

```text
bakalari confirm-marks [--all-unconfirmed] [ID ...]
```

| Argument or option | Meaning |
|---|---|
| `ID` | The id of a mark to confirm (repeatable; see `marks --unconfirmed --json` for the ids). |
| `--all-unconfirmed` | Confirm every mark that waits for it. |

Pass either ids or `--all-unconfirmed`. The command prints the confirmed marks, or `Nothing to confirm.` when no
mark waits (then no confirmation is sent) or the server had nothing to confirm (HTTP 204). HTTP 403 hint: the account
lacks the right CanConfirmClassification.

```console
$ bakalari confirm-marks --all-unconfirmed
Confirmed 3 mark(s):
    ČJL  2026-10-05  3-      weight 4  Slohová práce (písemná práce) [new]
    ČJL  2026-10-08  2       weight 1  Interpunkce (ústní zkoušení) - Pěkná práce, pozor na čárky.
    F    2026-10-09  5/20              Laboratorní práce (laboratorní práce) [new]
$ bakalari confirm-marks 'QX7K0A(2)C'
Nothing to confirm.
```

## Absence, subjects and homeworks

### `absence`

Prints the absence per subject with the school's threshold, and with `--days` per day (`GET /api/3/absence/student`).

```text
bakalari absence [--days] [--json]
```

| Option | Meaning |
|---|---|
| `--days` | Also list the days with absence. |
| `--json` | Print JSON instead of text. |

The threshold line appears when the school sets one; a subject whose share of missed lessons has reached it is marked
`[over the threshold]`. The per-subject lines need the right ShowAbsencePercentage. The last line sums the days.

```console
$ bakalari absence --days
Threshold: 25% of the lessons
Český jazyk a literatura: missed 5 of 20 lessons (25.0%), late 1 [over the threshold]
Matematika: missed 2 of 21 lessons (9.5%), left early 1
Fyzika: missed 3 of 8 lessons (37.5%), school activity 1, distance teaching 1 [over the threshold]
(no subject): missed 0 of 4 lessons (0.0%), school activity 2
2026-09-14: excused 5 (total 5)
2026-09-22: unsolved 2, unexcused 1, late 1 (total 4)
2026-10-06: left early 1, school activity 3, distance teaching 1 (total 5)
Total: unsolved 2, excused 5, unexcused 1, late 1, left early 1, school activity 3, distance teaching 1
```

### `subjects`

Lists the subjects with their teachers (`GET /api/3/subjects`), or with `--themes` the lesson themes of one subject
(`GET /api/3/subjects/themes/{id}`).

```text
bakalari subjects [--themes SUBJECT] [--json]
```

| Option | Meaning |
|---|---|
| `--themes SUBJECT` | The lesson themes of a subject (id, abbreviation or name). A key that matches no subject is sent as an id as given. |
| `--json` | Print JSON instead of text. |

The list has the id, the abbreviation, the name, the teacher and any contacts the school publishes. The themes have
the date, the lesson, its time, the lesson's number in the subject with the theme, and a note in parentheses.

```console
$ bakalari subjects
2   Čj  Český jazyk a literatura | Mgr. Jana Nováková
10  M   Matematika | Ing. Petr Svoboda
TV  TV  Tělesná výchova | Bc. Eva Dvořáková | eva.dvorakova@school.example | school phone +420 100 010 203 | mobile +420 100 040 506
$ bakalari subjects --themes Čj
Čj Český jazyk a literatura
2026-09-01  1. hod  8:00-8:45  1. Opakování učiva 6. ročníku
2026-09-03  3. hod  10:00-10:45  2. Slovní druhy
2026-10-13  2. hod  8:55-9:40  12. Diktát: vyjmenovaná slova po B
```

### `homeworks`

Lists the homeworks given or due in a period; the server's default is 14 days back to one day ahead
(`GET /api/3/homeworks`).

```text
bakalari homeworks [--since DATE] [--until DATE] [--open] [--count] [--json]
```

| Option | Meaning |
|---|---|
| `--since DATE` | The start of the period. |
| `--until DATE` | The end of the period. |
| `--open` | Only the homeworks that are not closed. |
| `--count` | Print the server's counter of open homeworks. It takes no other option. |
| `--json` | Print JSON instead of text. |

Each homework starts with its due date, subject, flags and id, followed by the text, the notice and the attachments.
The flags are `done` (the teacher's: handed in), `finished` (the student's own tick, see
[`homework-done`](#homework-done)), `closed` (no longer current) and `electronic` (handed in on the web). The id of an
attachment is what [`attachment`](#attachment) takes.

```console
$ bakalari homeworks
due 2026-10-07  Čj  [finished]  id HW0A1B2C3D
    Pracovní sešit str. 12, cvičení 3 a 4.
due 2026-10-15  M  [electronic]  id HW0A1B2C4E
    Vypracujte úlohy z přiloženého listu.
    Postup najdete na https://school.example/ukoly/zlomky
    attachment: zlomky.pdf (id 'UAB  3XYZQ', 48213 bytes, application/pdf)
    attachment: obrázek.jpg (id 'UAB  3XYZR', 0 bytes, image/jpeg)
due 2026-09-24  Čj  [done, finished, closed]  id HW0A1B2B9F
    Naučit se básničku nazpaměť.
$ bakalari homeworks --count
2
```

### `homework-done`

**Changes data on the server.** Ticks a homework as finished by the student (its `finished` flag; `done` is the
teacher's), or unticks it with `--undo` (`PUT /api/3/homeworks/{id}/student-done/{true|false}`). Pass the id exactly
as listed.

```text
bakalari homework-done [--undo] ID
```

| Argument or option | Meaning |
|---|---|
| `ID` | The homework id (see [`homeworks`](#homeworks)); quote an id with spaces. |
| `--undo` | Untick the homework. |

```console
$ bakalari homework-done HW0A1B2C4E
Marked homework HW0A1B2C4E as finished.
$ bakalari homework-done HW0A1B2C4E --undo
Marked homework HW0A1B2C4E as not finished.
```

## Komens messages

### `messages`

Lists the received messages, or the sent or noticeboard ones: id, date, sender, title and flags.

```text
bakalari messages [--sent | --noticeboard] [--since DATE] [--unread] [--count] [--json]
```

| Option | Meaning |
|---|---|
| `--sent` | The sent messages (with the recipient instead of the sender). |
| `--noticeboard` | The noticeboard. |
| `--since DATE` | Only the messages from `DATE` on. |
| `--unread` | Only the unread messages. |
| `--count` | Print the number of unread messages (the server's counter; with `--sent`, the number of sent messages). It takes no `--since` or `--unread`. |
| `--json` | Print JSON instead of text. |

The flags in brackets are `unread`, `to confirm` (the sender asks for a confirmation, see
[`confirm-message`](#confirm-message)), `hidden` and the number of attachments. Listing messages does not mark them as
read.

```console
$ bakalari messages
400101  2026-10-12 09:15  Mgr. Petra Ukázková: Třídní schůzky  [1 attachment]
400099  2026-10-05 14:02  Jan Vzorový (ředitelství): Souhlas s exkurzí  [unread, to confirm]
400087  2026-09-28 07:30  Ing. Tomáš Vzorník: Rozvrh  [hidden, 1 attachment]
$ bakalari messages --sent
400120  2026-10-14 07:41  to Mgr. Petra Ukázková: Dotaz k domácímu úkolu  [1 attachment]
400108  2026-10-10 18:20  to 2 recipient(s): omluvenka: Adam Příkladný, 6.B
$ bakalari messages --count
1
```

### `message`

Prints one message as plain text (or HTML) with its attachments. Reading does not mark it as read; `--mark-read`
does (that changes data on the server).

```text
bakalari message [--sent | --noticeboard] [--html] [--mark-read] [--json] ID
```

| Argument or option | Meaning |
|---|---|
| `ID` | The message id (see [`messages`](#messages)). |
| `--sent` | A sent message, with its recipients. |
| `--noticeboard` | A noticeboard message (found in the noticeboard list, which carries whole messages). |
| `--html` | Print the text as HTML. |
| `--mark-read` | **Changes data on the server.** Mark the message as read, when it is not read yet; not with `--sent`. A note on standard error says what happened. |
| `--json` | Print JSON instead of text (the text as HTML). |

The header has the title, the sender, the recipients of a sent message (with the time each one processed it), the
date, the message type and its life time (`ToRead` or `ToConfirm`), the period of an excuse, and the flags. The plain
text keeps paragraphs, line breaks and list items and puts link targets after their text.

```console
$ bakalari message 400095
Title: Sběr papíru
From: Jan Vzorový (ředitelství) (administrator)
Date: 2026-10-01 11:45
Type: OBECNA, ToRead

Ve středu proběhne sběr papíru.
Děkujeme.
$ bakalari message 400120 --sent
Title: Dotaz k domácímu úkolu
From: Eva Příkladná (parents)
To:
    Mgr. Petra Ukázková (teacher), processed 2026-10-14 07:41
    Ing. Tomáš Vzorník, Ph.D. (teacher)
Date: 2026-10-14 07:41
Type: OBECNA, ToRead

Dobrý den,
posílám lékařskou zprávu a prosím o zadání úkolu.
$ bakalari message 400099 --noticeboard --mark-read
Title: Souhlas s exkurzí
From: Jan Vzorový (ředitelství) (administrator)
Date: 2026-10-05 14:02
Type: OBECNA, ToConfirm
Flags: unread, to confirm

Prosíme o potvrzení účasti na exkurzi do planetária.
bakalari: marked message 400099 as read
```

### `message-types`

Lists the message types the account may send with their recipient types and recipients: the codes for
[`send-message`](#send-message).

```text
bakalari message-types [--reply-to ID] [--json]
```

| Option | Meaning |
|---|---|
| `--reply-to ID` | What a reply to the message `ID` allows (see [`reply`](#reply)). |
| `--json` | Print JSON instead of text. |

Each type shows its code, its name and what it offers (`title`, `confirmation`, `e-mail notification`). Below it are
its recipient types with their code, name, selection (`ONE` recipient, `MULTI` for one or more, `ZERO` when the
recipients are implied) and the copies they offer, and for `ONE` and `MULTI` the recipients with their codes.

```console
$ bakalari message-types
OBECNA  Obecná zpráva  [title, confirmation, e-mail notification]
    U  učitel  ONE  [copy for parent]
        UQX7K  Ukázková Petra, Mgr.
        T8M4W  Vzorník Tomáš, Ing., Ph.D.
        ' 9KX'  Zkušební Alena
    UV  učitelé - všichni  ZERO
    VS  vedení školy  MULTI  [copy for class teacher]
        RS  ředitel školy (default)
        ZR  zástupce ředitele
OMLUVENKA  Omluvení absence
    U  třídní učitel  ONE
        UQX7K  Ukázková Petra, Mgr. (default)
$ bakalari message-types --reply-to 400095
OBECNA  Obecná zpráva  [title, confirmation]
    OD  odesílateli  ZERO
```

### `send-message`

**Changes data on the server.** Sends a Komens message (`POST /api/3/komens/message`). The codes come from
[`message-types`](#message-types).

```text
bakalari send-message --type CODE --recipient-type CODE [--to CODE ...] [--title TEXT]
                      (--text TEXT | --text-file PATH) [--html] [--attach PATH ...]
                      [--require-confirmation] [--email-notification]
                      [--copy-for-class-teacher] [--copy-for-parent]
```

| Option | Meaning |
|---|---|
| `--type CODE` | The message type, e.g. `OBECNA`. |
| `--recipient-type CODE` | The recipient type, e.g. `U`. |
| `--to CODE` | A recipient (repeatable): its code, or its name; none for a recipient type with the selection `ZERO`. |
| `--title TEXT` | The title, for message types that have one. |
| `--text TEXT` | The text of the message. |
| `--text-file PATH` | Read the text from a UTF-8 file (`-` for standard input). |
| `--html` | The text is HTML (default: plain text, line breaks kept). |
| `--attach PATH` | Upload and attach a file (repeatable). |
| `--require-confirmation` | Ask the recipients to confirm the message. |
| `--email-notification` | Notify the recipients by e-mail. |
| `--copy-for-class-teacher` | Send a copy to the class teacher. |
| `--copy-for-parent` | Send a copy to the parent. |

Before it uploads or sends anything, the command checks the command line against the message types the account may
send: the type and the recipient type must exist, `ONE` takes exactly one `--to`, `MULTI` one or more and `ZERO`
none, `--title` is required for a type with a title and refused otherwise, the confirmation and e-mail options need a
type that offers them and the copy options a recipient type that offers them, and every `--attach` file must exist.
A violation exits with status 2, and no file and no message is sent. Plain text is HTML-escaped and its line breaks
become `<br>`, because message texts are HTML; `--html` sends the text unchanged. HTTP 403 hint: the account lacks
the right SendMessages (or SendAttachments).

```console
$ bakalari send-message --type OBECNA --recipient-type U --to UQX7K --title 'Dotaz k úkolu' --text 'Dobrý den, platí úkol z matematiky na pondělí? Děkuji, Bára Kocourková'
Sent the OBECNA message "Dotaz k úkolu" to Ukázková Petra, Mgr. (UQX7K).
$ echo 'Omlouvám Viléma z výuky 20. 10. kvůli návštěvě lékaře.' | bakalari send-message --type OMLUVENKA --recipient-type U --to UQX7K --text-file - --attach omluvenka.pdf
Sent the OMLUVENKA message to Ukázková Petra, Mgr. (UQX7K) with 1 attachment(s).
$ bakalari send-message --type OBECNA --recipient-type U --title T --text x
bakalari: error: the recipient type U needs --to CODE (see 'bakalari message-types')
```

### `reply`

**Changes data on the server.** Replies to a received message the way the server allows for it: the command reads
the message, uploads the `--attach` files, asks the server which reply types are allowed
(`GET /api/3/komens/message-types/reply/{id}`) and sends the reply with the first of them.

```text
bakalari reply [--title TEXT] (--text TEXT | --text-file PATH) [--html] [--attach PATH ...]
               [--require-confirmation] ID
```

| Argument or option | Meaning |
|---|---|
| `ID` | The id of the received message. |
| `--title TEXT` | The title (default: `Re: ` and the original title, when the reply type has a title). |
| `--text TEXT`, `--text-file PATH`, `--html`, `--attach PATH` | As for [`send-message`](#send-message). |
| `--require-confirmation` | Ask the recipient to confirm the reply. |

HTTP 403 hint: the account lacks the right SendMessages (or SendAttachments).

```console
$ bakalari reply 400095 --text 'Děkuji, přijdeme.'
Replied to message 400095 "Sběr papíru" from Jan Vzorový (ředitelství).
```

### `confirm-message`

**Changes data on the server.** Confirms that a message asking for it was read
(`PUT /api/3/komens/message/{id}/mark-as-confirmed`); [`messages`](#messages) flags such messages `to confirm`.

```text
bakalari confirm-message ID
```

HTTP 403 hint: the message does not ask for a confirmation.

```console
$ bakalari confirm-message 400099
Confirmed message 400099.
```

### `hide-message`

**Changes data on the server.** Hides a message, or shows it again with `--undo`
(`PUT /api/3/komens/message/{id}/mark-as-hidden` or `mark-as-unhidden`).

```text
bakalari hide-message [--undo] ID
```

| Argument or option | Meaning |
|---|---|
| `ID` | The message id. |
| `--undo` | Show the hidden message again. |

HTTP 403 hint: the message cannot be hidden.

```console
$ bakalari hide-message 400087
Hid message 400087.
$ bakalari hide-message 400087 --undo
Message 400087 is shown again.
```

### `delete-message`

**Changes data on the server.** Deletes a message that allows it (`DELETE /api/3/komens/message/{id}`).

```text
bakalari delete-message ID
```

HTTP 403 hint: the message cannot be deleted.

```console
$ bakalari delete-message 400087
Deleted message 400087.
```

### `attachment`

Downloads an attachment of a message or a homework into a file or directory and prints the path
(`GET /api/3/komens/attachment/{id}`). An existing file is never overwritten without `--force`.

```text
bakalari attachment [-o PATH] [--force] ID
```

| Argument or option | Meaning |
|---|---|
| `ID` | The attachment id (see [`message`](#message) and [`homeworks`](#homeworks)). |
| `-o PATH`, `--output PATH` | The file or the directory to save to (default: the current directory). |
| `--force` | Overwrite an existing file. |

In a directory the file gets the name the server sends, made safe (no directory parts, control characters or
Windows device names), or `attachment-ID`. An existing file or a missing directory exits with status 2. The same
endpoint serves message and homework attachments; the server lets users download attachments of their own messages
only, and an unknown id answers HTTP 500 (exit status 1).

```console
$ bakalari attachment 'UAB  3XYZQ' -o ~/Downloads
Saved /home/bara/Downloads/zlomky.pdf (48213 bytes, application/pdf).
$ bakalari attachment 'UAB  3XYZQ' -o ~/Downloads
bakalari: error: /home/bara/Downloads/zlomky.pdf already exists: pass --force to overwrite it
```

## GDPR and payments

### `consents`

Lists the GDPR consents of the account or, with `--child`, of its children. Answering a consent is possible on the
Bakaláři web only.

```text
bakalari consents [--child] [--count] [--json]
```

| Option | Meaning |
|---|---|
| `--child` | The consents of the children of a parent account. |
| `--count` | Print the number of new consents (of the account itself; not with `--child`). |
| `--json` | Print JSON instead of text. |

Each line has the state, the title, the validity and the answers the account may give.

```console
$ bakalari consents --child
Agreed  Pořizování fotografií žáka na školních akcích (from 2025-09-01, validity neomezenou) [can disagree]
Agreed  Zveřejnění jména žáka ve výsledcích soutěží (from 2025-09-01, validity 5 year(s)) [can disagree, can request revocation]
Agreed  Účast na preventivním programu (from 2026-09-01, validity 1 rok)
```

### `commissioners`

Lists the school's data protection officers with their contacts, or says that the school lists none. `--json`
prints JSON instead of text.

```text
bakalari commissioners [--json]
```

```console
$ bakalari commissioners
Mgr. Ludmila Pokorná | poverenec@skola.example | mobile +420 799 000 111 | https://poverenec.example | data box x7k2mpq
```

### `class-fund`

Prints the class fund balance and, with the options, its payments by month, how to pay into it (the IBAN and the QR
payment string) and the regular payments.

```text
bakalari class-fund [--payments] [--asc] [--search TEXT] [--info] [--regular] [--json]
```

| Option | Meaning |
|---|---|
| `--payments` | The income and expenses by month, newest first. |
| `--asc` | Oldest month first (implies `--payments`). |
| `--search TEXT` | Only the payments matching `TEXT` (implies `--payments`); an empty text exits with status 2. |
| `--info` | How to pay into the fund, with the IBAN and the QR string. |
| `--regular` | The summary of the regular payments (raw JSON). |
| `--json` | Print JSON instead of text: `summary`, and `payments`, `info` (with `iban` and `qr_payment`) and `regular` when asked for. |

The QR payment string is the Czech "QR Platba" (SPAYD) format that banking apps scan; draw it as a QR code with any
QR tool. It is not available when the account cannot be converted to an IBAN or a symbol is invalid. HTTP 403 hint:
the Payments module is not enabled for the school.

```console
$ bakalari class-fund --payments --info
Kolářová Eliška (2.B): balance 1250.50 CZK, spent -3870.25 CZK
Payments:
    2026-10  160.00 CZK
        2026-10-08      -90.00  Divadlo 2.B
        2026-10-02      250.00  Příjem z banky (Kolářová Eliška)
    2026-09  -49.50 CZK
        2026-09-21     -399.50  Pracovní sešit Fyzika 2
        2026-09-03      350.00  Příjem z banky (Kolářová Eliška)
    2026-08  0.00 CZK
Payment details:
    Instructions: Pro platbu do třídního fondu použijte níže uvedený bankovní účet, specifický a variabilní symbol.
    Account: 35-1234567899/0100
    IBAN: CZ59 0100 0000 3512 3456 7899
    Variable symbol: 2026001234
    Specific symbol: 2222
    Message: 2.B Kolářová Eliška třídní fond
    QR payment: SPD*1.0*ACC:CZ5901000000351234567899*CC:CZK*X-VS:2026001234*X-SS:2222*MSG:2.B Kolarova Eliska tridni fond
```

## Teacher accounts

These commands work for teacher accounts only. Other accounts get HTTP 403 `Some privilege is missing (IsTeacher)`,
and the command exits with status 1 and the hint "this is available to teacher accounts only":

```console
$ bakalari classbook
bakalari: error: GET /api/3/classbook answered HTTP 403 Forbidden: Some privilege is missing (IsTeacher).
bakalari: hint: this is available to teacher accounts only
```

### `classbook`

Prints the teacher's class-book records of a period, by default this week (`GET /api/3/classbook`).

```text
bakalari classbook [--since DATE] [--until DATE] [--json]
```

| Option | Meaning |
|---|---|
| `--since DATE` | The first day (default: Monday of this week, or six days before `--until`). |
| `--until DATE` | The last day (default: six days after the first, or Sunday of this week). |
| `--json` | Print JSON instead of text. |

Each day has a summary line, followed by one line per record: the lesson and its time, the subject, the groups, the
record's number in the subject with the theme, and a change in brackets. `--until` before `--since` exits with
status 2.

```console
$ bakalari classbook --since 2026-09-21
2026-09-21 po WorkDay: 3 record(s)
    1.  8:00 - 8:45  M   2.B               14. Pythagorova věta
                     Fy  1.A sk1, 1.B sk1  1. Ukázkové téma
                                           (no theme) [Suplování za: Fiktivní Oto]
2026-09-28 po Celebration (Den české státnosti): 0 record(s)
```

### `lesson-tags`

Lists the tags a teacher can attach to class-book records (`GET /api/3/classbook/lessonTags`): the id, the
abbreviation and the title. `--json` prints JSON instead of text.

```text
bakalari lesson-tags [--json]
```

```console
$ bakalari lesson-tags
T1     EC1  Projekt
'T 2'  EXK  Exkurze
T3     -    -
```

### `marking`

Lists the units (subject and group) the teacher gives marks in (`GET /api/3/marking/atoms`), or with `ATOM` the
students' marks of one unit (`GET /api/3/marking/marks/{id}`).

```text
bakalari marking [--json] [ATOM]
```

| Argument or option | Meaning |
|---|---|
| `ATOM` | The id of a marking unit. |
| `--json` | Print JSON instead of text. |

```console
$ bakalari marking
A1B2C3  2.B Matematika [M]
A1B2C4  1.A Fyzika sk1 [Fy] (disabled: Klasifikace je uzavřena)
'A[9]'  Seminář
$ bakalari marking A1B2C3
Pokusný Adam: 1, N (average 1,00)
Zkušební Bára Marie: 2- (average 2,50) [released]
```

## Raw access

### `api`

Sends a request to any endpoint with the account's token and prints the JSON answer (or the status for an empty
one), e.g. `api GET /api/3/marks -p from=2026-10-01`. A non-`GET` request may change data on the server.

```text
bakalari api [-p KEY=VALUE ...] [--form KEY=VALUE ... | --body JSON] [--no-auth] METHOD PATH
```

| Argument or option | Meaning |
|---|---|
| `METHOD` | The HTTP method: `GET`, `POST`, `PUT`, `DELETE`, `PATCH` (in any case). |
| `PATH` | The path below the school's address, e.g. `/api/3/marks`, sent as typed: percent-encode ids (a space is `%20`). A full URL is refused. |
| `-p KEY=VALUE`, `--param KEY=VALUE` | A query parameter (repeatable; a repeated key is sent several times). |
| `--form KEY=VALUE` | A form field of the body (repeatable). |
| `--body JSON` | A JSON body, sent exactly as typed (`null` works) with `Content-Type: application/json`; it must be valid JSON. |
| `--no-auth` | Send the request without a login (public endpoints). |

HTTP 200, 201, 202 and 204 count as success; any other status exits with status 1 and the server's message. A JSON
answer is printed as indented JSON, a text answer (HTML, XML, ...) decoded with its charset, a binary answer as a
line with its type and size, and an empty answer as its status (`HTTP 204 (no content)`).

```console
$ bakalari api GET /api/3/marks/count-new
2
$ bakalari api GET /api/3 --no-auth
{
  "ApiVersion": "3.52.1",
  "ApplicationVersion": "2.2.1009.7",
  "BaseUrl": "api/3"
}
$ bakalari api POST /api/3/komens/messages/received --form dateFrom=2026-10-01
{
  "Messages": []
}
```

## Endpoints without a command

The library wraps a few endpoints that have no command; `api` reaches them (and every endpoint in the
[endpoint coverage](endpoints.md) that has no typed method):

| Library method | With `api` |
|---|---|
| `available_api_versions()` | `bakalari api GET /api --no-auth` |
| `timetable_json(...)` | `bakalari api GET /api/3/timetable/actual -p date=2026-10-22` |
| `lesson_absence(lesson_id)`, `lesson_past(lesson_id)`, `lesson_students_timetable(lesson_id)` (teachers) | `bakalari api GET /api/3/lesson/LESSON_ID/absence` (or `/past`, `/studentsTimetable`) |
| `emergency_configuration()` (teachers) | `bakalari api GET /api/3/emergency/configuration` |
| `rating_templates()` (teachers) | `bakalari api GET /api/3/komens/rating-templates` |
| `save_classbook_record(record)` (teachers; changes data) | Use the library: `ClassBookRecord.request_body()` builds the body. |
| `register_notification(token)` (changes data) | `bakalari api POST /api/3/register-notification -p token=TOKEN --body null` |

The server expects the official app's push token for `register-notification`, so a third-party token receives no
notifications; poll `messages --count`, `marks --new` or `homeworks --count` instead, not more often than every few
minutes.
