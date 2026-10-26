"""Validate distribution contents and smoke-test an installed wheel away from the checkout."""

import runpy
import subprocess
import tarfile
import tempfile
import venv
import zipfile
from pathlib import Path


def main():
    wheels = sorted(Path("dist").glob("*.whl"))
    sdists = sorted(Path("dist").glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise SystemExit("Expected exactly one wheel and one sdist in dist/.")
    with zipfile.ZipFile(wheels[0]) as wheel:
        wheel_files = wheel.namelist()
    with tarfile.open(sdists[0]) as sdist:
        sdist_files = [name.partition("/")[2] for name in sdist.getnames()]
    problems = []
    if "bakalari/py.typed" not in wheel_files:
        problems.append("the wheel has no bakalari/py.typed")
    if any(name.startswith(("tests/", "unittests/")) for name in wheel_files):
        problems.append("the wheel contains tests")
    if not any(name.endswith(".dist-info/licenses/LICENSE") for name in wheel_files):
        problems.append("the wheel has no LICENSE")
    for required in ("LICENSE", "CHANGELOG.md", "bakalari/py.typed", "unittests/support.py",
                     "unittests/__init__.py", "tests/test_live.py", "tests/test_mcp_sdk.py", "docs/guide.md"):
        if required not in sdist_files:
            problems.append(f"the sdist has no {required}")
    if any(name.startswith((".github/", ".claude/", "reports/")) for name in sdist_files):
        problems.append("the sdist contains repository tooling or generated reports")
    if problems:
        raise SystemExit("\n".join(problems))

    version = runpy.run_path("bakalari/_version.py")["__version__"]
    with tempfile.TemporaryDirectory(prefix="bakalari-wheel-") as directory:
        root = Path(directory)
        builder = venv.EnvBuilder(with_pip=True)
        builder.create(root / "venv")
        context = builder.ensure_directories(root / "venv")
        python = context.env_exe
        scripts = Path(context.bin_path)
        suffix = ".exe" if Path(python).suffix == ".exe" else ""
        cli = str(scripts / f"bakalari{suffix}")
        mcp = str(scripts / f"bakalari-mcp{suffix}")
        subprocess.run([python, "-m", "pip", "install", "--no-deps", str(wheels[0].resolve())],
                       cwd=root, check=True, timeout=120)
        result = subprocess.run([cli, "--version"], cwd=root, check=True, capture_output=True,
                                text=True, timeout=30)
        if result.stdout.strip() != f"bakalari {version}":
            raise SystemExit(f"Unexpected CLI version: {result.stdout!r}")
        for command in ([python, "-m", "bakalari", "--help"], [mcp, "--help"],
                        [python, "-m", "bakalari", "mcp"]):
            subprocess.run(command, cwd=root, check=True, input="", capture_output=True,
                           text=True, timeout=30)
    print(f"Validated {wheels[0].name} and {sdists[0].name}; installed entry points work.")


if __name__ == "__main__":
    main()
