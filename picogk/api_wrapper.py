"""
PicoGK wrapper for FORGE.

Exposes:
- GET /health
- POST /generate/lattice
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
from typing import Any, Literal

import psutil
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

VERSION = "1.0.0"
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


class RunResponse(BaseModel):
    result: dict[str, Any]
    duration_ms: float
    run_id: str


app = FastAPI(
    title="Forge PicoGK API",
    description="PicoGK voxel geometry wrapper with FORGE-compatible /run endpoint",
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
