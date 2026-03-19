# CHANGELOG — FORGE Cluster A: Geometry Kernel

All changes are relative to the originals in `originals/`. Every file in
`originals/` is an exact, unmodified copy of the source from vpneoterra/forgenew.

---

## [2.2.0] — 2026-03-19 — Cluster A Consolidation

### Added

#### forge-python-base (NEW)
- `forge-python-base/Dockerfile` — Shared Python 3.11-slim base image.
  **Rationale:** cadquery, paramak, and parastell all used identical apt
  packages and pip packages (fastapi, uvicorn, pydantic, psutil). Extracting
  these into a shared base eliminates ~300 MB of duplicated layers across the
  three services.
- `forge-python-base/requirements-base.txt` — Pinned common dependencies:
  fastapi==0.115.6, uvicorn[standard]==0.32.1, pydantic==2.9.2,
  psutil==5.9.8, prometheus-client==0.21.0, pint==0.24.3, httpx==0.27.2.
  **Rationale:** Originals used `>=` ranges (e.g., `fastapi>=0.111.0`),
  making builds non-reproducible. All versions are now pinned.

#### forge-geometry-unified (NEW)
- `forge-geometry-unified/Dockerfile` — Single container running all 4 engines.
  **Rationale:** cadquery, paramak, and parastell all install CadQuery + OCC
  (~600 MB each). By building one shared layer, ~1.8 GB of redundant data is
  eliminated. Suited for production deployments where resource efficiency matters.
- `forge-geometry-unified/api_gateway.py` — Unified FastAPI gateway that routes
  requests to all 4 sub-solvers with consistent run_id, /health, /version, and
  /metrics endpoints.
  Routes: /cadquery/*, /paramak/*, /parastell/*, /picogk/*
- `forge-geometry-unified/requirements.txt` — Minimal additional deps (all
  engine packages installed in Dockerfile stages).

#### Top-level infrastructure
- `docker-compose.yml` — Complete compose file with two profiles:
  - `--profile individual` (or `dev`): Runs all 4 services separately.
  - `--profile unified` (or `production`): Runs the consolidated container.
- `.env.example` — All configurable environment variables with defaults.
- `.dockerignore` — Shared ignore file preventing __pycache__, .git, .env,
  and binary artifacts from entering any build context.
- `AI_CONTEXT.md` — Machine-readable documentation for AI tooling.
- `README.md` — Full cluster documentation with ASCII architecture diagram.
- `CHANGELOG.md` — This file.

### Changed

#### cadquery/Dockerfile
- **Removed** `--platform=linux/arm64` from both FROM lines.
  **Rationale:** Hardcoding ARM64 prevents multi-platform CI/CD builds.
  Multi-platform support is now via `docker buildx --platform linux/amd64,linux/arm64`.
- **Changed** `FROM python:3.11-slim` → `FROM forge-python-base:1.0.0`.
  **Rationale:** Inherits shared non-root user, apt libs, and pinned Python deps.
- **Added** `ARG SOLVER_VERSION` and `ARG GIT_COMMIT` build arguments.
  **Rationale:** Enables the `/version` endpoint to report the exact solver
  version and commit SHA deployed, critical for reproducibility in physics sims.
- **Added** `bd_warehouse==0.10.0` to dependencies (from Dockerfile.patch).
  **Rationale:** bd_warehouse was already documented in the patch file;
  consolidated into the improved Dockerfile.
- **Changed** healthcheck from `python -c urllib.request...` to `curl -f`.
  **Rationale:** Consistent curl-based healthchecks across all services.
  Requires curl in the image (already added to forge-python-base).
- **Pinned** all requirement versions (no `>=` ranges).

#### paramak/Dockerfile
- **Removed** `--platform=linux/arm64` from both FROM lines.
- **Changed** `FROM python:3.11-slim` → `FROM forge-python-base:1.0.0`.
- **Added** `ARG SOLVER_VERSION` and `ARG GIT_COMMIT`.
- **Changed** healthcheck to `curl -f` pattern.
- **Pinned** all requirement versions.

#### parastell/Dockerfile
- **Removed** `--platform=linux/arm64` from both FROM lines.
- **Changed** `FROM python:3.11-slim` → `FROM forge-python-base:1.0.0`.
- **Added** `ARG SOLVER_VERSION` and `ARG GIT_COMMIT`.
- **Changed** healthcheck to `curl -f` pattern.
- **Increased** `start-period` to 120s (DAGMC cold-start is slower).
- **Pinned** all requirement versions.

#### picogk/Dockerfile
- **Aligned** Python version from 3.12 to 3.11.
  **Rationale:** PicoGK used Python 3.12 while the rest of the cluster used
  3.11. Aligning to 3.11 ensures consistent runtime across all services and
  avoids version-split issues in the unified container.
- **Changed** `FROM python:3.12-slim` → `FROM forge-python-base:1.0.0`.
  **Rationale:** Non-root `forge` user and common libs are now inherited from
  the base image; removed duplicate `useradd` and apt install steps.
- **Added** `ARG SOLVER_VERSION` and `ARG GIT_COMMIT`.

#### All service requirements.txt files
- **Pinned** all version specifiers (`>=` → `==`).
  **Rationale:** `>=` ranges allow silent breaking changes on `pip install`.
  Pinned versions ensure reproducible builds across environments.
- **Removed** duplicate common deps (fastapi, uvicorn, pydantic, psutil, pint)
  that are now provided by forge-python-base.

### Not Changed (intentional)

- `cadquery/api_wrapper.py` — Copied unchanged from originals. The API wrapper
  logic is correct; changes limited to infrastructure layer.
- `paramak/api_wrapper.py` — Copied unchanged.
- `parastell/api_wrapper.py` — Copied unchanged.
- `picogk/api_wrapper.py` — Copied unchanged.
- All files in `originals/` — Exact copies of upstream source, never modified.

---

## [2.1.0] — Prior state (originals baseline)

Original files as received from vpneoterra/forgenew. See `originals/` for
the unmodified source. Key characteristics of the original state:

- ARM64 platform hardcoded in cadquery, paramak, parastell Dockerfiles
- CadQuery/OCC installed 3 separate times (~1.8 GB redundancy)
- PicoGK used Python 3.12 (inconsistent with cluster)
- Requirements used `>=` ranges (non-reproducible builds)
- No shared base image (common deps duplicated per service)
- No unified container option
- Healthchecks used Python `urllib.request` (no curl required, but inconsistent)
