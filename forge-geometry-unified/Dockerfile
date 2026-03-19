# ============================================================
# forge-geometry-unified — Single Container with All 4 Geometry Engines
#
# Consolidation rationale:
#   CadQuery + OCC (~600 MB) is a shared dependency of cadquery, paramak,
#   and parastell. In the individual setup, it was installed 3 separate times
#   (~1.8 GB wasted). This unified image installs CadQuery/OCC ONCE as a
#   base layer, then adds Paramak, ParaStell, and PicoGK on top.
#
# Estimated image savings: ~1.8 GB compared to running all 4 separately
#
# Exposes a unified API gateway on port 8020 that routes to sub-solvers:
#   POST /cadquery/* → CadQuery engine
#   POST /paramak/*  → Paramak engine
#   POST /parastell/*→ ParaStell engine
#   POST /picogk/*   → PicoGK engine
#   GET  /health     → Aggregate health of all engines
#   GET  /metrics    → Aggregate Prometheus metrics
#
# Build:
#   docker build -t forge-geometry-unified:2.2.0 ./forge-geometry-unified
#
# Run (production):
#   docker run -p 8020:8020 --memory=4g forge-geometry-unified:2.2.0
# ============================================================

# ── Stage 1: CadQuery/OCC base layer (heavy, installed ONCE) ─
FROM forge-python-base:1.0.0 AS cq-layer

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglu1-mesa \
    libsm6 \
    libxss1 \
    libxtst6 \
    libhdf5-dev \
    git \
    gcc \
    g++ \
    cmake \
    make \
    wget \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip==24.3.1 setuptools wheel

# ── CadQuery + OCC — installed ONCE, shared by all engines ───
RUN pip install --no-cache-dir \
    cadquery==2.4.0 \
    cadquery-ocp==7.7.2.1 \
    numpy==1.26.4 \
    scipy==1.13.1 \
    pyparsing==3.1.4

# CAD utilities
RUN pip install --no-cache-dir \
    cq_warehouse==0.9.5 \
    bd_warehouse==0.10.0 || true

# ── Paramak (additional layer on top of CadQuery) ────────────
RUN pip install --no-cache-dir paramak==0.8.3 || \
    pip install --no-cache-dir "git+https://github.com/fusion-energy/paramak.git@main" || true

# ── ParaStell deps (DAGMC, pystell, netCDF4) ─────────────────
RUN pip install --no-cache-dir \
    netCDF4==1.7.1 \
    h5py==3.11.0

RUN pip install --no-cache-dir dagmc==3.2.4 || true
RUN pip install --no-cache-dir pystell==1.0.0 || true

RUN git clone --depth=1 https://github.com/svalinn/parastell.git /build/parastell && \
    pip install --no-cache-dir -e /build/parastell --no-build-isolation || \
    pip install --no-cache-dir -r /build/parastell/requirements.txt || true

# ── Stage 2: Unified runtime ──────────────────────────────────
FROM forge-python-base:1.0.0 AS runtime

ARG SOLVER_VERSION=2.2.0
ARG GIT_COMMIT=unknown

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglu1-mesa \
    libsm6 \
    libfontconfig1 \
    libhdf5-serial-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy ALL installed packages from cq-layer (one set covers all engines)
COPY --from=cq-layer /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=cq-layer /usr/local/bin /usr/local/bin
COPY --from=cq-layer /build/parastell /opt/parastell

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Application files
COPY api_gateway.py /app/api_gateway.py

RUN mkdir -p /data /opt/forge/data /app && \
    chown -R forge:forge /data /opt/forge/data /app

WORKDIR /app
USER forge

ENV SOLVER_VERSION=${SOLVER_VERSION} \
    GIT_COMMIT=${GIT_COMMIT} \
    FORGE_PORT=8020 \
    FORGE_TIMEOUT=300 \
    PARASTELL_HOME=/opt/parastell \
    FORGE_DATA_DIR=/opt/forge/data \
    PICOGK_VOXEL_SIZE=0.2

EXPOSE 8020

LABEL org.opencontainers.image.title="forge-geometry-unified" \
      org.opencontainers.image.description="Unified FORGE geometry container: CadQuery + Paramak + ParaStell + PicoGK" \
      org.opencontainers.image.version="${SOLVER_VERSION}"

HEALTHCHECK --interval=30s --timeout=15s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8020/health || exit 1

CMD ["python", "-m", "uvicorn", "api_gateway:app", "--host", "0.0.0.0", "--port", "8020", "--workers", "1"]
