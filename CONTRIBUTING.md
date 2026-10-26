# Contributing to bakalari

Thank you for helping. This guide covers the development setup, the tests, the code conventions and the release
process. By taking part you agree to follow the [code of conduct](CODE_OF_CONDUCT.md). Report security problems
privately as described in [SECURITY.md](SECURITY.md), never in a public issue.

## Development setup

You need Python 3.9 or newer. The package has no runtime dependencies. Test your changes on the oldest supported
Python (3.9) and on the newest.

```bash
git clone https://github.com/robco/bakalari.git
cd bakalari
python3 -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
```

mypy stays below version 2 because mypy 2 can no longer check code against Python 3.9 (`python_version` in
`pyproject.toml`).

## Tests

### Offline tests

The offline suite needs no network and no account. It drives the client through a scripted transport
(`FakeTransport` in `unittests/support.py`) and uses the synthetic fixtures in `unittests/fixtures/`.

```bash
python -m pytest                                      # the whole offline suite
python -m unittest unittests.test_marks -v             # one test module, no test dependencies
python -m pytest --cov=bakalari --cov-fail-under=90    # CI coverage threshold
```

The default pytest discovery path is `unittests/`, so it never selects live tests even when credentials are
present. Without third-party test tools, run `python -m unittest discover -s unittests -t . -v`.

### MCP SDK interoperability

On Python 3.10 or newer, install the optional reference client and run the offline interoperability test:

```bash
python -m pip install -e ".[dev,mcp-test]"
python -m pytest tests/test_mcp_sdk.py
```

CI runs this test alongside the unit tests under coverage. It uses synthetic school responses and requires no
account. The installed library and MCP server still have no runtime dependencies.

### Live tests (read-only)

`tests/test_live.py` runs against a real Bakaláři installation when all three variables are set and
`BAKALARI_SKIP_LIVE` is not:

```bash
export BAKALARI_URL=https://...        # the address of your school's Bakaláři web
export BAKALARI_USERNAME=...
export BAKALARI_PASSWORD=...
python -m unittest tests.test_live -v
```

Set `BAKALARI_SKIP_LIVE=1` to skip them even when the credentials are set. CI never runs them. The rules for
live tests:

- **They never change data.** No marking messages as read, no sending messages, no confirming marks, no marking
  homework as done, no consent changes, no notification registration: only read endpoints.
- **They never use a wrong password with a real username.** Bakaláři counts failed logins and shows them to the
  account owner at the next login. The negative login test uses a random, unknown username.
- They assert structure only (types, non-negative counters, parsing with validation on), never concrete personal
  values, and they skip (`skipTest`) when the school or account has a module disabled (`BakalariPermissionError`).
- Their output can contain personal data. Don't paste it into issues or pull requests unless it's redacted.

## Fixture privacy rule

Fixtures are synthetic. Copy the **shape** of a real response (keys, nesting, value types, enum values,
space-padded ids, empty and null fields) but never its values. Invent the names, ids, texts, marks and dates, and
use `https://school.example/bakaweb` as the address. Never commit a real name, id, school, message text or token,
not even from your own account, and never commit a captured response with the plan to anonymize it later.

## Code conventions

The package uses only the standard library and runs on Python 3.9. Keep `from __future__ import annotations` and
the `typing` style (`Optional`, `Dict`, `List`, `Tuple`, `Mapping`). Don't use `match`, `X | Y` at runtime,
`dataclass(slots=..., kw_only=...)`, `zip(strict=...)` or `datetime.UTC`.

1. **One module per Bakaláři area** (`marks.py`, `komens.py`, ...) holds the area's response models and its
   `XxxEndpoints(ClientCore)` mixin, which `BakalariClient` combines. Endpoint methods are thin: they build the
   path (ids go through `quote_segment`), call `get_json`, `post_json` or `request`, and parse the result with the
   model's `from_json`.
2. **Models** are `@dataclass(frozen=True)` subclasses of `Model` with a `from_json` classmethod. Entity models end
   with a `raw` field holding the original object, which is hidden from `repr()` and `to_dict()`. Field names are
   the snake_case API names (`school_class` for `Class`), and collections are tuples.
3. **Values** go through the `bakalari._parse` helpers: ids exact (`ident`), display strings trimmed (`text`),
   timestamps as aware `datetime` (`parse_datetime`) or `date` (`parse_date`), numbers and booleans via
   `to_int`, `to_float` and `to_bool`, `{Id, Abbrev, Name}` objects as `Item`, and attachments as
   `AttachmentInfo`. Parsing is lenient: a missing optional field gets a default.
4. **Contract checks**: a top-level `from_json(data, *, validate=True)` checks the essential shape with
   `check_shape` when it validates, and with `require_mapping` or `require_list` always. Endpoint methods take
   `validate: bool = True` and pass it on. Counter endpoints use `require_int`.
5. **Dates in requests** are formatted with `format_date`. Date parameters are named `since` and `until` and
   accept a `date`, a `datetime` or an ISO string.
