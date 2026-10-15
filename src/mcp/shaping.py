"""Output shaping: small defaults, binary summaries, truncation, size guard, compact JSON."""

import html
import json
import os
import re
from typing import Any

MAX_RESPONSE_BYTES = int(os.environ.get("MCP_MAX_RESPONSE_BYTES", "100000"))
TEXT_LIMIT = 2000
X2MANY_LIMIT = 50
GENERIC_BINARY_MIN = 10_000

BINARY_TYPES = ("binary", "image")
TEXT_TYPES = ("text", "html")
X2MANY_TYPES = ("one2many", "many2many")
NOISE_PREFIXES = (
    "message_", "activity_", "website_message", "rating_", "has_message",
    "__last_update", "access_", "avatar_", "image_",
)

_BASE64_RE = re.compile(r"^[A-Za-z0-9+/=\s]+$")
_TAG_BREAK_RE = re.compile(r"<\s*(br|/p|/div|/li|/tr|/h[1-6])\b[^>]*>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_BLANK_LINES_RE = re.compile(r"\n\s*\n+")


def dumps(obj: Any) -> str:
    """Compact JSON; non-ASCII text (Arabic) stays readable UTF-8."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def size_of(obj: Any) -> int:
    return len(dumps(obj).encode())


# ── Field selection ──────────────────────────────────────────────────────────

def is_noise(name: str) -> bool:
    return name.startswith(NOISE_PREFIXES)


def compact_default_fields(fields_meta: dict[str, dict]) -> list[str]:
    """Every field except binaries, one2many lists and chatter/avatar noise."""
    return [
        name for name, meta in fields_meta.items()
        if meta.get("type") not in BINARY_TYPES
        and meta.get("type") != "one2many"
        and not is_noise(name)
    ]


# ── Value shaping ────────────────────────────────────────────────────────────

def _b64_size(text: str) -> int:
    stripped = text.rstrip("=")
    return len(stripped) * 3 // 4


def summarize_binary(value: Any) -> Any:
    """Replace binary content by ``{"binary": true, "size": ..., "filename": ...}``.

    Handles Odoo 20 dicts ``{content, size, filename}``, plain base64 (<= 18) and the
    human-readable size strings Odoo returns with ``bin_size`` ("61.6 Kb").
    """
    if value in (False, None, ""):
        return False
    if isinstance(value, dict):
        out: dict[str, Any] = {"binary": True}
        if "size" in value:
            out["size"] = value["size"]
        elif isinstance(value.get("content"), str):
            out["size"] = _b64_size(value["content"])
        if value.get("filename"):
            out["filename"] = value["filename"]
        return out
    if isinstance(value, str):
        if len(value) < 32 and re.search(r"\d\s*(bytes|[kmg]b)$", value.strip(), re.I):
            return {"binary": True, "size": value.strip()}
        return {"binary": True, "size": _b64_size(value)}
    return {"binary": True}


def html_to_text(value: str) -> str:
    text = _TAG_BREAK_RE.sub("\n", value)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _BLANK_LINES_RE.sub("\n\n", text).strip()


def truncate_text(value: str, limit: int = TEXT_LIMIT) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"…[truncated, {len(value)} chars; pass full_text=true]"


def cut_x2many(value: Any, limit: int = X2MANY_LIMIT) -> Any:
    if isinstance(value, list) and len(value) > limit:
        return value[:limit] + [f"…(+{len(value) - limit} more; total {len(value)})"]
    return value


def shape_record(
    record: dict, fields_meta: dict[str, dict], *, include_binary: bool = False, full_text: bool = False
) -> dict:
    out = {}
    for name, value in record.items():
        ftype = fields_meta.get(name, {}).get("type")
        if ftype in BINARY_TYPES:
            if not include_binary:
                value = summarize_binary(value)
        elif ftype in TEXT_TYPES and isinstance(value, str) and not full_text:
            if ftype == "html":
                value = html_to_text(value)
            value = truncate_text(value)
        elif ftype in X2MANY_TYPES:
            value = cut_x2many(value)
        elif isinstance(value, str) and not full_text and len(value) > GENERIC_BINARY_MIN:
            value = truncate_text(value)
        out[name] = value
    return out


def shape_records(records: list[dict], fields_meta: dict[str, dict], **kwargs: Any) -> list[dict]:
    return [shape_record(r, fields_meta, **kwargs) for r in records]


def looks_like_base64(value: str) -> bool:
    return len(value) >= GENERIC_BINARY_MIN and bool(_BASE64_RE.match(value[:2000]))


def shape_generic(obj: Any, *, full_text: bool = False) -> Any:
    """Shape arbitrary method results: summarise binaries, cut huge strings and lists."""
    if isinstance(obj, dict):
        if isinstance(obj.get("content"), str) and isinstance(obj.get("size"), int):
            return summarize_binary(obj)
        return {k: shape_generic(v, full_text=full_text) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [shape_generic(v, full_text=full_text) for v in obj]
    if isinstance(obj, (bytes, bytearray)):
        return {"binary": True, "size": len(obj)}
    if isinstance(obj, str):
        if looks_like_base64(obj):
            return {"binary": True, "size": _b64_size(obj)}
        if not full_text:
            return truncate_text(obj, TEXT_LIMIT * 5)
    return obj


# ── Size guard ───────────────────────────────────────────────────────────────

def guard_records(payload: dict, key: str = "records", max_bytes: int | None = None) -> dict:
    """Drop items of ``payload[key]`` from the end until the payload fits in ``max_bytes``."""
    max_bytes = max_bytes or MAX_RESPONSE_BYTES
    items = payload.get(key)
    if not isinstance(items, list) or size_of(payload) <= max_bytes:
        return payload
    total = len(items)
    sizes = [size_of(item) + 1 for item in items]
    overhead = size_of({**payload, key: []}) + 400  # room for the note and flags
    kept, used = 0, overhead
    for s in sizes:
        if used + s > max_bytes:
            break
        used += s
        kept += 1
    payload = {**payload, key: items[:kept], "truncated": True}
    payload["note"] = (
        f"Response cut to {kept} of {total} {key} to stay under {max_bytes // 1000} KB. "
        "Ask for fewer fields or a smaller limit."
    )
    return payload


def guard_any(result: Any, max_bytes: int | None = None) -> Any:
    """Size guard for results without a known shape (execute_method)."""
    max_bytes = max_bytes or MAX_RESPONSE_BYTES
    if size_of(result) <= max_bytes:
        return result
    if isinstance(result, dict) and isinstance(result.get("result"), list):
        return guard_records(result, "result", max_bytes)
    text = dumps(result)
    cut = text.encode()[: max_bytes - 500].decode(errors="ignore")
    return {
        "truncated": True,
        "note": f"Result is {len(text.encode()) // 1000} KB; showing the first {len(cut.encode()) // 1000} KB as text. "
        "Narrow the call (fewer ids or fields) to get a complete result.",
        "preview": cut,
    }


# ── Pipe tables ──────────────────────────────────────────────────────────────

def cell(value: Any) -> str:
    if value is None or value is False:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ")
    return text.replace("|", "\\|")


def pipe_table(header: list[str], rows: list[list[Any]]) -> str:
    lines = ["|".join(header)]
    lines.extend("|".join(cell(v) for v in row) for row in rows)
    return "\n".join(lines)
