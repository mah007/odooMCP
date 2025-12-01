"""MCP server for Odoo integration."""

import asyncio
import json
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from mcp.server import Server
from mcp.types import TextContent, Tool
from pydantic import ValidationError

from .odoo_client import OdooClient, OdooConfig

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
            config = OdooConfig(
                url=os.environ["ODOO_URL"],
                database=os.environ["ODOO_DB"],
                username=os.environ["ODOO_USERNAME"],
                password=os.environ.get("ODOO_PASSWORD"),
                api_key=os.environ.get("ODOO_API_KEY"),
                timeout=int(os.environ.get("ODOO_TIMEOUT", "120")),
            )
            odoo_client = OdooClient(config)
        except (KeyError, ValidationError) as e:
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
                },
                "required": ["model"],
            },
        ),
        Tool(
            name="execute_kw",
            description=(
                "Call any Odoo model method via execute_kw with optional positional "
                "and keyword arguments, including context."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "Odoo model name",
                    },
                    "method": {
                        "type": "string",
                        "description": "Method name to invoke (e.g., 'name_search', 'fields_view_get')",
                    },
                    "args": {
                        "type": "array",
                        "description": "Positional arguments to pass",
                        "items": {},
                        "default": [],
                    },
                    "kwargs": {
                        "type": "object",
                        "description": "Keyword arguments to pass",
                        "default": {},
                    },
                    "context": {
                        "type": "object",
                        "description": "Optional context dict (lang, tz, etc.)",
                        "default": None,
                    },
                },
                "required": ["model", "method"],
            },
        ),
        Tool(
            name="get_server_info",
            description="Fetch Odoo server version and about information for capability discovery",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="list_databases",
            description="List databases exposed by the Odoo instance (requires admin rights)",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="render_report",
            description="Render a report using the XML-RPC report endpoint",
            inputSchema={
                "type": "object",
                "properties": {
                    "report_name": {
                        "type": "string",
                        "description": "Technical report name (e.g., 'sale.report_saleorder')",
                    },
                    "docids": {
                        "type": ["array", "integer"],
                        "description": "Record IDs to render",
                        "items": {"type": "integer"},
                    },
                    "context": {
                        "type": "object",
                        "description": "Optional context dict",
                        "default": None,
                    },
                    "data": {
                        "type": "object",
                        "description": "Optional data payload for the report",
                        "default": None,
                    },
                },
                "required": ["report_name", "docids"],
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
            )
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2, default=str)
            )]
            
        elif name == "list_models":
            models = await asyncio.to_thread(client.get_model_list)
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
            )
            return [TextContent(
                type="text",
                text=json.dumps(fields, indent=2, default=str)
            )]

        elif name == "execute_kw":
            result = await asyncio.to_thread(
                client.execute_kw,
                model=arguments["model"],
                method=arguments["method"],
                args=arguments.get("args", []),
                kwargs=arguments.get("kwargs", {}),
                context=arguments.get("context"),
            )
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2, default=str)
            )]

        elif name == "get_server_info":
            version = await asyncio.to_thread(client.get_version_info)
            about = None
            try:
                about = await asyncio.to_thread(client.get_about_info)
            except Exception:
                about = "About endpoint not available"

            return [TextContent(
                type="text",
                text=json.dumps({"version": version, "about": about}, indent=2, default=str)
            )]

        elif name == "list_databases":
            databases = await asyncio.to_thread(client.list_databases)
            return [TextContent(
                type="text",
                text=json.dumps(databases, indent=2, default=str)
            )]

        elif name == "render_report":
            report = await asyncio.to_thread(
                client.render_report,
                report_name=arguments["report_name"],
                docids=arguments["docids"],
                context=arguments.get("context"),
                data=arguments.get("data"),
            )
            return [TextContent(
                type="text",
                text=json.dumps(report, indent=2, default=str)
            )]

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
