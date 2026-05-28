# Stage 1: Build React frontend
# vite.config.ts outDir is '../src/controller/static' relative to /build
# so built assets land at /src/controller/static
FROM node:20-alpine AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime
FROM python:3.11-slim
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Copy everything needed for install up front
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install (non-editable so README.md + src are present)
RUN pip install --no-cache-dir .

# Copy built frontend from Stage 1
COPY --from=frontend-builder /src/controller/static ./src/controller/static

COPY start.sh ./
RUN chmod +x start.sh && mkdir -p data logs

EXPOSE 8000 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/health && curl -f http://localhost:8001/api/auth/status || exit 1

CMD ["./start.sh"]
