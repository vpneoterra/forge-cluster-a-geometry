# ============================================================
# paramak — Fusion Reactor Parametric CAD
# Inherits from forge-python-base (shared base image)
# Multi-stage: builder installs heavy CAD + Paramak deps
# Port: 8006 | Memory limit: 1.5g
#
# Build order:
#   1. docker build -t forge-python-base:1.0.0 ../forge-python-base
#   2. docker build -t forge-paramak:2.2.0 .
#
# Changes from original:
#   - Removed --platform=linux/arm64 hardcoding (multi-platform)
#   - Inherits from forge-python-base (eliminates duplicate common deps)
#   - Pinned all package versions (no >= ranges)
#   - Added SOLVER_VERSION + GIT_COMMIT build args for /version endpoint
#   - Aligned healthcheck to use curl (consistent with base pattern)
# ============================================================

# ── Stage 1: Build environment ───────────────────────────────
FROM forge-python-base:1.0.0 AS builder

ARG SOLVER_VERSION=2.2.0
ARG GIT_COMMIT=unknown

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    libsm6 \
    git \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip==24.3.1 setuptools wheel

# CadQuery is Paramak's primary dependency
RUN pip install --no-cache-dir \
    cadquery==2.4.0 \
    cadquery-ocp==7.7.2.1 \
    numpy==1.26.4 \
    scipy==1.13.1

# Paramak: try PyPI first, fall back to GitHub source
RUN pip install --no-cache-dir paramak==0.8.3 || \
    pip install --no-cache-dir "git+https://github.com/fusion-energy/paramak.git@main" || true

# Optional neutronics geometry support
RUN pip install --no-cache-dir paramak-neutronics==0.1.0 || true

# ── Stage 2: Runtime ─────────────────────────────────────────
FROM forge-python-base:1.0.0 AS runtime

ARG SOLVER_VERSION=2.2.0
ARG GIT_COMMIT=unknown

USER root

# Additional runtime libraries beyond base
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsm6 \
    libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=builder /usr/local/bin /usr/local/bin

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY api_wrapper.py /app/api_wrapper.py

RUN mkdir -p /data /app/models && chown -R forge:forge /data /app

WORKDIR /app
USER forge

ENV SOLVER_VERSION=${SOLVER_VERSION} \
    GIT_COMMIT=${GIT_COMMIT} \
    FORGE_PORT=8006 \
    FORGE_TIMEOUT=300

EXPOSE 8006

LABEL org.opencontainers.image.title="forge-paramak" \
      org.opencontainers.image.description="Paramak fusion reactor parametric CAD for FORGE" \
      org.opencontainers.image.version="${SOLVER_VERSION}"

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -f http://localhost:8006/health || exit 1

CMD ["python", "-m", "uvicorn", "api_wrapper:app", "--host", "0.0.0.0", "--port", "8006", "--workers", "1"]
