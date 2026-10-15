"""Odoo version detection and transport selection."""

import re
import ssl
import xmlrpc.client
from dataclasses import dataclass
from typing import Any

import httpx

from src.mcp.transport.base import USER_AGENT, OdooError

DETECT_TIMEOUT = 5.0
API_MODES = ("auto", "xmlrpc", "json2")


@dataclass(frozen=True)
class VersionInfo:
    major: int
    minor: int
    raw: str
    saas: bool


def parse_version_info(version_info: Any, raw: str | None = None) -> VersionInfo:
    """Parse Odoo's ``version_info`` ([20, 0, 0, 'final', 0, ''] or ['saas~18', 4, ...])."""
    if not isinstance(version_info, (list, tuple)) or not version_info:
        raise ValueError(f"Unrecognised version_info: {version_info!r}")
    first = version_info[0]
    saas = isinstance(first, str) and "saas" in first
    digits = re.search(r"\d+", str(first))
    if not digits:
        raise ValueError(f"Unrecognised version_info: {version_info!r}")
    major = int(digits.group())
    minor = 0
    if len(version_info) > 1:
        minor_digits = re.search(r"\d+", str(version_info[1]))
        minor = int(minor_digits.group()) if minor_digits else 0
    if not raw:
        raw = f"saas~{major}.{minor}" if saas else f"{major}.{minor}"
    return VersionInfo(major=major, minor=minor, raw=str(raw), saas=saas)


def detect_version(url: str, *, verify_ssl: bool = True, timeout: float = DETECT_TIMEOUT) -> VersionInfo:
    """Ask the server for its version, trying the 19+ endpoint, then the legacy ones."""
    url = url.rstrip("/")
    errors: list[str] = []
    with httpx.Client(timeout=timeout, verify=verify_ssl, headers={"User-Agent": USER_AGENT}) as http:
        try:
            resp = http.get(f"{url}/web/version")
            if resp.status_code == 200:
                data = resp.json()
                return parse_version_info(data["version_info"], data.get("version"))
            errors.append(f"/web/version: HTTP {resp.status_code}")
        except Exception as exc:  # noqa: BLE001 — try the next method
            errors.append(f"/web/version: {exc}")

        try:
            resp = http.post(
                f"{url}/web/webclient/version_info",
                json={"jsonrpc": "2.0", "method": "call", "params": {}, "id": 1},
            )
            if resp.status_code == 200:
                result = resp.json().get("result") or {}
                if "server_version_info" in result:
                    return parse_version_info(
                        result["server_version_info"], result.get("server_version")
                    )
            errors.append(f"/web/webclient/version_info: HTTP {resp.status_code}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"/web/webclient/version_info: {exc}")

    try:
        ctx = ssl.create_default_context()
        if not verify_ssl:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", context=ctx, allow_none=True)
        info = common.version()
        return parse_version_info(info["server_version_info"], info.get("server_version"))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"xmlrpc version(): {exc}")

    raise OdooError("VersionDetectionError", "Could not detect the Odoo version. " + "; ".join(errors))


def select_mode(api_mode: str, version: VersionInfo, credential_type: str = "api_key") -> tuple[str, str | None]:
    """Choose the transport. Returns ``(mode, note)``; ``note`` explains a non-obvious choice."""
    if api_mode == "xmlrpc":
        return "xmlrpc", None
    if api_mode == "json2":
        if version.major < 19:
            raise OdooError(
                "UnsupportedTransport",
                f"JSON-2 needs Odoo 19 or newer; this server runs {version.raw}. "
                "Set the connection's API mode to 'auto' or 'xmlrpc'.",
            )
        return "json2", None
    # auto: saas~18.x stays on XML-RPC even though late saas 18 releases have JSON-2.
    if version.major >= 19:
        if credential_type == "password":
            return "xmlrpc", (
                "Using XML-RPC because the connection stores a password; JSON-2 needs an API key "
                "with RPC scope (Odoo → avatar → Preferences → Account Security → New API Key). "
                "XML-RPC is deprecated in Odoo 19+ and removed in Odoo 22."
            )
        return "json2", None
    return "xmlrpc", None
