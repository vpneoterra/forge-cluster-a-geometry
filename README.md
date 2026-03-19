# FORGE Cluster A — Geometry Kernel

Consolidated repository for the FORGE Geometry Kernel cluster. Contains four
geometry engines — CadQuery, Paramak, ParaStell, and PicoGK — packaged as
production-ready Docker containers with a shared base image and an optional
unified single-container deployment.

**Repo:** `vpneoterra/forge-cluster-a-geometry`

---

## What This Cluster Does

The Geometry Kernel provides parametric solid geometry generation and export
capabilities for the FORGE platform:

| Engine | Port | Capability |
|---|---|---|
| **CadQuery** | 8002 | General parametric CAD: box, cylinder, sphere, torus, custom scripts. Exports STEP, STL, BREP, SVG. |
| **Paramak** | 8006 | Fusion reactor parametric CAD: tokamaks (BallReactor, SingleNullReactor, etc.). Exports STEP/STL. |
| **ParaStell** | 8007 | Stellarator geometry from VMEC MHD equilibrium files. Exports STEP + optional DAGMC h5m. |
| **PicoGK** | 8015 | Voxel-based geometry: lattice generation (BCC, FCC, etc.) and boolean operations. Exports STL + VDB. |
| **Unified Gateway** | 8020 | All 4 engines in one container. Routes via `/cadquery/*`, `/paramak/*`, `/parastell/*`, `/picogk/*`. |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    FORGE Cluster A: Geometry Kernel              │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              forge-python-base:1.0.0                      │   │
│  │  Python 3.11-slim + libgl1 + libglib2.0-0 + curl         │   │
│  │  fastapi + uvicorn + pydantic + psutil + prometheus-client│   │
│  │  Non-root forge user (uid 1000)                           │   │
│  └───────────┬────────────┬──────────────┬────────────┬─────┘   │
│              │            │              │            │           │
│    Individual mode (--profile individual)             │           │
│              │            │              │            │           │
│  ┌───────────▼──┐ ┌───────▼───┐ ┌───────▼─────┐ ┌───▼───────┐ │
│  │  cadquery    │ │  paramak  │ │  parastell  │ │  picogk   │ │
│  │  :8002       │ │  :8006    │ │  :8007      │ │  :8015    │ │
│  │              │ │           │ │             │ │           │ │
│  │  cadquery    │ │  cadquery │ │  cadquery   │ │  (shim)   │ │
│  │  cadquery-ocp│ │  cadquery-│ │  cadquery-  │ │           │ │
│  │  cq_warehouse│ │  ocp      │ │  ocp        │ │           │ │
│  │  bd_warehouse│ │  paramak  │ │  DAGMC      │ │           │ │
│  └──────────────┘ └───────────┘ │  pystell    │ └───────────┘ │
│                                  │  parastell  │               │
│                                  └─────────────┘               │
│                                                                   │
│    Unified mode (--profile unified)  ~1.8 GB smaller             │
│                                                                   │
│  ┌────────────────────────────────────────────────────────┐     │
│  │           forge-geometry-unified:2.2.0  :8020          │     │
│  │                                                         │     │
│  │  ┌──────────────────────────────────────────────────┐  │     │
│  │  │  cq-layer (intermediate build stage)             │  │     │
│  │  │  cadquery + cadquery-ocp ─── installed ONCE      │  │     │
│  │  │  paramak ──────────────────── on top of cq       │  │     │
│  │  │  parastell + DAGMC + pystell ─ on top of cq      │  │     │
│  │  │  picogk shim ──────────────── pure Python        │  │     │
│  │  └──────────────────────────────────────────────────┘  │     │
│  │                                                         │     │
│  │  api_gateway.py routes:                                 │     │
│  │    POST /cadquery/generate  POST /cadquery/export       │     │
│  │    POST /paramak/generate   POST /parastell/run         │     │
│  │    POST /picogk/generate/lattice  POST /picogk/boolean  │     │
│  │    GET  /health  GET /version  GET /metrics             │     │
│  └────────────────────────────────────────────────────────┘     │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## What Changed from the Originals

| Area | Before | After |
|---|---|---|
| Base image | `python:3.11-slim` repeated × 3 | `forge-python-base:1.0.0` shared |
| ARM64 hardcode | `--platform=linux/arm64` in 3 Dockerfiles | Removed — use `docker buildx` for multi-platform |
| Python versions | 3.11 (cq/paramak/parastell), **3.12 (picogk)** | **3.11 for all** |
| Requirement pins | `>=` ranges (non-reproducible) | `==` pinned versions |
| Unified option | None | `forge-geometry-unified` on port 8020 |
| CadQuery/OCC | Installed 3× (~1.8 GB waste) | Installed once in unified mode |
| Healthchecks | `python -c urllib.request...` | `curl -f` (consistent) |
| Version endpoint | Not present | `SOLVER_VERSION` + `GIT_COMMIT` |
| Docker Compose | Not present | Full `docker-compose.yml` with profiles |

