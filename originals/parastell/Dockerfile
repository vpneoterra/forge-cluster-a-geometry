# ============================================================
# ParaStell - Stellarator Geometry Tool - ARM64-compatible
# Depends: CadQuery, DAGMC, pystell
# Port: 8007 | Memory: 1.5g
# ============================================================

FROM --platform=linux/arm64 python:3.11-slim AS builder

LABEL maintainer="forge-production" \
      description="ParaStell stellarator geometry CAD tool" \
      version="2.1.0"

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libxrender1 \
    libxext6 \
    libsm6 \
    libfontconfig1 \
    gcc \
    g++ \
    cmake \
    make \
    git \
    wget \
    libhdf5-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# CadQuery base (ParaStell dependency)
RUN pip install --no-cache-dir \
    cadquery \
    cadquery-ocp \
    numpy>=1.24 \
    scipy>=1.10

# DAGMC (Direct Accelerated Geometry Monte Carlo)
# ARM64 wheel may not be available; build from source
RUN pip install --no-cache-dir \
    dagmc || \
    git clone --depth=1 https://github.com/svalinn/DAGMC.git /build/dagmc && \
    pip install --no-cache-dir /build/dagmc || true

# PyStell (stellarator geometry parameterization)
RUN pip install --no-cache-dir \
    pystell || \
    git clone --depth=1 https://github.com/PrincetonUniversity/pystell.git /build/pystell && \
    pip install --no-cache-dir /build/pystell || true

# ParaStell
RUN git clone --depth=1 https://github.com/svalinn/parastell.git /build/parastell
WORKDIR /build/parastell
RUN pip install --no-cache-dir -e . --no-build-isolation || \
    pip install --no-cache-dir -r requirements.txt || true

# ── Runtime ───────────────────────────────────────────────────
FROM --platform=linux/arm64 python:3.11-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libxrender1 \
    libfontconfig1 \
    libhdf5-serial-dev \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 -s /bin/bash forge

COPY --from=builder /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /build/parastell /opt/parastell

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY api_wrapper.py /app/api_wrapper.py

RUN mkdir -p /data /app/models && chown -R forge:forge /data /app

WORKDIR /app
USER forge

EXPOSE 8007

ENV FORGE_TIMEOUT=300 \
    FORGE_PORT=8007 \
    PARASTELL_HOME=/opt/parastell \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8007/health')"

CMD ["python", "-m", "uvicorn", "api_wrapper:app", "--host", "0.0.0.0", "--port", "8007", "--workers", "1"]
