# AI_CONTEXT.md — FORGE Cluster A: Geometry Kernel

**Machine-readable context document for AI tooling, LLM agents, and code assistants.**

This document describes every file in this repository, how the repo differs from
the originals in `vpneoterra/forgenew`, and the architectural rationale for all
consolidation decisions.

---

## Repository Identity

| Field | Value |
|---|---|
| Repo | `vpneoterra/forge-cluster-a-geometry` |
| Cluster | A — Geometry Kernel |
| Upstream source | `vpneoterra/forgenew` (originals preserved in `originals/`) |
| Python version | 3.11 (all services aligned) |
| Base image | `forge-python-base:1.0.0` |

---

## Engines in This Cluster

| Engine | Port | Role | Key Dependency |
|---|---|---|---|
| CadQuery | 8002 | General parametric CAD (STEP/STL/BREP/SVG) | cadquery-ocp (OCC) |
| Paramak | 8006 | Fusion reactor tokamak/stellarator CAD | cadquery + paramak |
| ParaStell | 8007 | Stellarator geometry from VMEC equilibria | cadquery + DAGMC + pystell |
| PicoGK | 8015 | Voxel-based geometry (lattice + boolean + TPMS + scientific implicits) | pure Python (NumPy + scikit-image + trimesh) |
| Unified Gateway | 8020 | All 4 engines in one container | All of above |

---

## File-by-File Description

### Top-Level Files

| File | Purpose |
|---|---|
| `README.md` | Human-readable cluster documentation with build/run instructions |
| `AI_CONTEXT.md` | This file — machine-readable context for AI tooling |
| `CHANGELOG.md` | Every change from original with rationale |
| `docker-compose.yml` | Complete compose file. Two profiles: `individual` and `unified` |
| `.env.example` | Template for all environment variables with defaults |
| `.dockerignore` | Shared build context exclusions (prevents bloat from __pycache__, .git, etc.) |

### forge-python-base/

**Purpose:** Shared Python 3.11 base image. All 4 geometry services inherit FROM this.

| File | Purpose |
|---|---|
| `Dockerfile` | FROM python:3.11-slim. Adds libgl1, libglib2.0-0, curl, non-root `forge` user (uid 1000), and common pip deps |
| `requirements-base.txt` | Pinned common deps: fastapi==0.115.6, uvicorn[standard]==0.32.1, pydantic==2.9.2, psutil==5.9.8, prometheus-client==0.21.0, pint==0.24.3, httpx==0.27.2 |

**Why this exists:** cadquery, paramak, and parastell all had identical apt install
blocks and identical pip deps. forge-python-base extracts these into a single shared
layer, reducing total image layer duplication by ~300 MB.

### cadquery/

**Purpose:** Improved version of the CadQuery parametric CAD service.

| File | Purpose |
|---|---|
| `Dockerfile` | Multi-stage. Builder stage installs cadquery==2.4.0 + cadquery-ocp==7.7.2.1. Runtime stage inherits from forge-python-base. Removed --platform=linux/arm64. Added SOLVER_VERSION/GIT_COMMIT args. |
| `requirements.txt` | Pinned: cadquery==2.4.0, cadquery-ocp==7.7.2.1, numpy==1.26.4, scipy==1.13.1, cq_warehouse==0.9.5, bd_warehouse==0.10.0 |
| `api_wrapper.py` | **Unchanged from original.** FastAPI app on port 8002. Endpoints: GET /health, GET /metrics, POST /generate, POST /run, POST /export |

**Endpoints:**
- `GET  /health` → `{"status":"ok", "cadquery_available": bool, "uptime_seconds": float}`
- `GET  /metrics` → Prometheus text format
- `POST /generate` → `GeometryParams` → STEP file + bounding box metrics
- `POST /run` → Alias for /generate
- `POST /export` → STEP input → STL/STEP/BREP/SVG output

### paramak/

**Purpose:** Improved version of the Paramak fusion reactor CAD service.