Original files are preserved verbatim in `originals/` for full traceability.

---

## Port Mapping

| Service | Host Port | Container Port | Profile |
|---|---|---|---|
| cadquery | 8002 | 8002 | individual, dev |
| paramak | 8006 | 8006 | individual, dev |
| parastell | 8007 | 8007 | individual, dev |
| picogk | 8015 | 8015 | individual, dev |
| forge-geometry-unified | 8020 | 8020 | unified, production |

---

## How to Build and Run

### Prerequisites

- Docker 24.0+
- Docker Compose v2 (bundled with Docker Desktop)
- `docker buildx` for multi-platform builds (optional)

### Step 1: Build the shared base image

```bash
# Must be built first — all services inherit from this
docker build -t forge-python-base:1.0.0 ./forge-python-base
```

### Step 2A: Run in Individual Mode (development/debugging)

Each engine runs as its own container. Best for development — restart one
service without affecting others.

```bash
# Configure environment
cp .env.example .env
# Edit .env to override any defaults

# Build and start all 4 individual services
docker-compose --profile individual up --build

# Or start specific services
docker-compose --profile individual up cadquery picogk

# Health checks
curl http://localhost:8002/health   # CadQuery
curl http://localhost:8006/health   # Paramak
curl http://localhost:8007/health   # ParaStell
curl http://localhost:8015/health   # PicoGK
```

### Step 2B: Run in Unified Mode (production)

Single container with all 4 engines. ~1.8 GB smaller than individual mode.

```bash
# Build and start unified container
docker-compose --profile unified up --build

# Health and version checks
curl http://localhost:8020/health
curl http://localhost:8020/version

# Engine-specific requests
curl -X POST http://localhost:8020/cadquery/generate \
  -H "Content-Type: application/json" \
  -d '{"shape": "box", "dimensions": {"length": 10, "width": 10, "height": 10}}'

curl -X POST http://localhost:8020/picogk/generate/lattice \
  -H "Content-Type: application/json" \
  -d '{"latticeType": "BCC", "cellSize": 5.0, "beamThickness": 1.0}'
```

### Build with version metadata (CI/CD)

```bash
# Inject git commit SHA at build time (surfaces in /version endpoint)
docker build \
  --build-arg SOLVER_VERSION=2.2.0 \
  --build-arg GIT_COMMIT=$(git rev-parse --short HEAD) \
  -t forge-cadquery:2.2.0 \
  ./cadquery
```

### Multi-platform builds (ARM64 + AMD64)

```bash
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t forge-cadquery:2.2.0 \
  ./cadquery
```

---

## API Quick Reference

### CadQuery (port 8002 or /cadquery/* on 8020)

```bash
# Generate a parametric shape
curl -X POST http://localhost:8002/generate \
  -H "Content-Type: application/json" \
  -d '{
    "shape": "cylinder",
    "dimensions": {"height": 50, "radius": 10},
    "operations": [{"op": "fillet", "params": {"radius": 2.0}}]
  }'

# Export STEP → STL
curl -X POST http://localhost:8002/export \
  -H "Content-Type: application/json" \
  -d '{"step_b64": "<base64_step>", "output_format": "stl"}'
```

### Paramak (port 8006 or /paramak/* on 8020)

```bash
curl -X POST http://localhost:8006/generate \
  -H "Content-Type: application/json" \
  -d '{
    "device_type": "BallReactor",
    "params": {
      "inner_bore_radial_thickness": 50,
      "inboard_tf_leg_radial_thickness": 200,
      "center_column_shield_radial_thickness": 50,
      "divertor_radial_thickness": 100,
      "inner_plasma_gap_radial_thickness": 50,
      "plasma_radial_thickness": 200,
      "outer_plasma_gap_radial_thickness": 50,
      "firstwall_radial_thickness": 50,
      "blanket_radial_thickness": 100,
      "blanket_rear_wall_radial_thickness": 50
    },
    "export_format": "step"
  }'
```

### ParaStell (port 8007 or /parastell/* on 8020)

```bash
# With VMEC file (base64-encoded)
curl -X POST http://localhost:8007/run \
  -H "Content-Type: application/json" \
  -d '{
    "vmec_file_b64": "<base64_netcdf>",
    "toroidal_angles": [0, 90, 180, 270, 360],
    "poloidal_angles": [0, 60, 120, 180, 240, 300, 360],
    "wall_s": 1.2,
    "export_dagmc": false
  }'
```

