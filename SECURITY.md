# Security policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| 1.x     | Yes       |
| < 1.0   | No        |

Security fixes are released as new 1.x versions. Upgrade to the latest release to get them.

## Reporting a vulnerability

Report vulnerabilities privately through GitHub's private vulnerability reporting:
[Report a vulnerability](https://github.com/robco/bakalari-api/security/advisories/new) (the repository's
Security tab, then "Report a vulnerability"). Don't open a public issue, pull request or discussion about a
security problem.

Please include:

- the affected version (`bakalari --version`) and your Python version,
- what the problem is and what an attacker could do with it,
- steps to reproduce, preferably with synthetic data or the offline test helpers in `tests/support.py`.

Never send real passwords, access or refresh tokens, session files or personal data of students, not even in a
private report. If reproducing the problem needs a real installation, describe the setup instead.

The maintainer aims to acknowledge a report within a week and will keep you informed. When a fix is released,
the advisory is published and credits you, unless you prefer otherwise.

## Scope

In scope are problems in this package and its `bakalari` command, for example:

- **Credential and token handling**: exposing the password, the access or refresh token, session data or a
  one-time web login link; sending credentials or tokens to a host other than the configured installation;
  weakening TLS certificate verification.
- **Leaking secrets or personal data** in log records (`-v`), exception messages, `repr()` or error output.
- **Unsafe file writes**: session files that other users can read, attachment downloads that write outside the
  chosen directory (for example through a file name sent by the server) or that overwrite files without `--force`.

Out of scope:

- Vulnerabilities in the Bakaláři server, its web application or its API. Report those to BAKALÁŘI software
  s.r.o. or to your school.
- Attacks that require control of the computer or the user account running the client.
- The fact that anyone who has the password or a valid refresh token can use the account. That is how the API
  works, so protect session files like passwords.

## Disclaimer

bakalari-api is an unofficial project. It is not affiliated with, endorsed by or supported by BAKALÁŘI software
s.r.o., the vendor of the Bakaláři school information system.
