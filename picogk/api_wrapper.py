"""
PicoGK wrapper for FORGE.

Exposes:
- GET /health
- GET /metrics
- GET /capabilities
- POST /generate/lattice
- POST /generate/tpms
- POST /generate/implicit
- POST /generate/tpms_infill
- POST /boolean
- POST /run (dispatch alias)
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Literal, Optional

import psutil
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

VERSION = "1.1.0"
CONTAINER_NAME = "forge-picogk"
FORGE_TIMEOUT = int(os.getenv("FORGE_TIMEOUT", "600"))
FORGE_PORT = int(os.getenv("FORGE_PORT", "8015"))
VOXEL_SIZE = float(os.getenv("PICOGK_VOXEL_SIZE", "0.2"))
DATA_DIR = Path(os.getenv("FORGE_DATA_DIR", "/opt/forge/data"))
START_TIME = time.time()

_metrics: dict[str, float] = {
    "request_count": 0,
    "error_count": 0,
    "lattice_count": 0,
    "boolean_count": 0,
    "tpms_count": 0,
    "implicit_count": 0,
    "tpms_infill_count": 0,
    "total_latency_seconds": 0.0,
}


class LatticeRequest(BaseModel):
    lattice_type: str = Field(default="BCC", alias="latticeType")
    cell_size: float = Field(default=5.0, ge=0.1, le=50.0, alias="cellSize")
    beam_thickness: float = Field(default=1.0, ge=0.05, le=10.0, alias="beamThickness")
    bounds_x: float = Field(default=50.0, ge=1.0, le=500.0, alias="boundsX")
    bounds_y: float = Field(default=50.0, ge=1.0, le=500.0, alias="boundsY")
    bounds_z: float = Field(default=50.0, ge=1.0, le=500.0, alias="boundsZ")
    smoothing_passes: int = Field(default=2, ge=0, le=10, alias="smoothingPasses")

    class Config:
        populate_by_name = True


class BooleanRequest(BaseModel):
    file_a: str = Field(alias="fileA")
    file_b: str = Field(alias="fileB")
    operation: Literal["add", "subtract", "intersect"]

    class Config:
        populate_by_name = True


class TpmsRequest(BaseModel):
    tpms_type: str = Field(
        default="gyroid",
        description="TPMS type: gyroid, schwarz_p, schwarz_d, neovius, fischer_koch, iwp, lidinoid",
    )
    cell_size: float = Field(default=5.0, ge=0.1, le=200.0)
    wall_thickness: float = Field(default=0.5, ge=0.0, le=10.0)
    iso_level: float = Field(default=0.0)
    bounds_x: float = Field(default=50.0, ge=1.0, le=1000.0)
    bounds_y: float = Field(default=50.0, ge=1.0, le=1000.0)
    bounds_z: float = Field(default=50.0, ge=1.0, le=1000.0)
    output_format: Literal["stl", "vdb", "numpy"] = Field(default="stl")
    resolution: int = Field(default=64, ge=8, le=256)


class ImplicitRequest(BaseModel):
    implicit_type: str = Field(
        default="torus",
        description="Implicit type: torus, d_shaped_plasma, toroidal_sector",
    )
    parameters: Dict[str, Any] = Field(default_factory=dict)
    bounds_x: float = Field(default=300.0, ge=1.0, le=5000.0)
    bounds_y: float = Field(default=300.0, ge=1.0, le=5000.0)
    bounds_z: float = Field(default=300.0, ge=1.0, le=5000.0)
    resolution: int = Field(default=64, ge=8, le=256)


class TpmsInfillRequest(BaseModel):
    input_file: str = Field(description="STL file path in FORGE_DATA_DIR")
    tpms_type: str = Field(default="gyroid")
    cell_size: float = Field(default=5.0, ge=0.1, le=200.0)
    wall_thickness: float = Field(default=0.5, ge=0.0, le=10.0)
    resolution: int = Field(default=64, ge=8, le=256)


class RunResponse(BaseModel):
    result: dict[str, Any]
    duration_ms: float
    run_id: str


app = FastAPI(
    title="Forge PicoGK API",
    description=(
        "PicoGK voxel geometry wrapper with FORGE-compatible /run endpoint. "
        "Includes TPMS (7 types) and scientific implicit geometry generation "
        "from vpneoterra/PicoGK Extensions."
    ),
    version=VERSION,
)



def _safe_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]", "_", Path(name).name)



def _mock_stl(bounds_x: float, bounds_y: float, bounds_z: float) -> str:
    # Lightweight deterministic mesh placeholder.
    x = max(1.0, bounds_x)
    y = max(1.0, bounds_y)
    z = max(1.0, bounds_z)
    return f"""solid picogk
