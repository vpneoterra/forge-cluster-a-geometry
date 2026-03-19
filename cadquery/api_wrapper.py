"""
CadQuery Parametric CAD - FastAPI Wrapper
Container: cadquery | Port: 8002
POST /generate → geometry params → STEP file + metrics
POST /export → convert to STL/DAGMC
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import sys
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import psutil
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

# ── Structured JSON logging ──────────────────────────────────
class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "container": "cadquery",
            **({"exception": self.formatException(record.exc_info)} if record.exc_info else {}),
        })

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JSONFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger("cadquery-api")

START_TIME = time.time()
FORGE_TIMEOUT = int(os.getenv("FORGE_TIMEOUT", "300"))
VERSION = "2.1.0"
CONTAINER_NAME = "cadquery"
DATA_DIR = Path("/data")
MODELS_DIR = Path("/app/models")

_metrics: dict[str, float] = {
    "request_count": 0, "error_count": 0,
    "generate_count": 0, "export_count": 0,
    "total_latency_seconds": 0.0, "queue_depth": 0,
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info({"event": "startup", "container": CONTAINER_NAME, "version": VERSION})
    # Warm up CadQuery import (can be slow first time)
    try:
        import cadquery as cq  # noqa: F401
        logger.info({"event": "cadquery_loaded"})
    except ImportError as e:
        logger.warning({"event": "cadquery_import_warning", "error": str(e)})
    yield
    logger.info({"event": "shutdown", "container": CONTAINER_NAME})

app = FastAPI(
    title="CadQuery Parametric CAD API",
    description="CadQuery parametric CAD geometry generation and export",
    version=VERSION,
    lifespan=lifespan,
)

# ── Models ────────────────────────────────────────────────────
class GeometryParams(BaseModel):
    shape: Literal["box", "cylinder", "sphere", "torus", "shell", "custom"] = "box"
    dimensions: dict[str, float] = Field(
        default={"length": 10.0, "width": 10.0, "height": 10.0},
        description="Shape dimensions in mm",
    )
    operations: list[dict[str, Any]] = Field(
        default=[],
        description="List of CSG operations: {op: 'fillet'|'chamfer'|'shell', params: {...}}",
    )
    custom_script: str | None = Field(
        default=None,
        description="Raw CadQuery Python script. Must set result = cq.Workplane(...)",
    )
    run_id: str | None = None

class GenerateResponse(BaseModel):
    result: dict[str, Any]
    duration_ms: float
    run_id: str

class ExportRequest(BaseModel):
    step_b64: str = Field(..., description="Base64-encoded STEP file content")
    output_format: Literal["stl", "step", "brep", "svg"] = "stl"
    linear_deflection: float = Field(default=0.1, ge=0.001, le=10.0)
    angular_deflection: float = Field(default=0.1, ge=0.01, le=1.0)
    run_id: str | None = None

# ── CadQuery helpers ──────────────────────────────────────────
def _build_shape(params: GeometryParams):
    """Build CadQuery shape from parameters."""
    import cadquery as cq

    dims = params.dimensions

    if params.custom_script:
        namespace: dict = {}
        exec(params.custom_script, {"cq": cq}, namespace)  # noqa: S102
        if "result" not in namespace:
            raise ValueError("custom_script must define 'result' variable")
        shape = namespace["result"]
    elif params.shape == "box":
        shape = cq.Workplane("XY").box(
            dims.get("length", 10), dims.get("width", 10), dims.get("height", 10)
        )
    elif params.shape == "cylinder":
        shape = cq.Workplane("XY").cylinder(
            dims.get("height", 20), dims.get("radius", 5)
        )
    elif params.shape == "sphere":
        shape = cq.Workplane("XY").sphere(dims.get("radius", 10))
    elif params.shape == "torus":
        shape = cq.Workplane("XY").torus(
            dims.get("radius1", 20), dims.get("radius2", 5)
        )
    elif params.shape == "shell":
        shape = cq.Workplane("XY").box(
            dims.get("length", 20), dims.get("width", 20), dims.get("height", 20)
        ).shell(-dims.get("thickness", 1.0))
    else:
        shape = cq.Workplane("XY").box(10, 10, 10)

    # Apply operations
    for op in params.operations:
        op_type = op.get("op", "")
        op_params = op.get("params", {})
        if op_type == "fillet":
            shape = shape.edges().fillet(op_params.get("radius", 1.0))
        elif op_type == "chamfer":
            shape = shape.edges().chamfer(op_params.get("length", 1.0))
        elif op_type == "shell":
            shape = shape.shell(-abs(op_params.get("thickness", 1.0)))

    return shape

def _compute_metrics(shape) -> dict[str, Any]:
    """Compute geometric properties."""
    try:
        bb = shape.val().BoundingBox()
        vol = shape.val().Volume()
        area = shape.val().Area()
        return {
            "volume_mm3": round(vol, 6),
            "surface_area_mm2": round(area, 6),
            "bounding_box": {
                "xmin": round(bb.xmin, 4), "xmax": round(bb.xmax, 4),
                "ymin": round(bb.ymin, 4), "ymax": round(bb.ymax, 4),
                "zmin": round(bb.zmin, 4), "zmax": round(bb.zmax, 4),
            },
        }
    except Exception as exc:
        return {"metrics_error": str(exc)}

# ── Routes ────────────────────────────────────────────────────
@app.get("/health")
async def health():
    _metrics["request_count"] += 1
    cq_available = False
    try:
        import cadquery  # noqa: F401
        cq_available = True
    except ImportError:
        pass
    return {
        "status": "ok",
        "container": CONTAINER_NAME,
        "uptime_seconds": round(time.time() - START_TIME, 2),
        "version": VERSION,
        "cadquery_available": cq_available,
    }

@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    _metrics["request_count"] += 1
    uptime = time.time() - START_TIME
    total_runs = _metrics["generate_count"] + _metrics["export_count"]
    avg_lat = _metrics["total_latency_seconds"] / total_runs if total_runs > 0 else 0.0
    mem = psutil.virtual_memory()
    lines = [
        f'forge_request_count{{container="{CONTAINER_NAME}"}} {_metrics["request_count"]:.0f}',
        f'forge_latency_seconds{{container="{CONTAINER_NAME}"}} {avg_lat:.6f}',
        f'forge_error_count{{container="{CONTAINER_NAME}"}} {_metrics["error_count"]:.0f}',
        f'forge_queue_depth{{container="{CONTAINER_NAME}"}} {_metrics["queue_depth"]:.0f}',
        f'forge_uptime_seconds{{container="{CONTAINER_NAME}"}} {uptime:.2f}',
        f'forge_memory_bytes_used{{container="{CONTAINER_NAME}"}} {mem.used}',
        f'forge_generate_count{{container="{CONTAINER_NAME}"}} {_metrics["generate_count"]:.0f}',
        f'forge_export_count{{container="{CONTAINER_NAME}"}} {_metrics["export_count"]:.0f}',
    ]
    return "\n".join(lines) + "\n"

@app.post("/generate", response_model=GenerateResponse)
async def generate(request: GeometryParams):
    _metrics["request_count"] += 1
    _metrics["queue_depth"] += 1
    run_id = request.run_id or str(uuid.uuid4())
    t0 = time.time()

    logger.info({"event": "generate_start", "run_id": run_id, "shape": request.shape})

    try:
        def _sync_generate():
            shape = _build_shape(request)
            geo_metrics = _compute_metrics(shape)

            # Export to STEP
            step_buf = io.BytesIO()
            import cadquery as cq
            cq.exporters.export(shape, "/tmp/tmp_out.step", cq.exporters.ExportTypes.STEP)
            step_bytes = Path("/tmp/tmp_out.step").read_bytes()

            # Save to /data
            out_path = None
            if DATA_DIR.exists():
                out_dir = DATA_DIR / run_id
                out_dir.mkdir(parents=True, exist_ok=True)
                step_file = out_dir / "geometry.step"
                step_file.write_bytes(step_bytes)
                out_path = str(step_file)

            return {
                "step_b64": base64.b64encode(step_bytes).decode(),
                "metrics": geo_metrics,
                "output_path": out_path,
                "shape": request.shape,
            }

        loop = asyncio.get_event_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, _sync_generate),
                timeout=FORGE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail=f"Generation timed out after {FORGE_TIMEOUT}s")

        duration_ms = (time.time() - t0) * 1000
        _metrics["generate_count"] += 1
        _metrics["total_latency_seconds"] += duration_ms / 1000

        logger.info({"event": "generate_complete", "run_id": run_id, "duration_ms": round(duration_ms, 2)})
        return GenerateResponse(result=result, duration_ms=round(duration_ms, 2), run_id=run_id)

    except HTTPException:
        raise
    except Exception as exc:
        _metrics["error_count"] += 1
        logger.exception({"event": "generate_error", "run_id": run_id, "error": str(exc)})
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        _metrics["queue_depth"] = max(0, _metrics["queue_depth"] - 1)

@app.post("/run", response_model=GenerateResponse)
async def run(request: GeometryParams):
    """Alias for /generate for API consistency."""
    return await generate(request)

@app.post("/export", response_model=GenerateResponse)
async def export_geometry(request: ExportRequest):
    _metrics["request_count"] += 1
    _metrics["queue_depth"] += 1
    run_id = request.run_id or str(uuid.uuid4())
    t0 = time.time()

    logger.info({"event": "export_start", "run_id": run_id, "format": request.output_format})

    try:
        step_bytes = base64.b64decode(request.step_b64)

        def _sync_export():
            import cadquery as cq
            with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as f:
                f.write(step_bytes)
                step_path = f.name

            shape = cq.importers.importStep(step_path)

            out_path = f"/tmp/{run_id}_output.{request.output_format}"
            fmt_map = {
                "stl": cq.exporters.ExportTypes.STL,
                "step": cq.exporters.ExportTypes.STEP,
                "brep": cq.exporters.ExportTypes.BREP,
                "svg": cq.exporters.ExportTypes.SVG,
            }
            cq.exporters.export(
                shape, out_path,
                fmt_map[request.output_format],
                tolerance=request.linear_deflection,
                angularTolerance=request.angular_deflection,
            )
            output_bytes = Path(out_path).read_bytes()

            if DATA_DIR.exists():
                out_dir = DATA_DIR / run_id
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / f"output.{request.output_format}").write_bytes(output_bytes)

            return {
                "output_b64": base64.b64encode(output_bytes).decode(),
                "format": request.output_format,
                "size_bytes": len(output_bytes),
            }

        loop = asyncio.get_event_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, _sync_export),
                timeout=FORGE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail=f"Export timed out after {FORGE_TIMEOUT}s")

        duration_ms = (time.time() - t0) * 1000
        _metrics["export_count"] += 1
        _metrics["total_latency_seconds"] += duration_ms / 1000

        logger.info({"event": "export_complete", "run_id": run_id, "duration_ms": round(duration_ms, 2)})
        return GenerateResponse(result=result, duration_ms=round(duration_ms, 2), run_id=run_id)

    except HTTPException:
        raise
    except Exception as exc:
        _metrics["error_count"] += 1
        logger.exception({"event": "export_error", "run_id": run_id, "error": str(exc)})
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        _metrics["queue_depth"] = max(0, _metrics["queue_depth"] - 1)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("FORGE_PORT", "8002")))
