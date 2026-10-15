# Contributing to bakalari-api

Thank you for helping. This guide covers the development setup, the tests, the code conventions and the release
process. By taking part you agree to follow the [code of conduct](CODE_OF_CONDUCT.md). Report security problems
privately as described in [SECURITY.md](SECURITY.md), never in a public issue.

## Development setup

You need Python 3.9 or newer. The package has no runtime dependencies. Test your changes on the oldest supported
Python (3.9) and on the newest.

```bash
git clone https://github.com/robco/bakalari-api.git
cd bakalari-api
python3 -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
python -m pip install -e .
python -m pip install ruff "mypy<2" build twine coverage
```

mypy stays below version 2 because mypy 2 can no longer check code against Python 3.9 (`python_version` in
`pyproject.toml`).

## Tests

### Offline tests

The offline suite needs no network and no account. It drives the client through a scripted transport
(`FakeTransport` in `tests/support.py`) and uses the synthetic fixtures in `tests/fixtures/`.

```bash
BAKALARI_SKIP_LIVE=1 python -m unittest discover -v    # the whole offline suite
python -m unittest tests.test_marks -v                  # one test module
coverage run -m unittest discover && coverage report    # CI requires at least 90 %
```

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
8. **Tests** are offline and deterministic (`unittest`), one test module per area module (`tests/test_marks.py`),
   with synthetic fixtures `tests/fixtures/<area>*.json`. They cover model parsing (padded ids, nulls, missing
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
by installing it into a fresh virtual environment.

## Release process

Versions follow [Semantic Versioning](https://semver.org/). The version is set in one place,
`bakalari/_version.py`.

1. Set `__version__ = "X.Y.Z"` in `bakalari/_version.py`.
2. In `CHANGELOG.md`, rename the "Unreleased" section to `## [X.Y.Z] - YYYY-MM-DD`, add a new empty "Unreleased"
   section above it, and update the link references at the bottom.
3. Commit (`git commit -am "Release X.Y.Z"`), push to `main`, and wait for CI to pass.
4. Tag the commit and push the tag:

   ```bash
   git tag -a vX.Y.Z -m "bakalari-api X.Y.Z"
   git push origin vX.Y.Z
   ```

5. The [Release workflow](.github/workflows/release.yml) checks that the tag is `v` plus the version in
   `bakalari/_version.py` and that `CHANGELOG.md` has a section for it. It then runs CI, publishes the sdist and
   the wheel to PyPI with trusted publishing (environment `pypi`), and creates the GitHub Release with the changelog
   section as its notes and the distribution files attached.

To rehearse a release, start the Release workflow by hand (Actions, Release, Run workflow). It runs the same
checks and publishes to TestPyPI (environment `testpypi`). TestPyPI accepts each version only once.

### First-time setup

1. On GitHub, under Settings, Environments, create the environments `pypi` and `testpypi`. For `pypi`, protection
   rules are recommended: required reviewers, and deployments only from tags matching `v*`.
2. On PyPI, open [Publishing](https://pypi.org/manage/account/publishing/) in your account settings and add a
   pending GitHub Actions publisher:
   - PyPI Project Name: `bakalari-api`
   - Owner: `robco`
   - Repository name: `bakalari-api`
   - Workflow name: `release.yml`
   - Environment name: `pypi`

   The first release creates the project on PyPI. No API token is needed.
3. For the rehearsal, add the same publisher on [TestPyPI](https://test.pypi.org/manage/account/publishing/) with
   the environment name `testpypi`.
4. Enable private vulnerability reporting (Settings, Advanced Security, Private vulnerability reporting), which
   SECURITY.md and the issue forms link to.
