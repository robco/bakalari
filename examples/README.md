# Examples

Small, runnable scripts that use the `bakalari` library. Each one explains itself in its docstring and with
`--help`, needs only the standard library and the installed package (`python -m pip install bakalari-api`), and
reports a module the school has not enabled (HTTP 403) instead of failing with a traceback.

The scripts that log in read the school's address and the login from the environment, through
`BakalariClient.from_env()`:

```bash
export BAKALARI_URL=https://skola.bakalari.cz     # your school's Bakaláři address (find_school.py finds it)
export BAKALARI_USERNAME=...                      # the login of the Bakaláři web
export BAKALARI_PASSWORD=...
```

| Script | What it does | Changes data |
|---|---|---|
| [weekly_timetable.py](weekly_timetable.py) | This week's timetable (or another week's), its changed lessons and the substitutions list | No |
| [new_marks.py](new_marks.py) | New marks and marks waiting for a parent's confirmation, with the subject averages | No |
| [unread_messages.py](unread_messages.py) | Unread Komens messages with their text; downloads their attachments into a folder without marking anything as read | No (writes files locally) |
| [homeworks_ics.py](homeworks_ics.py) | The homeworks due in the next 7 days as an iCalendar (`.ics`) file for calendar applications | No (writes the file locally) |
| [persistent_session.py](persistent_session.py) | Keeps the session in a file (mode 0600) through `on_session_update`, so later runs need no password | No (writes the session file locally) |
| [class_fund_qr.py](class_fund_qr.py) | The class fund's payment instructions and the Czech QR payment (SPAYD) string | No |
| [find_school.py](find_school.py) | Finds a school's Bakaláři address in the public school directory (no login) | No |

```bash
python examples/weekly_timetable.py
python examples/weekly_timetable.py 2026-11-02
python examples/new_marks.py --all
python examples/unread_messages.py ~/Downloads/komens
python examples/homeworks_ics.py ~/homeworks.ics
python examples/persistent_session.py              # later runs work without BAKALARI_PASSWORD
python examples/class_fund_qr.py 500
python examples/find_school.py Kocourkov --check
```

The output contains personal data of the student and the family. Keep it, the downloaded files and the session
file to yourself; the session file holds the tokens of the account.
