#!/bin/sh
set -e

# Ensure data directory exists
mkdir -p /app/data /app/logs

echo "Starting MCP service on port ${MCP_PORT:-8000}..."
uvicorn src.mcp.app:app \
  --host 0.0.0.0 \
  --port "${MCP_PORT:-8000}" \
  --log-level info &

echo "Starting Controller service on port ${CONTROLLER_PORT:-8001}..."
exec uvicorn src.controller.app:app \
  --host 0.0.0.0 \
  --port "${CONTROLLER_PORT:-8001}" \
  --log-level info
