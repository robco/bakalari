"""Test doubles: a scripted transport, canned responses, the fixtures and a client factory."""
from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, Union

from bakalari import BakalariClient, HttpResponse

FIXTURES = Path(__file__).parent / "fixtures"
BASE_URL = "https://school.example/bakaweb"
USERNAME = "test.user"
PASSWORD = "Secret-Pa55word"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_text_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def json_response(status: int, payload: Any) -> HttpResponse:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    return HttpResponse(status, headers, json.dumps(payload).encode("utf-8"))


def text_response(
    status: int, text: str, content_type: str = "text/html; charset=utf-8", url: str = ""
) -> HttpResponse:
    return HttpResponse(status, {"Content-Type": content_type}, text.encode("utf-8"), url)


def binary_response(content: bytes, headers: Optional[Mapping[str, str]] = None, status: int = 200) -> HttpResponse:
    return HttpResponse(status, dict(headers or {"Content-Type": "application/octet-stream"}), content)


def empty_response(status: int = 204) -> HttpResponse:
    return HttpResponse(status, {}, b"")


def token_response(access: str = "access-1", refresh: str = "refresh-1", expires_in: int = 3600) -> HttpResponse:
    return json_response(200, {
        "bak:UserId": "U1", "access_token": access, "token_type": "Bearer", "expires_in": expires_in,
        "scope": "offline_access bakalari_api timetable_widget", "refresh_token": refresh,
        "bak:ApiVersion": "3.52.1", "bak:AppVersion": "2.2.1009.7",
    })


INVALID_GRANT = json_response(400, {
    "error": "invalid_grant", "error_description": "Špatný login nebo heslo",
    "error_uri": "https://documentation.openiddict.com/errors/ID2024",
})
UNAUTHORIZED = json_response(401, {"Message": "Authorization has been denied for this request."})
FORBIDDEN = json_response(403, {"Message": "An error has occurred."})
NOT_TEACHER = json_response(403, {"Message": "Some privilege is missing (IsTeacher)."})


@dataclass
class Call:
    method: str
    url: str
    headers: Dict[str, str]
    body: Optional[bytes]

    @property
    def path(self) -> str:
        return urllib.parse.urlsplit(self.url).path

    @property
    def raw_path(self) -> str:
        """The path as sent, still percent-encoded (``path`` is the same; kept for readability in tests)."""
        return urllib.parse.urlsplit(self.url).path

    @property
    def api_path(self) -> str:
        """The path after the base URL's ``/bakaweb`` prefix, e.g. ``/api/3/marks``."""
        prefix = urllib.parse.urlsplit(BASE_URL).path
        return self.path[len(prefix):] if self.path.startswith(prefix) else self.path

    @property
    def query(self) -> Dict[str, str]:
        return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.url).query))

    @property
    def form(self) -> Dict[str, str]:
        return dict(urllib.parse.parse_qsl((self.body or b"").decode("utf-8")))

    @property
    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8")) if self.body else None


Responder = Union[HttpResponse, Callable[[Call], HttpResponse], BaseException]


class FakeTransport:
    """Answers each request with the next scripted response (an exception instance is raised) and records the
    calls."""

    def __init__(self, *responses: Responder) -> None:
        self.responses: List[Any] = list(responses)
        self.calls: List[Call] = []

    def __call__(
        self, method: str, url: str, headers: Mapping[str, str], body: Optional[bytes], timeout: float
    ) -> HttpResponse:
        call = Call(method, url, dict(headers), body)
        self.calls.append(call)
        if not self.responses:
            raise AssertionError(f"Unexpected request {method} {url}")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response(call) if callable(response) else response

    @property
    def api_calls(self) -> List[Call]:
        """The calls after the login, i.e. without requests to the token endpoint."""
        return [call for call in self.calls if not call.path.endswith("/api/login")]


class FakeClock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def make_client(
    *responses: Responder, clock: Optional[FakeClock] = None, **kwargs: Any
) -> Tuple[BakalariClient, FakeTransport]:
    """A client with a scripted transport; the first authorized request consumes a token response."""
    transport = FakeTransport(*responses)
    client = BakalariClient(
        BASE_URL + "/", USERNAME, PASSWORD, transport=transport, clock=clock or FakeClock(), **kwargs
    )
    return client, transport


def logged_in_client(*responses: Responder, **kwargs: Any) -> Tuple[BakalariClient, FakeTransport]:
    """Like :func:`make_client`, but prepends the token response of the implicit first login."""
    return make_client(token_response(), *responses, **kwargs)
