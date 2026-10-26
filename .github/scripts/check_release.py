"""Check the release tag and changelog before building anything for publication."""

import os
import re
import runpy
from pathlib import Path

version = runpy.run_path("bakalari/_version.py")["__version__"]
if os.environ.get("GITHUB_REF_TYPE") != "tag" or os.environ.get("GITHUB_REF_NAME") != f"v{version}":
    raise SystemExit(f"Publish from the tag v{version}; it must match bakalari/_version.py.")

changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
section = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## |^\[[^\]]+\]: |\Z)",
                    changelog, flags=re.MULTILINE | re.DOTALL)
if not section or not section.group(1).strip():
    raise SystemExit(f"CHANGELOG.md needs a non-empty release section for {version}.")
print(f"Validated bakalari {version}")
