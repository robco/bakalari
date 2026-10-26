"""The client core: configuration, the OAuth2 token lifecycle and the request method every endpoint module uses.

Authentication is OAuth2 on ``POST /api/login`` (form-encoded, client id ``ANDR`` of the official mobile app):
the password grant returns a Bearer access token valid for one hour and a refresh token, and the refresh-token
grant on the same endpoint renews both (the refresh token rotates; it expires after about a month without use).
The client keeps the tokens privately, logs in on the first authorized request, renews the access token shortly
before it expires and, when the server refuses a token anyway, renews it and retries the request once. Tokens and
the password never appear in ``repr()``, log records or exception messages.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import ssl
import threading
import time
import urllib.parse
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, Type, TypeVar, Union

from ._version import __version__
from .errors import (
    BakalariAuthError,
    BakalariConfigError,
    BakalariConnectionError,
    BakalariContractError,
    BakalariError,
    BakalariHTTPError,
    BakalariNotFoundError,
    BakalariPermissionError,
    ExpectedStatus,
    _safe_path,
)
from .http import HttpResponse, Transport, urllib_transport

log = logging.getLogger("bakalari.client")

DEFAULT_CLIENT_ID = "ANDR"
TOKEN_PATH = "/api/login"
API_PATH = "/api/3"
USERNAME_ENV = "BAKALARI_USERNAME"
PASSWORD_ENV = "BAKALARI_PASSWORD"
BASE_URL_ENV = "BAKALARI_URL"
METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH")
RETRY_METHODS = ("GET", "PUT", "DELETE")
RETRY_STATUSES = (502, 503, 504)
USER_AGENT = f"bakalari-python/{__version__}"
# Path segments that are web pages rather than the installation root, so a URL copied from the browser works.
_PAGE_SEGMENTS = ("login", "next", "api", "timetable", "dashboard", "logout")

SessionCallback = Callable[["SessionState"], None]
_Client = TypeVar("_Client", bound="ClientCore")


def normalize_base_url(url: str) -> str:
    """The installation root for a URL as users copy it: adds ``https://`` when the scheme is missing and drops
    the query, a trailing slash and a page path such as ``/login`` or ``/next/dash.aspx``.

    >>> normalize_base_url("skola.bakalari.cz/bakaweb/login")
    'https://skola.bakalari.cz/bakaweb'
    """
    url = (url or "").strip()
    if not url:
        raise BakalariConfigError(f"No Bakaláři address: pass base_url or set {BASE_URL_ENV}.")
    if "://" not in url:
        url = "https://" + url
    parts = urllib.parse.urlsplit(url)
    segments: List[str] = []
    for segment in parts.path.split("/"):
        if segment.lower() in _PAGE_SEGMENTS:
            break
        if segment:
            segments.append(segment)
    path = "/" + "/".join(segments) if segments else ""
    return urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc, path, "", ""))


@dataclass(frozen=True)
class TokenInfo:
    """The non-secret part of a token response; ``expires_at`` is the expiry in epoch seconds."""

    user_id: str
    token_type: str
    expires_in: int
    scope: str
    api_version: str
    expires_at: float

    @property
    def scopes(self) -> Tuple[str, ...]:
        return tuple(self.scope.split())


@dataclass(frozen=True)
class SessionState:
    """What it takes to resume a session without the password: the tokens and their metadata.

    Treat it like a password (store it, for instance, in a file only its owner can read): the refresh token
    grants access to the account for about a month. ``to_dict()`` and ``from_dict()`` convert it to JSON data.
    The tokens are left out of ``repr()``.
    """

    base_url: str
    refresh_token: str = field(repr=False)
    access_token: str = field(default="", repr=False)
    expires_at: float = 0.0
    user_id: str = ""
    scope: str = ""
    api_version: str = ""
    token_type: str = "Bearer"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SessionState":
        if not isinstance(data, Mapping) or not data.get("base_url") or not data.get("refresh_token"):
            raise BakalariConfigError("A Bakaláři session needs at least 'base_url' and 'refresh_token'.")
        return cls(
            base_url=str(data["base_url"]),
            refresh_token=str(data["refresh_token"]),
            access_token=str(data.get("access_token") or ""),
            expires_at=float(data.get("expires_at") or 0.0),
            user_id=str(data.get("user_id") or ""),
            scope=str(data.get("scope") or ""),
            api_version=str(data.get("api_version") or ""),
            token_type=str(data.get("token_type") or "Bearer"),
        )


def _expects(expected: Optional[ExpectedStatus], status: int) -> bool:
    if expected is None:
        return True
    if isinstance(expected, int):
        return status == expected
    return status in expected


def _html_title(response: HttpResponse) -> str:
    """The ``<title>`` of an HTML error page, decoded with the declared charset (IIS pages use windows-1250)."""
    charset = "utf-8"
    declared = re.search(r"charset=([\w-]+)", response.header("Content-Type") or "", re.I) or re.search(
        rb"charset=[\"']?([\w-]+)", response.body[:2048], re.I
    )
    if declared:
        value = declared.group(1)
        charset = value.decode("ascii", "replace") if isinstance(value, bytes) else value
    try:
        page = response.body.decode(charset, errors="replace")
    except LookupError:
        page = response.text
    title = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
    return " ".join(html.unescape(title.group(1)).split()) if title else ""


class ClientCore:
    """Configuration, tokens and requests of :class:`~bakalari.BakalariClient` (see there for the endpoints).

    ``base_url`` is the installation root that serves both the web and the API (the web login page is
    ``<base_url>/login``); a URL copied from the browser is accepted too. Pass ``username`` and ``password``,
    or a ``refresh_token`` (or :meth:`import_session`) to resume a session without the password.

    ``renew_margin`` is how many seconds before expiry the access token is renewed. ``retries`` re-sends GET, PUT
    and DELETE requests that fail with a connection error or HTTP 502/503/504, waiting ``retry_backoff`` seconds,
    then twice as long, and so on. ``on_session_update`` is called with the new :class:`SessionState` after every
    login and renewal, so an application can persist the rotating refresh token. ``transport``, ``clock`` and
    ``sleep`` exist for tests. The client is safe to share between threads.
    """

    def __init__(
        self,
        base_url: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        *,
        refresh_token: Optional[str] = None,
        client_id: str = DEFAULT_CLIENT_ID,
        timeout: float = 30.0,
        renew_margin: float = 60.0,
        retries: int = 0,
        retry_backoff: float = 0.5,
        ssl_context: Optional[ssl.SSLContext] = None,
        transport: Optional[Transport] = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        on_session_update: Optional[SessionCallback] = None,
        user_agent: str = USER_AGENT,
    ) -> None:
        self.base_url = normalize_base_url(base_url)
        self.client_id = client_id
        self.timeout = timeout
        self.renew_margin = renew_margin
        self.retries = max(0, int(retries))
        self.retry_backoff = retry_backoff
        self.user_agent = user_agent
        self.on_session_update = on_session_update
        self._username = username
        self._password = password
        self._transport = transport or urllib_transport(ssl_context)
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.RLock()
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = refresh_token or None
        self._token_info: Optional[TokenInfo] = None

    @classmethod
    def from_env(
        cls: Type[_Client],
        *,
        username_env: str = USERNAME_ENV,
        password_env: str = PASSWORD_ENV,
        base_url: Optional[str] = None,
        environ: Optional[Mapping[str, str]] = None,
        **kwargs: Any,
    ) -> _Client:
        """Creates a client with the login from environment variables (``BAKALARI_USERNAME`` and
        ``BAKALARI_PASSWORD`` by default) and the address from ``base_url`` or ``BAKALARI_URL``."""
        env = os.environ if environ is None else environ
        url = base_url or env.get(BASE_URL_ENV)
        missing = ([] if url else [BASE_URL_ENV]) + [name for name in (username_env, password_env) if not env.get(name)]
        if missing:
            raise BakalariConfigError(
                f"Missing environment variable(s): {', '.join(missing)}. Set the Bakaláři address and web login in "
                "the OS/user/session environment and restart the shell or IDE."
            )
        return cls(str(url), env[username_env], env[password_env], **kwargs)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self.base_url!r}, authenticated={self.is_authenticated})"

    def __enter__(self: _Client) -> _Client:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.logout()

    @property
    def is_authenticated(self) -> bool:
        """True while the client holds an access token (it may still need renewing)."""
        return self._token_info is not None

    @property
    def token_info(self) -> Optional[TokenInfo]:
        """The non-secret part of the current token, or ``None`` before the first login."""
        return self._token_info

    # --- Public endpoints (no login) ---------------------------------------------------------------------

    def available_api_versions(self) -> List[Dict[str, Any]]:
        """``GET /api``: the API versions the installation serves, e.g. ``[{"ApiVersion": "3.52.1", ...}]``."""
        data = self.get_json("/api", authorized=False)
        if not isinstance(data, list):
            raise BakalariContractError(["GET /api must return a JSON array"], "API version list")
        return data

    def api_version(self) -> Dict[str, Any]:
        """``GET /api/3``: ``ApiVersion`` (e.g. 3.52.1), ``ApplicationVersion`` and ``BaseUrl``."""
        data = self.get_json(API_PATH, authorized=False)
        if not isinstance(data, dict):
            raise BakalariContractError([f"GET {API_PATH} must return a JSON object"], "API version")
        return data

    # --- Authentication ----------------------------------------------------------------------------------

    def login(self, username: Optional[str] = None, password: Optional[str] = None) -> TokenInfo:
        """Logs in with the OAuth2 password grant and stores the tokens; defaults to the client's login.

        Raises :class:`BakalariAuthError` (HTTP 400, ``body["error"] == "invalid_grant"``) for a wrong login.
        A rejected login keeps the previous tokens and login. Bakaláři counts failed logins per account and
        shows them to the account owner, so never probe a real account with a wrong password.
        """
        username = self._username if username is None else username
        password = self._password if password is None else password
        if not username or not password:
            raise BakalariConfigError(
                "No Bakaláři login: pass username and password, a refresh token, or create the client with "
                "BakalariClient.from_env()."
            )
        with self._lock:
            response = self._token_request({"grant_type": "password", "username": username, "password": password})
            info = self._store_tokens(response)
            self._username, self._password = username, password
        log.info("Logged in to the Bakaláři API as user %s (API %s)", info.user_id, info.api_version)
        self._notify_session_update()
        return info

    def refresh(self) -> TokenInfo:
        """Renews the tokens with the refresh-token grant, without sending the password again."""
        with self._lock:
            if not self._refresh_token:
                raise BakalariError("No Bakaláři refresh token is stored: call login() first.")
            response = self._token_request({"grant_type": "refresh_token", "refresh_token": self._refresh_token})
            info = self._store_tokens(response)
        log.info("Renewed the Bakaláři API tokens")
        self._notify_session_update()
        return info

    def ensure_token(self) -> TokenInfo:
        """Logs in (or renews a stored refresh token) when there is no access token yet, renews the access token
        when it expires within ``renew_margin`` seconds, and returns the current token info."""
        with self._lock:
            if self._token_info is None or not self._access_token:
                return self._renew() if self._refresh_token else self.login()
            if self._clock() >= self._token_info.expires_at - self.renew_margin:
                return self._renew()
            return self._token_info

    def logout(self) -> None:
        """Forgets the tokens. The API has no revocation endpoint; the access token expires within an hour."""
        with self._lock:
            self._access_token = self._refresh_token = None
            self._token_info = None

    def export_session(self) -> SessionState:
        """The current tokens as a :class:`SessionState` to resume later with :meth:`import_session` or the
        ``refresh_token`` argument. It holds secrets: store it like a password."""
        with self._lock:
            if not self._refresh_token:
                raise BakalariError("No Bakaláři session to export: log in first.")
            info = self._token_info
            return SessionState(
                base_url=self.base_url,
                refresh_token=self._refresh_token,
                access_token=self._access_token or "",
                expires_at=info.expires_at if info else 0.0,
                user_id=info.user_id if info else "",
                scope=info.scope if info else "",
                api_version=info.api_version if info else "",
                token_type=info.token_type if info else "Bearer",
            )

    def import_session(self, state: Union[SessionState, Mapping[str, Any]]) -> None:
        """Resumes a session exported by :meth:`export_session` (or its ``to_dict()`` data). A still valid access
        token is reused; otherwise the next request renews the tokens with the refresh token."""
        if not isinstance(state, SessionState):
            state = SessionState.from_dict(state)
        if normalize_base_url(state.base_url) != self.base_url:
            raise BakalariConfigError(f"The session belongs to {state.base_url}, not to {self.base_url}.")
        with self._lock:
            self._refresh_token = state.refresh_token
            if state.access_token and state.expires_at > self._clock():
                self._access_token = state.access_token
                self._token_info = TokenInfo(
                    user_id=state.user_id,
                    token_type=state.token_type,
                    expires_in=max(0, int(state.expires_at - self._clock())),
                    scope=state.scope,
                    api_version=state.api_version,
                    expires_at=state.expires_at,
                )
            else:
                self._access_token, self._token_info = None, None

    def _renew(self) -> TokenInfo:
        with self._lock:
            try:
                return self.refresh()
            except BakalariAuthError:
                if not (self._username and self._password):
                    raise
                log.info("The Bakaláři refresh token was rejected; logging in again")
                return self.login()

    def _notify_session_update(self) -> None:
        if self.on_session_update is not None:
            self.on_session_update(self.export_session())

    def _token_request(self, grant: Mapping[str, str]) -> HttpResponse:
        form = {"client_id": self.client_id, **grant}
        return self.request("POST", TOKEN_PATH, form=form, authorized=False)

    def _store_tokens(self, response: HttpResponse) -> TokenInfo:
        try:
            body = response.json() or {}
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        access_token, refresh_token = body.get("access_token"), body.get("refresh_token")
        try:
            expires_in = int(body.get("expires_in") or 0)
        except (TypeError, ValueError):
            expires_in = 0
        token_type = str(body.get("token_type") or "")
        if not access_token or not refresh_token or expires_in <= 0 or token_type.lower() != "bearer":
            raise BakalariError(
                "The Bakaláři token response lacks a Bearer access_token, a refresh_token or a positive expires_in."
            )
        info = TokenInfo(
            user_id=str(body.get("bak:UserId") or ""),
            token_type=token_type,
            expires_in=expires_in,
            scope=str(body.get("scope") or ""),
            api_version=str(body.get("bak:ApiVersion") or ""),
            expires_at=self._clock() + expires_in,
        )
        with self._lock:
            self._access_token, self._refresh_token, self._token_info = access_token, refresh_token, info
        return info

    # --- Requests ----------------------------------------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        form: Optional[Mapping[str, Any]] = None,
        json_body: Any = None,
        data: Optional[bytes] = None,
        headers: Optional[Mapping[str, str]] = None,
        authorized: bool = True,
        access_token: Optional[str] = None,
        expected_status: Optional[ExpectedStatus] = 200,
    ) -> HttpResponse:
        """Sends a request (``path`` relative to the base URL, e.g. ``/api/3/user``) and returns the response.

        ``params`` become the query string (``None`` values are left out), ``form`` a form-encoded body,
        ``json_body`` a JSON body and ``data`` a raw body (pass its ``Content-Type`` in ``headers``, e.g. for a
        multipart upload). With ``authorized`` the request carries the managed Bearer token (logging in or
        renewing it first as needed, and renewing once more and retrying when the server answers 401), or
        ``access_token`` when given, e.g. a forged token for a negative check. A status not in
        ``expected_status`` (an int or a collection of ints; ``None`` accepts any) raises
        :class:`BakalariAuthError` (HTTP 401, or HTTP 400 from the token endpoint),
        :class:`BakalariPermissionError` (403), :class:`BakalariNotFoundError` (404) or
        :class:`BakalariHTTPError`.
        """
        method = method.upper()
        if method not in METHODS:
            raise ValueError(f"Unsupported method {method!r}: use one of {', '.join(METHODS)}")
        if sum(body is not None for body in (form, json_body, data)) > 1:
            raise ValueError("Pass only one of form, json_body and data")
        if not path.startswith("/"):
            path = "/" + path
        managed = authorized and access_token is None
        if managed:
            self.ensure_token()
        token = (self._access_token if managed else access_token) if authorized else None
        response = self._send(method, path, params, form, json_body, data, headers, token)
        if managed and response.status == 401 and not _expects(expected_status, 401):
            log.info("The Bakaláři API refused the access token; renewing it and retrying once")
            self._renew()
            response = self._send(method, path, params, form, json_body, data, headers, self._access_token)
        if not _expects(expected_status, response.status):
            raise self._unexpected_status(method, path, response, expected_status or 200)
        return response

    def get_json(
        self, path: str, params: Optional[Mapping[str, Any]] = None, *, authorized: bool = True
    ) -> Any:
        """``GET`` an endpoint and return its decoded JSON body (``None`` for an empty body)."""
        return self._decode_json("GET", path, self.request("GET", path, params=params, authorized=authorized))

    def post_json(
        self,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        form: Optional[Mapping[str, Any]] = None,
        json_body: Any = None,
        expected_status: ExpectedStatus = 200,
    ) -> Any:
        """``POST`` to an authorized endpoint and return its decoded JSON body (``None`` for an empty body)."""
        response = self.request(
            "POST", path, params=params, form=form, json_body=json_body, expected_status=expected_status
        )
        return self._decode_json("POST", path, response)

    @staticmethod
    def _decode_json(method: str, path: str, response: HttpResponse) -> Any:
        try:
            return response.json()
        except ValueError:
            kind = response.content_type or "no content type"
            raise BakalariContractError(
                [f"{method} {_safe_path(path)} returned {kind} instead of JSON (HTTP {response.status})"], "response"
            ) from None

    def _send(
        self,
        method: str,
        path: str,
        params: Optional[Mapping[str, Any]],
        form: Optional[Mapping[str, Any]],
        json_body: Any,
        data: Optional[bytes],
        extra_headers: Optional[Mapping[str, str]],
        token: Optional[str],
    ) -> HttpResponse:
        url = self.base_url + path
        query = {key: value for key, value in (params or {}).items() if value is not None}
        if query:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(query, doseq=True)
        # Some installations answer every request without Accept-Language with HTTP 500, as the mobile app sends it.
        headers = {"Accept": "application/json", "Accept-Language": "cs", "User-Agent": self.user_agent}
        body = data
        if form is not None:
            body = urllib.parse.urlencode(form, doseq=True).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif json_body is not None:
            body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        headers.update(extra_headers or {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        attempts = 1 + (self.retries if method in RETRY_METHODS else 0)
        diagnostic_path = _safe_path(path)
        for attempt in range(attempts):
            last = attempt == attempts - 1
            try:
                response = self._transport(method, url, headers, body, self.timeout)
            except BakalariConnectionError as error:
                if last:
                    raise
                log.info("%s %s failed (%s); retrying", method, diagnostic_path, error)
            else:
                log.debug("%s %s -> HTTP %s", method, diagnostic_path, response.status)
                if last or response.status not in RETRY_STATUSES:
                    return response
                log.info("%s %s answered HTTP %s; retrying", method, diagnostic_path, response.status)
            self._sleep(self.retry_backoff * (2 ** attempt))
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _unexpected_status(
        method: str, path: str, response: HttpResponse, expected: ExpectedStatus
    ) -> BakalariHTTPError:
        body: Any = None
        if response.status >= 400:  # error bodies carry no tokens; a successful token response would
            try:
                body = response.json()
            except ValueError:
                body = _html_title(response) if "html" in response.content_type else response.text[:500]
        error_class: Type[BakalariHTTPError]
        if response.status == 401 or (path == TOKEN_PATH and response.status == 400):
            error_class = BakalariAuthError
        elif response.status == 403:
            error_class = BakalariPermissionError
        elif response.status == 404:
            error_class = BakalariNotFoundError
        else:
            error_class = BakalariHTTPError
        return error_class(method, path, response.status, expected, body)


def api_path(*segments: Any) -> str:
    """``/api/3/...`` from literal path segments (callers quote ids with ``quote_segment``)."""
    return API_PATH + "".join(f"/{segment}" for segment in segments)

