# ============================================================
# forge-python-base — Shared Python Base Image for Cluster A
# All geometry kernel services inherit FROM this image.
#
# Provides:
#   - Python 3.11-slim runtime
#   - Non-root 'forge' user (uid 1000)
#   - Common system libraries (GL, GLib, curl)
#   - Pinned common Python deps (FastAPI, uvicorn, pydantic, psutil, etc.)
#   - Standard HEALTHCHECK pattern (overridable per service)
#   - PYTHONUNBUFFERED / PYTHONDONTWRITEBYTECODE env vars
#
# Build: docker build -t forge-python-base:1.0.0 ./forge-python-base
# ============================================================

FROM python:3.11-slim

LABEL maintainer="forge-production" \
      description="Shared Python base image for FORGE Cluster A Geometry Kernel" \
      version="1.0.0" \
      org.opencontainers.image.title="forge-python-base" \
      org.opencontainers.image.description="Shared base for FORGE geometry services" \
      org.opencontainers.image.version="1.0.0"

# ── Environment ──────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ── System dependencies ──────────────────────────────────────
# libgl1       : OpenGL (required by CadQuery/OCC even in headless mode)
# libglib2.0-0 : GLib (required by many OpenGL-dependent packages)
# curl         : Used in HEALTHCHECK CMD pattern
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libxrender1 \
    libxext6 \
    libfontconfig1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── Non-root user ─────────────────────────────────────────────
# All services run as 'forge' (uid 1000) — never root in production
RUN useradd -m -u 1000 -s /bin/bash forge

# ── Common Python dependencies ───────────────────────────────
# Pinned versions for reproducibility; services may add on top
COPY requirements-base.txt /tmp/requirements-base.txt
RUN pip install --no-cache-dir --upgrade pip==24.3.1 && \
    pip install --no-cache-dir -r /tmp/requirements-base.txt && \
    rm /tmp/requirements-base.txt

# ── Standard directories ─────────────────────────────────────
RUN mkdir -p /data /app && chown -R forge:forge /data /app

WORKDIR /app

# ── Default healthcheck (override per service with correct port) ─
# Services should override CMD to point to their own port
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${FORGE_PORT:-8000}/health || exit 1

# Switch to non-root user for all subsequent layers
USER forge