### PicoGK (port 8015 or /picogk/* on 8020)

```bash
# Lattice generation
curl -X POST http://localhost:8015/generate/lattice \
  -H "Content-Type: application/json" \
  -d '{
    "latticeType": "BCC",
    "cellSize": 5.0,
    "beamThickness": 1.0,
    "boundsX": 50.0,
    "boundsY": 50.0,
    "boundsZ": 50.0
  }'
```

---

## Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `FORGE_PORT` | per-service | HTTP port the service listens on |
| `FORGE_TIMEOUT` | 300 | Max seconds for a geometry generation request |
| `SOLVER_VERSION` | 2.2.0 | Solver version for /version endpoint |
| `GIT_COMMIT` | unknown | Git SHA injected at build time |
| `PARASTELL_HOME` | /opt/parastell | Path to ParaStell source (parastell + unified) |
| `FORGE_DATA_DIR` | /opt/forge/data | Geometry output directory (picogk + unified) |
| `PICOGK_VOXEL_SIZE` | 0.2 | Voxel resolution in mm |
| `PYTHONUNBUFFERED` | 1 | Disable output buffering (set in base image) |
| `PYTHONDONTWRITEBYTECODE` | 1 | No .pyc files (set in base image) |
| `CADQUERY_MEMORY` | 1500m | Docker memory limit for cadquery |
| `PARAMAK_MEMORY` | 1500m | Docker memory limit for paramak |
| `PARASTELL_MEMORY` | 2000m | Docker memory limit for parastell |
| `UNIFIED_MEMORY` | 4000m | Docker memory limit for unified container |

---

## Repository Structure

```
forge-cluster-a-geometry/
├── README.md                         # This file
├── AI_CONTEXT.md                     # Machine-readable context for AI tooling
├── CHANGELOG.md                      # All changes from originals with rationale
├── docker-compose.yml                # Cluster compose (individual + unified profiles)
├── .env.example                      # Environment variable template
├── .dockerignore                     # Shared build context exclusions
│
├── originals/                        # EXACT copies of original source files
│   ├── cadquery/
│   ├── paramak/
│   ├── parastell/
│   └── picogk/
│
├── forge-python-base/                # NEW: Shared base image
│   ├── Dockerfile                    # python:3.11-slim + common deps + forge user
│   └── requirements-base.txt        # Pinned: fastapi, uvicorn, pydantic, psutil, etc.
│
├── cadquery/                         # Improved cadquery service
│   ├── Dockerfile                    # FROM forge-python-base, no --platform hardcode
│   ├── api_wrapper.py               # Unchanged from original
│   └── requirements.txt             # Pinned cadquery-specific deps
│
├── paramak/                          # Improved paramak service
│   ├── Dockerfile
│   ├── api_wrapper.py               # Unchanged from original
│   └── requirements.txt
│
├── parastell/                        # Improved parastell service
│   ├── Dockerfile
│   ├── api_wrapper.py               # Unchanged from original
│   └── requirements.txt
│
├── picogk/                           # Improved picogk service (Python 3.11 aligned)
│   ├── Dockerfile
│   ├── api_wrapper.py               # Unchanged from original
│   └── requirements.txt
│
└── forge-geometry-unified/           # NEW: All 4 engines in one container
    ├── Dockerfile                    # CadQuery/OCC installed once (~1.8 GB savings)
    ├── api_gateway.py               # Unified FastAPI routing to all sub-solvers
    └── requirements.txt
```

---

## ARM64 Notes

- **CadQuery**: ARM64 wheels available on PyPI for `cadquery` and `cadquery-ocp`.
- **Paramak**: Installs cleanly on ARM64 via pip.
- **ParaStell/DAGMC**: DAGMC may require source compilation on ARM64 (HDF5 + MOAB).
  Build time ~45 min on Graviton3. See `originals/parastell/BUILD_NOTES.md`.
- **PicoGK**: Pure Python shim, works on all architectures.

Use `docker buildx build --platform linux/amd64,linux/arm64` for multi-platform images.
The `--platform=linux/arm64` hardcode has been removed from all Dockerfiles.

---

## Traceability

All original source files are preserved verbatim in `originals/`. To diff
any improved file against its original:

```bash
diff originals/cadquery/Dockerfile cadquery/Dockerfile
diff originals/picogk/Dockerfile picogk/Dockerfile
```

The `api_wrapper.py` files are identical to their originals (no changes).
Only Dockerfiles and requirements.txt files were modified.
