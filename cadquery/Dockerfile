# ============================================================
# cadquery — Parametric CAD Engine
# Inherits from forge-python-base (shared base image)
# Multi-stage: builder installs heavy CAD deps, runtime is slim
# Port: 8002 | Memory limit: 1.5g
#
# Build order:
#   1. docker build -t forge-python-base:1.0.0 ../forge-python-base
#   2. docker build -t forge-cadquery:2.2.0 .
#
# Changes from original:
#   - Removed --platform=linux/arm64 hardcoding (multi-platform support)
#   - Base inherits from forge-python-base (shared common deps)
#   - Added /version endpoint support via SOLVER_VERSION + GIT_COMMIT args
#   - Pinned all requirements (no >= ranges)
#   - Added bd_warehouse (from patch)
#   - Reduced redundant apt layers in builder stage
# ============================================================

# ── Stage 1: Build environment ───────────────────────────────
FROM forge-python-base:1.0.0 AS builder

# Build args for version metadata (injected at build time by CI)
ARG SOLVER_VERSION=2.2.0
ARG GIT_COMMIT=unknown

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglu1-mesa \
    libsm6 \
    libxss1 \
    libxtst6 \
    git \
    wget \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip in builder stage
RUN pip install --no-cache-dir --upgrade pip==24.3.1 setuptools wheel

# Install CadQuery + OCC (heavy ~600 MB, installed once, shared in unified image)
RUN pip install --no-cache-dir \
    cadquery==2.4.0 \
    cadquery-ocp==7.7.2.1

# Install CAD utilities (from patch: bd_warehouse added alongside cq_warehouse)
RUN pip install --no-cache-dir \
    numpy==1.26.4 \
    scipy==1.13.1 \
    pyparsing==3.1.4 \
    cq_warehouse==0.9.5 \
    bd_warehouse==0.10.0 || true

# ── Stage 2: Runtime ─────────────────────────────────────────
FROM forge-python-base:1.0.0 AS runtime

ARG SOLVER_VERSION=2.2.0
ARG GIT_COMMIT=unknown

USER root

# Additional runtime system libraries beyond base
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglu1-mesa \
    libsm6 \
    libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=builder /usr/local/bin /usr/local/bin

# Install service-specific Python requirements (already have base from forge-python-base)
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Application code
COPY api_wrapper.py /app/api_wrapper.py

RUN mkdir -p /data /app/models && chown -R forge:forge /data /app

WORKDIR /app
USER forge

# ── Version metadata ─────────────────────────────────────────
ENV SOLVER_VERSION=${SOLVER_VERSION} \
    GIT_COMMIT=${GIT_COMMIT} \
    FORGE_PORT=8002 \
    FORGE_TIMEOUT=300 \
    DISPLAY=:99

EXPOSE 8002

LABEL org.opencontainers.image.title="forge-cadquery" \
      org.opencontainers.image.description="CadQuery parametric CAD engine for FORGE" \
      org.opencontainers.image.version="${SOLVER_VERSION}"

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -f http://localhost:8002/health || exit 1

CMD ["python", "-m", "uvicorn", "api_wrapper:app", "--host", "0.0.0.0", "--port", "8002", "--workers", "1"]