6. **Docstrings** in English on every public class and method: one or two sentences naming the HTTP method and
   path (``GET /api/3/marks``) and notable server behaviour. Comments only explain non-obvious server quirks.
7. **Errors** are never swallowed. Endpoints that need a module or a right let `BakalariPermissionError`
   propagate. Tokens and passwords never appear in messages, log records or `repr()`.
8. **Tests** are offline and deterministic (`unittest`), one test module per area module (`unittests/test_marks.py`),
   with synthetic fixtures `unittests/fixtures/<area>*.json`. They cover model parsing (padded ids, nulls, missing
   fields), `to_dict()` JSON round trips, the HTTP method, path (including percent-encoded ids), query and body of
   every endpoint method, status handling, contract errors and lenient parsing.

## Lint and type check

```bash
ruff check .        # pycodestyle, pyflakes, isort, bugbear and comprehensions; line length 120
mypy bakalari       # the settings in pyproject.toml, checked against Python 3.9 (needs mypy < 2)
```

Ruff's pyupgrade (`UP`) rules are off on purpose, so that the `Optional[...]` typing style stays.

To check the packaging the way CI does:

```bash
python -m build
twine check --strict dist/*
```

## Pull requests

Keep a pull request focused on one change, add tests, update the documentation and add an entry to
`CHANGELOG.md` under "Unreleased". CI runs the offline tests on Python 3.9 to 3.14 on Linux and on Python 3.13 on
macOS and Windows, checks coverage (at least 90 %), runs ruff and mypy, and builds the package, checking the wheel
by installing it into a fresh virtual environment. Python 3.12 runs the combined test/build job, which also
checks the MCP SDK and uploads JUnit, HTML and coverage reports. The remaining matrix jobs use only the standard
library to check compatibility.

## Release process

Versions follow [Semantic Versioning](https://semver.org/). The version is set in one place,
`bakalari/_version.py`. Setuptools reads that value for the distribution, and the library, CLI and MCP server
use it at runtime. The filename is a project convention, not a GitHub Actions or PyPI requirement

1. Set `__version__ = "X.Y.Z"` in `bakalari/_version.py`.
2. In `CHANGELOG.md`, rename "Unreleased" to `## [X.Y.Z] - YYYY-MM-DD`, add a new empty "Unreleased"
   section above it, and update the link references at the bottom.
3. Commit the changes, push to `main`, and wait for **Python Package CI** to pass.
4. Create and push the release tag:

   ```bash
   git tag -a vX.Y.Z -m "bakalari X.Y.Z"
   git push origin vX.Y.Z
   ```

5. On GitHub, publish a release for that tag and use the changelog section as its release notes. The
   [Python Package Publish workflow](.github/workflows/python-publish.yml) starts on `release: published`.
   It builds the wheel and source distribution, uploads them as `release-dists`, then publishes them to PyPI.
   A tag push alone does not publish a package.

Publishing does not rerun CI or enforce tag naming or changelog formatting. The package version comes from
`bakalari/_version.py` in the selected checkout, regardless of the branch, tag or release name.
CI runs tests, lint, type and distribution checks separately; its `python-package` artifact and test and
coverage reports are retained for 30 days. The publish job uses the `pypi` environment and OpenID Connect
trusted publishing to upload the distributions from its own build job.

To publish manually, select a branch or tag in GitHub's **Run workflow** dialog, or use:

```bash
gh workflow run python-publish.yml --ref main
# Or publish a specific tag:
gh workflow run python-publish.yml --ref vX.Y.Z
```

A manual run also publishes to **PyPI**. PyPI accepts each distribution filename only once; bump the package
version before a new release and check a partially completed upload before retrying. For a local build
check without publishing, use `python -m build`, `python -m twine check --strict dist/*` and
`python .github/scripts/check_distribution.py`.

### First-time setup and migration

1. On GitHub, create the `pypi` environment (Settings, Environments). Allow the branches and tags you intend
   to publish from; remove any tag-only restriction if you want manual publishing from `main`.
2. Configure a [PyPI trusted publisher](https://docs.pypi.org/trusted-publishers/adding-a-publisher/):
   - PyPI project: `bakalari`
   - Owner: `robco`
   - Repository: `bakalari`
   - Workflow filename: `python-publish.yml`
   - Environment: `pypi`

   If the project does not exist, add a pending publisher in the account's Publishing settings. No API token
   is needed. If migrating from the previous workflow, replace the publisher for `release.yml` with the one
   above; PyPI matches the workflow filename exactly.
3. If branch protection requires the old CI job names, update those required checks to the checks reported by
   **Python Package CI**, including the compatibility matrix and **Test & Build (Python 3.12)**.
4. The old tag-push publisher and manual TestPyPI rehearsal are replaced by this release-based workflow.
   The `testpypi` environment and its publisher are no longer used.
5. Enable private vulnerability reporting (Settings, Advanced Security, Private vulnerability reporting), which
   SECURITY.md and the issue forms link to.
