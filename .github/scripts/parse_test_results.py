"""Append a pytest JUnit report to the GitHub Actions job summary."""

import os
import xml.etree.ElementTree as ET
from pathlib import Path


def main():
    report = Path("reports/test-results.xml")
    lines = ["## Test results", ""]
    if report.exists():
        root = ET.parse(report).getroot()
        suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
        counts = {key: sum(int(s.get(key, "0")) for s in suites)
                  for key in ("tests", "failures", "errors", "skipped")}
        passed = counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"]
        lines += ["| Total | Passed | Failed | Errors | Skipped |", "|---|---|---|---|---|",
                  f'| {counts["tests"]} | {passed} | {counts["failures"]} | {counts["errors"]} | {counts["skipped"]} |']
        if not counts["tests"] or counts["failures"] or counts["errors"]:
            lines += ["", "Tests did not pass; see the test report and workflow logs."]
    else:
        lines += ["No test report was produced. Check the preceding steps."]
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as summary:
        summary.write("\n".join(lines) + "\n\n")


if __name__ == "__main__":
    main()
