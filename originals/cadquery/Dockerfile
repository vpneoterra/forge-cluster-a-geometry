# ============================================================
# CadQuery - Parametric CAD Engine - ARM64-compatible
# Multi-stage build: builder + runtime
# Port: 8002 | Memory: 1g
# ============================================================

# ── Stage 1: Build environment ───────────────────────────────
FROM --platform=linux/arm64 python:3.11-slim AS builder

LABEL maintainer="forge-production" \
      description="CadQuery parametric CAD engine" \
      version="2.1.0"

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libxrender1 \
    libxext6 \
    libsm6 \
    libglu1-mesa \
    libfontconfig1 \
    libxss1 \
    libxtst6 \
    git \
    wget \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install CadQuery and its dependencies
# cadquery uses OCC (Open CASCADE) which has ARM64 wheels via cadquery-ocp
RUN pip install --no-cache-dir \
    cadquery \
    cadquery-ocp \
    numpy>=1.24 \
    scipy>=1.10 \
    pyparsing>=3.0

# Install DAGMC support for neutronics geometry export
RUN pip install --no-cache-dir \
    cq_warehouse \
    cadquery-server || true

# ── Stage 2: Runtime ─────────────────────────────────────────
FROM --platform=linux/arm64 python:3.11-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libxrender1 \
    libxext6 \
    libsm6 \
    libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 -s /bin/bash forge

COPY --from=builder /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=builder /usr/local/bin /usr/local/bin

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY api_wrapper.py /app/api_wrapper.py

RUN mkdir -p /data /app/models && chown -R forge:forge /data /app

WORKDIR /app
USER forge

EXPOSE 8002

ENV FORGE_TIMEOUT=300 \
    FORGE_PORT=8002 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DISPLAY=:99

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8002/health')"

CMD ["python", "-m", "uvicorn", "api_wrapper:app", "--host", "0.0.0.0", "--port", "8002", "--workers", "1"]
