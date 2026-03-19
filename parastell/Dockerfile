# ============================================================
# parastell — Stellarator Geometry Tool
# Inherits from forge-python-base (shared base image)
# Multi-stage: builder compiles DAGMC deps from source
# Port: 8007 | Memory limit: 2g (DAGMC is memory-intensive)
#
# Build order:
#   1. docker build -t forge-python-base:1.0.0 ../forge-python-base
#   2. docker build -t forge-parastell:2.2.0 .
#
# Changes from original:
#   - Removed --platform=linux/arm64 hardcoding (multi-platform)
#   - Inherits from forge-python-base (eliminates duplicate common deps)
#   - Pinned all package versions (no >= ranges)
#   - Added SOLVER_VERSION + GIT_COMMIT build args for /version endpoint
#   - Healthcheck uses curl (consistent with base pattern)
#   - Increased start-period to 120s (DAGMC build takes longer to cold-start)
#
# ARM64 note: DAGMC requires HDF5 and may need compilation from source.
# See originals/parastell/BUILD_NOTES.md for ARM64-specific guidance.
# ============================================================

# ── Stage 1: Build environment ───────────────────────────────
FROM forge-python-base:1.0.0 AS builder

ARG SOLVER_VERSION=2.2.0
ARG GIT_COMMIT=unknown

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    libsm6 \
    gcc \
    g++ \
    cmake \
    make \
    git \
    wget \
    libhdf5-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip==24.3.1 setuptools wheel

# CadQuery base (ParaStell dependency)
RUN pip install --no-cache-dir \
    cadquery==2.4.0 \
    cadquery-ocp==7.7.2.1 \
    numpy==1.26.4 \
    scipy==1.13.1 \
    netCDF4==1.7.1 \
    h5py==3.11.0

# DAGMC: try pip, fall back to source build
RUN pip install --no-cache-dir dagmc==3.2.4 || \
    ( git clone --depth=1 https://github.com/svalinn/DAGMC.git /build/dagmc && \
      pip install --no-cache-dir /build/dagmc ) || true

# PyStell: stellarator geometry parameterization
RUN pip install --no-cache-dir pystell==1.0.0 || \
    ( git clone --depth=1 https://github.com/PrincetonUniversity/pystell.git /build/pystell && \
      pip install --no-cache-dir /build/pystell ) || true

# ParaStell
RUN git clone --depth=1 https://github.com/svalinn/parastell.git /build/parastell
WORKDIR /build/parastell
RUN pip install --no-cache-dir -e . --no-build-isolation || \
    pip install --no-cache-dir -r requirements.txt || true

# ── Stage 2: Runtime ─────────────────────────────────────────
FROM forge-python-base:1.0.0 AS runtime

ARG SOLVER_VERSION=2.2.0
ARG GIT_COMMIT=unknown

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    libsm6 \
    libfontconfig1 \
    libhdf5-serial-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /build/parastell /opt/parastell

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY api_wrapper.py /app/api_wrapper.py

RUN mkdir -p /data /app/models && chown -R forge:forge /data /app

WORKDIR /app
USER forge

ENV SOLVER_VERSION=${SOLVER_VERSION} \
    GIT_COMMIT=${GIT_COMMIT} \
    FORGE_PORT=8007 \
    FORGE_TIMEOUT=300 \
    PARASTELL_HOME=/opt/parastell

EXPOSE 8007

LABEL org.opencontainers.image.title="forge-parastell" \
      org.opencontainers.image.description="ParaStell stellarator geometry tool for FORGE" \
      org.opencontainers.image.version="${SOLVER_VERSION}"

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8007/health || exit 1

CMD ["python", "-m", "uvicorn", "api_wrapper:app", "--host", "0.0.0.0", "--port", "8007", "--workers", "1"]