| File | Purpose |
|---|---|
| `Dockerfile` | Multi-stage. Builder installs cadquery + paramak==0.8.3. Removed --platform=linux/arm64. Added SOLVER_VERSION/GIT_COMMIT args. |
| `requirements.txt` | Pinned: cadquery==2.4.0, cadquery-ocp==7.7.2.1, numpy==1.26.4, scipy==1.13.1, paramak==0.8.3 |
| `api_wrapper.py` | **Unchanged from original.** FastAPI app on port 8006. Endpoints: GET /health, GET /metrics, POST /generate, POST /run |

**Endpoints:**
- `GET  /health` → `{"status":"ok", "paramak_available": bool}`
- `GET  /metrics` → Prometheus text format
- `POST /generate` → `ReactorParams` (device_type, params, export_format) → STEP/STL/SVG
- `POST /run` → Alias for /generate

**Key types:** `device_type` is a Paramak class name (e.g., `"BallReactor"`,
`"SingleNullReactor"`, `"CenterColumnShieldCylinder"`). `params` dict maps to
constructor arguments of the selected class.

### parastell/

**Purpose:** Improved version of the ParaStell stellarator geometry service.

| File | Purpose |
|---|---|
| `Dockerfile` | Multi-stage. Builder installs cadquery + DAGMC + pystell + parastell from GitHub. Removed --platform=linux/arm64. start-period=120s (DAGMC is slow). |
| `requirements.txt` | Pinned: cadquery==2.4.0, cadquery-ocp==7.7.2.1, numpy==1.26.4, scipy==1.13.1, netCDF4==1.7.1, h5py==3.11.0 |
| `api_wrapper.py` | **Unchanged from original.** FastAPI app on port 8007. Endpoints: GET /health, GET /metrics, POST /run |

**Endpoints:**
- `GET  /health` → `{"status":"ok", "packages": {"parastell":bool, "cadquery":bool, ...}}`
- `GET  /metrics` → Prometheus text format
- `POST /run` → `ParaStellRequest` (vmec_file_b64, toroidal_angles, poloidal_angles, wall_s) → STEP + optional DAGMC h5m

**ARM64 note:** DAGMC requires HDF5 + MOAB, which may need source compilation on ARM64.
Fallback to CadQuery torus demo when VMEC file not provided. See `originals/parastell/BUILD_NOTES.md`.

### picogk/

**Purpose:** Improved version of the PicoGK voxel geometry service.

| File | Purpose |
|---|---|
| `Dockerfile` | Single-stage. FROM forge-python-base:1.0.0. Python 3.11. Copies api_wrapper.py, tpms.py, scientific_implicits.py. |
| `requirements.txt` | Pinned: fastapi==0.116.1, uvicorn[standard]==0.35.0, psutil==7.0.0, scikit-image==0.24.0, scipy==1.13.1, trimesh==4.4.3, numpy==1.26.4 |
| `api_wrapper.py` | FastAPI app on port 8015. Endpoints: GET /health, GET /metrics, GET /capabilities, POST /generate/lattice, POST /generate/tpms, POST /generate/implicit, POST /generate/tpms_infill, POST /boolean, POST /run |
| `tpms.py` | Pure Python/NumPy TPMS implicit surface library. 7 TPMS types. Marching cubes STL export via scikit-image. Mirrors vpneoterra/PicoGK Extensions/TPMS/TPMS_Implicits.cs. |
| `scientific_implicits.py` | Pure Python/NumPy scientific implicit functions. Torus, D-shaped plasma, toroidal sector. Mirrors vpneoterra/PicoGK Extensions/ScientificImplicits/ScientificImplicits.cs. |

**Endpoints:**
- `GET  /health` → `{"status":"healthy", "voxel_size": float, "runtime": "PicoGK wrapper"}` (unchanged)
- `GET  /metrics` → Prometheus text format (HELP/TYPE annotated, includes tpms/implicit/tpms_infill counters)
- `GET  /capabilities` → Lists available TPMS types and implicit functions with formulas
- `POST /generate/lattice` → `LatticeRequest` → STL + VDB metadata (unchanged)
- `POST /generate/tpms` → `TpmsRequest` → STL + mesh statistics + voxel count
- `POST /generate/implicit` → `ImplicitRequest` → STL + mesh statistics
- `POST /generate/tpms_infill` → `TpmsInfillRequest` → infilled STL file path
- `POST /boolean` → `BooleanRequest` (fileA, fileB, operation) → STL + VDB (unchanged)
- `POST /run` → Dispatch alias routing to /boolean or /generate/lattice (unchanged)

