"""Print this week's timetable and its changes.

The script prints the actual timetable of the week (substitutions, cancellations, room changes and events
included), then the changed lessons on their own, then the substitutions list for 14 days from that week's Monday.
A week other than the current one can be given as any of its dates.

Usage:

    export BAKALARI_URL=https://skola.bakalari.cz BAKALARI_USERNAME=... BAKALARI_PASSWORD=...
    python examples/weekly_timetable.py [YYYY-MM-DD]

It only reads data. A school without the Substitutions module still gets the timetable.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import List, Optional

from bakalari import BakalariClient, BakalariConfigError, BakalariError, BakalariPermissionError, to_date, week_of


def iso_date(value: str) -> dt.date:
    try:
        return to_date(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a date in the form YYYY-MM-DD: {value!r}") from None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Print a week's timetable and its changes.")
    parser.add_argument("date", nargs="?", type=iso_date, default=dt.date.today(), help="a day of the week")
    args = parser.parse_args(argv)
    monday, sunday = week_of(args.date)

    try:
        client = BakalariClient.from_env()
        timetable = client.actual_timetable(args.date)
    except BakalariConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    except BakalariPermissionError as error:
        print(f"The timetable is not available for this account (HTTP 403: {error.message or 'no reason given'}).",
              file=sys.stderr)
        return 1
    except BakalariError as error:
        print(f"Bakaláři error: {error}", file=sys.stderr)
        return 1

    print(f"Timetable of the week {monday} - {sunday}")
    print(timetable.format() or "No school days in this week.")

    print("\nChanged lessons:")
    for lesson in timetable.changed_lessons:
        print("   ", lesson.format())
    if not timetable.changed_lessons:
        print("    none")

    print("\nSubstitutions list:")
    try:
        substitutions = client.substitutions(monday)    # 14 days from that Monday
    except BakalariPermissionError:
        print("    The Substitutions module is not enabled for this account.")
    except BakalariError as error:
        print(f"    Could not load the substitutions: {error}")
    else:
        print(f"    {substitutions.start} - {substitutions.end}")
        for change in substitutions.changes:
            print("   ", change.format())
        if not substitutions.changes:
            print("    no changes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
