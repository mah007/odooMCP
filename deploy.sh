#!/bin/bash

# Odoo MCP Server - Enhanced Deployment Script
# This script automates the deployment of the enhanced Odoo MCP Server

set -e

echo "======================================"
echo "Odoo MCP Server - Enhanced Deployment"
echo "======================================"
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Error: Docker is not installed."
    echo "Please install Docker first: https://docs.docker.com/engine/install/"
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "❌ Error: Docker Compose is not installed."
    echo "Please install Docker Compose first: https://docs.docker.com/compose/install/"
    exit 1
fi

echo "✅ Docker and Docker Compose are installed"
echo ""

# Check if .env file exists
if [ ! -f .env ]; then
    echo "⚠️  Warning: .env file not found"
    echo "Creating a template .env file..."
    cat > .env <<EOF
# Odoo Connection (Required)
ODOO_URL=https://your-odoo-instance.com
ODOO_DB=your_database_name
ODOO_USERNAME=your_odoo_user
ODOO_API_KEY=your_odoo_api_key_or_password

# MCP Server Configuration
MCP_HOST=0.0.0.0
MCP_PORT=8000
MCP_DEBUG=false
MCP_LOG_LEVEL=INFO

# MCP Server Security (Highly Recommended)
# Generate a strong key with: openssl rand -hex 32
MCP_API_KEY=CHANGE_THIS_TO_A_STRONG_RANDOM_KEY

# Cache Configuration
CACHE_ENABLED=true
CACHE_TTL=300
CACHE_MAX_SIZE=1000
EOF
    echo "✅ Template .env file created"
    echo ""
    echo "⚠️  IMPORTANT: Please edit the .env file with your actual configuration before proceeding."
    echo "Press Enter to open the .env file in nano, or Ctrl+C to exit and edit manually."
    read
    nano .env
fi

echo "📋 Current configuration:"
echo "  ODOO_URL: $(grep ODOO_URL .env | cut -d'=' -f2)"
echo "  ODOO_DB: $(grep ODOO_DB .env | cut -d'=' -f2)"
echo "  MCP_PORT: $(grep MCP_PORT .env | cut -d'=' -f2)"
echo "  MCP_API_KEY: $(grep MCP_API_KEY .env | cut -d'=' -f2 | sed 's/./*/g')"
echo ""

# Confirm deployment
read -p "Do you want to proceed with the deployment? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Deployment cancelled."
    exit 0
fi

echo ""
echo "🔨 Building and starting the MCP server..."
echo ""

# Stop existing container if running
docker compose down 2>/dev/null || true

# Build and start the container
docker compose up --build -d

echo ""
echo "⏳ Waiting for the server to start..."
sleep 5

# Check if the container is running
if docker ps | grep -q mcp-server; then
    echo "✅ MCP server container is running"
else
    echo "❌ Error: MCP server container failed to start"
    echo "Checking logs..."
    docker logs mcp-server
    exit 1
fi

echo ""
echo "🔍 Testing the server..."
echo ""

# Test the health endpoint
if curl -s http://localhost:8000/health | grep -q "ok"; then
    echo "✅ Health check passed"
else
    echo "❌ Health check failed"
    echo "Server logs:"
    docker logs mcp-server
    exit 1
fi

echo ""
echo "======================================"
echo "✅ Deployment Successful!"
echo "======================================"
echo ""
echo "Your Odoo MCP Server is now running on port $(grep MCP_PORT .env | cut -d'=' -f2)"
echo ""
echo "Next steps:"
echo "1. Configure your n8n MCP Client node to connect to this server"
echo "2. Use the API Key from your .env file for authentication"
echo "3. Read the DEPLOYMENT_GUIDE.md for detailed integration instructions"
echo ""
echo "Useful commands:"
echo "  View logs:    docker logs -f mcp-server"
echo "  Stop server:  docker compose down"
echo "  Restart:      docker compose restart"
echo ""