**TPMS types (from vpneoterra/PicoGK Extensions/TPMS/TPMS_Implicits.cs):**
- `gyroid` — sin(x)cos(y) + sin(y)cos(z) + sin(z)cos(x)
- `schwarz_p` — cos(x) + cos(y) + cos(z)
- `schwarz_d` — sin(x)sin(y)sin(z) + sin(x)cos(y)cos(z) + cos(x)sin(y)cos(z) + cos(x)cos(y)sin(z)
- `neovius` — 3(cos(x)+cos(y)+cos(z)) + 4cos(x)cos(y)cos(z)
- `fischer_koch` — cos(2x)sin(y)cos(z) + cos(x)cos(2y)sin(z) + sin(x)cos(y)cos(2z)
- `iwp` — cos(x)cos(y) + cos(y)cos(z) + cos(z)cos(x) - cos(x)cos(y)cos(z)
- `lidinoid` — 0.5[sin(2x)cos(y)sin(z)+sin(2y)cos(z)sin(x)+sin(2z)cos(x)sin(y)] - 0.5[cos(2x)cos(2y)+cos(2y)cos(2z)+cos(2z)cos(2x)] + 0.15

**Scientific implicit types (from vpneoterra/PicoGK Extensions/ScientificImplicits/ScientificImplicits.cs):**
- `torus` — (sqrt(x²+y²)-R)²+z²-r² (tokamak vacuum vessel shape)
- `d_shaped_plasma` — D-shape with elongation κ and triangularity δ (toroidally symmetric)
- `toroidal_sector` — Angular wedge of a torus (blanket modules, TF coil segments)

**Implementation note:** All geometry is generated in pure Python/NumPy with
marching cubes STL export (scikit-image). No .NET runtime or native PicoGK
bridge library required. The `_mock_stl()` function is retained for the
existing /generate/lattice and /boolean endpoints.

### forge-geometry-unified/

**Purpose:** Single container running all 4 engines. CadQuery/OCC installed once.

| File | Purpose |
|---|---|
| `Dockerfile` | Three-stage build. Stage 1 (cq-layer): installs CadQuery + OCC + Paramak + ParaStell + PicoGK. Stage 2 (runtime): copies all packages from cq-layer. |
| `api_gateway.py` | FastAPI app on port 8020. Routes to all 4 sub-solvers. Probes engine availability at startup. Provides /health, /version, /metrics aggregates. |
| `requirements.txt` | Empty (all deps in Dockerfile stages and forge-python-base) |

**Unified API routes:**

| Method | Path | Engine |
|---|---|---|
| POST | /cadquery/generate | CadQuery |
| POST | /cadquery/run | CadQuery (alias) |
| POST | /cadquery/export | CadQuery |
| POST | /paramak/generate | Paramak |
| POST | /paramak/run | Paramak (alias) |
| POST | /parastell/run | ParaStell |
| POST | /picogk/generate/lattice | PicoGK |
| POST | /picogk/generate/tpms | PicoGK |
| POST | /picogk/generate/implicit | PicoGK |
| POST | /picogk/generate/tpms_infill | PicoGK |
| GET  | /picogk/capabilities | PicoGK |
| POST | /picogk/boolean | PicoGK |
| POST | /picogk/run | PicoGK (alias) |
| GET | /health | Aggregate (all engines) |
| GET | /version | Version metadata + engine availability |
| GET | /metrics | Aggregate Prometheus metrics |
| GET | /docs | OpenAPI auto-docs |

### originals/

Exact, unmodified copies of all source files from vpneoterra/forgenew.
Never modified. Preserved for full traceability.

