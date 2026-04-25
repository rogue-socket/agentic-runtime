"""Built-in HTTP request tool.

Makes external HTTP/HTTPS requests and returns the response body, status
code, and headers.  Uses stdlib ``urllib`` — no additional dependencies.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import socket
import ssl
import urllib.error
import urllib.request
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from .base import RuntimeContext, ToolResult


_ALLOWED_SCHEMES = {"http", "https"}
_MAX_RESPONSE_BYTES = 1_048_576  # 1 MB safety limit

# SSRF protection: block requests to private / link-local / loopback networks
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("::ffff:0:0/96"),  # IPv4-mapped IPv6
]


def _resolve_host_addresses(hostname: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve hostname once and return the list of IP addresses.

    Returns an empty list on DNS failure (treated as blocked by callers).
    """
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return []
    addrs = []
    for _family, _type, _proto, _canon, sockaddr in infos:
        addr = ipaddress.ip_address(sockaddr[0])
        # Normalize IPv4-mapped IPv6 to their IPv4 equivalent for
        # consistent matching against IPv4 blocked networks.
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        addrs.append(addr)
    return addrs


def _is_private_address(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if a resolved IP address falls within a blocked network."""
    return any(addr in net for net in _BLOCKED_NETWORKS)


def _is_private_host(hostname: str) -> bool:
    """Resolve *hostname* and return True if any address is private/blocked.

    Fail-closed: returns True (blocked) when DNS resolution fails.
    """
    addrs = _resolve_host_addresses(hostname)
    if not addrs:
        return True  # DNS failure — fail closed
    for addr in addrs:
        if _is_private_address(addr):
            return True
    return False


class _SSRFSafeConnection(http.client.HTTPConnection):
    """HTTPConnection subclass that validates resolved IPs at connect time.

    Prevents DNS rebinding SSRF by checking every resolved address against
    the blocked-network list inside the actual socket.connect() call —
    eliminating the TOCTOU gap between a pre-check DNS lookup and urllib's
    internal DNS lookup.
    """

    def connect(self) -> None:
        """Connect to the host, validating resolved IPs against blocklist."""
        infos = socket.getaddrinfo(
            self.host, self.port, socket.AF_UNSPEC, socket.SOCK_STREAM,
        )
        if not infos:
            raise urllib.error.URLError("DNS resolution failed")

        for family, socktype, proto, _canon, sockaddr in infos:
            addr = ipaddress.ip_address(sockaddr[0])
            if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
                addr = addr.ipv4_mapped
            if _is_private_address(addr):
                raise urllib.error.URLError(
                    "Requests to private or internal network addresses are blocked."
                )

        # All addresses passed — proceed with normal connection.
        super().connect()


class _SSRFSafeHTTPSConnection(_SSRFSafeConnection, http.client.HTTPSConnection):
    """HTTPS variant of SSRF-safe connection."""

    pass


class _SSRFSafeHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(_SSRFSafeConnection, req)  # type: ignore[return-value]


class _SSRFSafeHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(_SSRFSafeHTTPSConnection, req)  # type: ignore[return-value]


def _build_ssrf_safe_opener() -> urllib.request.OpenerDirector:
    """Build a urllib opener that validates resolved IPs at connect time."""
    return urllib.request.build_opener(
        _SSRFSafeHTTPHandler, _SSRFSafeHTTPSHandler,
    )


_ssrf_opener = _build_ssrf_safe_opener()


def _ssrf_safe_urlopen(req: urllib.request.Request, *, timeout: float = 30):
    """Open a URL request using the SSRF-safe opener.

    This is the single callsite for HTTP requests — tests can patch this
    function instead of ``urllib.request.urlopen``.
    """
    return _ssrf_opener.open(req, timeout=timeout)


class HttpTool:
    """Make HTTP requests to external APIs."""

    name = "tools.http"
    description = "Performs an HTTP request and returns status, headers, and body"
    input_schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Target URL (http/https)"},
            "method": {
                "type": "string",
                "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                "description": "HTTP method (default GET)",
            },
            "headers": {
                "type": "object",
                "description": "Request headers",
                "additionalProperties": {"type": "string"},
            },
            "body": {
                "type": "string",
                "description": "Request body (sent as-is)",
            },
            "json_body": {
                "type": "object",
                "description": "JSON request body (sets Content-Type automatically)",
            },
        },
        "required": ["url"],
    }
    timeout: Optional[float] = 30.0
    retries: Optional[int] = None

    async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
        """Function implementation."""
        url = input.get("url", "")
        method = input.get("method", "GET").upper()
        headers = dict(input.get("headers") or {})

        # Validate URL scheme
        parsed = urlparse(url)
        if parsed.scheme not in _ALLOWED_SCHEMES:
            return ToolResult(
                success=False,
                output=None,
                error=f"URL scheme '{parsed.scheme}' is not allowed. Use http or https.",
                metadata=None,
            )

        # SSRF protection: pre-flight check blocks obvious private targets.
        # The SSRF-safe opener below also validates at connect time to prevent
        # DNS rebinding attacks.
        if parsed.hostname and _is_private_host(parsed.hostname):
            return ToolResult(
                success=False,
                output=None,
                error="Requests to private or internal network addresses are blocked.",
                metadata=None,
            )

        data: Optional[bytes] = None
        json_body = input.get("json_body")
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        elif "body" in input and input["body"] is not None:
            data = input["body"].encode("utf-8")

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        effective_timeout = self.timeout if self.timeout is not None else 30

        try:
            with _ssrf_safe_urlopen(req, timeout=effective_timeout) as resp:
                body_bytes = resp.read(_MAX_RESPONSE_BYTES)
                body_text = body_bytes.decode("utf-8", errors="replace")
                resp_headers = {k: v for k, v in resp.getheaders()}
                status = resp.status
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            return ToolResult(
                success=False,
                output={"status": exc.code, "body": err_body},
                error=f"HTTP {exc.code}",
                metadata=None,
            )
        except urllib.error.URLError as exc:
            return ToolResult(
                success=False,
                output=None,
                error=f"Request failed: {exc.reason}",
                metadata=None,
            )

        return ToolResult(
            success=True,
            output={
                "status": status,
                "headers": resp_headers,
                "body": body_text,
            },
            error=None,
            metadata=None,
        )