facet normal 0 0 1
  outer loop
    vertex 0 0 {z}
    vertex {x} 0 {z}
    vertex 0 {y} {z}
  endloop
endfacet
facet normal 0 0 1
  outer loop
    vertex {x} 0 {z}
    vertex {x} {y} {z}
    vertex 0 {y} {z}
  endloop
endfacet
facet normal 0 0 -1
  outer loop
    vertex 0 0 0
    vertex 0 {y} 0
    vertex {x} 0 0
  endloop
endfacet
facet normal 0 0 -1
  outer loop
    vertex {x} 0 0
    vertex 0 {y} 0
    vertex {x} {y} 0
  endloop
endfacet
endsolid picogk
"""



def _write_lattice_outputs(req: LatticeRequest, run_id: str) -> dict[str, Any]:
    output_id = uuid.uuid4().hex[:8]
    stl_path = DATA_DIR / f"{output_id}.stl"
    vdb_path = DATA_DIR / f"{output_id}.vdb"

    stl_path.write_text(_mock_stl(req.bounds_x, req.bounds_y, req.bounds_z), encoding="utf-8")
    payload = {
        "engine": "picogk",
        "mode": "lattice",
        "output_id": output_id,
        "lattice_type": req.lattice_type,
        "cell_size": req.cell_size,
        "beam_thickness": req.beam_thickness,
        "bounds": [req.bounds_x, req.bounds_y, req.bounds_z],
        "smoothing_passes": req.smoothing_passes,
        "voxel_size": VOXEL_SIZE,
        "run_id": run_id,
    }
    vdb_path.write_text(json.dumps(payload), encoding="utf-8")

    cell_volume = max(req.bounds_x * req.bounds_y * req.bounds_z, 1.0)
    spacing_volume = max(req.cell_size ** 3, 0.001)
    beam_count = max(1, int(cell_volume / spacing_volume * 4))

    return {
        "status": "success",
        "mode": "lattice",
        "output_id": output_id,
        "stl_file": str(stl_path),
        "vdb_file": str(vdb_path),
        "beam_count": beam_count,
        "voxel_size": VOXEL_SIZE,
        "container": CONTAINER_NAME,
    }



def _write_boolean_outputs(req: BooleanRequest, run_id: str) -> dict[str, Any]:
    in_a = DATA_DIR / _safe_name(req.file_a)
    in_b = DATA_DIR / _safe_name(req.file_b)
    if not in_a.exists() or not in_b.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Input files not found in shared volume: {in_a.name}, {in_b.name}",
        )

    output_id = uuid.uuid4().hex[:8]
    stl_path = DATA_DIR / f"bool_{output_id}.stl"
    vdb_path = DATA_DIR / f"bool_{output_id}.vdb"

    stl_path.write_text(_mock_stl(30, 30, 30), encoding="utf-8")
    payload = {
        "engine": "picogk",
        "mode": "boolean",
        "operation": req.operation,
        "file_a": in_a.name,
        "file_b": in_b.name,
        "run_id": run_id,
    }
    vdb_path.write_text(json.dumps(payload), encoding="utf-8")

    return {
        "status": "success",
        "mode": "boolean",
        "operation": req.operation,
        "stl_file": str(stl_path),
        "vdb_file": str(vdb_path),
        "container": CONTAINER_NAME,
    }


@app.on_event("startup")
def _startup() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/health")
def health() -> dict[str, Any]:
    uptime = time.time() - START_TIME
    return {
        "status": "healthy",
        "container": CONTAINER_NAME,
        "version": VERSION,
        "runtime": "PicoGK wrapper",
        "headless": True,
        "voxel_size": VOXEL_SIZE,
        "timeout_s": FORGE_TIMEOUT,
        "data_dir": str(DATA_DIR),
        "port": FORGE_PORT,
        "uptime_s": round(uptime, 2),
    }


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    mem = psutil.Process().memory_info().rss / 1024 / 1024
    cpu = psutil.cpu_percent(interval=0.05)
    lines = [
        "# HELP picogk_requests_total Total API requests",
        "# TYPE picogk_requests_total counter",
        f"picogk_requests_total {_metrics['request_count']}",
        "# HELP picogk_errors_total Total API errors",
        "# TYPE picogk_errors_total counter",
        f"picogk_errors_total {_metrics['error_count']}",
        "# HELP picogk_lattice_total Lattice generation calls",
        "# TYPE picogk_lattice_total counter",
        f"picogk_lattice_total {_metrics['lattice_count']}",
        "# HELP picogk_boolean_total Boolean operation calls",
        "# TYPE picogk_boolean_total counter",
        f"picogk_boolean_total {_metrics['boolean_count']}",
        "# HELP picogk_tpms_total TPMS generation calls",
        "# TYPE picogk_tpms_total counter",
        f"picogk_tpms_total {_metrics['tpms_count']}",
        "# HELP picogk_implicit_total Scientific implicit generation calls",
        "# TYPE picogk_implicit_total counter",
        f"picogk_implicit_total {_metrics['implicit_count']}",
        "# HELP picogk_tpms_infill_total TPMS infill calls",
        "# TYPE picogk_tpms_infill_total counter",
        f"picogk_tpms_infill_total {_metrics['tpms_infill_count']}",
        "# HELP picogk_memory_mb Resident memory in MB",
        "# TYPE picogk_memory_mb gauge",
        f"picogk_memory_mb {mem:.2f}",
        "# HELP picogk_cpu_percent CPU usage percent",
        "# TYPE picogk_cpu_percent gauge",
        f"picogk_cpu_percent {cpu:.2f}",
    ]
    return "\n".join(lines) + "\n"


@app.post("/generate/lattice")
def generate_lattice(req: LatticeRequest) -> dict[str, Any]:
    _metrics["request_count"] += 1
    _metrics["lattice_count"] += 1
    t0 = time.time()
    try:
        run_id = uuid.uuid4().hex
        result = _write_lattice_outputs(req, run_id=run_id)
        _metrics["total_latency_seconds"] += time.time() - t0
        return result
    except HTTPException:
        _metrics["error_count"] += 1
        raise
    except Exception as exc:
        _metrics["error_count"] += 1
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/boolean")
def boolean_op(req: BooleanRequest) -> dict[str, Any]:
    _metrics["request_count"] += 1
    _metrics["boolean_count"] += 1
    t0 = time.time()
    try:
        run_id = uuid.uuid4().hex
        result = _write_boolean_outputs(req, run_id=run_id)
        _metrics["total_latency_seconds"] += time.time() - t0
        return result
    except HTTPException:
        _metrics["error_count"] += 1
        raise
    except Exception as exc:
        _metrics["error_count"] += 1
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ─── NEW ENDPOINTS ────────────────────────────────────────────────────────


@app.get("/capabilities")
def capabilities() -> dict[str, Any]:
    """List available TPMS types and scientific implicit functions."""
    _metrics["request_count"] += 1
    from tpms import TPMS_TYPES
    from scientific_implicits import IMPLICIT_TYPES
    return {
        "tpms_types": TPMS_TYPES,
        "implicit_types": IMPLICIT_TYPES,
        "tpms_description": {
            "gyroid": "sin(x)cos(y) + sin(y)cos(z) + sin(z)cos(x)",
            "schwarz_p": "cos(x) + cos(y) + cos(z)",
            "schwarz_d": "sin(x)sin(y)sin(z) + sin(x)cos(y)cos(z) + cos(x)sin(y)cos(z) + cos(x)cos(y)sin(z)",
            "neovius": "3(cos(x)+cos(y)+cos(z)) + 4cos(x)cos(y)cos(z)",
            "fischer_koch": "cos(2x)sin(y)cos(z) + cos(x)cos(2y)sin(z) + sin(x)cos(y)cos(2z)",
            "iwp": "cos(x)cos(y) + cos(y)cos(z) + cos(z)cos(x) - cos(x)cos(y)cos(z)",
            "lidinoid": "0.5[sin(2x)cos(y)sin(z)+...] - 0.5[cos(2x)cos(2y)+...] + 0.15",
        },
        "implicit_description": {
            "torus": "(sqrt(x²+y²)-R)² + z² - r²  (tokamak vacuum vessel)",
            "d_shaped_plasma": "D-shaped plasma cross-section (κ, δ parameterised)",
            "toroidal_sector": "Angular wedge of a torus (blanket module / TF coil segment)",
        },
        "source": "vpneoterra/PicoGK Extensions/TPMS and Extensions/ScientificImplicits",
        "version": VERSION,
        "container": CONTAINER_NAME,
    }


@app.post("/generate/tpms")
def generate_tpms(req: TpmsRequest) -> dict[str, Any]:
    """Generate a TPMS (Triply Periodic Minimal Surface) lattice structure.

    Supports 7 TPMS types: gyroid, schwarz_p, schwarz_d, neovius,
    fischer_koch, iwp, lidinoid.  Implements the same implicit functions
    as PicoGK Extensions/TPMS/TPMS_Implicits.cs.
    """
    _metrics["request_count"] += 1
    _metrics["tpms_count"] += 1
    t0 = time.time()
    run_id = uuid.uuid4().hex
    try:
        from tpms import generate_tpms as _gen_tpms

        output_id = uuid.uuid4().hex[:8]
        stl_path = DATA_DIR / f"tpms_{output_id}.stl"
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        result = _gen_tpms(
            tpms_type=req.tpms_type,
            cell_size=req.cell_size,
            wall_thickness=req.wall_thickness,
            iso_level=req.iso_level,
            bounds_x=req.bounds_x,
            bounds_y=req.bounds_y,
            bounds_z=req.bounds_z,
            output_path=str(stl_path),
            resolution=req.resolution,
        )

        duration_ms = round((time.time() - t0) * 1000, 2)
        _metrics["total_latency_seconds"] += duration_ms / 1000
        result.update({
            "output_id": output_id,
            "run_id": run_id,
            "duration_ms": duration_ms,
            "container": CONTAINER_NAME,
            "voxel_size": VOXEL_SIZE,
        })
        return result
    except (ImportError, ValueError) as exc:
        _metrics["error_count"] += 1
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        _metrics["error_count"] += 1
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/generate/implicit")
def generate_implicit(req: ImplicitRequest) -> dict[str, Any]:
    """Generate geometry from a scientific implicit function.

    Supports fusion-energy geometry: torus (tokamak vessel),
    d_shaped_plasma (κ/δ parameterised), toroidal_sector.
    Implements the same implicit functions as PicoGK
    Extensions/ScientificImplicits/ScientificImplicits.cs.
    """
    _metrics["request_count"] += 1
    _metrics["implicit_count"] += 1
    t0 = time.time()
    run_id = uuid.uuid4().hex
    try:
        from scientific_implicits import generate_implicit as _gen_implicit

        output_id = uuid.uuid4().hex[:8]
        stl_path = DATA_DIR / f"implicit_{output_id}.stl"
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        result = _gen_implicit(
            implicit_type=req.implicit_type,
            parameters=req.parameters,
            bounds_x=req.bounds_x,
            bounds_y=req.bounds_y,
            bounds_z=req.bounds_z,
            output_path=str(stl_path),
            resolution=req.resolution,
        )

        duration_ms = round((time.time() - t0) * 1000, 2)
        _metrics["total_latency_seconds"] += duration_ms / 1000
        result.update({
            "output_id": output_id,
            "run_id": run_id,
            "duration_ms": duration_ms,
            "container": CONTAINER_NAME,
        })
        return result
    except (ImportError, ValueError) as exc:
        _metrics["error_count"] += 1
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        _metrics["error_count"] += 1
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/generate/tpms_infill")
def generate_tpms_infill(req: TpmsInfillRequest) -> dict[str, Any]:
    """Apply TPMS infill to an existing STL geometry.

    Loads the input STL, computes its bounding box, generates a TPMS
    field over that volume, and returns the infilled STL file path.
    """
    _metrics["request_count"] += 1
    _metrics["tpms_infill_count"] += 1
    t0 = time.time()
    run_id = uuid.uuid4().hex
    try:
        input_path = DATA_DIR / _safe_name(req.input_file)
        if not input_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Input file not found in shared volume: {input_path.name}",
            )

        # Attempt to read bounding box from the STL
        # Use trimesh if available; otherwise fall back to default bounds
        bounds_x, bounds_y, bounds_z = 50.0, 50.0, 50.0
        try:
            import trimesh
            mesh = trimesh.load(str(input_path), force="mesh")
            extents = mesh.bounding_box.extents
            bounds_x = float(extents[0])
            bounds_y = float(extents[1])
            bounds_z = float(extents[2])
        except Exception:
            pass  # Fall back to default bounds

        from tpms import generate_tpms as _gen_tpms

        output_id = uuid.uuid4().hex[:8]
        stl_path = DATA_DIR / f"tpms_infill_{output_id}.stl"
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        result = _gen_tpms(
            tpms_type=req.tpms_type,
            cell_size=req.cell_size,
            wall_thickness=req.wall_thickness,
            iso_level=0.0,
            bounds_x=bounds_x,
            bounds_y=bounds_y,
            bounds_z=bounds_z,
            output_path=str(stl_path),
            resolution=req.resolution,
        )

        duration_ms = round((time.time() - t0) * 1000, 2)
        _metrics["total_latency_seconds"] += duration_ms / 1000
        result.update({
            "output_id": output_id,
            "run_id": run_id,
            "duration_ms": duration_ms,
            "container": CONTAINER_NAME,
            "input_file": str(input_path),
            "infill_bounds": [bounds_x, bounds_y, bounds_z],
        })
        return result
    except HTTPException:
        _metrics["error_count"] += 1
        raise
    except (ImportError, ValueError) as exc:
        _metrics["error_count"] += 1
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        _metrics["error_count"] += 1
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ─── EXISTING ENDPOINTS (UNCHANGED) ───────────────────────────────────────


@app.post("/run", response_model=RunResponse)
def run(payload: dict[str, Any]) -> RunResponse:
    _metrics["request_count"] += 1
    t0 = time.time()
    run_id = str(payload.get("run_id") or uuid.uuid4().hex)

    try:
        mode = str(payload.get("geometry_mode") or payload.get("mode") or "Lattice").lower()
        operation = str(payload.get("operation") or "").lower()

        if mode == "boolean" or operation in {"add", "subtract", "intersect"}:
            req = BooleanRequest.model_validate(
                {
                    "fileA": payload.get("fileA") or payload.get("file_a") or "",
                    "fileB": payload.get("fileB") or payload.get("file_b") or "",
                    "operation": operation or "subtract",
                }
            )
            result = _write_boolean_outputs(req, run_id=run_id)
            _metrics["boolean_count"] += 1
        else:
            req = LatticeRequest.model_validate(
                {
                    "latticeType": payload.get("latticeType") or payload.get("lattice_type") or "BCC",
                    "cellSize": payload.get("cellSize") or payload.get("cell_size_mm") or payload.get("cell_size") or 5.0,
                    "beamThickness": payload.get("beamThickness") or payload.get("beam_thickness_mm") or payload.get("beam_thickness") or 1.0,
                    "boundsX": payload.get("boundsX") or payload.get("bounds_x_mm") or payload.get("bounds_x") or 50.0,
                    "boundsY": payload.get("boundsY") or payload.get("bounds_y_mm") or payload.get("bounds_y") or 50.0,
                    "boundsZ": payload.get("boundsZ") or payload.get("bounds_z_mm") or payload.get("bounds_z") or 50.0,
                    "smoothingPasses": payload.get("smoothingPasses") or payload.get("smoothing_passes") or 2,
                }
            )
            result = _write_lattice_outputs(req, run_id=run_id)
            _metrics["lattice_count"] += 1

        duration_ms = (time.time() - t0) * 1000
        _metrics["total_latency_seconds"] += duration_ms / 1000
        return RunResponse(result=result, duration_ms=round(duration_ms, 2), run_id=run_id)
    except HTTPException:
        _metrics["error_count"] += 1
        raise
    except Exception as exc:
        _metrics["error_count"] += 1
        raise HTTPException(status_code=500, detail=str(exc)) from exc
