"""MCP tool definitions and handlers."""

import asyncio
import json
from typing import Any

from mcp.types import TextContent, Tool

from src.mcp.odoo_client import OdooClient

TOOLS: list[Tool] = [
    Tool(
        name="search_records",
        description="Search for Odoo records using a domain filter",
        inputSchema={
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "Odoo model name (e.g. 'res.partner')"},
                "domain": {
                    "type": "array",
                    "description": "Odoo domain filter (e.g. [['name','ilike','john']])",
                    "items": {"type": "array"},
                    "default": [],
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Fields to return (all if omitted)",
                },
                "limit": {"type": "integer", "description": "Max records to return"},
                "offset": {"type": "integer", "description": "Records to skip", "default": 0},
                "order": {"type": "string", "description": "Sort order, e.g. 'name asc'"},
            },
            "required": ["model"],
        },
    ),
    Tool(
        name="get_record",
        description="Fetch specific Odoo records by ID",
        inputSchema={
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "ids": {"type": "array", "items": {"type": "integer"}},
                "fields": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["model", "ids"],
        },
    ),
    Tool(
        name="create_record",
        description="Create a new Odoo record",
        inputSchema={
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "values": {"type": "object", "description": "Field values for the new record"},
            },
            "required": ["model", "values"],
        },
    ),
    Tool(
        name="update_record",
        description="Update existing Odoo records",
        inputSchema={
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "ids": {"type": "array", "items": {"type": "integer"}},
                "values": {"type": "object"},
            },
            "required": ["model", "ids", "values"],
        },
    ),
    Tool(
        name="delete_record",
        description="Delete Odoo records by ID",
        inputSchema={
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "ids": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["model", "ids"],
        },
    ),
    Tool(
        name="search_count",
        description="Count Odoo records matching a domain",
        inputSchema={
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "domain": {"type": "array", "items": {"type": "array"}, "default": []},
            },
            "required": ["model"],
        },
    ),
    Tool(
        name="list_models",
        description="List all available Odoo models",
        inputSchema={
            "type": "object",
            "properties": {
                "transient": {
                    "type": "boolean",
                    "description": "Include transient (wizard) models",
                    "default": False,
                }
            },
        },
    ),
    Tool(
        name="get_model_fields",
        description="Get field definitions for an Odoo model",
        inputSchema={
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "fields": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["model"],
        },
    ),
    Tool(
        name="model_info",
        description="Get comprehensive metadata for an Odoo model",
        inputSchema={
            "type": "object",
            "properties": {"model": {"type": "string"}},
            "required": ["model"],
        },
    ),
    Tool(
        name="execute_method",
        description="Call any method on an Odoo model",
        inputSchema={
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "method": {"type": "string"},
                "args": {"type": "array", "default": []},
                "kwargs": {"type": "object", "default": {}},
            },
            "required": ["model", "method"],
        },
    ),
]


def _text(data: Any) -> list[TextContent]:
    if isinstance(data, str):
        return [TextContent(type="text", text=data)]
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def _ids(raw: Any) -> list[int]:
    """Coerce ids to a list of ints — handles both [1,2] and ['1','2'] from LLMs."""
    if isinstance(raw, (int, str)):
        return [int(raw)]
    return [int(i) for i in raw]


async def call_tool(name: str, arguments: dict[str, Any], client: OdooClient) -> list[TextContent]:
    """Dispatch a tool call. All XML-RPC calls are offloaded to a thread."""

    if name == "search_records":
        result = await asyncio.to_thread(
            client.search_read,
            model=arguments["model"],
            domain=arguments.get("domain", []),
            fields=arguments.get("fields"),
            offset=arguments.get("offset", 0),
            limit=arguments.get("limit"),
            order=arguments.get("order"),
        )
        return _text(result)

    if name == "get_record":
        result = await asyncio.to_thread(
            client.read,
            model=arguments["model"],
            ids=_ids(arguments["ids"]),
            fields=arguments.get("fields"),
        )
        return _text(result)

    if name == "create_record":
        record_id = await asyncio.to_thread(
            client.create, arguments["model"], arguments["values"]
        )
        return _text({"id": record_id, "message": f"Created record with ID {record_id}"})

    if name == "update_record":
        ids = _ids(arguments["ids"])
        ok = await asyncio.to_thread(client.write, arguments["model"], ids, arguments["values"])
        return _text({"success": ok, "ids": ids})

    if name == "delete_record":
        ids = _ids(arguments["ids"])
        ok = await asyncio.to_thread(client.unlink, arguments["model"], ids)
        return _text({"success": ok, "ids": ids})

    if name == "search_count":
        count = await asyncio.to_thread(
            client.search_count, arguments["model"], arguments.get("domain", [])
        )
        return _text({"count": count})

    if name == "list_models":
        models = await asyncio.to_thread(client.get_model_list)
        if not arguments.get("transient", False):
            models = [m for m in models if not m.get("transient", False)]
        models.sort(key=lambda m: m["model"])
        return _text(models)

    if name == "get_model_fields":
        fields = await asyncio.to_thread(
            client.fields_get,
            model=arguments["model"],
            fields=arguments.get("fields"),
        )
        return _text(fields)

    if name == "model_info":
        info = await asyncio.to_thread(client.get_model_info, arguments["model"])
        return _text(info)

    if name == "execute_method":
        result = await asyncio.to_thread(
            client.execute,
            arguments["model"],
            arguments["method"],
            *arguments.get("args", []),
            **arguments.get("kwargs", {}),
        )
        return _text(result)

    raise ValueError(f"Unknown tool: {name}")
