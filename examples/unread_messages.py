"""Print the unread Komens messages and download their attachments into a folder.

The script lists the received messages that are not read yet with their text and saves their attachments into
FOLDER (default ``komens-attachments``), one subfolder per message. A file that exists already is kept and
reported, never overwritten, so running the script again downloads only what is new.

Usage:

    export BAKALARI_URL=https://skola.bakalari.cz BAKALARI_USERNAME=... BAKALARI_PASSWORD=...
    python examples/unread_messages.py [FOLDER]

It does not mark anything as read: the message list already carries the texts, and the script never calls
``client.mark_message_read()`` (nor any other method that changes data on the server).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Optional

from bakalari import BakalariClient, BakalariConfigError, BakalariError, BakalariHTTPError, BakalariPermissionError


def printable(value: str) -> str:
    """The server's text without control characters, which must not reach the terminal."""
    return "".join(character if character.isprintable() else " " for character in value)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Print unread Komens messages and download their attachments.")
    parser.add_argument("folder", nargs="?", default="komens-attachments", help="where to save the attachments")
    args = parser.parse_args(argv)

    try:
        client = BakalariClient.from_env()
        messages = client.messages("received")
        counter = client.unread_messages_count()
    except BakalariConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    except BakalariPermissionError as error:
        print(f"Komens is not available for this account (HTTP 403: {error.message or 'no reason given'}).",
              file=sys.stderr)
        return 1
    except BakalariError as error:
        print(f"Bakaláři error: {error}", file=sys.stderr)
        return 1

    unread = [message for message in messages if not message.read]
    print(f"{len(unread)} unread message(s) in the list (the server's counter says {counter}).")
    for message in unread:
        sent = f"{message.sent:%Y-%m-%d %H:%M}" if message.sent else "-"
        print(f"\n{sent}  {printable(message.sender.name)}: {printable(message.title)}")
        if message.needs_confirmation:
            print("(asks for a confirmation that it was read)")
        print(message.plain_text)                   # control characters are removed already

        if not message.attachments:
            continue
        # Ids are opaque strings; keep only safe characters for the folder name.
        target = Path(args.folder) / f"{sent[:10]}-{re.sub(r'[^0-9A-Za-z_-]', '_', message.id)}"
        target.mkdir(parents=True, exist_ok=True)
        for attachment in message.attachments:
            try:
                file = client.download_attachment(attachment)
                path = file.save(target)               # a sanitized file name inside the folder
            except FileExistsError as error:
                print(f"    kept the existing file {error.filename}")
            except BakalariHTTPError as error:        # e.g. HTTP 500 for an attachment that is gone
                print(f"    could not download {printable(attachment.name)}: HTTP {error.status}")
            else:
                print(f"    saved {path} ({file.size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
