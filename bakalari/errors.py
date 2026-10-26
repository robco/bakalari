"""Exceptions raised by the Bakaláři client."""
from __future__ import annotations

from typing import Any, Collection, Iterable, Optional, Union

ExpectedStatus = Union[int, Collection[int]]


class BakalariError(Exception):
    """Base class of every error raised by this package."""


class BakalariConfigError(BakalariError):
    """Missing or invalid configuration, e.g. an unset credential environment variable."""


class BakalariConnectionError(BakalariError):
    """The Bakaláři server could not be reached (DNS, TLS, refused connection, timeout)."""


def _format_expected(expected: ExpectedStatus) -> str:
    if isinstance(expected, int):
        return str(expected)
    return " or ".join(str(status) for status in sorted(expected))


def _safe_path(path: str) -> str:
    """A request path or URL for diagnostics, without query or fragment secrets."""
    return path.split("#", 1)[0].split("?", 1)[0]


class BakalariHTTPError(BakalariError):
    """The server answered with an unexpected HTTP status.

    ``body`` holds the parsed error body for HTTP 4xx/5xx answers (the client redacts known credentials) and is
    ``None`` otherwise, so an unexpected successful token response never ends up in a message or a log.
    ``path`` and the exception message omit the request's query string and fragment.
    """

    def __init__(self, method: str, path: str, status: int, expected: ExpectedStatus, body: Any = None) -> None:
        self.method = method
        self.path = _safe_path(path)
        self.status = status
        self.expected = expected
        self.body = body
        detail = f": {body}" if body not in (None, "", {}) else ""
        super().__init__(
            f"Bakaláři API {method} {self.path} returned HTTP {status} instead of {_format_expected(expected)}{detail}"
        )

    @property
    def message(self) -> str:
        """The server's own error text (``Message`` or ``error_description``), or an empty string."""
        if isinstance(self.body, dict):
            return str(self.body.get("Message") or self.body.get("error_description") or self.body.get("error") or "")
        return self.body if isinstance(self.body, str) else ""


class BakalariAuthError(BakalariHTTPError):
    """Authentication failed: the token endpoint rejected the login or the refresh token (HTTP 400
    ``invalid_grant``), or an API endpoint refused the access token (HTTP 401)."""


class BakalariPermissionError(BakalariHTTPError):
    """HTTP 403: the account may not use the endpoint, e.g. the module is not enabled for the school or the
    user type (``Some privilege is missing (IsTeacher)``)."""


class BakalariNotFoundError(BakalariHTTPError):
    """HTTP 404: the endpoint or the requested object (message, attachment, subject, ...) does not exist."""


class BakalariContractError(BakalariError):
    """A response does not match the structure this client expects; ``problems`` lists every violation."""

    subject = "response"

    def __init__(self, problems: Iterable[str], subject: Optional[str] = None) -> None:
        self.problems = list(problems)
        super().__init__(
            f"The Bakaláři {subject or self.subject} violates its contract:\n- " + "\n- ".join(self.problems)
        )


class TimetableContractError(BakalariContractError):
    """The timetable payload does not match the documented structure; ``problems`` lists every violation."""

    subject = "timetable"
