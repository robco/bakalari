"""Export the homeworks due in the next 7 days as an iCalendar (.ics) file.

Every homework due between today and 7 days from now becomes an all-day event on its due date, with the subject
and the beginning of the assignment as the title and the whole assignment, the teacher, the attachments and the
student's "finished" tick in the description. Calendar applications import the file (or subscribe to it when it is
regenerated regularly); the events keep their ids, so a new export updates the old one.

Usage:

    export BAKALARI_URL=https://skola.bakalari.cz BAKALARI_USERNAME=... BAKALARI_PASSWORD=...
    python examples/homeworks_ics.py [OUTPUT]        # default: homeworks.ics

It only reads data.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import urllib.parse
from typing import List, Optional

from bakalari import BakalariClient, BakalariConfigError, BakalariError, BakalariPermissionError
from bakalari.homeworks import Homework

DAYS_AHEAD = 7
# The server lists the homeworks given or due in the requested interval; asking from a month back also finds
# assignments that were given long before they are due.
DAYS_BACK = 31


def ics_text(value: str) -> str:
    """A TEXT value escaped as RFC 5545 requires."""
    escaped = value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return escaped.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")


def fold(line: str) -> str:
    """A content line folded into lines of at most 75 octets, without splitting a UTF-8 character."""
    parts: List[str] = []
    current, size = "", 0
    for character in line:
        length = len(character.encode("utf-8"))
        if size + length > (75 if not parts else 74):     # continuation lines start with a space
            parts.append(current)
            current, size = "", 0
        current += character
        size += length
    parts.append(current)
    return "\r\n ".join(parts)


def event_lines(homework: Homework, due: dt.date, host: str, stamp: str) -> List[str]:
    """The VEVENT of one homework: an all-day event on its due date."""
    subject = homework.subject.name if homework.subject else "Homework"
    first_line = homework.content.splitlines()[0] if homework.content else ""
    summary = f"{subject}: {first_line}" if first_line else subject
    details = [homework.content]
    if homework.notice:
        details.append(homework.notice)
    if homework.teacher:
        details.append(f"Teacher: {homework.teacher.name}")
    if homework.attachments:
        details.append("Attachments: " + ", ".join(attachment.name for attachment in homework.attachments))
    if homework.finished:
        details.append("Ticked as finished.")
    description = "\n".join(details)
    return [
        "BEGIN:VEVENT",
        f"UID:{urllib.parse.quote(homework.id, safe='')}@{host}",      # stable, so a new export updates it
        f"DTSTAMP:{stamp}",
        f"DTSTART;VALUE=DATE:{due:%Y%m%d}",
        f"DTEND;VALUE=DATE:{due + dt.timedelta(days=1):%Y%m%d}",
        f"SUMMARY:{ics_text(summary)}",
        f"DESCRIPTION:{ics_text(description)}",
        "TRANSP:TRANSPARENT",
        "END:VEVENT",
    ]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Export the homeworks due in the next 7 days as iCalendar.")
    parser.add_argument("output", nargs="?", default="homeworks.ics", help="the .ics file to write")
    args = parser.parse_args(argv)
    today = dt.date.today()
    last_day = today + dt.timedelta(days=DAYS_AHEAD)

    try:
        client = BakalariClient.from_env()
        homeworks = client.homeworks(since=today - dt.timedelta(days=DAYS_BACK), until=last_day)
    except BakalariConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    except BakalariPermissionError as error:
        print(f"The homeworks are not available for this account (HTTP 403: {error.message or 'no reason given'}).",
              file=sys.stderr)
        return 1
    except BakalariError as error:
        print(f"Bakaláři error: {error}", file=sys.stderr)
        return 1

    due = sorted(
        ((homework.end, homework) for homework in homeworks if homework.end and today <= homework.end <= last_day),
        key=lambda pair: (pair[0], pair[1].id),
    )
    host = urllib.parse.urlsplit(client.base_url).hostname or "bakalari"
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//bakalari-api//homeworks example//EN", "CALSCALE:GREGORIAN"]
    for day, homework in due:
        lines.extend(event_lines(homework, day, host, stamp))
    lines.append("END:VCALENDAR")
    with open(args.output, "w", encoding="utf-8", newline="") as file:
        file.write("".join(fold(line) + "\r\n" for line in lines))
    print(f"Wrote {len(due)} homework(s) due from {today} to {last_day} to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
