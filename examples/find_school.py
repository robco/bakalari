"""Find a school's Bakaláři address in the public school directory.

The script searches the official directory (sluzby.bakalari.cz) for the municipalities whose name contains TEXT,
ignoring case, diacritics and the spacing around dashes, and prints their schools with the address to put into
BAKALARI_URL. When BAKALARI_URL is set already, the matching school is marked. With ``--check`` it also asks each
address for its API version, a public request that needs no login, to confirm that a Bakaláři installation answers
there.

Usage:

    python examples/find_school.py TEXT [--check]       # e.g. Kocourkov, "praha 4-modrany"

Unlike the other examples it needs no login, so it does not create the client with ``from_env()`` and never sends
BAKALARI_USERNAME or BAKALARI_PASSWORD anywhere: check that an address found here is your school's before you use
your login with it.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

from bakalari import BASE_URL_ENV, BakalariClient, BakalariError, BakalariPermissionError, normalize_base_url
from bakalari.schools import SchoolDirectory


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Find a school's Bakaláři address in the public directory.")
    parser.add_argument("text", help="a part of the municipality's name")
    parser.add_argument("--check", action="store_true", help="ask each address for its API version (no login)")
    args = parser.parse_args(argv)
    try:
        configured_url = normalize_base_url(os.environ.get(BASE_URL_ENV, ""))
    except (ValueError, BakalariError):              # not set, or not a URL
        configured_url = ""

    try:
        schools = SchoolDirectory().find(args.text)
    except ValueError as error:                       # empty or too broad: asks for a more specific name
        print(f"Usage error: {error}", file=sys.stderr)
        return 2
    except BakalariError as error:
        print(f"The school directory failed: {error}", file=sys.stderr)
        return 1

    if not schools:
        print(f"No municipality matches {args.text!r}.")
        return 1
    for school in schools:
        marker = "   <- your BAKALARI_URL" if configured_url and school.base_url == configured_url else ""
        print(f"{school.name}\n    {school.base_url or '(no address listed)'}{marker}")
        if not args.check or not school.base_url:
            continue
        try:
            version = BakalariClient(school.base_url, timeout=10).api_version()   # public: no login, no token
        except BakalariPermissionError as error:
            print(f"    refused the API request (HTTP 403: {error.message or 'no reason given'})")
        except (BakalariError, ValueError) as error:     # ValueError: an address too malformed to use
            print(f"    no Bakaláři API answers there: {error}")
        else:
            print(f"    Bakaláři REST API {version.get('ApiVersion', '?')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
