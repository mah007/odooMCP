"""FastAPI Controller service — port 8001.

Serves the React SPA and provides REST API endpoints for admin management.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from src.shared.database import init_db
from src.controller.routes import auth, connections, api_keys, dashboard

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Controller service started")
    yield
    logger.info("Controller service stopped")


app = FastAPI(title="Odoo MCP Controller", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# API routers
app.include_router(auth.router)
app.include_router(connections.router)
app.include_router(api_keys.router)
app.include_router(dashboard.router)

# Serve built React SPA — only if the static directory exists (i.e. after frontend build)
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        index = STATIC_DIR / "index.html"
        return FileResponse(str(index))
else:
    @app.get("/", include_in_schema=False)
    async def dev_root():
        return {
            "message": "Controller API is running. Frontend not built yet.",
            "api_docs": "/docs",
        }
