"""
Paramak Fusion Reactor CAD - FastAPI Wrapper
Container: paramak | Port: 8006
POST /generate: reactor params + device_type → 3D model
"""

from __future__ import annotations

import asyncio
import base64
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

# ── Structured logging ────────────────────────────────────────
class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "container": "paramak",
            **({"exception": self.formatException(record.exc_info)} if record.exc_info else {}),
        })

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JSONFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger("paramak-api")

START_TIME = time.time()
FORGE_TIMEOUT = int(os.getenv("FORGE_TIMEOUT", "300"))
VERSION = "2.1.0"
CONTAINER_NAME = "paramak"
DATA_DIR = Path("/data")

_metrics: dict[str, float] = {
    "request_count": 0, "error_count": 0,
    "generate_count": 0, "total_latency_seconds": 0.0, "queue_depth": 0,
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info({"event": "startup", "container": CONTAINER_NAME})
    try:
        import paramak  # noqa: F401
        logger.info({"event": "paramak_loaded"})
    except ImportError as e:
        logger.warning({"event": "paramak_import_warning", "error": str(e)})
    yield
    logger.info({"event": "shutdown", "container": CONTAINER_NAME})

app = FastAPI(
    title="Paramak Fusion Reactor CAD API",
    description="Paramak fusion reactor parametric 3D model generation",
    version=VERSION,
    lifespan=lifespan,
)

# ── Device type catalogue ─────────────────────────────────────
DEVICE_TYPES = Literal[
    "BallReactor",
    "BallReactorParameterised",
    "SingleNullReactor",
    "SegmentedBlanketBallReactor",
    "CenterColumnShieldCylinder",
    "CenterColumnShieldHyperbola",
    "CenterColumnShieldFlatTopHyperbola",
    "CenterColumnShieldCircular",
    "BlanketConstantThicknessArcV",
    "BlanketConstantThicknessArcH",
    "custom",
]

class ReactorParams(BaseModel):
    device_type: str = Field(
        default="BallReactor",
        description="Paramak reactor class name",
    )
    params: dict[str, Any] = Field(
        default={
            "inner_bore_radial_thickness": 50,
            "inboard_tf_leg_radial_thickness": 200,
            "center_column_shield_radial_thickness": 50,
            "divertor_radial_thickness": 100,
            "inner_plasma_gap_radial_thickness": 50,
            "plasma_radial_thickness": 200,
            "outer_plasma_gap_radial_thickness": 50,
            "firstwall_radial_thickness": 50,
            "blanket_radial_thickness": 100,
            "blanket_rear_wall_radial_thickness": 50,
        },
        description="Constructor parameters for the reactor class",
    )
    export_format: Literal["step", "stl", "svg", "stp"] = "step"
    rotation_angle: float = Field(default=360.0, ge=0.0, le=360.0)
    custom_script: str | None = Field(
        default=None,
        description="Raw Python script using paramak. Must set 'reactor' variable.",
    )
    run_id: str | None = None

class GenerateResponse(BaseModel):
    result: dict[str, Any]
    duration_ms: float
    run_id: str

# ── Helper ────────────────────────────────────────────────────
def _build_reactor(request: ReactorParams):
    """Build a Paramak reactor model."""
    import paramak

    if request.custom_script:
        ns: dict = {}
        exec(request.custom_script, {"paramak": paramak}, ns)  # noqa: S102
        if "reactor" not in ns:
            raise ValueError("custom_script must define 'reactor' variable")
        return ns["reactor"]

    # Get the reactor class dynamically
    reactor_cls = getattr(paramak, request.device_type, None)
    if reactor_cls is None:
        raise ValueError(
            f"Unknown device_type '{request.device_type}'. "
            f"Available: {[c for c in dir(paramak) if 'Reactor' in c or 'Ball' in c]}"
        )

    # Add rotation_angle if accepted by the class
    params = dict(request.params)
    try:
        reactor = reactor_cls(**params, rotation_angle=request.rotation_angle)
    except TypeError:
        reactor = reactor_cls(**params)

    return reactor

def _export_reactor(reactor, fmt: str, run_id: str) -> tuple[bytes, dict[str, Any]]:
    """Export reactor to file and return bytes + metrics."""
    import paramak  # noqa: F401

    out_path = f"/tmp/{run_id}_reactor.{fmt}"

    if fmt in ("step", "stp"):
        reactor.export_stp(out_path)
    elif fmt == "stl":
        reactor.export_stl(out_path)
    elif fmt == "svg":
        reactor.export_svg(out_path)
    else:
        reactor.export_stp(out_path)

    output_bytes = Path(out_path).read_bytes()

    # Collect geometry metrics
    geo_metrics: dict[str, Any] = {}
    try:
        geo_metrics["component_count"] = len(reactor.shapes_and_components)
        geo_metrics["components"] = [c.name for c in reactor.shapes_and_components]
    except Exception:
        pass

    return output_bytes, geo_metrics

# ── Routes ────────────────────────────────────────────────────
@app.get("/health")
async def health():
    _metrics["request_count"] += 1
    paramak_ok = False
    try:
        import paramak  # noqa: F401
        paramak_ok = True
    except ImportError:
        pass
    return {
        "status": "ok",
        "container": CONTAINER_NAME,
        "uptime_seconds": round(time.time() - START_TIME, 2),
        "version": VERSION,
        "paramak_available": paramak_ok,
    }

@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    _metrics["request_count"] += 1
    uptime = time.time() - START_TIME
    avg_lat = (
        _metrics["total_latency_seconds"] / _metrics["generate_count"]
        if _metrics["generate_count"] > 0 else 0.0
    )
    mem = psutil.virtual_memory()
    lines = [
        f'forge_request_count{{container="{CONTAINER_NAME}"}} {_metrics["request_count"]:.0f}',
        f'forge_latency_seconds{{container="{CONTAINER_NAME}"}} {avg_lat:.6f}',
        f'forge_error_count{{container="{CONTAINER_NAME}"}} {_metrics["error_count"]:.0f}',
        f'forge_queue_depth{{container="{CONTAINER_NAME}"}} {_metrics["queue_depth"]:.0f}',
        f'forge_uptime_seconds{{container="{CONTAINER_NAME}"}} {uptime:.2f}',
        f'forge_memory_bytes_used{{container="{CONTAINER_NAME}"}} {mem.used}',
        f'forge_generate_count{{container="{CONTAINER_NAME}"}} {_metrics["generate_count"]:.0f}',
    ]
    return "\n".join(lines) + "\n"

@app.post("/generate", response_model=GenerateResponse)
async def generate(request: ReactorParams):
    _metrics["request_count"] += 1
    _metrics["queue_depth"] += 1
    run_id = request.run_id or str(uuid.uuid4())
    t0 = time.time()

    logger.info({
        "event": "generate_start", "run_id": run_id,
        "device_type": request.device_type, "export_format": request.export_format,
    })

    try:
        def _sync_generate():
            reactor = _build_reactor(request)
            output_bytes, geo_metrics = _export_reactor(reactor, request.export_format, run_id)

            output_b64 = base64.b64encode(output_bytes).decode()
            out_path = None
            if DATA_DIR.exists():
                out_dir = DATA_DIR / run_id
                out_dir.mkdir(parents=True, exist_ok=True)
                out_file = out_dir / f"reactor.{request.export_format}"
                out_file.write_bytes(output_bytes)
                out_path = str(out_file)

            return {
                "output_b64": output_b64,
                "format": request.export_format,
                "device_type": request.device_type,
                "size_bytes": len(output_bytes),
                "output_path": out_path,
                **geo_metrics,
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
async def run(request: ReactorParams):
    """Alias for /generate for API consistency."""
    return await generate(request)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("FORGE_PORT", "8006")))
