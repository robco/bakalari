# Bakalari usage guide

[Project overview](../README.md) · [Library reference](library.md) · [CLI reference](cli.md) · [MCP guide](mcp.md)

## Contents

- [Installation](#installation) and [configuration](#configuration)
- [Quick start](#quick-start)
- [Command line](#command-line)
- [MCP server mode](#mcp-server-mode)
- [Authentication and sessions](#authentication-and-sessions)
- [Python usage](#guide)
- [Errors](#errors) and [troubleshooting](#troubleshooting)
- [API coverage](#endpoint-coverage) and [examples](#examples)
- [Privacy and safety](#privacy-and-safety)

## Česky

**bakalari** je neoficiální knihovna a nástroj pro příkazovou řádku v Pythonu (3.9 a novější) pro REST API v3
školního systému Bakaláři. Používá jen standardní knihovnu Pythonu, nemá žádné další závislosti a pokrývá všechny
známé moduly: rozvrh (i rozvrh celé třídy a veřejný rozvrh), suplování, známky (včetně výpočtu průměru s
hypotetickými známkami a potvrzování známek rodiči), absenci, předměty a probraná témata, domácí úkoly, zprávy
Komens (čtení, odesílání, odpovědi, přílohy), akce školy, souhlasy GDPR, třídní fond s QR platbou, profil
uživatele a vyhledání školy v adresáři škol.

```bash
pip install bakalari
export BAKALARI_URL=https://skola.bakalari.cz    # adresa webu Bakaláři vaší školy
export BAKALARI_USERNAME=...                     # stejné přihlašovací údaje jako na webu
export BAKALARI_PASSWORD=...
bakalari timetable                               # rozvrh na tento týden
bakalari marks --new                             # nové známky
bakalari schools Kocourkov                       # adresa školy podle obce (bez přihlášení)
```

Neznáte adresu své školy? Příkaz `bakalari schools <obec>` ji najde ve veřejném adresáři škol. Bakaláři počítají
neúspěšná přihlášení a ukazují je majiteli účtu, proto nezkoušejte hesla ani cizí účty. Projekt není nijak spojen
se společností BAKALÁŘI software s.r.o. Další dokumentace je v angličtině.

[Ukázky použití s AI asistentem](ai-examples.md) obsahují skutečné snímky konverzací a příklady dotazů v češtině
i angličtině: dnešní rozvrh, plán učení, podepisování známek a vyřizování školních zpráv.

## Features

| Area | What you get |
|---|---|
| [Account](#profile-and-modules) | The typed profile (user type, class, school, school year and semester, the students of a parent account), enabled modules and rights, presence at school, web modules, a one-time web login link |
| [Timetable](#timetable) | The actual week with its changes, the permanent timetable, the timetable of a whole class; lessons resolved into subjects, teachers, rooms, groups and week cycles |
| [Substitutions](#substitutions) | The changes of the timetable for two weeks, grouped by day |
| [Marks](#marks) | Marks and averages by subject, new and unconfirmed marks, final (certificate) marks, pedagogical measures, the what-if prediction of an average, confirming (signing) marks |
| [Absence](#absence) | Absence per day and per subject with the school's percentage threshold |
| [Subjects](#subjects-and-themes) | Subjects with their teachers and contacts, the class-book themes of a subject |
| [Homeworks](#homeworks) | Homeworks by date range, the open-homework counter, ticking a homework as finished, attachments |
| [Komens](#komens-messages) | Received, sent and noticeboard messages, details as HTML or plain text, unread counters, marking as read, confirming, hiding and deleting, message types and recipients, sending, replying, uploading and downloading attachments |
| [Events](#events) | The school's events, your own events and the public events |
| [GDPR](#gdpr) | Consents of the person and of a parent's children, the school's data protection officers |
| [Payments](#payments-class-fund) | The class fund balance and movements, the payment instructions with the IBAN and the Czech QR payment (SPAYD) string |
| [Teachers](#teacher-endpoints) | Class book, lesson tags, lesson attendance and history, marking atoms and sheets, emergency configuration |
| [Public pages](#public-timetable-no-login) | The public timetables of classes, teachers and rooms (no login) |
| [School directory](#school-directory-no-login) | Municipalities and schools of the official directory with their Bakaláři addresses (no login) |
| [Anything else](#raw-requests) | `request()`, `get_json()` and `post_json()` with the same token handling |

## Installation

Requires **Python 3.9 or newer**. The installed library and CLI have no third-party runtime dependencies.
Use a virtual environment to keep the installation separate from other Python projects.

**macOS / Linux (Bash or Zsh):**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install bakalari
```

**Windows (PowerShell):**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install bakalari
```

If PowerShell does not allow activation scripts, use `.\.venv\Scripts\python.exe -m pip install bakalari`
and `.\.venv\Scripts\python.exe -m bakalari` directly. After activation, the `python` and `bakalari` commands
below work in that environment. Activate it again when opening a new terminal.

**From source** (also use this before the first release is available on PyPI):

```bash
git clone https://github.com/robco/bakalari.git
cd bakalari
python -m pip install .
```

Both install the `bakalari` package and the `bakalari` command (`python -m bakalari` works too).

Check the installation without contacting a school:

```bash
python -m bakalari --version
python -m bakalari --help
```

`--version` prints the installed package version. The separate `bakalari version` command contacts your school
and prints its API version.

### Configuration

The client needs your school's Bakaláři address and the login of the Bakaláři web:

| Variable | Meaning |
|---|---|
| `BAKALARI_URL` | The address of the Bakaláři web, e.g. `https://skola.bakalari.cz` or `https://www.skola.cz/bakaweb`; a URL copied from the browser (`.../login`, `.../next/dash.aspx`) works too |
| `BAKALARI_USERNAME` | The username of the Bakaláři web |
| `BAKALARI_PASSWORD` | The password of the Bakaláři web |
| `BAKALARI_SESSION_FILE` | Optional CLI session file; lets later commands resume without the password variables |

Replace the example school address and login with your own. The environment variables belong to the current
terminal session; Python programs started there inherit them. A secret store or your IDE's private run
configuration can supply them too. Keep passwords out of source files and version control.

**Bash / Zsh:**

```bash
export BAKALARI_URL='https://skola.bakalari.cz'
export BAKALARI_USERNAME='your-username'
export BAKALARI_PASSWORD='your-password'
```

**PowerShell:**

```powershell
$env:BAKALARI_URL = 'https://skola.bakalari.cz'
$env:BAKALARI_USERNAME = 'your-username'
$env:BAKALARI_PASSWORD = 'your-password'
```

Don't know your school's address? Run `bakalari schools 'Praha'` (replace the municipality), then use the
address of your school from the results. This search needs no login. The school address must be its Bakaláři
installation, which can include a path such as `/bakaweb`, rather than the school's general website.

## Quick start

### On the command line

After [configuring the environment](#configuration), check which account and modules are available:

```bash
bakalari profile
bakalari modules --rights
```

Then try the information you need:

```bash
bakalari timetable                  # this week's timetable with its changes
bakalari timetable --week 1         # next week
bakalari marks --new                # new marks
bakalari messages --unread          # unread Komens messages
bakalari homeworks --open           # homeworks that are not closed yet
bakalari schools Kocourkov          # find a school's address (no login)
```

```text
Actual timetable, week 2026-10-12 - 2026-10-18
2026-10-12 po WorkDay: 2 lesson(s)
     1.  8:00-8:45  Třídnická hodina | 1.A [Absence: Třídnická hodina: Nováková Jana]
     2.  8:55-9:40  Český jazyk a literatura | Mgr. Jana Nováková | 205 | 1.A Chl
2026-10-13 út WorkDay: 1 lesson(s)
     1.  8:00-8:45  Matematika | RNDr. Petr Dvořák | 105 | 1.A [RoomChanged: Změna učebny: 105]
2026-10-14 st Holiday (podzimní prázdniny): 0 lesson(s)
```

The output above is illustrative; your dates, subjects and lessons come from your school. Use
`bakalari timetable --help` for command-specific options. The [command line guide](#command-line) below shows
saved sessions, exports, message workflows and every command.

### In Python

```python
from bakalari import BakalariClient

client = BakalariClient.from_env()       # BAKALARI_URL, BAKALARI_USERNAME, BAKALARI_PASSWORD

timetable = client.actual_timetable()    # logs in on the first request that needs a token
print(timetable.format())

for subject in client.marks().subjects:
    print(subject.format_summary())      # ČJL Český jazyk a literatura: average 2,57, 3 mark(s)

print(client.unread_messages_count(), "unread message(s)")
```

`from_env()` reads the login from other variables with `username_env=` and `password_env=` (e.g. the login of
another child), takes the address as `base_url=` instead of `BAKALARI_URL`, and passes any other keyword to the
constructor (`timeout=`, `retries=`, `on_session_update=`, ...). You can also pass everything directly:

```python
import os

client = BakalariClient(
    os.environ["BAKALARI_URL"], os.environ["BAKALARI_USERNAME"], os.environ["BAKALARI_PASSWORD"],
    timeout=10, retries=2,
)
```

The responses become dataclasses: `to_dict()` gives JSON-ready data and `raw` keeps the server's object. Ids are
kept exactly as sent (they may be space-padded, `" 2"`), display strings are trimmed, timestamps are
timezone-aware `datetime` objects with the server's offset and dates without a time are `datetime.date`. Methods
with a `validate` parameter check the payload's shape first and raise `BakalariContractError` listing every
problem; `validate=False` parses leniently. Details are in the
[library guide](https://github.com/robco/bakalari/blob/main/docs/library.md).

## Command line

<!-- cli:start -->
The `bakalari` command (also `python -m bakalari`) reads the school's address from `BAKALARI_URL` and the login from
`BAKALARI_USERNAME` and `BAKALARI_PASSWORD`. With `--session-file PATH` (or `BAKALARI_SESSION_FILE`) it keeps the
session in a file readable by you only (mode 0600), so later commands need no password while the refresh token is
valid. `version`, `schools` and `public-timetable` need no login.

```text
bakalari [global options] COMMAND [options]
```

Global options: `--base-url URL`, `--username-env NAME` and `--password-env NAME` (read the login from other
variables, e.g. another child's), `--session-file PATH`, `--timeout SECONDS` (30), `--retries N` (2: `GET`, `PUT` and
`DELETE` after a connection error or HTTP 502, 503 or 504), `-v` (log each request to standard error, never secrets)
and `--version`.

Put global options **before** the command: `bakalari --timeout 10 timetable`. Options belonging to the command
follow its name: `bakalari timetable --day today`. Run `bakalari --help` to browse commands and
`bakalari COMMAND --help` for a command's complete options. Unless labelled otherwise, the commands below work
in both Bash and PowerShell after configuration.

### Keep a session between commands

```bash
bakalari --session-file bakalari.session.json login
bakalari --session-file bakalari.session.json profile
bakalari --session-file bakalari.session.json timetable --day today
bakalari --session-file bakalari.session.json marks --new
```

The first command creates the session; the following ones can use it without the username and password
variables. The file also supplies the school address if `BAKALARI_URL` is unset. Reuse the same file path;
relative paths are resolved from your current directory. To avoid repeating the option, set
`BAKALARI_SESSION_FILE` with `export BAKALARI_SESSION_FILE='bakalari.session.json'` in Bash/Zsh, or
`$env:BAKALARI_SESSION_FILE = 'bakalari.session.json'` in PowerShell.

Treat this file like a password and keep it out of version control. Run
`bakalari --session-file bakalari.session.json logout` to delete it. If the refresh token expires, supply the
login variables again and run `login`. Do not run commands that share a session file concurrently: token
renewals can race. See [authentication and sessions](#authentication-and-sessions) for the token lifecycle.

### Everyday queries and exports

```bash
bakalari timetable --day tomorrow --details
bakalari timetable --week 1
bakalari timetable --permanent
bakalari substitutions --day today
bakalari marks --subject M
bakalari predict M 1:3 2-:5
bakalari absence --days
bakalari subjects --themes M
bakalari homeworks --open
bakalari events --my --since today
bakalari marks --json > marks.json
bakalari timetable --json > timetable.json
```

`M` is an example subject abbreviation; use the id, abbreviation or name shown by `subjects` or `marks`.
`predict` calculates a hypothetical average without changing the actual marks. Export commands write local
files, replacing files with the same names. JSON output includes the parsed fields, with dates as strings;
the [Python export example](#export-data-as-json-or-csv) also shows CSV output.

### Find a message and download its attachments

```bash
bakalari messages --unread
bakalari message 'MESSAGE_ID'
bakalari attachment 'ATTACHMENT_ID' -o ./
```

Replace `MESSAGE_ID` with an id from the first command, then `ATTACHMENT_ID` with one printed in the message's
detail. Keep quotes around ids containing spaces. Listing and opening messages does not mark them as read.
The download uses the server's sanitized file name in the current directory and refuses to overwrite an
existing file. Pass `--force` only to replace that file.

### Send a message or change a record

First inspect the account's available message types and recipient codes:

```bash
bakalari message-types
```

**Changes data:** each command below performs its named action immediately; there is no confirmation prompt.
They are independent examples. Replace all placeholder ids and the recipient code with values from your
account. For sending, `OBECNA` and `U` must be offered by `message-types` too.

```bash
bakalari send-message --type OBECNA --recipient-type U --to 'RECIPIENT_CODE' --title 'Dotaz' --text 'Dobrý den, mám dotaz k domácímu úkolu.'
bakalari reply 'MESSAGE_ID' --text 'Děkuji za zprávu.'
bakalari message 'MESSAGE_ID' --mark-read
bakalari confirm-marks 'MARK_ID'
bakalari homework-done 'HOMEWORK_ID'
```

Use `--text-file message.txt` instead of `--text` for a longer UTF-8 message, and `--attach document.pdf` to
include a local file. CLI message text is plain text by default and is escaped into HTML; use `--html` for
HTML you prepared yourself. To find ids, use `messages`, `marks --unconfirmed --json`, or `homeworks`.

### Use another child's login

Set additional credential variables, such as `BAKALARI_SECOND_USERNAME` and `BAKALARI_SECOND_PASSWORD`, using
the same syntax as in [configuration](#configuration), then select them explicitly:

```bash
bakalari --username-env BAKALARI_SECOND_USERNAME --password-env BAKALARI_SECOND_PASSWORD --session-file second-child.session.json profile
```

Keep a separate session file per account. Changing the credential variable names does not switch the account
inside an existing session file. Pass `--base-url` too if the other child attends a different school.

### All commands

| Command | What it does |
|---|---|
| `mcp [--allow-writes]` | Local MCP server for AI applications; 50 read tools and 11 optional write tools |
| `version` | The API version of the school's installation (no login) |
| `schools [QUERY]` | The school's Bakaláři address from the public directory, by municipality (no login) |
| `public-timetable (--list \| --class ID \| --teacher ID \| --room ID)` | The timetables the school publishes, `--permanent` or `--next` week (no login) |
| `login`, `logout` | Log in (or renew the session file) and print the user id, API version and token expiry; delete the session file |
| `profile` (`whoami`) | The account: type, name, class, school, school year and semester, the students of a parent account |
| `modules [--rights]` | The modules enabled for the account (and its rights) |
| `web-login`, `web-modules` | A one-time link that opens the Bakaláři web logged in (a credential); the web pages the app links to |
| `at-school` | Whether the school's access system registers the student at school now |
| `timetable` | The actual week with its changes (`--date`, `--week N`), `--permanent`, a whole class (`--class [ID]`), one day (`--day`), `--details` |
| `substitutions` | The changes of the timetable for 14 days (`--since`, `--day`) |
| `events` | The school's events (`--my`, `--public`, `--since`, `--details`) |
| `marks` | Marks and averages per subject (`--subject`, `--new`, `--unconfirmed`, `--since`, `--count-new`) |
| `final-marks`, `measures` | The certificate marks of every term; praises and reprimands |
| `predict SUBJECT MARK:WEIGHT ...` | The average with hypothetical marks, computed by the server, e.g. `predict M 1:3 2-:5` |
| `confirm-marks (ID ... \| --all-unconfirmed)` | Confirm (sign) marks as a parent (changes data) |
| `absence [--days]` | Absence per subject (and per day) with the school's threshold |
| `subjects [--themes SUBJECT]` | Subjects with their teachers; the lesson themes of one subject |
| `homeworks` | Homeworks (`--since`, `--until`, `--open`), or the number of open ones (`--count`) |
| `homework-done ID [--undo]` | Tick (or untick) a homework as finished (changes data) |
| `messages` | Received, `--sent` or `--noticeboard` messages with their flags (`--unread`, `--since`, `--count`) |
| `message ID` | One message as text (`--html`) with its attachments; `--mark-read` marks it as read (changes data) |
| `message-types` | The message types, recipient types and recipient codes for sending (`--reply-to ID`) |
| `send-message`, `reply ID` | Send a message or reply to one, with `--text`/`--text-file` and `--attach` (changes data) |
| `confirm-message ID`, `hide-message ID [--undo]`, `delete-message ID` | Confirm, hide (or show again) or delete a message (changes data) |
| `attachment ID [-o PATH] [--force]` | Download a message or homework attachment; never overwrites without `--force` |
| `consents [--child] [--count]`, `commissioners` | GDPR consents; the school's data protection officers |
| `class-fund` | The class fund balance, `--payments` by month, `--info` with the IBAN and the QR payment string, `--regular` |
| `classbook`, `lesson-tags`, `marking [ATOM]` | Teacher accounts: class-book records, lesson tags, marking units and their marks |
| `api METHOD PATH` | A raw request to any endpoint (`-p KEY=VALUE`, `--form`, `--body JSON`, `--no-auth`); prints the answer |

Most commands accept `--json` and then print JSON instead of text. Dates are `YYYY-MM-DD`, `today`, `yesterday` or
`tomorrow`. Commands marked "changes data" perform writes; a raw `api` request can also change data, depending on
the endpoint. Exit status: 0 success, 1 a Bakaláři API, connection or contract error (with a hint, e.g.
that the module is not enabled for the account), 2 a usage or configuration error, 130 interrupted. Errors go to
standard error as `bakalari: error: ...`; normal request diagnostics omit credentials and query strings, and
control characters in server texts are removed. `web-login` intentionally prints a credential-bearing link,
and raw `api` output can contain anything returned by the selected endpoint.

The [command line reference](https://github.com/robco/bakalari/blob/main/docs/cli.md) describes every command
and option with sample output, the session file, the exit status and the error hints.
<!-- cli:end -->

## MCP server mode

Use `bakalari mcp` to let an MCP-compatible AI application work with your school account. It provides **50 read
tools** for school lookup, profiles, timetables, substitutions, marks, absence, subjects, homework, Komens, events,
GDPR, payments and teacher endpoints. **11 additional write tools** are available with `--allow-writes`.
It runs locally over stdio, with Python 3.9+ and no additional runtime dependencies.

### Set up your account and connect a host

Install the package as described under [installation](#installation). When using this feature from a source
checkout, run `python -m pip install .` from the repository root in your virtual environment. Confirm that this
interpreter includes MCP mode:

```bash
python -m bakalari mcp --help
```

Set `BAKALARI_URL`, `BAKALARI_USERNAME` and `BAKALARI_PASSWORD` as shown under [configuration](#configuration),
then save a session and check the account before connecting your AI application:

```bash
bakalari --session-file /absolute/path/bakalari.session.json login
bakalari --session-file /absolute/path/bakalari.session.json profile
```

For hosts using an `mcpServers` JSON configuration, add this entry, replacing both absolute paths:

```json
{
  "mcpServers": {
    "bakalari": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["-m", "bakalari", "--session-file", "/absolute/path/bakalari.session.json", "mcp"]
    }
  }
}
```

The host launches the process and communicates through stdin/stdout. Use an absolute executable path: desktop
applications may not inherit your terminal's virtual environment or environment variables. On Windows use the
virtual environment's `Scripts\python.exe`; the [full guide](mcp.md#connect-an-mcp-host) includes a complete
Windows configuration. Restart or reconnect the host after changing its configuration.

A saved session lets the server resume without the password while its refresh token remains valid. It renews
and saves tokens automatically. Alternatively, supply `BAKALARI_URL`, `BAKALARI_USERNAME` and `BAKALARI_PASSWORD`
through the host's environment settings. `BAKALARI_SESSION_FILE` also selects a session file. Keep a separate
session file and host entry for each account; see [multiple accounts](mcp.md#use-multiple-accounts).

These commands start the same server:

```bash
bakalari --session-file /absolute/path/bakalari.session.json mcp
bakalari-mcp --session-file /absolute/path/bakalari.session.json
python -m bakalari.mcp --session-file /absolute/path/bakalari.session.json
```

When started manually, it waits quietly for MCP messages; it is not an interactive chat prompt. EOF stops it,
and Ctrl-C interrupts it. Tool discovery requires no login. School lookup requires no configuration; published
timetables and API-version tools need only a school URL. Private data requires an account.

### Everyday MCP workflows

Start by asking the assistant to check your profile and available modules. Then try:

| Ask your assistant | Tools and behavior |
|---|---|
| “Show tomorrow's lessons and substitutions.” | `actual_timetable`, `substitutions`; the assistant selects the requested day from the weekly results. |
| “Show my new marks and predict the average if I receive a 1 with weight 3.” | `marks`, `predict_marks`; prediction does not save grades. |
| “List unfinished homework due this week.” | `homeworks`; the assistant filters the returned dates and completion flags. |
| “Summarize unread messages without marking them read.” | `messages`, `message`; reading leaves messages unread. |
| “Show the class fund balance and payment instructions.” | `class_fund_summary`, `class_fund_payment_info`; no payment is initiated. |
| “Find schools in Praha and show a published class timetable.” | `find_schools`, then `public_timetable_targets` and `public_timetable` for the school configured by the operator. |

MCP tools use JSON arguments, not CLI flags. For example, `actual_timetable` takes
`{"date": "2026-10-19"}`, and `predict_marks` takes `{"subject": "MAT", "hypothetical": [["1", 3]]}`.
Replace sample dates and subject identifiers with your own. Dates must be `YYYY-MM-DD`; relative dates such as
`tomorrow` must be resolved by the assistant. The [usage guide](mcp.md#everyday-workflows) gives complete
sequences for reading data, sending messages, attachments and teacher records.

### Enable changes to school data

To expose write tools, append `--allow-writes` after `mcp` in the host's `args`, or run:

```bash
bakalari --session-file /absolute/path/bakalari.session.json mcp --allow-writes
```

This enables homework completion, mark confirmation, message read/confirmed/hidden states, deletion,
sending/replying, attachment uploads and class-book updates. Without the flag, write tools are absent and calls
to them are rejected. The flag enables the tools for the whole process; your MCP host controls approval of each
call. School permissions still apply. See the [write examples](mcp.md#write-workflows) before using them.

### Results, limits and troubleshooting

Successful tools return `{"data": ...}` as structured content and JSON text; older protocol versions receive
text only. Downloads and uploads transfer base64 content up to **512 KiB**, without accessing local files.
Input frames are limited to **1 MiB**, and serialized result data to **8 MiB**. Reading a message does not mark
it read, and error output omits credentials and upstream response bodies. Tool errors normally keep the process
running. Optional `-v` diagnostics go to stderr so stdout remains valid MCP traffic.

This is a **local stdio server**, without an HTTP/SSE endpoint. It implements tools using protocol versions
`2025-11-25`, `2025-06-18`, `2025-03-26` and `2024-11-05`; resources and prompts are not provided. Credentials,
one-time login links, arbitrary API requests and local filesystem access are not exposed as tools.

If the host cannot connect, first verify its executable path and `python -m bakalari mcp --help`. If tools are
visible but private calls fail, check the saved session and account with the regular `profile` command. A missing
write tool needs `--allow-writes` and a server restart. A permission error means the school/account lacks the
required module or role.

The [MCP user guide](mcp.md) includes step-by-step macOS/Linux and Windows setup, environment options,
multiple accounts, all 61 tools, read and write examples, attachment transfers, response examples,
[offline connection checks](mcp.md#verify-the-connection-without-a-school-account),
[troubleshooting](mcp.md#troubleshooting), and Python client/server examples.

## Authentication and sessions

The client logs in with the username and password of the Bakaláři web (the OAuth2 password grant on
`POST /api/login`, as the official mobile app does). It logs in on the first request that needs a token, renews the
access token (valid for an hour) with the refresh token shortly before it expires (`renew_margin`, 60 seconds),
and when the server refuses a token anyway, it renews it and retries the request once. When the refresh token
itself is rejected and the client knows the password, it logs in again. The client is safe to share between
threads.

```python
info = client.login()                    # an explicit login; returns the non-secret TokenInfo
print(info.user_id, info.api_version, info.expires_at)
print(client.token_info, client.is_authenticated)
```

**Resuming without the password.** `export_session()` returns a `SessionState` (the base URL, the tokens and
their metadata) and `import_session()` resumes it, also from its `to_dict()` data. A still valid access token is
reused, otherwise the next request renews the tokens with the refresh token. You can also start a client from a
refresh token alone:

```python
import json

from bakalari import BakalariClient, SessionState

state = client.export_session()                       # holds the tokens: a secret
saved = json.dumps(state.to_dict())

later = BakalariClient(state.base_url)                # no password needed
later.import_session(SessionState.from_dict(json.loads(saved)))
print(later.user_profile().full_name)                 # renews the tokens when needed

resumed = BakalariClient(state.base_url, refresh_token=state.refresh_token)
```

**Keeping the session up to date.** Every renewal returns a new refresh token, so store the newest one:
`on_session_update` is called with a fresh `SessionState` after every login and renewal.

```python
import json
import os
import tempfile
from pathlib import Path

from bakalari import BakalariClient, SessionState

session_path = Path.home() / ".bakalari.session.json"

def save_session(state: SessionState) -> None:
    # Write a new file, then replace the old session atomically. Mode 0600 on POSIX.
    descriptor, temporary = tempfile.mkstemp(dir=session_path.parent, prefix=".bakalari-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(state.to_dict(), file)
        os.replace(temporary, session_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

client = BakalariClient.from_env(on_session_update=save_session)
client.user_profile()                            # triggers login and saves the session
```

[examples/persistent_session.py](https://github.com/robco/bakalari/blob/main/examples/persistent_session.py)
does this completely: it loads the file, replaces it atomically with mode 0600 and works without the password
variables while the refresh token is valid. The command line has the same built in: with `--session-file PATH` (or
`BAKALARI_SESSION_FILE`) every command loads the session first and saves it at every login and renewal,
`bakalari login` creates it and `bakalari logout` deletes it. Both write the same `SessionState.to_dict()` JSON.

**Security notes**

- **Failed logins are shown to the account owner.** Bakaláři counts failed logins per account and shows them at
  the next web login. Never try passwords, never use someone else's account, and never test error handling with a
  real username and a wrong password (use a random, unknown username instead).
- **Tokens are secrets.** The access token is valid for an hour; the refresh token keeps giving access to the
  account until it goes unused for about a month (each renewal issues a new one). The client keeps both in private
  attributes, out of `repr()`, log records and exception messages, but `SessionState.to_dict()` contains them:
  store it like a password (file mode 0600), never commit it and never paste it into an issue.
- **Logout only forgets.** `logout()` (also called when a `with BakalariClient(...) as client:` block ends) forgets
  the tokens held by the client. The API has no revocation endpoint: an access token copied elsewhere stays valid
  until it expires within the hour, and a stored refresh token until it expires, so delete session files you no
  longer need.
- **The web login link is a credential.** `web_login_url()` opens the Bakaláři web logged in for anyone who has the
  link, until it is used.

## Guide

The examples use the `client` from the quick start. Each area needs its Bakaláři module (and sometimes a right) to
be enabled for the school and the account; otherwise the server answers HTTP 403 and the method raises
`BakalariPermissionError`. The [library guide](https://github.com/robco/bakalari/blob/main/docs/library.md)
lists every parameter and model field.

To run any reading example independently, put this at the top of a `.py` file, then run it with `python your_file.py`:

```python
from bakalari import BakalariClient

client = BakalariClient.from_env()
```

Each area below explains its reading operations first. Blocks explicitly marked **changes data** perform writes
when executed. Example ids and recipient codes are synthetic: obtain real values from the matching list methods
and keep any spaces in them. Lists can be empty, and optional fields can be `None`.

### Export data as JSON or CSV

Use `to_dict()` for JSON exports: it converts dates and nested models to JSON-ready values. For CSV, select the
columns you want. This example fetches marks once and creates two local files without changing the school data:

```python
import csv
import json
from pathlib import Path

marks = client.marks()
Path("marks.json").write_text(
    json.dumps(marks.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
)
with open("marks.csv", "w", newline="", encoding="utf-8") as file:
    writer = csv.writer(file)
    writer.writerow(["subject", "date", "mark", "weight", "caption"])
    for subject in marks.subjects:
        for mark in subject.marks:
            writer.writerow([subject.subject.name, mark.date, mark.text, mark.weight, mark.caption])
```

These files contain personal data and replace files with the same names. `raw` contains the server's original
fields for inspection; unlike `to_dict()`, it preserves the API's naming and representation.

### Timetable

```python
import datetime as dt

timetable = client.actual_timetable(dt.date.today())    # the week that contains the date
for day in timetable.days:
    print(day.format_summary())                    # 2026-10-12 po WorkDay: 2 lesson(s)
    for lesson in day.lessons:
        print("   ", lesson.format(with_date=False))

for lesson in timetable.changed_lessons:          # substitutions, cancellations, room changes, events
    print(lesson.date, lesson.hour.caption, lesson.title, lesson.change.change_type, lesson.change.description)

today = timetable.lessons_on(dt.date.today())
rows = [lesson.to_dict() for lesson in timetable.lessons]     # flat, JSON-ready dicts

permanent = client.permanent_timetable()          # the regular timetable; lessons list their week cycles
profile = client.user_profile()
if profile.school_class is not None:              # the timetable of the whole class, with every group
    whole_class = client.class_timetable(profile.school_class)
    next_week = client.class_timetable(profile.school_class, dt.date.today() + dt.timedelta(weeks=1))
```

A `Lesson` has `date`, `hour` (`caption`, `begin`, `end`), `subject`, `teacher` and `room` (each an `Item` with
`id`, `abbrev` and `name`, or `None`), `groups`, `cycles`, `theme`, `change`, `homeworks`, `notice` and `raw`. An
event that replaces a lesson (a class teacher's hour, an excursion) has no subject, only its `change`.

### Substitutions

```python
substitutions = client.substitutions()            # 14 days from Monday of this week; since= for another start
print(substitutions.start, substitutions.end)
for day, changes in substitutions.by_day().items():
    print(day)
    for change in changes:
        print("   ", change.format(with_date=False))   # 3. hod (10:00 - 10:45) Substitution: ... | 1.B, F, 031
```

Every entry is a `Change` (the model of the timetable's changes): `change_type` (Substitution, Canceled, Added,
Removed, RoomChanged, Absence), `description`, `day`, `hours`, `time` and `lesson_info` with the class, group,
subject and room abbreviations.

### Marks

```python
marks = client.marks()                            # since=date returns only the marks from that day on
for subject in marks.subjects:
    print(subject.subject.abbrev, subject.average_text, subject.average)    # "M", "1,50", 1.5
    for mark in subject.marks:
        print("   ", mark.format())               # 2026-10-05  3-      weight 4  Slohová práce [new, unconfirmed]

for mark in marks.new_marks:
    print(mark.date, mark.text, mark.weight, mark.caption, mark.numeric_value)

czech = marks.subject("ČJL")                      # by id, abbreviation or name; None if there is no such subject
if czech is not None and czech.prediction_enabled:
    prediction = client.predict_marks(czech, [("1", 3), ("2-", 5)])   # (mark, weight) pairs
    print(czech.average, "->", prediction.average)

for term in client.final_marks():                 # the certificates, oldest first
    print(term.format())
for measure in client.pedagogical_measures():     # praises and reprimands
    print(measure.format())
```

`new_marks_count()` is the server's own counter, which is often 0 even when marks are flagged new; use
`Marks.new_marks`. The prediction sends the subject's current marks with the hypothetical ones, so pass marks
fetched without `since`. For hypothetical point marks, send the request yourself with `what_if()` and
`Mark.what_if_entry()`.

**Changes data — confirm marks as a parent.** Inspect `marks.unconfirmed_marks` before running this block;
it signs all marks in that collection:

```python
if marks.unconfirmed_marks:
    confirmed = client.confirm_marks(marks.unconfirmed_marks)
    print("Confirmed:", confirmed)
```

### Absence

```python
absence = client.absence()
print(absence.percentage_threshold)               # e.g. 0.25 (25 %); 0 or None when the school sets none
for subject in absence.subjects:
    share = f"{subject.percentage:.0%}" if subject.percentage is not None else "-"
    print(subject.subject_name, subject.base, "of", subject.lessons_count, share, subject.over_threshold)
for day in absence.days:
    print(day.date, day.counts(), day.total)      # unsolved, ok, missed, late, soon, school, distance_teaching
print(absence.totals())
```

### Subjects and themes

```python
from bakalari.subjects import find_subject

subjects = client.subjects()
for subject in subjects:
    teacher = subject.teacher.name if subject.teacher else ""
    print(repr(subject.id), subject.abbrev, subject.name, teacher, subject.teacher_email)

maths = find_subject(subjects, "M")               # by id (padded or not), abbreviation or name
if maths is not None:
    themes = client.subject_themes(maths)          # or an id exactly as sent, e.g. " 2"
    for theme in themes.themes:
        print(theme.date, theme.hour_caption, theme.lesson_label, theme.theme, theme.note)
```

### Homeworks

```python
import datetime as dt
from pathlib import Path

today = dt.date.today()
homeworks = client.homeworks(since=today - dt.timedelta(days=14), until=today + dt.timedelta(days=7))
folder = Path("homework-attachments")
folder.mkdir(exist_ok=True)
for homework in homeworks:
    subject = homework.subject.abbrev if homework.subject else ""
    print(homework.end, subject, homework.content, "finished" if homework.finished else "")
    for attachment in homework.attachments:
        try:
            client.download_attachment(attachment).save(folder)    # see Komens below
        except FileExistsError:
            pass                                  # saved before; save() never overwrites by default

print(client.active_homeworks_count(), "open homework(s)")
```

`done` is the teacher's flag (handed in), `finished` the student's own tick and `closed` marks a homework that is
no longer current (`is_active` is its opposite). Without `since` and `until` the server returns 14 days back and
one day ahead. **Changes data — tick one selected homework as finished:** replace the example id with the id
of the assignment you have completed. To undo the tick instead, pass `done=False`.

```python
client.set_homework_done("HOMEWORK_ID")
```

### Komens messages

Lists and details:

```python
messages = client.messages()                      # "received" (default), "sent" or "noticeboard"; since=date
unread = [message for message in messages if not message.read]
print(client.unread_messages_count(), "unread")   # the server's counter; also "noticeboard"
for message in messages:
    print(message.id, message.sent, message.sender.name, message.title, len(message.attachments))

if messages:
    message = client.message(messages[0])         # the detail (an id works too); does NOT mark it as read
    print(message.title)
    print(message.plain_text)                     # message.text is the original HTML
else:
    print("No received messages.")
sent = client.messages("sent")
if sent:
    detail = client.message(sent[0], "sent")      # a sent message's detail adds its recipients
```

**Changes data — update a selected message.** Fetch the message you intend to update by its id first.
Marking it as read, confirming, hiding and deleting are separate operations; reading its detail alone changes
nothing. The calls below illustrate alternatives, rather than a required sequence:

```python
message = client.message("MESSAGE_ID")
client.mark_message_read(message)
if message.needs_confirmation:                    # can_confirm and not confirmed yet
    client.confirm_message(message)
```

Use `client.hide_message(message)` when `message.can_hide` is true (`unhide_message()` restores visibility),
or `client.delete_message(message)` when `message.can_delete` is true, only when you intend that action.

Attachments of messages (and of homeworks) download with `download_attachment()`. `save()` writes into a
directory under a sanitized file name and never overwrites an existing file unless you pass `overwrite=True`:

```python
from pathlib import Path

folder = Path("komens-attachments")
folder.mkdir(exist_ok=True)
if messages:
    message = client.message(messages[0])
    for attachment in message.attachments:       # AttachmentInfo: id, name, content_type, size
        file = client.download_attachment(attachment)  # filename, content_type, content (bytes)
        try:
            path = file.save(folder)
            print(path, file.size)
        except FileExistsError:
            print("Already downloaded:", file.filename)
```

Sending (right `SendMessages`) takes the codes from `message_types()`:

```python
types = client.message_types()
for message_type in types.types:                  # OBECNA (a general message), OMLUVENKA (an excuse), ...
    print(message_type.code, message_type.name)
    for recipient_type in message_type.recipient_types:     # ONE, MULTI or ZERO recipients to choose
        print("   ", recipient_type.code, recipient_type.name, recipient_type.selection,
              [recipient.code for recipient in recipient_type.recipients])
```

**Changes data — upload and send.** Replace the example codes with values listed above and use an existing
local attachment. The library accepts HTML as the message body; escape user-provided plain text with
`html.escape()` before including it in HTML. Leave out the upload and `attachments` argument if no file is needed.

```python
attachment_id = client.upload_attachment("omluvenka.pdf")  # right SendAttachments; a path, bytes or a file object
client.send_message(
    message_type="OBECNA",                        # MessageType.code
    recipient_type="U",                           # RecipientType.code
    recipients=["UQX7K"],                         # Recipient.code values; none for the selection ZERO
    title="Absence",
    text="<p>Dobrý den, ...</p>",                 # HTML, as the web editor writes it
    attachments=[attachment_id],
)
```

**Changes data — reply to a selected received message:**

```python
message = client.message("MESSAGE_ID")
client.reply_to_message(message, "<p>Děkuji, beru na vědomí.</p>")
```

### Events

```python
import datetime as dt

for event in client.events(since=dt.date.today()):     # scope="my" or "public"; without since the whole year
    kind = event.event_type.name if event.event_type else ""
    classes = ", ".join(item.abbrev for item in event.classes)
    print(event.start, event.end, event.whole_day, event.title, kind, classes)
```

An event lists its `times` (one `EventTime` per day), `dates`, `classes`, `teachers`, `rooms` and `students`.

### GDPR

```python
for consent in client.consents():                 # child_consents() for the children of a parent account
    print(consent.title, consent.state, consent.valid_from, consent.valid_to, consent.can_agree)
for officer in client.gdpr_commissioners():       # the school's data protection officers
    print(officer.name, officer.email, officer.phone, officer.data_box)
print(client.new_consents_count())
```

Answering a consent is not supported: its request is not documented (see the endpoint coverage).

### Payments (class fund)

```python
summary = client.class_fund_summary()
print(summary.student_name_with_class, summary.balance, summary.spent)

for month in client.class_fund_payments():        # newest first; sort="asc", search="divadlo"
    print(month.month, month.balance)
    for item in month.items:
        print(f"    {item.date} {item.amount:+.2f} {item.description}")

info = client.class_fund_payment_info()
print(info.instructions)
print(info.bank_account, info.formatted_iban, info.variable_symbol, info.specific_symbol)
print(info.qr_payment())                          # SPD*1.0*ACC:CZ...*CC:CZK*X-VS:...*X-SS:...*MSG:...
print(info.qr_payment(amount=500))                # SPD*1.0*ACC:CZ...*AM:500.00*CC:CZK*...: your own amount
```

`qr_payment()` returns the Czech "QR Platba" (SPAYD) string that banking apps scan; draw it as a QR code with any
QR library. It returns `None` when the bank account cannot be converted to an IBAN.

### Profile and modules

```python
profile = client.user_profile()
print(profile.user_type, profile.user_type_text, profile.full_name, profile.school_name)
print(profile.school_class.abbrev if profile.school_class else "")
if profile.school_year is not None:
    print(profile.school_year.name, profile.school_year.start, profile.school_year.end)
if profile.semester is not None:
    print(profile.semester.id, profile.semester.start, profile.semester.end)
for student in profile.students:                  # the students of a parent account
    print(student.full_name, student.school_class)
print(profile.module_names)                       # ["Komens", "Absence", "Events", "Marks", ...]
print(profile.has_right("Marks", "PredictMarks"), profile.rights_of("Komens"))
print(client.enabled_modules())
print(client.student_at_school())                 # needs the AccessSystem module
```

A parent with several children has one login per child; `from_env(username_env=..., password_env=...)` reads
another child's login from other variables.

### Web login link

```python
url = client.web_login_url()                      # opens the Bakaláři dashboard logged in; works once
web = client.web_modules()
for module in web.modules:                        # documents, teaching resources, ...
    print(module.name, module.url)
if web.modules:
    documents = client.web_login_url(web.modules[0].url)
```

Treat the link like a password until it is used: anyone who opens it is logged in.

### Public timetable (no login)

```python
from bakalari import BakalariClient

school = BakalariClient("https://skola.bakalari.cz")     # no username or password needed
targets = school.public_timetable_targets()
print([target.name for target in targets.classes], len(targets.teachers), len(targets.rooms))
target = targets.find("1.A", "class")             # by id or name, ignoring case and spaces
if target is not None:
    timetable = school.public_timetable("class", target, week="next")    # "actual", "permanent" or "next"
    print(timetable.format())
    print(school.public_timetable_url("class", target))
```

Schools choose what they publish; a timetable they do not publish raises `BakalariPermissionError`.
`bakalari.public_timetable.parse_public_timetable()` and `parse_public_targets()` parse saved pages offline.

### School directory (no login)

```python
from bakalari.schools import SchoolDirectory

directory = SchoolDirectory()
for school in directory.find("Kocourkov"):        # ignores case, diacritics and spacing around dashes
    print(school.name, school.base_url)           # pass base_url to BakalariClient
municipalities = directory.municipalities()       # names with their number of schools
schools = directory.schools("Kocourkov")
```

### Teacher endpoints

Teacher accounts only; other accounts get `BakalariPermissionError` (`Some privilege is missing (IsTeacher)`).

```python
import datetime as dt

today = dt.date.today()
monday = today - dt.timedelta(days=today.weekday())
book = client.classbook(monday, monday + dt.timedelta(days=4))
for record in book.records:
    print(repr(record.lesson_id), record.date, record.hour_caption, record.subject, record.label, record.theme)

tags = client.lesson_tags()
if book.records:
    record = book.records[0]
    past = client.lesson_past(record.lesson_id)   # the last theme and the label for the next record
    attendance = client.lesson_absence(record.lesson_id)   # raw JSON

for atom in client.marking_atoms():               # the subjects and groups you give marks in
    sheet = client.marking_marks(atom.id)
    for student in sheet.students:
        print(student.name, [mark.mark_value for mark in sheet.marks_of(student)])
```

**Changes data — save a class-book record.** Select the intended lesson by its id from the records printed
above. No write occurs if the selected id is absent:

```python
record = next((item for item in book.records if item.lesson_id == "LESSON_ID"), None)
if record is not None:
    past = client.lesson_past(record.lesson_id)
    body = record.request_body(theme="Lineární rovnice", label=record.label or past.next_label)
    saved = client.save_classbook_record(body)
```

### Raw requests

`request()`, `get_json()` and `post_json()` reach any endpoint with the same token handling, for endpoints without
a typed method or the full payload of one that has it:

```python
payload = client.get_json("/api/3/marks", {"from": "2026-10-01"})   # the decoded JSON; logs in as needed
response = client.request("GET", "/api/3/komens/messages/received/unread")
print(response.status, response.content_type, response.json())
versions = client.get_json("/api", authorized=False)                # a public endpoint, no login
answer = client.request("POST", "/api/3/komens/messages/sent", form={}, expected_status=None)  # any status
print(answer.status, answer.text[:80])
```

`params` become the query string, `form` a form body, `json_body` a JSON body and `data` raw bytes (with its
`Content-Type` in `headers`). A status other than `expected_status` (200 by default; a collection of statuses or
`None` for any) raises the matching error. Percent-encode ids in paths with `urllib.parse.quote(id, safe="")`.

## Errors

The library's API, connection, configuration and response-validation errors derive from `BakalariError`:

| Exception | Raised when | Notable attributes |
|---|---|---|
| `BakalariError` | The base class; raised itself for a few client-side conditions, e.g. a homework the server refused to tick, no session to export or no way to reply to a message | |
| `BakalariConfigError` | No address or login (an unset environment variable), an invalid session or a session of another school | |
| `BakalariConnectionError` | The server cannot be reached (DNS, TLS, refused connection, timeout) | |
| `BakalariHTTPError` | The server answered with an unexpected HTTP status | `method`, `path`, `status`, `expected`, `body`, `message` |
| `BakalariAuthError` (a `BakalariHTTPError`) | The login or the refresh token was rejected (HTTP 400 `invalid_grant`), or a token was refused (HTTP 401) | as above |
| `BakalariPermissionError` (a `BakalariHTTPError`) | HTTP 403: the module or right is not enabled for the account, a teacher-only endpoint, a public timetable the school does not publish | as above |
| `BakalariNotFoundError` (a `BakalariHTTPError`) | HTTP 404: an unknown endpoint or object | as above |
| `BakalariContractError` | The response is not JSON or does not have the expected structure | `problems` (every violation) |
| `TimetableContractError` (a `BakalariContractError`) | The timetable payload does not have the expected structure | `problems` |

Wrong arguments raise `ValueError` or `TypeError` before any request (an empty id, an unknown folder or scope,
an empty search text), and `AttachmentFile.save()` raises `FileExistsError` instead of overwriting.

```python
from bakalari import BakalariClient, BakalariConfigError, BakalariError, BakalariPermissionError

try:
    client = BakalariClient.from_env(timeout=10, retries=2)
    summary = client.class_fund_summary()
    print(summary.balance)
except BakalariConfigError as error:
    print("Check the environment variables:", error)
except BakalariPermissionError as error:
    print("The Payments module is not enabled for this account:", error.message)
except BakalariError as error:
    print("Bakaláři error:", error)
```

## Troubleshooting

| Symptom | What to check or do |
|---|---|
| `bakalari` is not found | Activate the environment where you installed the package, or use `python -m bakalari`. On Windows without activation, use `.\.venv\Scripts\python.exe -m bakalari`. |
| `No module named bakalari` | Install with `python -m pip install bakalari` using the same Python interpreter that runs your script. |
| Missing environment variables / exit status 2 | Set the variables in the terminal or IDE that starts the command. Use the Bash or PowerShell syntax above, or select an existing session with `--session-file`. |
| HTTP 400 `invalid_grant` or HTTP 401 | Check the school URL and your own login on the school's web page. A saved refresh token may have expired; supply the correct login variables and run `login` again. Avoid repeated attempts with a wrong password. |
| HTTP 403 | Run `bakalari modules --rights`. The module may be disabled or require another account type. Teacher commands need a teacher account; public timetables must be published by the school. |
| HTTP 404 | Check the school installation URL, endpoint and object id. Copy ids exactly, including spaces, and quote them in the shell. |
| HTTP 301/302/303/307/308 after a redirect | The default transport blocks HTTPS downgrades and redirects of authenticated or body-carrying requests to another origin. Check the final HTTPS installation address on your school's website and configure it directly. |
| Connection error or timeout | Check the address and network, then try `bakalari --timeout 60 timetable`. A private certificate authority can be configured with `ssl_context` in Python; see the library guide's transport section. |
| HTML instead of JSON / contract error | Check that the address is the Bakaláři installation, not the school's homepage or a login portal. The API may also have changed; inspect the reported contract problems before trying `validate=False`. That option cannot turn an HTML page into API data. |
| An empty list or a zero counter | Check dates, account and module availability. `new_marks_count()` may return 0 even when marks are flagged new; use `bakalari marks --new` or `client.marks().new_marks`. |
| A session belongs to another school or account | Use a separate session file for each account. `--base-url` and credential variables do not replace the account stored in an existing session. |
| An attachment already exists | Choose another output path or explicitly request replacement with CLI `--force` or Python `save(..., overwrite=True)`. |

For request diagnostics, run `bakalari -v timetable`. Logs go to standard error; they omit query strings and
bodies but can contain account and object ids. Redact personal data before sharing an error report.

## Endpoint coverage

The client knows the endpoints of the community documentation of API v3 and those found in other clients and in
captured traffic of the official app. 71 of them have typed methods: every read endpoint of the REST API whose
request is known and the documented write endpoints (marking messages read, confirmed or hidden, deleting, sending
and replying to messages, uploading attachments, confirming marks, ticking homeworks, saving class-book records,
registering a push token). 41 of these were verified against a live installation (API 3.52.1, a parent account) on
2026-10-15 and 23 more by route and method without changing any data; the other 7 (teacher endpoints, the one-time
web login token and the public timetable pages) follow the community documentation and other clients. 17 known
endpoints have no typed method, mostly because their requests are undocumented (Komens drafts, consent answers,
emergency alarms, teacher payment prescriptions, ...); they stay reachable through `request()`.

[docs/endpoints.md](https://github.com/robco/bakalari/blob/main/docs/endpoints.md) lists every known endpoint
with its client method, return type, verification status and how to call the ones that are not wrapped.

Teacher methods, payment payloads, published timetable pages and write operations have not all been exercised
against a live installation. Treat their documented verification status as part of the API's limitations;
offline tests verify request construction and parsing, but cannot establish what every school accepts.

### Migrating from the unreleased 1.0 code

Use `BAKALARI_USERNAME` and `BAKALARI_PASSWORD` instead of `BAK_PTRK_USERNAME` and `BAK_PTRK_PASSWORD`, and set
`BAKALARI_URL` or pass `base_url`: there is no default school. `user_profile()` now returns a typed
`UserProfile`; its `raw` field holds the server's object. The distribution is `bakalari`; the Python import
and command remain `bakalari`. See [CHANGELOG.md](https://github.com/robco/bakalari/blob/main/CHANGELOG.md) for the full list of changes.

## Examples

The [examples](https://github.com/robco/bakalari/blob/main/examples/README.md) directory contains complete scripts with argument parsing and error handling.
Clone the repository as shown under [installation](#installation), install the package, and run these commands
from the repository root after setting the login variables. The scripts are in the source checkout; installing
the wheel alone does not create an `examples/` directory.

| Script | Example command | Result |
|---|---|---|
| [Weekly timetable](https://github.com/robco/bakalari/blob/main/examples/weekly_timetable.py) | `python examples/weekly_timetable.py` | This week's lessons, changes and substitutions |
| [New marks](https://github.com/robco/bakalari/blob/main/examples/new_marks.py) | `python examples/new_marks.py --all` | Marks and subject averages; does not confirm marks |
| [Unread messages](https://github.com/robco/bakalari/blob/main/examples/unread_messages.py) | `python examples/unread_messages.py ./attachments` | Message text and downloaded attachments; leaves messages unread |
| [Homework calendar](https://github.com/robco/bakalari/blob/main/examples/homeworks_ics.py) | `python examples/homeworks_ics.py ./homeworks.ics` | A local calendar file for assignments due in the next seven days |
| [Persistent session](https://github.com/robco/bakalari/blob/main/examples/persistent_session.py) | `python examples/persistent_session.py` | Resumes and updates a session file without needing a password on every run |
| [Class fund](https://github.com/robco/bakalari/blob/main/examples/class_fund_qr.py) | `python examples/class_fund_qr.py 500` | Payment instructions and a QR payment string for 500 CZK; does not initiate payment |
| [School search](https://github.com/robco/bakalari/blob/main/examples/find_school.py) | `python examples/find_school.py Praha` | Matching schools and their Bakaláři addresses; no login needed |

Add `--help` to any script for its options. These scripts read school data; the attachment, calendar and session
examples also write local files.

## Development and tests

```bash
git clone https://github.com/robco/bakalari.git
cd bakalari
python -m pip install -e ".[dev]"
python -m pytest    # the offline suite: no network, no account
ruff check .
mypy bakalari                                          # mypy < 2, which still checks against Python 3.9
```

The offline suite drives the client through a scripted transport with synthetic fixtures. The live tests
(`tests/test_live.py`) are read-only and run only when `BAKALARI_URL`, `BAKALARI_USERNAME` and `BAKALARI_PASSWORD`
are set. See [CONTRIBUTING.md](https://github.com/robco/bakalari/blob/main/CONTRIBUTING.md) for the
conventions, the fixture privacy rule and the release process, and
[SECURITY.md](https://github.com/robco/bakalari/blob/main/SECURITY.md) for reporting vulnerabilities.

## Privacy and safety

- **The data is personal.** Marks, absences, messages and profiles are personal data of children and their
  families. Keep what you fetch on your own devices, protect files and logs, and don't paste output into public
  issues unless it is redacted.
- **No telemetry.** Requests go to the configured installation, or to the public school directory
  (`sluzby.bakalari.cz`) when you use `SchoolDirectory` or `bakalari schools`. Public requests can follow redirects
  to another host. The default transport keeps requests with credentials or a body on their original origin and
  rejects HTTPS downgrades.
- **Secrets stay out of output.** Passwords and tokens never appear in log records, `repr()` or exception
  messages; verbose logging (`bakalari -v`, or the `bakalari` logger) shows the method, path and status of each
  request and the logins and renewals, never query strings or bodies.
- **Nothing changes by accident.** Reading never marks a message as read. Only these methods change data on the
  server: `mark_message_read`, `confirm_message`, `hide_message`, `unhide_message`, `delete_message`,
  `send_message`, `reply_to_message`, `upload_attachment`, `confirm_marks`, `set_homework_done`,
  `save_classbook_record` and `register_notification` (plus whatever you send with `request()`). On the command
  line, commands marked "changes data" in `bakalari --help` and `message --mark-read` perform writes. Raw
  `api` requests can also call write endpoints.
- **Downloads are safe to save.** `AttachmentFile.save()` sanitizes the server's file name (no directory parts,
  control characters or Windows device names) and never overwrites a file without `overwrite=True`.
- **Be gentle with the school's server.** Poll the counters (`unread_messages_count()`, `active_homeworks_count()`)
  rather than whole lists, and not more often than every few minutes.

## Disclaimer

bakalari is an unofficial project. It is not affiliated with, endorsed by or supported by BAKALÁŘI software
s.r.o., the vendor of the Bakaláři school information system; "Bakaláři" is used only to name the system this
client talks to. The REST API is not officially documented and may change without notice. Use the client in line
with your school's rules and the terms of the Bakaláři service.

## License

[MIT](https://github.com/robco/bakalari/blob/main/LICENSE)
