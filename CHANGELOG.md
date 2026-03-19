# CHANGELOG — FORGE Cluster A: Geometry Kernel

All changes are relative to the originals in `originals/`. Every file in
`originals/` is an exact, unmodified copy of the source from vpneoterra/forgenew.

---

## [2.3.0] — 2026-03-19 — PicoGK TPMS + Scientific Implicits Integration

### Added

#### picogk/tpms.py (NEW)
- Pure Python/NumPy TPMS (Triply Periodic Minimal Surface) implicit surface library.
  **Source:** vpneoterra/PicoGK `Extensions/TPMS/TPMS_Implicits.cs`
  **Rationale:** The C# implementation requires .NET runtime + native PicoGK bridge
  library unavailable in Docker. This re-implementation matches the exact formulas
  of all 7 C# classes using NumPy broadcasting.
- **7 TPMS types implemented:**
  - `gyroid` — sin(x)cos(y) + sin(y)cos(z) + sin(z)cos(x)
  - `schwarz_p` — cos(x) + cos(y) + cos(z)
  - `schwarz_d` — sin(x)sin(y)sin(z) + sin(x)cos(y)cos(z) + cos(x)sin(y)cos(z) + cos(x)cos(y)sin(z)
  - `neovius` — 3(cos(x)+cos(y)+cos(z)) + 4cos(x)cos(y)cos(z)
  - `fischer_koch` — cos(2x)sin(y)cos(z) + cos(x)cos(2y)sin(z) + sin(x)cos(y)cos(2z)
  - `iwp` — cos(x)cos(y) + cos(y)cos(z) + cos(z)cos(x) - cos(x)cos(y)cos(z)
  - `lidinoid` — 0.5[sin(2x)cos(y)sin(z)+...] - 0.5[cos(2x)cos(2y)+...] + 0.15
- Network and sheet solid modes (iso_level vs wall_thickness), matching TpmsImplicit base class.
- Marching cubes STL export via scikit-image; ASCII STL fallback.
- trimesh used for mesh I/O when available.

#### picogk/scientific_implicits.py (NEW)
- Pure Python/NumPy scientific implicit functions for fusion-energy geometry.
  **Source:** vpneoterra/PicoGK `Extensions/ScientificImplicits/ScientificImplicits.cs`
  **Rationale:** Same rationale as tpms.py — pure Python to avoid .NET dependency.
- **3 implicit types implemented:**
  - `torus` — sqrt((sqrt(x²+y²)-R)²+z²) - r (tokamak vacuum vessel)
  - `d_shaped_plasma` — D-shaped plasma cross-section parameterised by κ, δ
  - `toroidal_sector` — Angular wedge of a torus (blanket module / TF coil)

#### originals/picogk/PICOGK_REPO_REFERENCE.md (NEW)
- Documents the vpneoterra/PicoGK source repo and which C# classes were used
  as the reference for the Python implementations.

### Changed

#### picogk/api_wrapper.py
- **Version bumped** from 1.0.0 to 1.1.0.
- **Added** 3 new Pydantic request models: `TpmsRequest`, `ImplicitRequest`, `TpmsInfillRequest`.
- **Added** 4 new endpoints:
  - `GET  /capabilities` — Lists TPMS types and implicit functions with formulas.
  - `POST /generate/tpms` — TPMS lattice generation.
  - `POST /generate/implicit` — Scientific implicit geometry generation.
  - `POST /generate/tpms_infill` — Apply TPMS infill to existing STL geometry.
- **Added** 3 new metrics counters: `tpms_count`, `implicit_count`, `tpms_infill_count`.
- **Unchanged:** /health, /metrics, /generate/lattice, /boolean, /run endpoints
  — all behaviours, request/response schemas, and paths are identical to the
  original `originals/picogk/api_wrapper.py`.

#### picogk/requirements.txt
- **Added** scikit-image==0.24.0 (marching cubes STL generation from SDF).
- **Added** scipy==1.13.1 (required by scikit-image marching cubes).
- **Added** trimesh==4.4.3 (mesh I/O: STL, PLY, OFF, glTF export).
- **Added** numpy==1.26.4 (explicit pin for TPMS SDF sampling).
- **Unchanged:** fastapi==0.116.1, uvicorn[standard]==0.35.0, psutil==7.0.0.

#### picogk/Dockerfile
- **Added** `COPY tpms.py /app/tpms.py` and `COPY scientific_implicits.py /app/scientific_implicits.py`.
- **Version bumped** SOLVER_VERSION default from 1.1.0 to 1.2.0.
- **Unchanged:** All other Dockerfile instructions, base image, port, env vars.

#### forge-geometry-unified/api_gateway.py
- **Added** 4 new `/picogk/` routes mirroring the standalone service:
  - `GET  /picogk/capabilities`
  - `POST /picogk/generate/tpms`
  - `POST /picogk/generate/implicit`
  - `POST /picogk/generate/tpms_infill`
- **Unchanged:** All existing routes (/picogk/generate/lattice, /picogk/boolean,
  /picogk/run, all cadquery/paramak/parastell routes, /health, /version, /metrics).

### Not Changed (intentional)

- `picogk/api_wrapper.py` — /health, /metrics, /generate/lattice, /boolean, /run
  endpoints are UNCHANGED in path, request schema, response schema, and behaviour.
- `docker-compose.yml` — picogk service definition is UNCHANGED.
- All files in `originals/` — exact copies of upstream source, never modified.
- `forge-python-base/` — unchanged.
- `cadquery/`, `paramak/`, `parastell/` — unchanged.

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
