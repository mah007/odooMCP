"""FastAPI-based HTTP streaming MCP server for Odoo integration."""

import asyncio
import json
import time
import uuid
from typing import Any, Dict, List, Optional, Union
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse
import uvicorn
from mcp.types import Tool, TextContent

from .config import get_config
from .logger import get_logger
from .services.odoo_service import get_odoo_service
from .services.cache_service import get_cache_service

logger = get_logger(__name__)

# Session storage (in production, use Redis or similar)
sessions: Dict[str, Dict[str, Any]] = {}

# Global start time for uptime calculation
_start_time = time.time()


def _fix_tool_schema(tool_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Fix tool schema by adding missing required fields and cleaning annotations."""
    # Add title if missing
    if tool_dict.get("title") is None:
        tool_dict["title"] = tool_dict["name"].replace("_", " ").title()
    
    # Remove outputSchema to avoid validation issues
    if "outputSchema" in tool_dict:
        del tool_dict["outputSchema"]
    
    # Fix annotations - remove null values and ensure proper types
    annotations = tool_dict.get("annotations", {})
    if annotations is None:
        annotations = {}
    
    # Remove null values from annotations
    cleaned_annotations = {}
    for key, value in annotations.items():
        if value is not None:
            cleaned_annotations[key] = value
    
    tool_dict["annotations"] = cleaned_annotations
    
    return tool_dict


async def get_all_tools() -> List[Dict[str, Any]]:
    """Get all available tools."""
    tools = []
    
    # Record management tools
    record_tools = [
        Tool(
            name="create_record",
            description="Create new records in Odoo",
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "The Odoo model name",
                    },
                    "values": {
                        "type": "object",
                        "description": "Dictionary of field values",
                    },
                },
                "required": ["model", "values"],
            },
        ),
        Tool(
            name="update_record",
            description="Update existing records",
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "The Odoo model name",
                    },
                    "ids": {
                        "type": "array",
                        "description": "List of record IDs to update",
                        "items": {"type": "integer"},
                    },
                    "values": {
                        "type": "object",
                        "description": "Dictionary of field values to update",
                    },
                },
                "required": ["model", "ids", "values"],
            },
        ),
        Tool(
            name="delete_record",
            description="Delete records from Odoo (use with caution)",
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "The Odoo model name",
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
            description="Get detailed information about specific records",
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "The Odoo model name",
                    },
                    "ids": {
                        "type": "array",
                        "description": "List of record IDs",
                        "items": {"type": "integer"},
                    },
                    "fields": {
                        "type": "array",
                        "description": "List of fields to return (optional)",
                        "items": {"type": "string"},
                    },
                },
                "required": ["model", "ids"],
            },
        ),
        Tool(
            name="execute_method",
            description="Execute custom methods on Odoo models",
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "Odoo model name",
                    },
                    "method": {
                        "type": "string",
                        "description": "Method name to execute",
                    },
                    "ids": {
                        "type": "array",
                        "description": "List of record IDs (if method requires)",
                        "items": {"type": "integer"},
                    },
                    "args": {
                        "type": "array",
                        "description": "Additional positional arguments",
                        "items": {
                            "type": "string",
                            "description": "A positional argument value"
                        },
                    },
                    "kwargs": {
                        "type": "object",
                        "description": "Additional keyword arguments",
                    },
                },
                "required": ["model", "method"],
            },
        ),
    ]
    
    # Search tools
    search_tools = [
        Tool(
            name="search_records",
            description="Search for records in any Odoo model",
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "The Odoo model name (e.g., 'res.partner', 'sale.order')",
                    },
                    "domain": {
                        "type": "array",
                        "description": "Odoo domain filter (default: [])",
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "description": "Domain clause element"
                            },
                        },
                        "default": [],
                    },
                    "fields": {
                        "type": "array",
                        "description": "List of fields to return",
                        "items": {"type": "string"},
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of records",
                        "minimum": 1,
                        "maximum": 1000,
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Number of records to skip",
                        "minimum": 0,
                        "default": 0,
                    },
                    "order": {
                        "type": "string",
                        "description": "Sort order (e.g., 'name asc, id desc')",
                    },
                },
                "required": ["model"],
            },
        ),
        Tool(
            name="search_count",
            description="Count records matching search criteria",
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "Odoo model name",
                    },
                    "domain": {
                        "type": "array",
                        "description": "Search domain in Odoo format",
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "description": "Domain clause element"
                            },
                        },
                        "default": [],
                    },
                },
                "required": ["model"],
            },
        ),
    ]
    
    # Model tools
    model_tools = [
        Tool(
            name="list_models",
            description="Discover available models in your Odoo instance",
            inputSchema={
                "type": "object",
                "properties": {
                    "transient": {
                        "type": "boolean",
                        "description": "Include transient (wizard) models (default: false)",
                        "default": False,
                    },
                    "search": {
                        "type": "string",
                        "description": "Filter models by name (case-insensitive)",
                    },
                },
            },
        ),
        Tool(
            name="get_model_fields",
            description="Get field definitions for a model",
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "The Odoo model name",
                    },
                    "fields": {
                        "type": "array",
                        "description": "Specific fields to get info for (optional)",
                        "items": {"type": "string"},
                    },
                    "attributes": {
                        "type": "array",
                        "description": "Field attributes to include (optional)",
                        "items": {"type": "string"},
                    },
                },
                "required": ["model"],
            },
        ),
        Tool(
            name="model_info",
            description="Get comprehensive information about a model",
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "The Odoo model name",
                    },
                },
                "required": ["model"],
            },
        ),
    ]
    
    # Server management tools
    server_tools = [
            Tool(
                name="server_status",
                description="Get server status and health information",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="cache_stats",
                description="Get cache statistics and management",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "Cache action: 'stats', 'clear'",
                            "enum": ["stats", "clear"],
                            "default": "stats",
                        },
                    },
                },
            ),
    ]
    
    # Combine all tools and fix schemas
    all_tools = record_tools + search_tools + model_tools + server_tools
    for tool in all_tools:
        tool_dict = tool.model_dump()
        tools.append(_fix_tool_schema(tool_dict))
        
    return tools
    

async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """Call a tool and return the result."""
    logger.info(f"Tool called: {name} with arguments: {arguments}")
    
    try:
        odoo_service = get_odoo_service()
        
        # Record management tools
        if name == "create_record":
            model = arguments["model"]
            values = arguments["values"]
            logger.info(f"Creating record in {model}")
            result = odoo_service.create(model, values)
            return [TextContent(type="text", text=json.dumps({"id": result, "message": f"Created record with ID: {result}"}, indent=2))]
        
        elif name == "update_record":
            model = arguments["model"]
            ids = arguments["ids"]
            values = arguments["values"]
            logger.info(f"Updating {len(ids)} record(s) in {model}")
            success = odoo_service.write(model, ids, values)
            return [TextContent(type="text", text=json.dumps({"success": success, "ids": ids, "message": f"Update {'successful' if success else 'failed'} for IDs: {ids}"}, indent=2))]
        
        elif name == "delete_record":
            model = arguments["model"]
            ids = arguments["ids"]
            logger.info(f"Deleting {len(ids)} record(s) from {model}")
            success = odoo_service.unlink(model, ids)
            return [TextContent(type="text", text=json.dumps({"success": success, "ids": ids, "message": f"Delete {'successful' if success else 'failed'} for IDs: {ids}"}, indent=2))]
        
        elif name == "get_record":
            model = arguments["model"]
            ids = arguments["ids"]
            fields = arguments.get("fields")
            logger.info(f"Getting {len(ids)} record(s) from {model}")
            result = odoo_service.read(model, ids, fields)
            return [TextContent(type="text", text=json.dumps({"records": result, "count": len(result)}, indent=2, default=str))]
        
        elif name == "execute_method":
            model = arguments["model"]
            method = arguments["method"]
            ids = arguments.get("ids", [])
            args = arguments.get("args", [])
            kwargs = arguments.get("kwargs", {})
            logger.info(f"Executing method '{method}' on {model} with IDs: {ids}")
            
            # Prepare arguments - if ids are provided, add them to args
            if ids:
                args = [ids] + list(args)
            
            # Execute the method
            result = odoo_service.execute(model, method, *args, **kwargs)
            return [TextContent(type="text", text=json.dumps({"result": result}, indent=2, default=str))]
        
        # Search tools
        elif name == "search_records":
            model = arguments["model"]
            domain = arguments.get("domain", [])
            fields = arguments.get("fields")
            limit = arguments.get("limit")
            offset = arguments.get("offset", 0)
            order = arguments.get("order")
            
            logger.info(f"Searching records in {model} with domain: {domain}")
            result = odoo_service.search_read(
                model=model,
                domain=domain,
                fields=fields,
                offset=offset,
                limit=limit,
                order=order,
            )
            return [TextContent(type="text", text=json.dumps({"records": result, "count": len(result)}, indent=2, default=str))]
        
        elif name == "search_count":
            model = arguments["model"]
            domain = arguments.get("domain", [])
            logger.info(f"Counting records in {model} with domain: {domain}")
            ids = odoo_service.search(model=model, domain=domain)
            count = len(ids)
            return [TextContent(type="text", text=json.dumps({"count": count, "message": f"Found {count} records matching the criteria"}, indent=2))]
        
        # Model tools
        elif name == "list_models":
            include_transient = arguments.get("transient", False)
            search_term = arguments.get("search", "").lower()
            
            logger.info(f"Listing models (transient: {include_transient}, search: '{search_term}')")
            models = odoo_service.get_model_list()
            
            # Filter models
            filtered_models = []
            for model in models:
                if not include_transient and model.get("transient", False):
                    continue
                
                if search_term and search_term not in model["model"].lower() and search_term not in model["name"].lower():
                    continue
                    
                filtered_models.append(model)
            
            # Format output
            if not filtered_models:
                return [TextContent(type="text", text=json.dumps({"models": [], "count": 0, "message": "No models found matching the criteria."}, indent=2))]
            
            output = f"Found {len(filtered_models)} Odoo models:\n\n"
            for model in sorted(filtered_models, key=lambda x: x["model"]):
                transient_marker = " (transient)" if model.get("transient", False) else ""
                output += f"• **{model['model']}**{transient_marker}\n"
                output += f"  {model['name']}\n\n"
            
            return [TextContent(type="text", text=json.dumps({"models": filtered_models, "count": len(filtered_models), "formatted_output": output}, indent=2))]
        
        elif name == "get_model_fields":
            model = arguments["model"]
            fields = arguments.get("fields")
            attributes = arguments.get("attributes")
            
            logger.info(f"Getting fields for model: {model}")
            field_info = odoo_service.fields_get(
                model=model,
                fields=fields,
                attributes=attributes
            )
            
            if not field_info:
                return [TextContent(type="text", text=json.dumps({"fields": {}, "count": 0, "message": f"No fields found for model: {model}"}, indent=2))]
            
            # Format output for better readability
            output = f"Fields for model **{model}**:\n\n"
            
            for field_name, field_def in sorted(field_info.items()):
                field_type = field_def.get("type", "unknown")
                field_string = field_def.get("string", field_name)
                required = " (required)" if field_def.get("required", False) else ""
                readonly = " (readonly)" if field_def.get("readonly", False) else ""
                
                output += f"• **{field_name}** ({field_type}){required}{readonly}\n"
                output += f"  {field_string}\n"
                
                if field_def.get("help"):
                    output += f"  Help: {field_def['help']}\n"
                
                output += "\n"
            
            return [TextContent(type="text", text=json.dumps({"fields": field_info, "count": len(field_info), "formatted_output": output}, indent=2))]
        
        elif name == "model_info":
            model = arguments["model"]
            logger.info(f"Getting comprehensive info for model: {model}")
            
            # Get model metadata
            models = odoo_service.get_model_list()
            model_info = next((m for m in models if m["model"] == model), None)
            
            if not model_info:
                return [TextContent(type="text", text=json.dumps({"error": f"Model '{model}' not found."}, indent=2))]
            
            # Get field count
            field_info = odoo_service.fields_get(model=model)
            field_count = len(field_info)
            
            # Get record count (sample)
            try:
                sample_ids = odoo_service.search(model=model, limit=1)
                has_records = len(sample_ids) > 0
            except:
                has_records = "Unknown"
            
            # Format comprehensive output
            output = f"# Model Information: **{model}**\n\n"
            output += f"**Name:** {model_info['name']}\n"
            output += f"**Technical Name:** {model_info['model']}\n"
            output += f"**Type:** {'Transient (Wizard)' if model_info.get('transient', False) else 'Persistent'}\n"
            output += f"**Fields:** {field_count}\n"
            output += f"**Has Records:** {has_records}\n\n"
            
            # Show some key fields
            key_fields = []
            for field_name, field_def in field_info.items():
                if field_name in ['id', 'name', 'display_name', 'create_date', 'write_date']:
                    key_fields.append(f"• {field_name} ({field_def.get('type', 'unknown')})")
            
            if key_fields:
                output += "**Key Fields:**\n"
                output += "\n".join(key_fields[:10])  # Show first 10
                if len(key_fields) > 10:
                    output += f"\n... and {len(key_fields) - 10} more"
                output += "\n\n"
            
            output += f"Use `get_model_fields` with model='{model}' to see all field details."
            
            return [TextContent(type="text", text=json.dumps({
                "model_info": model_info,
                "field_count": field_count,
                "has_records": has_records,
                "key_fields": key_fields[:10],
                "formatted_output": output
            }, indent=2))]
        
        # Server management tools
        elif name == "server_status":
            return await handle_server_status(arguments)
        
        elif name == "cache_stats":
            return await handle_cache_stats(arguments)
        
        else:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}, indent=2))]
                
    except Exception as e:
        logger.error(f"Error handling tool {name}: {e}", exc_info=True)
        return [TextContent(type="text", text=json.dumps({"error": f"{type(e).__name__}: {str(e)}"}, indent=2))]

    
async def handle_server_status(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle server status requests."""
    config = get_config()
    cache_service = get_cache_service()
    
    # Test Odoo connection
    try:
        odoo_service = get_odoo_service()
        odoo_service.authenticate()
        odoo_connected = True
    except Exception as e:
        logger.warning(f"Odoo connection test failed: {e}")
        odoo_connected = False
        
    uptime = time.time() - _start_time
    cache_stats = cache_service.stats()
    
    # Format output
    output = "# Odoo MCP Server Status\n\n"
    output += f"**Status:** {'HEALTHY' if odoo_connected else 'DEGRADED'}\n"
    output += f"**Version:** 1.0.0\n"
    output += f"**Uptime:** {uptime:.2f}s\n\n"
    
    output += "## Odoo Connection\n"
    output += f"**Connected:** {'✅ Yes' if odoo_connected else '❌ No'}\n"
    output += f"**URL:** {config.odoo.url}\n"
    output += f"**Database:** {config.odoo.database}\n\n"
    
    output += "## Cache\n"
    output += f"**Enabled:** {'✅ Yes' if cache_stats['enabled'] else '❌ No'}\n"
    output += f"**Size:** {cache_stats['size']}/{cache_stats['max_size']}\n"
    output += f"**TTL:** {cache_stats['ttl']}s\n\n"
    
    output += "## Server Configuration\n"
    output += f"**Host:** {config.server.host}\n"
    output += f"**Port:** {config.server.port}\n"
    output += f"**Debug:** {config.server.debug}\n"
    output += f"**Log Level:** {config.server.log_level}\n"
        
    return [TextContent(type="text", text=json.dumps({
        "status": "HEALTHY" if odoo_connected else "DEGRADED",
        "version": "1.0.0",
        "uptime": uptime,
        "odoo_connected": odoo_connected,
        "odoo_url": config.odoo.url,
        "odoo_database": config.odoo.database,
        "cache_stats": cache_stats,
        "server_config": {
            "host": config.server.host,
            "port": config.server.port,
            "debug": config.server.debug,
            "log_level": config.server.log_level
        },
        "formatted_output": output
    }, indent=2))]


async def handle_cache_stats(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle cache statistics requests."""
    cache_service = get_cache_service()
    action = arguments.get("action", "stats")
    
    if action == "clear":
        cache_service.clear()
        return [TextContent(type="text", text=json.dumps({"success": True, "message": "Cache cleared successfully"}, indent=2))]
    
    # Get cache statistics
    stats = cache_service.stats()
    
    output = "# Cache Statistics\n\n"
    output += f"**Enabled:** {'✅ Yes' if stats['enabled'] else '❌ No'}\n"
    output += f"**Current Size:** {stats['size']}\n"
    output += f"**Maximum Size:** {stats['max_size']}\n"
    output += f"**TTL:** {stats['ttl']} seconds\n"
    output += f"**Usage:** {(stats['size'] / stats['max_size'] * 100):.1f}%\n"
    
    return [TextContent(type="text", text=json.dumps({
        "cache_stats": stats,
        "usage_percentage": (stats['size'] / stats['max_size'] * 100),
        "formatted_output": output
    }, indent=2))]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("Starting Odoo MCP HTTP Server...")
    try:
        # Test Odoo connection on startup
        odoo_service = get_odoo_service()
        odoo_service.authenticate()
        logger.info("Odoo connection test successful")
    except Exception as e:
        logger.warning(f"Odoo connection test failed: {e}")
    
    yield
    
    logger.info("Shutting down Odoo MCP HTTP Server...")


# Create FastAPI app
app = FastAPI(
    title="Odoo MCP HTTP Server",
    description="HTTP streaming MCP server for Odoo integration",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# API Key Authentication Middleware
@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    """Verify API key if configured."""
    config = get_config()
    
    # Skip authentication for health check and root GET endpoints
    if request.url.path in ["/health", "/"] and request.method == "GET":
        return await call_next(request)
    
    # If API key is configured, verify it
    if config.server.api_key:
        api_key = request.headers.get("X-API-Key") or request.headers.get("X-Api-Key")
        if not api_key or api_key != config.server.api_key:
            logger.warning(f"Unauthorized access attempt from {request.client.host}")
            return JSONResponse(
                status_code=401,
                content={"error": "Unauthorized", "message": "Invalid or missing API key"}
            )
    
    return await call_next(request)


def _stream_response(data: Dict[str, Any]):
    """Generate SSE stream from data."""
    yield f"data: {json.dumps(data)}\n\n"


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "Odoo MCP HTTP Server", "version": "1.0.0"}


@app.post("/")
async def root_post(request: Request):
    """Root POST endpoint - redirects to MCP endpoint for compatibility."""
    # Forward the request to the MCP endpoint
    return await mcp_endpoint(request)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        odoo_service = get_odoo_service()
        odoo_service.authenticate()
        return {"status": "healthy", "odoo_connected": True}
    except Exception as e:
        return {"status": "degraded", "odoo_connected": False, "error": str(e)}


@app.post("/mcp")
async def mcp_endpoint(request: Request):
    """Main MCP endpoint for handling JSON-RPC requests."""
    try:
        # Parse request body
        body = await request.json()
        
        # Extract JSON-RPC fields
        method = body.get("method")
        params = body.get("params", {})
        request_id = body.get("id")
        
        # Check for streaming preference
        wants_streaming = request.headers.get("accept") == "text/event-stream"
        
        # Generate session ID if not present
        session_id = request.headers.get("Mcp-Session-Id", str(uuid.uuid4()))
        
        logger.info(f"MCP request: {method} (streaming: {wants_streaming})")
        
        # Handle different MCP methods
        if method == "initialize":
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {},
                        "resources": {},
                        "prompts": {},
                        "logging": {
                            "setLevel": True
                        }
                    },
                    "serverInfo": {
                        "name": "odoo-mcp-server",
                        "version": "1.0.0"
                    }
                }
            }
            
            if wants_streaming:
                return EventSourceResponse(
                    _stream_response(response),
                    headers={"Mcp-Session-Id": session_id}
                )
            else:
                return JSONResponse(
                    content=response,
                    headers={"Mcp-Session-Id": session_id}
                )
        
        elif method == "tools/list":
            tools = await get_all_tools()
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"tools": tools}
            }
            
            if wants_streaming:
                return EventSourceResponse(_stream_response(response))
            else:
                return JSONResponse(content=response)
        
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            
            try:
                result = await call_tool(tool_name, arguments)
                
                # Handle different result types
                if isinstance(result, list):
                    # Result is already a list of TextContent objects
                    content = []
                    for item in result:
                        try:
                            # Try to parse as JSON and return as formatted text
                            parsed_json = json.loads(item.text)
                            content.append({
                                "type": "text",
                                "text": json.dumps(parsed_json, indent=2)
                            })
                        except json.JSONDecodeError:
                            # If not JSON, return as plain text
                            content.append({"type": "text", "text": item.text})
                elif isinstance(result, str):
                    # Result is a plain string (error case)
                    content = [{"type": "text", "text": result}]
                else:
                    # Fallback
                    content = [{"type": "text", "text": str(result)}]
                
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": content
                    }
                }
                
                if wants_streaming:
                    return EventSourceResponse(_stream_response(response))
                else:
                    return JSONResponse(content=response)
                    
            except Exception as e:
                logger.error(f"Error calling tool {tool_name}: {e}", exc_info=True)
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32603,
                        "message": "Internal error: " + str(e)
                    }
                }
                
                if wants_streaming:
                    return EventSourceResponse(_stream_response(response))
                else:
                    return JSONResponse(content=response)
        
        elif method in ["logging/set_level", "logging/set level", "logging/setLevel", "logging/set-level"]:
            # Handle logging level setting
            level = params.get("level", "info")
            
            # Validate log level against MCP specification
            valid_levels = ["debug", "info", "notice", "warning", "error", "critical", "alert", "emergency"]
            if level not in valid_levels:
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32602,
                        "message": "Invalid params",
                        "data": f"Invalid log level: {level}. Valid levels: {', '.join(valid_levels)}"
                    }
                }
                
                if wants_streaming:
                    return EventSourceResponse(_stream_response(response))
                else:
                    return JSONResponse(content=response)
            
            try:
                # Update the logger level
                import logging
                numeric_level = getattr(logging, level.upper(), logging.INFO)
                logging.getLogger().setLevel(numeric_level)
                
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {}
                }
                
                if wants_streaming:
                    return EventSourceResponse(_stream_response(response))
                else:
                    return JSONResponse(content=response)
                    
            except Exception as e:
                logger.error(f"Logging level setting error: {e}")
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32603,
                        "message": "Failed to set logging level: " + str(e)
                    }
                }
                
                if wants_streaming:
                    return EventSourceResponse(_stream_response(response))
                else:
                    return JSONResponse(content=response)
        
        elif method == "notifications/cancelled":
            # Handle notification cancellation - just acknowledge
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {}
            }
            
            if wants_streaming:
                return EventSourceResponse(_stream_response(response))
            else:
                return JSONResponse(content=response)
        
        else:
            # Log unknown methods for debugging
            logger.warning(f"Unknown method requested: {method}")
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            }
            
            if wants_streaming:
                return EventSourceResponse(_stream_response(response))
            else:
                return JSONResponse(content=response)
    
    except Exception as e:
        logger.error(f"Error processing MCP request: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32603,
                    "message": "Internal error: " + str(e)
                }
            }
        )


if __name__ == "__main__":
    config = get_config()
    uvicorn.run(
        "mcp_server_odoo.http_server:app",
        host=config.server.host,
        port=config.server.port,
        reload=config.server.debug,
        log_level=config.server.log_level.lower()
    )