"""Append coverage.py XML totals to the GitHub Actions job summary."""

import os
import xml.etree.ElementTree as ET
from pathlib import Path


def main():
    report = Path("reports/coverage.xml")
    lines = ["## Coverage", ""]
    if report.exists():
        root = ET.parse(report).getroot()
        lines += ["| Coverage | Rate |", "|---|---|"]
        for label, key in (("Lines", "line-rate"), ("Branches", "branch-rate")):
            lines.append(f'| {label} | {float(root.get(key, "0")):.2%} |')
    else:
        lines += ["No coverage report was produced. Check the test step."]
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as summary:
        summary.write("\n".join(lines) + "\n\n")


if __name__ == "__main__":
    main()
