"""Print the new marks and the marks waiting for a parent's confirmation, with the subject averages.

For every subject that has a new mark (flagged ``IsNew`` by the server) or an unconfirmed one, the script prints
the subject's average as the server computes it and those marks; with ``--all`` it lists the averages of every
subject too. The server's own new-marks counter is printed for comparison: it is often 0 even when marks are
flagged new.

Usage:

    export BAKALARI_URL=https://skola.bakalari.cz BAKALARI_USERNAME=... BAKALARI_PASSWORD=...
    python examples/new_marks.py [--all]

It only reads data: confirming (signing) marks is ``client.confirm_marks()``, which this script never calls.
"""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from bakalari import BakalariClient, BakalariConfigError, BakalariError, BakalariPermissionError


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Print new and unconfirmed marks with the subject averages.")
    parser.add_argument("--all", action="store_true", help="also list the averages of every subject")
    args = parser.parse_args(argv)

    try:
        client = BakalariClient.from_env()
        marks = client.marks()
        counter = client.new_marks_count()
    except BakalariConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    except BakalariPermissionError as error:
        print(f"The marks are not available for this account (HTTP 403: {error.message or 'no reason given'}).",
              file=sys.stderr)
        return 1
    except BakalariError as error:
        print(f"Bakaláři error: {error}", file=sys.stderr)
        return 1

    print(f"{len(marks.new_marks)} new and {len(marks.unconfirmed_marks)} unconfirmed mark(s); "
          f"the server's new-marks counter says {counter}.")
    for subject in marks.subjects:
        flagged = [mark for mark in subject.marks if mark.is_new or mark.is_unconfirmed]
        if not flagged:
            continue
        print()
        print(subject.format_summary())             # abbreviation, name, average and number of marks
        for mark in flagged:
            print("   ", mark.format())               # date, mark, weight, caption, [new, unconfirmed]

    if args.all:
        print("\nAverages:")
        for subject in marks.subjects:
            name = subject.subject.name or subject.subject.abbrev
            average = f"{subject.average:.2f}" if subject.average is not None else "-"
            print(f"    {name:<40} {average:>5}  ({len(subject.marks)} mark(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
