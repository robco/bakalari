## What and why

<!-- What does this pull request change, and why? Link the issue it resolves, e.g. "Fixes #12". -->

## Checklist

- [ ] Tests added or updated (offline and deterministic, in `tests/test_<area>.py`)
- [ ] The offline suite passes on Python 3.9 and on the latest Python: `BAKALARI_SKIP_LIVE=1 python -m unittest discover`
- [ ] Fixtures contain synthetic data only: no real names, ids, marks, messages, schools or tokens
- [ ] `ruff check .` and `mypy bakalari` pass
- [ ] Documentation updated (README, docs, docstrings)
- [ ] `CHANGELOG.md` updated under "Unreleased"
- [ ] No passwords, tokens, session files or personal data in the code, commits, logs or screenshots

<!-- Changed an endpoint? Say whether you ran the read-only live tests (tests/test_live.py) and with which account type. -->
