# ============================================================
# picogk — Voxel Geometry Engine (PicoGK shim)
# Inherits from forge-python-base (shared base image)
# Single-stage build (no heavy compilation required)
# Port: 8015 | Memory limit: 1g
#
# Build order:
#   1. docker build -t forge-python-base:1.0.0 ../forge-python-base
#   2. docker build -t forge-picogk:1.1.0 .
#
# Changes from original:
#   - Aligned to Python 3.11 (original used 3.12 — now consistent with cluster)
#   - Inherits from forge-python-base (non-root user already configured)
#   - Pinned all requirements versions (original already had pinned versions)
#   - Added SOLVER_VERSION + GIT_COMMIT build args for /version endpoint
#   - Healthcheck uses curl -f (consistent with base pattern)
#   - Removed redundant USER/RUN useradd (provided by base image)
# ============================================================

FROM forge-python-base:1.0.0

ARG SOLVER_VERSION=1.1.0
ARG GIT_COMMIT=unknown

# Switch to root only for installation, then back to forge
USER root

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY api_wrapper.py /app/api_wrapper.py

RUN mkdir -p /opt/forge/data && chown -R forge:forge /app /opt/forge/data

USER forge

ENV SOLVER_VERSION=${SOLVER_VERSION} \
    GIT_COMMIT=${GIT_COMMIT} \
    FORGE_PORT=8015 \
    FORGE_TIMEOUT=600 \
    FORGE_DATA_DIR=/opt/forge/data \
    PICOGK_VOXEL_SIZE=0.2

EXPOSE 8015

LABEL org.opencontainers.image.title="forge-picogk" \
      org.opencontainers.image.description="PicoGK voxel geometry engine shim for FORGE" \
      org.opencontainers.image.version="${SOLVER_VERSION}"

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${FORGE_PORT:-8015}/health || exit 1

CMD ["sh", "-c", "python -m uvicorn api_wrapper:app --host 0.0.0.0 --port ${FORGE_PORT:-8015} --workers 1"]
