"""Keep a Bakaláři session in a file, so that later runs need no password while the refresh token is valid.

The first run logs in with BAKALARI_USERNAME and BAKALARI_PASSWORD. ``on_session_update`` then writes the session
(the tokens) to SESSION_FILE (default ``~/.bakalari.session.json``) after every login and every renewal, because
each renewal issues a new refresh token. The file is replaced atomically and readable by its owner only (mode 0600
on POSIX systems). Later runs resume the session from the file and work even without the login variables until the
refresh token expires, which happens after about a month without use; then the login variables are needed again.
``--logout`` deletes the file.

Usage:

    export BAKALARI_URL=https://skola.bakalari.cz BAKALARI_USERNAME=... BAKALARI_PASSWORD=...
    python examples/persistent_session.py [--logout] [SESSION_FILE]

The session file holds secrets: anyone who has it can use the account. Never commit or share it. The API cannot
revoke tokens, so deleting the file (``--logout``) is all a logout can do: a copied access token stays valid for at
most an hour, a copied refresh token until it expires.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import functools
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

from bakalari import (
    BASE_URL_ENV,
    BakalariAuthError,
    BakalariClient,
    BakalariConfigError,
    BakalariError,
    BakalariPermissionError,
    SessionState,
)

DEFAULT_SESSION_FILE = Path.home() / ".bakalari.session.json"


def load_session(path: Path) -> Optional[SessionState]:
    """The saved session, or None when there is none (an unreadable file is ignored with a warning)."""
    try:
        with open(path, encoding="utf-8") as file:
            return SessionState.from_dict(json.load(file))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, BakalariConfigError) as error:  # json.JSONDecodeError is a ValueError
        print(f"Ignoring the session file {path}: {error}", file=sys.stderr)
        return None


def save_session(path: Path, state: SessionState) -> None:
    """Writes the session to a new file readable by its owner only, then replaces the old one atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".bakalari-session-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:   # mkstemp creates the file with mode 0600
            json.dump(state.to_dict(), file)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def create_client(path: Path) -> BakalariClient:
    """A client that resumes the saved session, with or without the login variables."""
    state = load_session(path)
    save = functools.partial(save_session, path)
    try:
        client = BakalariClient.from_env(on_session_update=save)
    except BakalariConfigError:
        if state is None:
            raise
        # No login variables: continue the saved session with its refresh token only.
        client = BakalariClient(os.environ.get(BASE_URL_ENV) or state.base_url, on_session_update=save)
    if state is not None:
        try:
            client.import_session(state)
        except BakalariConfigError as error:  # the session of another school
            print(f"Ignoring the session file {path}: {error}", file=sys.stderr)
    return client


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Use a Bakaláři session saved in a file.")
    parser.add_argument("session_file", nargs="?", type=Path, default=DEFAULT_SESSION_FILE)
    parser.add_argument("--logout", action="store_true", help="delete the session file")
    args = parser.parse_args(argv)
    path: Path = args.session_file

    if args.logout:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        print(f"Deleted {path}. The tokens cannot be revoked; a copied access token expires within an hour.")
        return 0
    if os.name == "posix" and path.exists() and path.stat().st_mode & 0o077:
        print(f"Warning: {path} is readable by other users; run chmod 600 on it.", file=sys.stderr)

    try:
        client = create_client(path)
        profile = client.user_profile()          # logs in or renews the tokens as needed
    except BakalariConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    except BakalariAuthError as error:
        print(f"The login or the saved session was rejected ({error.message or error}). Set BAKALARI_USERNAME and "
              "BAKALARI_PASSWORD to log in again.", file=sys.stderr)
        return 1
    except BakalariPermissionError as error:
        print(f"Not available for this account (HTTP 403: {error.message or 'no reason given'}).", file=sys.stderr)
        return 1
    except BakalariError as error:
        print(f"Bakaláři error: {error}", file=sys.stderr)
        return 1
    except OSError as error:                         # raised by save_session() through on_session_update
        print(f"Could not write the session file {path}: {error}", file=sys.stderr)
        return 1

    print(f"{profile.user_type_text or profile.user_type} at {profile.school_name or client.base_url}")
    info = client.token_info
    if info is not None:
        expiry = dt.datetime.fromtimestamp(info.expires_at).strftime("%Y-%m-%d %H:%M")
        print(f"Session file: {path}; the access token expires at {expiry} and is renewed automatically.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