| Directory | Contents |
|---|---|
| `originals/cadquery/` | Dockerfile, Dockerfile.patch, api_wrapper.py, api_wrapper_patch.py, requirements.txt, requirements_patch.txt, BUILD_NOTES.md |
| `originals/paramak/` | Dockerfile, api_wrapper.py, requirements.txt |
| `originals/parastell/` | Dockerfile, api_wrapper.py, requirements.txt, BUILD_NOTES.md |
| `originals/picogk/` | Dockerfile, api_wrapper.py, requirements.txt, PICOGK_REPO_REFERENCE.md |

---

## Differences from vpneoterra/forgenew Originals

| Category | Original | This Repo |
|---|---|---|
| Base image | `python:3.11-slim` (repeated per service) | `forge-python-base:1.0.0` (shared) |
| Platform | `--platform=linux/arm64` hardcoded | Multi-platform (removed flag) |
| Python versions | 3.11 (cadquery/paramak/parastell), 3.12 (picogk) | 3.11 for all |
| Requirements | `>=` ranges (non-reproducible) | Pinned `==` versions |
| Version endpoint | Not present | `SOLVER_VERSION` + `GIT_COMMIT` args |
| Unified container | Not present | `forge-geometry-unified` on port 8020 |
| CadQuery installs | 3 separate installs (~1.8 GB) | 1 install in unified mode |
| Healthcheck pattern | `python -c urllib.request...` | `curl -f` (consistent) |
| Docker Compose | Not present | `docker-compose.yml` with profiles |
| Shared .dockerignore | Not present | Root-level `.dockerignore` |

---

## Consolidation Rationale — ~1.8 GB Savings

CadQuery + OCC is the dominant dependency in this cluster:
- `cadquery==2.4.0` + `cadquery-ocp==7.7.2.1` ≈ 600 MB installed
- Used by: cadquery, paramak, parastell (3 of 4 services)
- In individual mode: installed 3× = ~1.8 GB redundancy

The `forge-geometry-unified` container resolves this by installing CadQuery/OCC
in the `cq-layer` build stage, then copying the Python site-packages to the
final runtime stage. Paramak and ParaStell are then installed on top of the
same CadQuery installation.

Total unified image vs 3 individual images:
- Individual (cadquery + paramak + parastell): ~1.8–2.5 GB each × 3 ≈ 6–7.5 GB
- Unified: ~2.5 GB (CadQuery once + Paramak + ParaStell overlay)
- Net savings: ~4–5 GB in registry storage

---

## Build Order and Dependencies

```
python:3.11-slim
    └── forge-python-base:1.0.0
            ├── forge-cadquery:2.2.0       (ports 8002)
            ├── forge-paramak:2.2.0        (port 8006)
            ├── forge-parastell:2.2.0      (port 8007)
            ├── forge-picogk:1.1.0         (port 8015)
            └── forge-geometry-unified:2.2.0 (port 8020)
                    └── cq-layer (intermediate)
                            ├── cadquery==2.4.0 + cadquery-ocp (ONCE)
                            ├── paramak==0.8.3 (on top of cadquery)
                            └── parastell + DAGMC + pystell (on top of cadquery)
```

---

## Environment Variables Reference

| Variable | Default | Used by | Description |
|---|---|---|---|
| `FORGE_PORT` | per-service | all | HTTP port the service listens on |
| `FORGE_TIMEOUT` | 300 | all | Max seconds for a geometry generation request |
| `SOLVER_VERSION` | 2.2.0 | all | Solver version string for /version endpoint |
| `GIT_COMMIT` | unknown | all | Git commit SHA injected at build time |
| `PARASTELL_HOME` | /opt/parastell | parastell, unified | Path to cloned parastell source |
| `FORGE_DATA_DIR` | /opt/forge/data | picogk, unified | Path for geometry output files |
| `PICOGK_VOXEL_SIZE` | 0.2 | picogk, unified | Voxel resolution in mm |
| `PYTHONUNBUFFERED` | 1 | all | Disable Python output buffering (set in base) |
| `PYTHONDONTWRITEBYTECODE` | 1 | all | No .pyc files in containers (set in base) |
