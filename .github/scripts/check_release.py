"""Check the release tag and changelog before building anything for publication."""

import os
import re
import runpy
from datetime import date
from pathlib import Path

version = runpy.run_path("bakalari/_version.py")["__version__"]
if os.environ.get("GITHUB_REF_TYPE") != "tag" or os.environ.get("GITHUB_REF_NAME") != f"v{version}":
    raise SystemExit(f"Publish from the tag v{version}; it must match bakalari/_version.py.")

changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
unreleased = re.search(r"^## \[Unreleased\]\s*\n(.*?)(?=^## |^\[[^\]]+\]: |\Z)",
                       changelog, flags=re.MULTILINE | re.DOTALL)
if unreleased and unreleased.group(1).strip():
    raise SystemExit("Move Unreleased notes into the versioned changelog section before publishing.")
section = re.search(rf"^## \[{re.escape(version)}\] - (\d{{4}}-\d{{2}}-\d{{2}})\n(.*?)(?=^## |^\[[^\]]+\]: |\Z)",
                    changelog, flags=re.MULTILINE | re.DOTALL)
if not section or not section.group(2).strip():
    raise SystemExit(f"CHANGELOG.md needs a dated, non-empty release section for {version}.")
try:
    date.fromisoformat(section.group(1))
except ValueError:
    raise SystemExit("The release changelog date must be a valid YYYY-MM-DD date.") from None
print(f"Validated bakalari {version}")
