# MCP server user guide

`bakalari mcp` makes this package available to an AI application that supports local Model Context Protocol
(MCP) servers. It exposes **50 read tools** and, with `--allow-writes`, **11 additional write tools**, using the
same Bakaláři client, account rights, token renewal and session persistence as the CLI. Python 3.9+ and the
standard library are sufficient; there is no MCP runtime dependency to install.

## Contents

- [Install and prepare an account](#install-and-prepare-an-account)
- [Start the server](#start-the-server) and [configuration reference](#configuration-reference)
- [Connect an MCP host](#connect-an-mcp-host) and [use multiple accounts](#use-multiple-accounts)
- [Everyday workflows](#everyday-workflows): school lookup, timetables, marks, homework, messages, payments and GDPR
- [Enable write tools](#enable-write-tools) and [write workflows](#write-workflows)
- [Tool catalog](#tool-catalog)
- [Results, errors and limits](#results-errors-and-limits)
- [Verify the connection without a school account](#verify-the-connection-without-a-school-account)
- [Troubleshooting](#troubleshooting)
- [Protocol and lifecycle](#protocol-and-lifecycle)
- [Python embedding and testing](#python-embedding-and-testing)

## Install and prepare an account

Use Python 3.9 or newer. From the root of a source checkout containing MCP mode, install into a virtual
environment. These commands install your checkout rather than assuming a previously published release includes
the feature. If installing a release instead, use `python -m pip install bakalari` and verify its MCP help.

### macOS and Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
python -m bakalari mcp --help
export BAKALARI_URL='https://skola.bakalari.cz'
export BAKALARI_USERNAME='your-username'
export BAKALARI_PASSWORD='your-password'
bakalari --session-file "$HOME/.config/bakalari/student.session.json" login
bakalari --session-file "$HOME/.config/bakalari/student.session.json" profile
```

Replace the sample URL and credentials with your own before running the login. The CLI creates the session
file's parent directory. `profile` confirms which account and school will be exposed to your assistant. The
session contains tokens, so keep it private. Once saved, you can remove the username/password variables from
this terminal with `unset BAKALARI_USERNAME BAKALARI_PASSWORD` and use the session path in the host configuration.

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m bakalari mcp --help
$env:BAKALARI_URL = 'https://skola.bakalari.cz'
$env:BAKALARI_USERNAME = 'your-username'
$env:BAKALARI_PASSWORD = 'your-password'
.\.venv\Scripts\python.exe -m bakalari --session-file "$env:LOCALAPPDATA\bakalari\student.session.json" login
.\.venv\Scripts\python.exe -m bakalari --session-file "$env:LOCALAPPDATA\bakalari\student.session.json" profile
```

This uses the virtual environment's interpreter directly and does not require PowerShell activation scripts.
After saving the session, `Remove-Item Env:BAKALARI_USERNAME, Env:BAKALARI_PASSWORD` removes these credentials from
the current PowerShell environment. POSIX mode 0600 does not apply on Windows; keep the file in your private user
profile with suitable filesystem permissions.

If you do not know the school address, `python -m bakalari schools Praha` searches the public directory without
logging in. Use the returned Bakaláři installation URL, which can include a path such as `/bakaweb`.

## Start the server

Install `bakalari` in a virtual environment as described in the [README](../README.md#installation).
Configure `BAKALARI_URL`, `BAKALARI_USERNAME` and `BAKALARI_PASSWORD` in the environment of the MCP server process,
or create a saved session first:

```bash
bakalari --session-file /absolute/path/bakalari.session.json login
bakalari --session-file /absolute/path/bakalari.session.json mcp
```

The MCP host normally launches and stops the process. Running it directly waits for protocol messages on
standard input; it does not print a banner or interactive prompt. Close stdin to stop it, or use Ctrl-C.

Equivalent entry points:

```bash
python -m bakalari --session-file /absolute/path/bakalari.session.json mcp
bakalari-mcp --session-file /absolute/path/bakalari.session.json
python -m bakalari.mcp --session-file /absolute/path/bakalari.session.json
```

Global options (`--base-url`, `--session-file`, `--username-env`, `--password-env`, `--timeout`, `--retries`, `-v`)
go before `mcp` in the main CLI. `--allow-writes` goes after it. The dedicated `bakalari-mcp` entry point accepts
these options without a subcommand. `BAKALARI_SESSION_FILE` also selects a session file.

Authentication is lazy: initialization and tool discovery require neither a school URL nor credentials.
School-directory tools require neither. Public timetable and API-version tools require a school URL but no
login. Private tools need credentials or a saved session. A configuration error becomes a tool error, so it
does not prevent discovery or terminate the connection.

## Configuration reference

| Setting | Purpose and default |
|---|---|
| `--base-url URL` / `BAKALARI_URL` | School installation URL. Explicit flag takes precedence over the environment; a saved session supplies its URL when neither is set. |
| `BAKALARI_USERNAME`, `BAKALARI_PASSWORD` | Credentials for initial login, or fallback when a refresh token is rejected. They are not MCP tool arguments. |
| `--username-env NAME`, `--password-env NAME` | Read credentials from alternate environment variable names. Useful when creating sessions for several children. |
| `--session-file PATH` / `BAKALARI_SESSION_FILE` | Resume and persist tokens. Explicit flag takes precedence; no session file is used by default. |
| `--timeout SECONDS` | Positive timeout per HTTP attempt; default `30`. |
| `--retries N` | Number of retries for eligible GET/PUT/DELETE failures; default `2`. POST requests are not automatically retried. |
| `-v`, `--verbose` | Log request diagnostics to stderr, never stdout. Logs can still contain object IDs. |
| `mcp --allow-writes` | Include write tools for this process; off by default. There is no environment-variable switch for this option. |

For example, give a slow installation more time and disable automatic request retries:

```bash
bakalari --session-file /absolute/path/student.session.json --timeout 60 --retries 0 -v mcp
```

Without a session file, the server can authenticate from environment variables but will not persist tokens
across restarts. With a session file, credentials are optional until that session can no longer be refreshed.
The session selects the account: changing username/password variables does not switch an already saved session
to another child. Stop the host before replacing a session with the regular `login` command.

## Connect an MCP host

For applications using an `mcpServers` JSON configuration, add an entry like this. Replace both absolute paths
with your virtual environment's Python executable and your saved session file:

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

On Windows use `C:\\absolute\\path\\.venv\\Scripts\\python.exe` and Windows paths in the JSON strings.
The package must be installed in that interpreter; the host does not need the repository as its working directory.
Use one entry and one session file per school account.

If your host launches servers with a restricted environment, provide the configuration through its environment
settings or secret store. A host supporting `env` can supply `BAKALARI_URL`, `BAKALARI_USERNAME`,
`BAKALARI_PASSWORD` or `BAKALARI_SESSION_FILE` there. Environment placeholders such as `${BAKALARI_PASSWORD}`
are host-specific; this server does not expand them in a JSON configuration. Keep credentials out of shared files.
A saved session avoids storing the password in the host configuration.

Example requests to your assistant:

- “What lessons do I have tomorrow, and are there any substitutions?”
- “Show my new marks and explain the averages by subject.”
- “Which homework assignments are due this week?”
- “Summarize my unread school messages without marking them read.”
- “What is the class fund balance and how do I top it up?”

### Windows host configuration

The following is a complete JSON example. Replace `YourName` and the project path. JSON backslashes must be
escaped; these are literal paths, not PowerShell expressions:

```json
{
  "mcpServers": {
    "bakalari": {
      "command": "C:\\Users\\YourName\\bakalari\\.venv\\Scripts\\python.exe",
      "args": [
        "-m", "bakalari", "--session-file",
        "C:\\Users\\YourName\\AppData\\Local\\bakalari\\student.session.json", "mcp"
      ]
    }
  }
}
```

### Supply a session through the host environment

For a host supporting per-server `env`, this is equivalent to passing `--session-file`:

```json
{
  "mcpServers": {
    "bakalari": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["-m", "bakalari", "mcp"],
      "env": {"BAKALARI_SESSION_FILE": "/absolute/path/student.session.json"}
    }
  }
}
```

To authenticate without a saved session, supply the three credential variables through the host's private
configuration or secret store instead. A terminal `export` does not necessarily reach an application opened
from the desktop. The exact configuration file location and connection UI depend on your host; these examples
apply to hosts that accept `mcpServers`, not every application's configuration syntax.

After saving the configuration, reconnect/restart the host, enable the server's tools if your host requires it,
and ask it to inspect `user_profile` and `enabled_modules`. There should be 50 tools in read-only mode and 61
with writes enabled. Tools remain listed even when the current account lacks their school module or teacher role;
the school checks permission when they are called.

## Use multiple accounts

Create a separate session for each child or school. These commands assume the indicated alternate credential
variables have been set to the corresponding account's login:

```bash
bakalari --base-url https://school-a.example --username-env CHILD_A_USERNAME --password-env CHILD_A_PASSWORD --session-file /absolute/path/child-a.session.json login
bakalari --base-url https://school-b.example --username-env CHILD_B_USERNAME --password-env CHILD_B_PASSWORD --session-file /absolute/path/child-b.session.json login
```

Replace both example school URLs. Then add distinct host entries:

```json
{
  "mcpServers": {
    "bakalari-child-a": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["-m", "bakalari", "--session-file", "/absolute/path/child-a.session.json", "mcp"]
    },
    "bakalari-child-b": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["-m", "bakalari", "--session-file", "/absolute/path/child-b.session.json", "mcp"]
    }
  }
}
```

Remove an inherited `BAKALARI_URL` if the session files should supply different school URLs, or add the matching
`--base-url` to each entry. Ask the assistant to name the account before reading or changing its data. There is
no MCP tool to switch accounts or school URLs; that choice belongs to the process configuration.

## Everyday workflows

The JSON blocks below are **tool-call parameters**: pass their `name` and `arguments` through your host's tool
interface, or as `params` of a `tools/call` request. They are not shell commands or complete JSON-RPC messages.
The [connection check](#verify-the-connection-without-a-school-account) demonstrates complete envelopes.
Dates are illustrative; use the requested dates, and replace placeholder IDs with exact values from earlier
results. Your assistant normally performs these tool calls for you.

### Check the account first

Ask: “Which school account is connected, and which modules can I use?”

```json
{"name": "user_profile", "arguments": {}}
```

Check `full_name`, `user_type`, `school_name` and module rights. `enabled_modules` with `{}` gives just the
module names. A tool being advertised does not mean this account has permission to call it. For example,
a parent account generally cannot use the teacher tools.

### Find a school and inspect public timetables

Ask: “Find schools in Praha.” No account or school URL is needed:

```json
{"name": "find_schools", "arguments": {"text": "Praha", "max_requests": 15}}
```

Choose the intended school from the results and configure its URL outside MCP. For example, run
`bakalari --base-url https://skola.bakalari.cz mcp`, replacing the sample address. Reconnect the host after
changing its command. Then discover published targets:

```json
{"name": "public_timetable_targets", "arguments": {}}
```

Use a returned class ID to fetch next week's timetable:

```json
{"name": "public_timetable", "arguments": {"kind": "class", "target_id": "CLASS_ID", "week": "next"}}
```

`kind` also accepts `teacher` and `room`; `week` also accepts `actual` and `permanent`. Use
`public_timetable_url` with the same arguments for a link. Publication is the school's choice.

### Plan a week of lessons and events

Ask: “Show the week of 19 October 2026, including substitutions and my events.”

```json
{"name": "actual_timetable", "arguments": {"date": "2026-10-19"}}
```

```json
{"name": "substitutions", "arguments": {"since": "2026-10-19"}}
```

```json
{"name": "events", "arguments": {"since": "2026-10-19", "scope": "my"}}
```

The timetable covers the whole week; substitutions cover two weeks. Ask the assistant to select the requested
dates and distinguish cancelled/changed lessons from normal lessons. `events` has a start date and no `until`
argument, so filter its returned events to the desired week. Use `permanent_timetable` with `{}` for the normal
weekly pattern, or `class_timetable` with a `class_id` from the profile to include the class's other groups.

### Review marks and predict an average

Ask: “Show new marks since 1 October and estimate my mathematics average after a 1 with weight 3.”

```json
{"name": "marks", "arguments": {"since": "2026-10-01"}}
```

Inspect each mark's `is_new` flag. `new_marks_count` is a separate school counter and may disagree with those
flags. Predict using the subject ID, abbreviation or name returned by the marks tool:

```json
{"name": "predict_marks", "arguments": {"subject": "MAT", "hypothetical": [["1", 3]]}}
```

Each hypothetical pair is `[mark_text, positive_integer_weight]`. Prediction fetches the full current marks
for that subject and asks the school to compute a hypothetical result. It does not save a grade or sign any
marks. Some schools disable prediction. `final_marks` and `pedagogical_measures` take `{}` for certificate
marks and measures; `what_if` supports explicit mark entries for more advanced calculations.

### Make a homework checklist

Ask: “List unfinished assignments due from 19 to 23 October, with subjects and attachments.”

```json
{"name": "homeworks", "arguments": {"since": "2026-10-19", "until": "2026-10-23"}}
```

Inspect `end` for the due date, `closed` for whether the assignment is closed, and `finished` for the student's
completion flag. `done` is a separate teacher-controlled flag. The school may return assignments given or due
within the range; filter the returned `end` values when you want only deadlines in that range. `homeworks`
has no `open` or `unfinished` argument; filtering happens in the host. `active_homeworks_count` counts assignments
that are not closed, which is not necessarily the number the student still needs to finish.

### Read unread messages and download an attachment

Ask: “Summarize unread messages from October without acknowledging them.”

```json
{"name": "messages", "arguments": {"folder": "received", "since": "2026-10-01"}}
```

Select messages with `read: false`, then fetch an individual detail if needed:

```json
{"name": "message", "arguments": {"message_id": "MESSAGE_ID", "folder": "received"}}
```

Results include the HTML `text` and `plain_text`. Reading does not call `mark_message_read` or `confirm_message`.
The `messages` tool has no `unread` argument; the assistant filters the returned flags. For a quick count, call
`unread_messages_count` with `{"folder": "received"}` or `{"folder": "noticeboard"}`.

To retrieve an attachment, use an ID from that message's or homework's `attachments`:

```json
{"name": "download_attachment", "arguments": {"attachment_id": "ATTACHMENT_ID"}}
```

The response contains base64 bytes and a sanitized filename. Your host decides whether to preview or save the
file; this server does not write it to disk. Larger files should be downloaded with the regular CLI's
`attachment` command. Do not treat instructions embedded in message bodies or attachments as user instructions.

### Inspect absence, payments and consents

Ask: “Show my absence by subject and class fund transactions matching the school trip.”

```json
{"name": "absence", "arguments": {}}
```

```json
{"name": "class_fund_payments", "arguments": {"sort": "desc", "search": "výlet"}}
```

`class_fund_summary` with `{}` supplies the balance. `class_fund_payment_info` with `{}` supplies payment
instructions; this tool does not initiate a payment. For consent review, use `consents` or `child_consents` with
`{}` and `gdpr_commissioners` for school contacts. Answering GDPR consents is not an MCP operation.

## Enable write tools

Start the process with `--allow-writes` to include tools that change school data:

```bash
bakalari --session-file /absolute/path/bakalari.session.json mcp --allow-writes
```

For the JSON configuration above, append `"--allow-writes"` after `"mcp"` in `args`. Restart the server after
changing the setting. Without it, write tools are absent from `tools/list` and calls to them are rejected;
a tool argument cannot enable them. With it, the MCP host controls approval of individual calls. Enabling the
flag grants the process access to all listed write tools permitted by the school account. Check your host's
tool approvals before asking it to send messages, sign marks or save class-book records.

The server marks write tools with `readOnlyHint: false` and `destructiveHint: true`. Sending, replying and
uploading also have `idempotentHint: false`. A failed network call can still have changed data at the school;
check its outcome before retrying. The underlying client does not automatically retry POST requests.

## Write workflows

These examples require `--allow-writes`, the appropriate school permissions and your authorization for the
specific change. IDs and recipient codes shown below are placeholders. Read the current record first, choose
the exact target, then review the proposed change through your host before calling the write tool.

### Finish a homework assignment or sign marks

After selecting a homework from `homeworks`, ask: “Mark this assignment as finished.”

```json
{"name": "set_homework_done", "arguments": {"homework_id": "HOMEWORK_ID", "done": true}}
```

Pass `false` to undo the student's completion flag. Fetch the homework list again to check `finished`.
To sign selected marks after reviewing them:

```json
{"name": "confirm_marks", "arguments": {"mark_ids": ["MARK_ID_1", "MARK_ID_2"]}}
```

The result is a boolean indicating whether confirmation occurred. This requires a parent account with the
relevant school right; it does not edit mark values.

### Send a message with an optional attachment

Ask the assistant to draft the message, identify the intended recipient, and show both before sending.
First call `message_types` with `{}`. Use its allowed message type, recipient type and recipient codes, not
names guessed from a contact list. Some types select recipients implicitly and require an empty recipient list.

For a small attachment, the host can supply the bytes directly. This illustrative upload contains the UTF-8
text `Hello\n`, encoded as base64:

```json
{
  "name": "upload_attachment",
  "arguments": {"filename": "note.txt", "content_type": "text/plain", "content_base64": "SGVsbG8K"}
}
```

It returns the new attachment ID in `data`. A file path cannot be used as `content_base64`; the MCP server does
not read your computer's files. The host must acquire the intended file through its own file-access controls.
Use the returned attachment ID in the message, or omit `attachments` if there is no file:

```json
{
  "name": "send_message",
  "arguments": {
    "message_type": "MESSAGE_TYPE_CODE",
    "recipient_type": "RECIPIENT_TYPE_CODE",
    "recipients": ["RECIPIENT_CODE"],
    "title": "Homework question",
    "text": "<p>Could you please clarify the homework deadline?</p>",
    "attachments": ["UPLOADED_ATTACHMENT_ID"],
    "require_confirmation": false
  }
}
```

`text` is the message body as HTML. Escape literal `<`, `>` and `&` when they are ordinary text. Sending returns
`data: null` on success, not a new message ID. Check `messages` with `{"folder": "sent"}` to inspect sent
messages. A timeout is not proof that sending failed; check the sent folder before retrying.

### Reply, acknowledge, hide or delete a message

Fetch the original with `message`, review its `can_answer` flag and the proposed reply, then:

```json
{
  "name": "reply_to_message",
  "arguments": {"message": "MESSAGE_ID", "text": "<p>Thank you for the clarification.</p>"}
}
```

The argument is called `message` for replies, whereas `message` and the state-changing tools take
`message_id`. Replying derives permitted recipients from the original message and the school's reply options.
Omit `title` to use the library's default reply title.

To acknowledge a message explicitly:

```json
{"name": "confirm_message", "arguments": {"message_id": "MESSAGE_ID"}}
```

`mark_message_read`, `hide_message`, `unhide_message`, and `delete_message` also take just `message_id`.
Check `can_confirm`, `can_hide` or `can_delete` on the detail where applicable. Confirming receipt and marking
read are separate operations; neither happens merely by reading the detail. Do not use deletion as a substitute
for hiding a message you may want to find later.

### Inspect and update a teacher class-book record

With a teacher account, read a date range:

```json
{"name": "classbook", "arguments": {"since": "2026-10-19", "until": "2026-10-23"}}
```

Select the intended record and use its `lesson_id` with `lesson_past` to obtain the previous theme and, for an
unwritten record, the next label. `lesson_tags` lists available tags. `save_classbook_record` takes a Bakaláři
request body with capitalized keys, not the lowercase model returned by `classbook`:

```json
{
  "name": "save_classbook_record",
  "arguments": {
    "record": {
      "Id": "RECORD_ID",
      "LessonId": "LESSON_ID",
      "ClassBookLevel": "SecondLevel",
      "Label": "14",
      "Notice": "",
      "PrivateNotice": "",
      "Tags": [],
      "Theme": "Linear equations",
      "WeekTheme": "Algebra",
      "Groups": [{"Id": "GROUP_ID", "ClassId": "CLASS_ID"}]
    }
  }
}
```

This is an illustrative complete body, not a patch. Replace every value with the selected record's values,
preserve existing notices/tags/week theme unless deliberately changing them, use the record's actual `level`
for `ClassBookLevel`, and include the editable groups with their class IDs. Do not copy the example's blank
fields over existing content. See the [teacher library guide](library.md#teachers) and
`ClassBookRecord.request_body()` for the exact mapping. Fetch the date range again after saving to verify it.

## Tool catalog

Names match Python client methods except the three school-directory tools. `tools/list` is the authoritative
source of argument schemas, required fields, enums and defaults. Parameters are JSON values, IDs are opaque
strings (preserve spaces), and dates must be valid `YYYY-MM-DD` strings. Omit optional parameters to use defaults;
`null` is accepted only where the schema explicitly permits it.

| Area | Read tools |
|---|---|
| School directory | `school_municipalities`, `schools`, `find_schools` |
| Account and API | `api_version`, `available_api_versions`, `user_profile`, `enabled_modules`, `student_at_school`, `web_modules` |
| Timetables | `actual_timetable`, `permanent_timetable`, `class_timetable`, `substitutions` |
| Published timetables | `public_timetable_targets`, `public_timetable`, `public_timetable_url` |
| Marks | `marks`, `new_marks_count`, `final_marks`, `pedagogical_measures`, `predict_marks`, `what_if` |
| Absence and subjects | `absence`, `subjects`, `subject_themes` |
| Homework and events | `homeworks`, `active_homeworks_count`, `events` |
| Komens | `messages`, `message`, `unread_messages_count`, `message_types`, `rating_templates`, `download_attachment` |
| GDPR | `consents`, `child_consents`, `new_consents_count`, `gdpr_commissioners` |
| Payments | `class_fund_summary`, `class_fund_payments`, `class_fund_payment_info`, `regular_payments_summary` |
| Teachers | `classbook`, `lesson_tags`, `lesson_absence`, `lesson_past`, `lesson_students_timetable`, `marking_atoms`, `marking_marks`, `emergency_configuration` |

| Area | Write tools, requiring `--allow-writes` |
|---|---|
| Homework and marks | `set_homework_done`, `confirm_marks` |
| Komens | `mark_message_read`, `confirm_message`, `hide_message`, `unhide_message`, `delete_message`, `send_message`, `reply_to_message`, `upload_attachment` |
| Teachers | `save_classbook_record` |

`predict_marks` accepts `{"subject": "MAT", "hypothetical": [["1", 3], ["2-", 5]]}`. It predicts an average
without changing grades. `message` accepts `{"message_id": "ID", "folder": "received"}` and never marks a
message read. `save_classbook_record` accepts the Bakaláři request body in `record`, including its `Id`; see
[class-book records in the library guide](library.md#teachers). School module and role restrictions
apply to every tool.

Credential management, login tokens, one-time web login links, push-token registration, arbitrary API requests,
local file access and the `send_message(extra=...)` escape hatch are deliberately not exposed. Authentication
and session files are managed by the operator. Use the regular library or CLI for these operations.

## Results, errors and limits

Successful calls return a JSON object `{"data": ...}` as `structuredContent` and the same JSON in a text block.
Older negotiated versions (`2024-11-05`, `2025-03-26`) receive the text block only. Models use the library's
`to_dict()` representation, with ISO dates and without raw payload copies. Message results also include
`plain_text`. Operations returning no value produce `{"data": null}`; counters and confirmations retain their
integer/boolean values.

Downloads return `id`, `filename`, `content_type`, `size`, and `content_base64` in `data`. Uploads take
`content_base64`, `filename`, and optionally `content_type`, and return an attachment ID usable by `send_message`.
Both are limited to **512 KiB** of decoded file content; download size is checked after fetching. Neither reads
nor writes a local path. Use the regular CLI for larger files.

Invalid tool arguments and school/API failures return `isError: true`. Unknown/disabled tools and malformed
protocol envelopes return JSON-RPC errors. Upstream exception text, HTTP bodies, passwords and tokens are not
included in errors. The connection remains available after a failed call. Standard output is reserved for
protocol traffic; CLI diagnostics and optional request logging go to standard error.

Input frames are limited to **1 MiB**, and serialized tool data to **8 MiB**. Larger results produce an error
rather than silently dropping records; narrow date ranges or request individual objects. School responses may
contain sensitive personal information or untrusted text. Only connect hosts you trust with this account's data.

Session renewal saves the rotated refresh token immediately, using the existing atomic session writer and mode
0600 on POSIX. Avoid running multiple processes against the same session file, because the school can rotate
refresh tokens independently of each process. A session for a different configured school is rejected.

### Example success and failure responses

For `unread_messages_count`, a successful `tools/call` result might look like this (the count is synthetic):

```json
{
  "content": [{"type": "text", "text": "{\"data\": 3}"}],
  "isError": false,
  "structuredContent": {"data": 3}
}
```

A missing required tool argument is a tool error, so the assistant can correct its call:

```json
{
  "content": [{"type": "text", "text": "arguments: missing required argument"}],
  "isError": true
}
```

Calling a disabled write tool returns a JSON-RPC error instead of a tool result:

```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "error": {"code": -32602, "message": "Unknown or disabled tool"}
}
```

The first two blocks show the contents of the JSON-RPC `result` field. The last shows a complete error response.
A failed tool call is not the same as the process exiting with an error code.

## Verify the connection without a school account

After installing the package, save this as `check_mcp.py` and run it with the same interpreter you configured
in the host. It starts a subprocess, completes the handshake, lists tools, and closes stdin. It does not call
any school or directory tool, authenticate, or create a session file:

```python
import json
import subprocess
import sys

messages = [
    {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "local-check", "version": "1.0"},
        },
    },
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
]
process = subprocess.run(
    [sys.executable, "-m", "bakalari", "mcp"],
    input="".join(json.dumps(message) + "\n" for message in messages),
    text=True, encoding="utf-8", capture_output=True, timeout=10, check=True,
)
responses = [json.loads(line) for line in process.stdout.splitlines()]
assert len(responses) == 2  # The initialized notification has no reply.
assert responses[0]["result"]["serverInfo"]["name"] == "bakalari"
tools = responses[1]["result"]["tools"]
assert len(tools) == 50
assert all(tool["annotations"]["readOnlyHint"] for tool in tools)
print(f"Connected: {len(tools)} read-only tools")
```

Expected output: `Connected: 50 read-only tools`. This validates the local executable and protocol, not your
school credentials. For a separate account check, run
`bakalari --session-file /absolute/path/student.session.json profile` with your session path.

For a host developer inspecting raw traffic, a subsequent call after initialization is one JSON object followed
by a newline:

```json
{
  "jsonrpc": "2.0", "id": 3, "method": "tools/call",
  "params": {"name": "actual_timetable", "arguments": {"date": "2026-10-19"}}
}
```

The block is pretty-printed for readability. On the stdio connection serialize each message to one line;
sending the displayed multi-line formatting directly would produce parse errors.

## Troubleshooting

| Symptom | What to check |
|---|---|
| `invalid choice: 'mcp'` or no `bakalari-mcp` command | The selected interpreter has an older install, or the virtual environment is not active. Install this checkout with that interpreter using `python -m pip install .`, then run `python -m bakalari mcp --help`. |
| `No module named bakalari` | Install the package in the exact Python executable named in the host configuration. A different terminal Python does not fix the host's environment. |
| The terminal stays blank | Normal for a stdio server waiting for input. Run the offline check above, or let an MCP host launch it. |
| The host reports connection refused at an HTTP URL | This mode has no HTTP listener. Configure a local command/stdio server; a host supporting only remote HTTP cannot connect directly. |
| Initialization works, but a school tool reports configuration failure | Discovery is lazy. Check the process's `BAKALARI_URL` or session path, the session file's format, and read/write permissions. |
| A session works in the terminal but fails in the host | Use an absolute session/executable path. Check the host's environment and any inherited `BAKALARI_URL`. The configured school must match the session. |
| Authentication failed | Stop the host, supply the correct login variables and renew the intended session with `bakalari --session-file PATH login`. Check `profile`, then restart. Avoid repeatedly trying an incorrect password. |
| Data belongs to a different child | A saved session selects its account even if different credential variables are set. Create separate sessions and distinct host entries, then check `user_profile`. |
| A write tool is missing or “Unknown or disabled tool” | Add `--allow-writes` after `mcp` and restart the process. Check the exact name from `tools/list`; CLI names such as `homework-done` are not MCP names. |
| The school does not permit the operation | Inspect profile modules/rights. Teacher tools need a teacher account; `--allow-writes` does not grant school permissions. |
| “unexpected value type”, “unknown argument”, or date errors | Use the tool schema: booleans are `true`/`false`, IDs are strings, dates are `YYYY-MM-DD`. Omit unused options instead of passing `null`. CLI filters such as `--unread`, `--new` or `--open` are not MCP arguments. |
| “Complete initialize and notifications/initialized” | The host must send both handshake messages before `tools/list` or `tools/call`. Use the offline example to compare the sequence. |
| JSON parse errors or invalid protocol output | Send one JSON object per line. Remove shell startup banners or `echo` output from command wrappers; send diagnostics to stderr. |
| Attachment or message size error | Decoded attachments are limited to 512 KiB; input frames to 1 MiB. Use the normal CLI for larger files. |
| Result exceeds 8 MiB | Narrow a supported date range or fetch individual messages. Do not add pagination arguments absent from the advertised schema. |
| Request timeout or apparent cancellation delay | Calls are synchronous and serial; cancellation cannot interrupt an in-flight HTTP request. Adjust `--timeout` and `--retries` before `mcp`, and check the school/network. |
| Sending/uploading failed after a timeout | The school may already have accepted it. Inspect the outcome before retrying; the MCP server does not automatically retry POST requests. |

For local request diagnostics, put `-v` before `mcp`. The host should capture stderr separately from protocol
output. Logs omit credentials and request bodies but may contain account/object IDs; redact personal data before
sharing them. You can reproduce a read failure with the corresponding regular CLI command for its more detailed
error hints. MCP errors deliberately do not expose upstream response bodies.

## Protocol and lifecycle

The server implements the [MCP stdio transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
and [tools capability](https://modelcontextprotocol.io/specification/2025-11-25/server/tools).
It supports `2025-11-25`, `2025-06-18`, `2025-03-26`, and `2024-11-05`, negotiating during `initialize`.
An unsupported requested version is counter-offered `2025-11-25`; the host must accept it or disconnect.

Messages are newline-delimited UTF-8 JSON-RPC 2.0. Initialize with `protocolVersion`, `capabilities` and
`clientInfo`, then send `notifications/initialized`. After that, use `tools/list`, `tools/call`, and `ping`.
The catalog fits in one page and does not change during the connection. Notifications receive no response.
There are no resources, prompts, subscriptions, server-initiated requests, batch requests, or HTTP/SSE listeners.
Remote HTTP deployment and the newer handshake-free protocol are outside this mode's supported transports and versions.

Calls run serially, protecting rotating account tokens. Cancellation notifications cannot interrupt an in-flight
synchronous school request; `--timeout` limits each HTTP attempt, and `--retries` controls retries. EOF shuts down
the server. Ctrl-C follows the normal CLI interrupted exit status (130).

## Python embedding and testing

```python
from bakalari import BakalariClient
from bakalari.mcp import MCPServer

client = BakalariClient.from_env()
MCPServer(client, allow_writes=False).serve()
```

For custom session persistence, set the client's `on_session_update` callback before passing it to the server.
`MCPServer.handle(message)` handles one decoded JSON-RPC object, while `serve(input_stream, output_stream)` accepts
binary streams for testing. A `client_provider` can create a client lazily, and `directory_provider` can provide
a custom `SchoolDirectory`. The CLI handles session files; direct embedding leaves persistence to the caller.

### Connect from a Python MCP client

To integrate through the protocol rather than calling `BakalariClient` directly, install the optional official
client SDK in a separate Python 3.10+ client environment with `python -m pip install 'mcp>=1.26,<2'`. The server
itself still needs no SDK. This example uses the same interpreter for client and server, so install `bakalari` (or this
checkout) there as well. Replace the absolute session path before running it; unlike the offline check, this
example fetches private school data:

```python
import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "bakalari", "--session-file", "/absolute/path/student.session.json", "mcp"],
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            catalog = await session.list_tools()
            print(f"Available tools: {len(catalog.tools)}")
            result = await session.call_tool("homeworks", {"since": "2026-10-19", "until": "2026-10-23"})
            if result.isError:
                for block in result.content:
                    if block.type == "text":
                        print(block.text)
                return
            print(result.structuredContent)  # {"data": [...]} for the negotiated modern structured-result versions.


if __name__ == "__main__":
    asyncio.run(main())
```

The context managers close the connection and subprocess when the program finishes. Your application can read
the JSON in text content as a fallback when negotiating a protocol version without structured results. Keep
returned homework, message and profile data out of public application logs.

### Run the offline implementation tests

The standard offline suite includes protocol, malformed-input, privacy, write-gating, endpoint-dispatch,
attachment, session-renewal and subprocess tests. The CI test/build job also checks discovery, schemas, tool calls,
errors and shutdown through the official MCP Python client with synthetic school responses:

```bash
# In a separate development/test virtual environment (Python 3.10+ for the SDK):
python -m pip install 'mcp>=1.26,<2' jsonschema
python -m unittest unittests.test_mcp tests.test_mcp_sdk -v
```

The SDK is a test dependency only; ordinary package installation remains dependency-free.
