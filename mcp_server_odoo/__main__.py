"""Main entry point for the MCP server."""

import sys
import asyncio
from .server import main

if __name__ == "__main__":
    asyncio.run(main())
