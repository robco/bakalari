"""HTTP plumbing on the standard library: the response type, the pluggable transport and header helpers."""
from __future__ import annotations

import base64
import binascii
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from http.client import HTTPMessage
from typing import Any, Callable, Mapping, Optional, Tuple

from .errors import BakalariConnectionError, _safe_path


@dataclass(frozen=True)
class HttpResponse:
    """A raw HTTP response. The body is left out of ``repr()`` because a token response carries secrets.

    ``url`` is the final URL after redirects when the transport knows it (the public timetable redirects to an
    error page when the school does not publish the requested timetable).
    """

    status: int
    headers: Mapping[str, str]
    body: bytes = field(repr=False)
    url: str = ""

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8-sig")) if self.body else None

    def header(self, name: str, default: Optional[str] = None) -> Optional[str]:
        """The value of a header, matched case-insensitively."""
        wanted = name.lower()
        return next((value for key, value in self.headers.items() if key.lower() == wanted), default)

    @property
    def content_type(self) -> str:
        """The media type without parameters, lower-cased (``application/json``), or an empty string."""
        return (self.header("Content-Type") or "").split(";", 1)[0].strip().lower()


# A transport sends one request: (method, url, headers, body, timeout) -> HttpResponse. It returns HTTP error
# statuses as responses and raises BakalariConnectionError when the server cannot be reached.
Transport = Callable[[str, str, Mapping[str, str], Optional[bytes], float], HttpResponse]


def _origin(url: str) -> Tuple[str, Optional[str], Optional[int]]:
    parts = urllib.parse.urlsplit(url)
    port = parts.port if parts.port is not None else {"https": 443, "http": 80}.get(parts.scheme)
    return parts.scheme, parts.hostname, port


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, url: str, sensitive: bool) -> None:
        self._origin = _origin(url)
        self._sensitive = sensitive

    def redirect_request(
        self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: HTTPMessage, newurl: str
    ) -> Optional[urllib.request.Request]:
        target = _origin(newurl)
        # Keep the original sensitivity across the entire chain, even if a POST becomes a GET.
        if (target[0] not in ("http", "https")
                or (req.type == "https" and target[0] != "https")
                or (self._sensitive and target != self._origin)):
            raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def urllib_transport(ssl_context: Optional[ssl.SSLContext] = None) -> Transport:
    """The default transport, without a cookie jar. Redirects never downgrade HTTPS; requests with an
    Authorization header or body stay on their original origin. Refused redirects return their HTTP status."""

    def send(method: str, url: str, headers: Mapping[str, str], body: Optional[bytes], timeout: float) -> HttpResponse:
        request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
        sensitive = body is not None or any(name.lower() == "authorization" for name in headers)
        opener = urllib.request.build_opener(
            _SafeRedirectHandler(url, sensitive), urllib.request.HTTPSHandler(context=ssl_context)
        )
        try:
            with opener.open(request, timeout=timeout) as response:
                return HttpResponse(response.status, dict(response.headers), response.read(), response.geturl())
        except urllib.error.HTTPError as error:
            with error:
                return HttpResponse(error.code, dict(error.headers or {}), error.read(), error.geturl() or url)
        except (urllib.error.URLError, OSError) as error:
            reason = getattr(error, "reason", error)
            # The query is left out of the message: it can carry a push token (register-notification).
            where = _safe_path(url)
            raise BakalariConnectionError(f"{method} {where} failed: {reason}") from error

    return send


_PARAMETER = re.compile(r';\s*([^\s=;]+)\s*=\s*("(?:[^"\\]|\\.)*"|[^;]*)')
_ENCODED_WORD = re.compile(r"^=\?([^?]+)\?([BbQq])\?(.*)\?=$")


def _decode_encoded_word(value: str) -> str:
    """Decodes an RFC 2047 encoded word (``=?utf-8?B?...?=``), which Bakaláři uses in ``name=``."""
    match = _ENCODED_WORD.match(value)
    if not match:
        return value
    charset, encoding, payload = match.groups()
    try:
        if encoding.upper() == "B":
            raw = base64.b64decode(payload + "=" * (-len(payload) % 4))
        else:
            raw = urllib.parse.unquote_to_bytes(payload.replace("_", " ").replace("=", "%"))
        return raw.decode(charset, errors="replace")
    except (binascii.Error, LookupError, ValueError):
        return value


def parse_content_disposition(value: Optional[str]) -> Optional[str]:
    """Returns the file name of a ``Content-Disposition`` header, or ``None``.

    Prefers the RFC 5987 ``filename*=utf-8''...`` parameter, then ``filename=``, then the ``name=`` parameter
    that Bakaláři attachment downloads send (possibly as an RFC 2047 ``=?utf-8?B?...?=`` encoded word). Path
    separators are removed, so the result is safe to use as a file name.
    """
    if not value:
        return None
    parameters = {}
    _, _, parameter_text = value.partition(";")
    for key, raw in _PARAMETER.findall(";" + parameter_text):
        raw = raw.strip()
        if len(raw) >= 2 and raw[0] == raw[-1] == '"':
            raw = re.sub(r"\\(.)", r"\1", raw[1:-1])
        parameters[key.lower()] = raw
    name: Optional[str] = None
    extended = parameters.get("filename*")
    if extended and "'" in extended:
        charset, _, encoded = extended.split("'", 2)
        try:
            name = urllib.parse.unquote(encoded, encoding=charset or "utf-8", errors="replace")
        except LookupError:
            name = urllib.parse.unquote(encoded)
    if not name:
        name = parameters.get("filename") or parameters.get("name")
        name = _decode_encoded_word(name) if name else None
    if not name:
        return None
    name = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return name if name not in ("", ".", "..") else None
