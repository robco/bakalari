[![Python Package CI](https://github.com/robco/bakalari/actions/workflows/python-package.yml/badge.svg)](https://github.com/robco/bakalari/actions/workflows/python-package.yml)
[![PyPI version](https://img.shields.io/pypi/v/bakalari.svg)](https://pypi.org/project/bakalari/)
[![Python versions](https://img.shields.io/pypi/pyversions/bakalari.svg)](https://pypi.org/project/bakalari/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/robco/bakalari/blob/main/LICENSE)

[![Buy Me a Coffee](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/robco)

# Bakalari API & MCP Server

An unofficial Python client, command line tool and MCP server for the **Bakaláři REST API v3**.
Read timetables, marks, homework, absence and Komens messages using the same account as your school's
Bakaláři website. The client handles login and token renewal and returns typed Python objects.

**Česky:** Neoficiální knihovna, příkazová řádka a MCP server pro Bakaláře. Rozvrh, známky, úkoly a zprávy
na jednom místě, bez dalších běhových závislostí. [Český úvod a příklady](https://github.com/robco/bakalari/blob/main/docs/guide.md#česky).

## Features

- Python 3.9 or newer, standard library only, with type hints and `py.typed`.
- Timetables, substitutions, marks, absence, subjects, homework, messages, events, GDPR consents,
  class fund payments and teacher endpoints.
- School search and published timetables without an account.
- CLI commands with JSON output, saved sessions and runnable example scripts.
- MCP server over stdio: 50 read tools, plus 11 write tools enabled explicitly with `--allow-writes`.
- Typed models, automatic token renewal, configurable retries and raw API access.
- Reading a message leaves it unread; passwords and tokens are excluded from logs and error messages.

Available modules and permissions depend on your school and account type.

## Documentation

| Guide | Contents |
|---|---|
| [Usage guide](https://github.com/robco/bakalari/blob/main/docs/guide.md) | Detailed walkthrough, sessions, practical workflows and troubleshooting |
| [Python library](https://github.com/robco/bakalari/blob/main/docs/library.md) | Client methods, models, errors and transports |
| [Command line](https://github.com/robco/bakalari/blob/main/docs/cli.md) | Commands, options, exports and configuration |
| [MCP server](https://github.com/robco/bakalari/blob/main/docs/mcp.md) | AI host setup, tool catalog and examples |
| [API coverage](https://github.com/robco/bakalari/blob/main/docs/endpoints.md) | Supported endpoints and known limitations |
| [Example scripts](https://github.com/robco/bakalari/tree/main/examples) | Timetables, marks, attachments, calendars, sessions and school search |

## Installation

Install from PyPI in a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U bakalari
```

On Windows, create the environment with `py -m venv .venv` and activate it in PowerShell with
`.\.venv\Scripts\Activate.ps1`.

To install from source (including before a release is available on PyPI):

```bash
git clone https://github.com/robco/bakalari.git
cd bakalari
python -m pip install .
```

Both install the library and the `bakalari` and `bakalari-mcp` commands. Check the installation with
`python -m bakalari --version` or `python -m bakalari --help`.

## Configuration

Set your school's Bakaláři address and account credentials in your environment:

```bash
export BAKALARI_URL='https://skola.bakalari.cz'
export BAKALARI_USERNAME='your-username'
export BAKALARI_PASSWORD='your-password'
```

In PowerShell, use `$env:BAKALARI_URL = 'https://skola.bakalari.cz'` and the same syntax for the other variables.
Use your own school's address and credentials. `bakalari schools Praha` searches the school directory without
logging in.

| Variable | Purpose |
|---|---|
| `BAKALARI_URL` | School's Bakaláři address, including `/bakaweb` if applicable |
| `BAKALARI_USERNAME` | Bakaláři web username |
| `BAKALARI_PASSWORD` | Bakaláři web password |
| `BAKALARI_SESSION_FILE` | Optional CLI session file for subsequent commands without the password |

For a saved session, run `bakalari --session-file ~/.bakalari-session.json login`, then set
`BAKALARI_SESSION_FILE` to that path. Protect the session file like a password and keep it out of version control.
See the [authentication guide](https://github.com/robco/bakalari/blob/main/docs/guide.md#authentication-and-sessions)
for refresh tokens and multiple accounts.

## Usage examples

### Command line

```bash
bakalari profile
bakalari timetable                  # this week's lessons and changes
bakalari marks --new                # new marks
bakalari messages --unread          # unread messages, left unread
bakalari homeworks --open           # open homework
bakalari --json absence             # JSON for scripts
```

Use `bakalari <command> --help` for options. Commands that change school data are identified in the
[CLI reference](https://github.com/robco/bakalari/blob/main/docs/cli.md#commands-that-change-data).

### Python library

```python
from bakalari import BakalariClient

client = BakalariClient.from_env()
print(client.actual_timetable().format())

for subject in client.marks().subjects:
    print(subject.format_summary())

print(client.unread_messages_count(), "unread message(s)")
```

Models expose `to_dict()` for JSON-ready data and `raw` for the original response. See the
[library reference](https://github.com/robco/bakalari/blob/main/docs/library.md) for the complete API.

### MCP server

Configure an MCP host to launch `bakalari mcp` (or `python -m bakalari mcp`) with the environment above:

```json
{
  "mcpServers": {
    "bakalari": {
      "command": "/absolute/path/to/.venv/bin/bakalari",
      "args": ["mcp"],
      "env": {
        "BAKALARI_SESSION_FILE": "/absolute/path/to/bakalari-session.json"
      }
    }
  }
}
```

Create the session first using `bakalari --session-file /absolute/path/to/bakalari-session.json login`.
On Windows, use the virtual environment's `Scripts/bakalari.exe` path. The host must support stdio MCP servers;
its exact configuration format can vary. Read tools are enabled by default; add `--allow-writes` only when you
want tools that change school data. The [MCP guide](https://github.com/robco/bakalari/blob/main/docs/mcp.md)
covers setup and practical workflows.

## Repository structure

```text
bakalari/             Python package, CLI and MCP server
unittests/            Offline tests, shared helpers and synthetic fixtures
tests/                Optional MCP SDK and read-only live integration tests
docs/                 User guides and API references
examples/             Runnable scripts
.github/workflows/    Python Package CI and Python Package Publish
.github/scripts/      CI report summaries and distribution checks
```

The package stays at the repository root. Each Bakaláři area has its own module; `client.py` combines the
endpoint mixins. Packaging and tool settings live in `pyproject.toml`, and `_version.py` is the version source.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m mypy bakalari
python -m build
python -m twine check --strict dist/*
```

Default tests run offline, even when account credentials are present. CI checks supported Python versions,
coverage (at least 90%), lint, types, MCP interoperability and installable distributions, and uploads reports.
See [CONTRIBUTING.md](https://github.com/robco/bakalari/blob/main/CONTRIBUTING.md) for integration tests,
code conventions and the release process. Publishing a GitHub release starts the **Python Package Publish**
workflow, which builds the package and publishes to PyPI using trusted publishing. Tests and distribution
checks run separately in **Python Package CI**. The publish workflow can also be run manually from a branch or tag.

## Support the project

If this project is useful to you, you can support its development through
[Buy Me a Coffee](https://www.buymeacoffee.com/robco) or [Revolut](https://revolut.me/robco).
You can also star the repository, report issues, improve documentation or contribute code.

## Privacy and security

School data is personal. Keep credentials, session files and fetched data private, and use synthetic data in
issues and tests. Report vulnerabilities as described in
[SECURITY.md](https://github.com/robco/bakalari/blob/main/SECURITY.md).

This project is not affiliated with or endorsed by BAKALÁŘI software s.r.o. The unofficial API may change;
use it in line with your school's rules. See the
[usage guide](https://github.com/robco/bakalari/blob/main/docs/guide.md#privacy-and-safety) for details.

## License

[MIT](https://github.com/robco/bakalari/blob/main/LICENSE) — Róbert Malovec.
