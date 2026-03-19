FROM python:3.12-slim

LABEL maintainer="forge-production" \
      description="PicoGK voxel geometry engine shim for FORGE" \
      version="1.0.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FORGE_PORT=8015 \
    FORGE_TIMEOUT=600 \
    FORGE_DATA_DIR=/opt/forge/data \
    PICOGK_VOXEL_SIZE=0.2

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 -s /bin/bash forge

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api_wrapper.py /app/api_wrapper.py

RUN mkdir -p /opt/forge/data && chown -R forge:forge /app /opt/forge/data

USER forge
EXPOSE 8015

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:${FORGE_PORT}/health || exit 1

CMD ["sh", "-c", "python -m uvicorn api_wrapper:app --host 0.0.0.0 --port ${FORGE_PORT:-8015} --workers 1"]
