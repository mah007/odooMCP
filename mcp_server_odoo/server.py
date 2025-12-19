"""MCP server for Odoo integration."""

import asyncio
import json
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from mcp.server import Server
from mcp.types import TextContent, Tool

from .config import get_config
from .odoo_client import OdooClient

# Load environment variables
load_dotenv()

# Initialize MCP server
server = Server("odoo-mcp-server")

# Global Odoo client instance
odoo_client: Optional[OdooClient] = None


def get_odoo_client() -> OdooClient:
    """Get or create Odoo client instance."""
    global odoo_client
    
    if odoo_client is None:
        try:
            config = get_config().odoo
            odoo_client = OdooClient(config)
        except Exception as e:
            raise ValueError(f"Invalid Odoo configuration: {e}")
    
    return odoo_client


@server.list_tools()
async def list_tools() -> List[Tool]:
    """List available tools."""
    return [
        Tool(
            name="search_records",
            description="Search for Odoo records",
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "Odoo model name (e.g., 'res.partner', 'sale.order')",
                    },
                    "domain": {
                        "type": "array",
                        "description": "Search domain in Odoo format (e.g., [['name', 'ilike', 'john']])",
                        "items": {"type": "array"},
                        "default": [],
                    },
                    "fields": {
                        "type": "array",
                        "description": "List of fields to return",
                        "items": {"type": "string"},
                        "default": None,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of records to return",
                        "default": None,
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Number of records to skip",
                        "default": 0,
                    },
                    "order": {
                        "type": "string",
                        "description": "Sort order (e.g., 'name asc, id desc')",
                        "default": None,
                    },
                    "context": {
                        "type": "object",
                        "description": "Optional Odoo context",
                        "default": None,
                    },
                },
                "required": ["model"],
            },
        ),
        Tool(
            name="create_record",
            description="Create a new Odoo record",
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "Odoo model name",
                    },
                    "values": {
                        "type": "object",
                        "description": "Field values for the new record",
                    },
                    "context": {
                        "type": "object",
                        "description": "Optional Odoo context",
                        "default": None,
                    },
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
                    "model": {
                        "type": "string",
                        "description": "Odoo model name",
                    },
                    "ids": {
                        "type": "array",
                        "description": "List of record IDs to update",
                        "items": {"type": "integer"},
                    },
                    "values": {
                        "type": "object",
                        "description": "Field values to update",
                    },
                    "context": {
                        "type": "object",
                        "description": "Optional Odoo context",
                        "default": None,
                    },
                },
                "required": ["model", "ids", "values"],
            },
        ),
        Tool(
            name="delete_record",
            description="Delete Odoo records",
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "Odoo model name",
                    },
                    "ids": {
                        "type": "array",
                        "description": "List of record IDs to delete",
                        "items": {"type": "integer"},
                    },
                    "context": {
                        "type": "object",
                        "description": "Optional Odoo context",
                        "default": None,
                    },
                },
                "required": ["model", "ids"],
            },
        ),
        Tool(
            name="get_record",
            description="Get specific Odoo records by ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "Odoo model name",
                    },
                    "ids": {
                        "type": "array",
                        "description": "List of record IDs to retrieve",
                        "items": {"type": "integer"},
                    },
                    "fields": {
                        "type": "array",
                        "description": "List of fields to return",
                        "items": {"type": "string"},
                        "default": None,
                    },
                    "context": {
                        "type": "object",
                        "description": "Optional Odoo context",
                        "default": None,
                    },
                },
                "required": ["model", "ids"],
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
                    },
                    "context": {
                        "type": "object",
                        "description": "Optional Odoo context",
                        "default": None,
                    },
                },
            },
        ),
        Tool(
            name="get_model_fields",
            description="Get field definitions for an Odoo model",
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "Odoo model name",
                    },
                    "fields": {
                        "type": "array",
                        "description": "Specific fields to get info for (optional)",
                        "items": {"type": "string"},
                        "default": None,
                    },
                    "context": {
                        "type": "object",
                        "description": "Optional Odoo context",
                        "default": None,
                    },
                },
                "required": ["model"],
            },
        ),
        Tool(
            name="search_count",
            description="Count records matching a domain",
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {"type": "string", "description": "Odoo model name"},
                    "domain": {
                        "type": "array",
                        "description": "Search domain in Odoo format",
                        "items": {"type": "array"},
                        "default": [],
                    },
                    "context": {
                        "type": "object",
                        "description": "Optional Odoo context",
                        "default": None,
                    },
                },
                "required": ["model"],
            },
        ),
        Tool(
            name="name_search",
            description="Perform a name_search lookup",
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {"type": "string", "description": "Odoo model name"},
                    "name": {"type": "string", "description": "Name fragment to search", "default": ""},
                    "domain": {"type": "array", "items": {"type": "array"}, "default": []},
                    "operator": {"type": "string", "description": "Search operator (default ilike)", "default": "ilike"},
                    "limit": {"type": "integer", "description": "Max results", "default": 100},
                    "context": {"type": "object", "description": "Optional Odoo context", "default": None},
                },
                "required": ["model"],
            },
        ),
        Tool(
            name="read_group",
            description="Aggregate records with read_group",
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {"type": "string", "description": "Odoo model name"},
                    "domain": {"type": "array", "items": {"type": "array"}, "default": []},
                    "fields": {"type": "array", "items": {"type": "string"}, "default": []},
                    "groupby": {"type": "array", "items": {"type": "string"}, "default": []},
                    "offset": {"type": "integer", "default": 0},
                    "limit": {"type": "integer", "default": None},
                    "order": {"type": "string", "default": None},
                    "lazy": {"type": "boolean", "default": True},
                    "context": {"type": "object", "description": "Optional Odoo context", "default": None},
                },
                "required": ["model"],
            },
        ),
        Tool(
            name="execute_kw",
            description="Call an arbitrary model method via execute_kw",
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {"type": "string", "description": "Odoo model name"},
                    "method": {"type": "string", "description": "Method name"},
                    "args": {"type": "array", "description": "Positional args", "default": []},
                    "kwargs": {"type": "object", "description": "Keyword args", "default": {}},
                },
                "required": ["model", "method"],
            },
        ),
        Tool(
            name="get_version",
            description="Return Odoo server version info",
            inputSchema={"type": "object"},
        ),
        Tool(
            name="render_report_pdf",
            description="Render a QWeb PDF report via ir.actions.report.render_report_pdf_rpc",
            inputSchema={
                "type": "object",
                "properties": {
                    "report_ref": {
                        "type": ["string", "integer"],
                        "description": "Report xmlid, name, or ID",
                    },
                    "docids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Record IDs to render",
                        "default": [],
                    },
                    "data": {
                        "type": "object",
                        "description": "Optional data payload passed to the report",
                        "default": None,
                    },
                    "context": {
                        "type": "object",
                        "description": "Optional Odoo context",
                        "default": None,
                    },
                },
                "required": ["report_ref"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle tool calls."""
    try:
        client = get_odoo_client()
        
        if name == "search_records":
            result = await asyncio.to_thread(
                client.search_read,
                model=arguments["model"],
                domain=arguments.get("domain", []),
                fields=arguments.get("fields"),
                offset=arguments.get("offset", 0),
                limit=arguments.get("limit"),
                order=arguments.get("order"),
                context=arguments.get("context"),
            )
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2, default=str)
            )]
            
        elif name == "create_record":
            result = await asyncio.to_thread(
                client.create,
                model=arguments["model"],
                values=arguments["values"],
                context=arguments.get("context"),
            )
            return [TextContent(
                type="text",
                text=f"Created record with ID: {result}"
            )]
            
        elif name == "update_record":
            success = await asyncio.to_thread(
                client.write,
                model=arguments["model"],
                ids=arguments["ids"],
                values=arguments["values"],
                context=arguments.get("context"),
            )
            return [TextContent(
                type="text",
                text=f"Update {'successful' if success else 'failed'} for IDs: {arguments['ids']}"
            )]
            
        elif name == "delete_record":
            success = await asyncio.to_thread(
                client.unlink,
                model=arguments["model"],
                ids=arguments["ids"],
                context=arguments.get("context"),
            )
            return [TextContent(
                type="text",
                text=f"Delete {'successful' if success else 'failed'} for IDs: {arguments['ids']}"
            )]
            
        elif name == "get_record":
            result = await asyncio.to_thread(
                client.read,
                model=arguments["model"],
                ids=arguments["ids"],
                fields=arguments.get("fields"),
                context=arguments.get("context"),
            )
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2, default=str)
            )]
            
        elif name == "list_models":
            models = await asyncio.to_thread(
                client.get_model_list,
                context=arguments.get("context"),
            )
            if not arguments.get("transient", False):
                models = [m for m in models if not m.get("transient", False)]
            
            # Format output
            output = "Available Odoo models:\n"
            for model in sorted(models, key=lambda x: x["model"]):
                output += f"- {model['model']}: {model['name']}\n"
                
            return [TextContent(type="text", text=output)]
            
        elif name == "get_model_fields":
            fields = await asyncio.to_thread(
                client.fields_get,
                model=arguments["model"],
                fields=arguments.get("fields"),
                context=arguments.get("context"),
            )
            return [TextContent(
                type="text",
                text=json.dumps(fields, indent=2, default=str)
            )]
        
        elif name == "search_count":
            result = await asyncio.to_thread(
                client.search_count,
                model=arguments["model"],
                domain=arguments.get("domain", []),
                context=arguments.get("context"),
            )
            return [TextContent(type="text", text=str(result))]

        elif name == "name_search":
            result = await asyncio.to_thread(
                client.name_search,
                model=arguments["model"],
                name=arguments.get("name", ""),
                domain=arguments.get("domain", []),
                operator=arguments.get("operator", "ilike"),
                limit=arguments.get("limit", 100),
                context=arguments.get("context"),
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

        elif name == "read_group":
            result = await asyncio.to_thread(
                client.read_group,
                model=arguments["model"],
                domain=arguments.get("domain", []),
                fields=arguments.get("fields"),
                groupby=arguments.get("groupby"),
                offset=arguments.get("offset", 0),
                limit=arguments.get("limit"),
                order=arguments.get("order"),
                lazy=arguments.get("lazy", True),
                context=arguments.get("context"),
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

        elif name == "execute_kw":
            result = await asyncio.to_thread(
                client.execute,
                model=arguments["model"],
                method=arguments["method"],
                *arguments.get("args", []),
                **arguments.get("kwargs", {}),
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

        elif name == "get_version":
            result = await asyncio.to_thread(client.get_version)
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

        elif name == "render_report_pdf":
            result = await asyncio.to_thread(
                client.render_report_pdf,
                report_ref=arguments["report_ref"],
                docids=arguments.get("docids", []),
                data=arguments.get("data"),
                context=arguments.get("context"),
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
            
        else:
            return [TextContent(
                type="text",
                text=f"Unknown tool: {name}"
            )]
            
    except Exception as e:
        return [TextContent(
            type="text",
            text=f"Error: {type(e).__name__}: {str(e)}"
        )]


async def main():
    """Run the MCP server."""
    from mcp.server.stdio import stdio_server
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
