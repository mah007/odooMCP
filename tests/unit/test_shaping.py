"""Output shaping: binaries, truncation, x2many cut, size guard, compact UTF-8 JSON."""

import base64
import json

from src.mcp import shaping
from tests.conftest import PARTNER_FIELDS


def test_dumps_keeps_arabic_unescaped_and_compact():
    text = shaping.dumps({"name": "Arabic / الْعَرَبيّة", "n": [1, 2]})
    assert "الْعَرَبيّة" in text and "\\u" not in text
    assert text == '{"name":"Arabic / الْعَرَبيّة","n":[1,2]}'
    assert json.loads(text)["name"].endswith("الْعَرَبيّة")


def test_summarize_binary_all_three_formats():
    raw = base64.b64encode(b"x" * 3000).decode()
    assert shaping.summarize_binary(raw) == {"binary": True, "size": 3000}  # Odoo <= 18 base64
    assert shaping.summarize_binary("61.6 Kb") == {"binary": True, "size": "61.6 Kb"}  # bin_size
    odoo20 = {"content": raw, "size": 3000, "filename": "logo.png"}
    assert shaping.summarize_binary(odoo20) == {"binary": True, "size": 3000, "filename": "logo.png"}
    assert shaping.summarize_binary({"content": raw, "size": 3000}) == {"binary": True, "size": 3000}
    assert shaping.summarize_binary(False) is False


def test_shape_record_binary_text_and_x2many():
    record = {
        "id": 1,
        "image_1920": {"content": "QUJD" * 5000, "size": 15000},
        "comment": "<p>Hello<br/>world</p>" + "<p>" + "x" * 3000 + "</p>",
        "category_id": list(range(120)),
        "name": "ok",
    }
    shaped = shaping.shape_record(record, PARTNER_FIELDS)
    assert shaped["image_1920"] == {"binary": True, "size": 15000}
    assert shaped["comment"].startswith("Hello\nworld")
    assert shaped["comment"].endswith("chars; pass full_text=true]")
    assert len(shaped["category_id"]) == 51 and shaped["category_id"][-1] == "…(+70 more; total 120)"
    full = shaping.shape_record(record, PARTNER_FIELDS, include_binary=True, full_text=True)
    assert full["image_1920"]["content"].startswith("QUJD")
    assert full["comment"] == record["comment"]


def test_compact_default_fields_skip_binary_one2many_and_noise():
    fields = shaping.compact_default_fields(PARTNER_FIELDS)
    assert "image_1920" not in fields and "child_ids" not in fields and "message_ids" not in fields
    assert {"name", "category_id", "company_id", "comment"} <= set(fields)


def test_shape_generic_summarises_binaries_in_method_results():
    blob = base64.b64encode(b"\x00" * 20000).decode()
    result = {"report": blob, "file": {"content": "QUJD", "size": 3}, "raw": b"abc", "name": "ok"}
    shaped = shaping.shape_generic(result)
    assert shaped["report"]["binary"] is True
    assert shaped["file"] == {"binary": True, "size": 3}
    assert shaped["raw"] == {"binary": True, "size": 3}
    assert shaped["name"] == "ok"


def test_size_guard_drops_records_from_the_end():
    records = [{"id": i, "text": "x" * 1000} for i in range(300)]
    payload = shaping.guard_records({"records": records, "total": 300}, max_bytes=50_000)
    assert payload["truncated"] is True
    assert 0 < len(payload["records"]) < 300
    assert payload["records"][0]["id"] == 0
    assert shaping.size_of(payload) <= 50_000
    assert f"cut to {len(payload['records'])} of 300" in payload["note"]


def test_size_guard_leaves_small_payloads_alone():
    payload = {"records": [{"id": 1}], "total": 1}
    assert shaping.guard_records(payload) is payload


def test_guard_any_for_unshaped_results():
    big = {"result": [{"i": i, "pad": "y" * 500} for i in range(1000)]}
    out = shaping.guard_any(big, max_bytes=20_000)
    assert out["truncated"] and shaping.size_of(out) <= 20_000
    out = shaping.guard_any({"result": "z" * 50_000}, max_bytes=20_000)
    assert out["truncated"] and "preview" in out


def test_pipe_table_escapes():
    table = shaping.pipe_table(["a", "b"], [["x|y", "line1\nline2"], [False, None]])
    assert table == "a|b\nx\\|y|line1 line2\n|"
