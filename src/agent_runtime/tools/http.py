"""Built-in HTTP request tool.

Makes external HTTP/HTTPS requests and returns the response body, status
code, and headers.  Uses stdlib ``urllib`` — no additional dependencies.
"""

from __future__ import annotations

import ipaddress
import json
import socket
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
]


def _is_private_host(hostname: str) -> bool:
    """Resolve *hostname* and return True if any address is private/blocked."""
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False  # DNS failure will surface later as URLError
    for _family, _type, _proto, _canon, sockaddr in infos:
        addr = ipaddress.ip_address(sockaddr[0])
        if any(addr in net for net in _BLOCKED_NETWORKS):
            return True
    return False


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

        # SSRF protection: block private / loopback / link-local targets
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

        try:
            with urllib.request.urlopen(req, timeout=self.timeout or 30) as resp:
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
