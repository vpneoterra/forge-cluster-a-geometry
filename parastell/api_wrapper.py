"""
ParaStell Stellarator Geometry - FastAPI Wrapper
Container: parastell | Port: 8007
POST /run: stellarator parameters → STEP/DAGMC geometry
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import shutil
import sys
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

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
            "container": "parastell",
            **({"exception": self.formatException(record.exc_info)} if record.exc_info else {}),
        })

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JSONFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger("parastell-api")

START_TIME = time.time()
FORGE_TIMEOUT = int(os.getenv("FORGE_TIMEOUT", "300"))
VERSION = "2.1.0"
CONTAINER_NAME = "parastell"
DATA_DIR = Path("/data")
PARASTELL_HOME = Path(os.getenv("PARASTELL_HOME", "/opt/parastell"))

_metrics: dict[str, float] = {
    "request_count": 0, "error_count": 0, "run_count": 0,
    "total_latency_seconds": 0.0, "queue_depth": 0,
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info({"event": "startup", "container": CONTAINER_NAME})
    try:
        import parastell  # noqa: F401
        logger.info({"event": "parastell_loaded"})
    except ImportError as e:
        logger.warning({"event": "parastell_import_warning", "error": str(e)})
    yield
    logger.info({"event": "shutdown"})

app = FastAPI(
    title="ParaStell Stellarator Geometry API",
    description="ParaStell stellarator geometry tool - STEP and DAGMC output",
    version=VERSION,
    lifespan=lifespan,
)

# ── Models ────────────────────────────────────────────────────
class WallParams(BaseModel):
    """First wall / blanket geometry parameters."""
    radial_build: dict[str, float] = Field(
        default={
            "plasma": 0.1, "sol": 0.05, "first_wall": 0.03,
            "blanket": 0.3, "back_wall": 0.03, "shield": 0.3,
        },
        description="Radial build dict: component → thickness in meters",
    )

class ParaStellRequest(BaseModel):
    # VMEC equilibrium reference
    vmec_file: str | None = Field(
        default=None,
        description="Path to VMEC wout NetCDF file (must be mounted at /data)",
    )
    vmec_file_b64: str | None = Field(
        default=None,
        description="Base64-encoded VMEC wout NetCDF file content",
    )
    # Geometric parameters
    toroidal_angles: list[float] = Field(
        default=[0.0, 90.0, 180.0, 270.0, 360.0],
        description="Toroidal angle array in degrees",
    )
    poloidal_angles: list[float] = Field(
        default=[0.0, 60.0, 120.0, 180.0, 240.0, 300.0, 360.0],
        description="Poloidal angle array in degrees",
    )
    wall_s: float = Field(
        default=1.2, ge=1.0, le=3.0,
        description="Normalized toroidal flux for wall surface",
    )
    wall_params: WallParams = Field(default=WallParams())
    num_phi: int = Field(default=60, ge=4, le=360, description="Toroidal resolution")
    num_theta: int = Field(default=60, ge=4, le=360, description="Poloidal resolution")
    export_dagmc: bool = Field(default=False, description="Also generate DAGMC h5m file")
    custom_script: str | None = Field(
        default=None,
        description="Raw Python script using parastell. Must produce output files in workdir.",
    )
    run_id: str | None = None

class RunResponse(BaseModel):
    result: dict[str, Any]
    duration_ms: float
    run_id: str

# ── Helpers ───────────────────────────────────────────────────
def _run_parastell(request: ParaStellRequest, workdir: Path) -> dict[str, Any]:
    """Execute ParaStell geometry generation."""
    result: dict[str, Any] = {}

    # Handle VMEC file
    vmec_path = None
    if request.vmec_file_b64:
        vmec_path = workdir / "wout.nc"
        vmec_path.write_bytes(base64.b64decode(request.vmec_file_b64))
    elif request.vmec_file:
        vmec_path = Path(request.vmec_file)
        if not vmec_path.exists():
            # Try under /data
            vmec_path = DATA_DIR / request.vmec_file
        if not vmec_path.exists():
            raise FileNotFoundError(f"VMEC file not found: {request.vmec_file}")

    if request.custom_script:
        ns: dict = {}
        try:
            import parastell
        except ImportError:
            parastell = None  # type: ignore[assignment]
        exec(  # noqa: S102
            request.custom_script,
            {"parastell": parastell, "workdir": str(workdir), "vmec_path": str(vmec_path)},
            ns,
        )
        result["custom_script_executed"] = True
    else:
        try:
            import parastell
            import numpy as np

            # Convert angles to radians
            tor_angles = np.deg2rad(request.toroidal_angles).tolist()
            pol_angles = np.deg2rad(request.poloidal_angles).tolist()

            # Initialize ParaStell geometry
            if vmec_path and vmec_path.exists():
                ps = parastell.Stellarator(str(vmec_path))
                ps.construct_invessel_build(
                    tor_angles, pol_angles,
                    wall_s=request.wall_s,
                )
                # Export STEP
                step_out = workdir / "stellarator.step"
                ps.export_step(str(step_out))
                if step_out.exists():
                    result["step_size_bytes"] = step_out.stat().st_size
                    result["step_b64"] = base64.b64encode(step_out.read_bytes()).decode()

                if request.export_dagmc:
                    h5m_out = workdir / "dagmc.h5m"
                    ps.export_dagmc(str(h5m_out))
                    if h5m_out.exists():
                        result["dagmc_b64"] = base64.b64encode(h5m_out.read_bytes()).decode()
            else:
                result["warning"] = "No VMEC file provided. Using synthetic geometry demo."
                # Generate a simple torus as placeholder
                import cadquery as cq
                torus = cq.Workplane("XY").torus(10, 3)
                step_out = workdir / "stellarator_demo.step"
                cq.exporters.export(torus, str(step_out), cq.exporters.ExportTypes.STEP)
                result["step_size_bytes"] = step_out.stat().st_size
                result["step_b64"] = base64.b64encode(step_out.read_bytes()).decode()
                result["demo_mode"] = True

        except ImportError as e:
            result["parastell_import_error"] = str(e)
            result["available_packages"] = _check_packages()

    # Collect output files
    output_files = [f.name for f in workdir.iterdir() if f.is_file()]
    result["output_files"] = output_files

    # Copy to /data
    if DATA_DIR.exists():
        out_dir = DATA_DIR / (request.run_id or "parastell_run")
        out_dir.mkdir(parents=True, exist_ok=True)
        for f in workdir.iterdir():
            if f.is_file() and f.suffix in (".step", ".h5m", ".nc", ".txt"):
                shutil.copy2(f, out_dir / f.name)
        result["output_path"] = str(out_dir)

    return result

def _check_packages() -> dict[str, bool]:
    """Check which key packages are available."""
    packages = {}
    for pkg in ["parastell", "cadquery", "dagmc", "netCDF4", "numpy"]:
        try:
            __import__(pkg)
            packages[pkg] = True
        except ImportError:
            packages[pkg] = False
    return packages

# ── Routes ────────────────────────────────────────────────────
@app.get("/health")
async def health():
    _metrics["request_count"] += 1
    return {
        "status": "ok",
        "container": CONTAINER_NAME,
        "uptime_seconds": round(time.time() - START_TIME, 2),
        "version": VERSION,
        "packages": _check_packages(),
    }

@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    _metrics["request_count"] += 1
    uptime = time.time() - START_TIME
    avg_lat = (
        _metrics["total_latency_seconds"] / _metrics["run_count"]
        if _metrics["run_count"] > 0 else 0.0
    )
    mem = psutil.virtual_memory()
    lines = [
        f'forge_request_count{{container="{CONTAINER_NAME}"}} {_metrics["request_count"]:.0f}',
        f'forge_latency_seconds{{container="{CONTAINER_NAME}"}} {avg_lat:.6f}',
        f'forge_error_count{{container="{CONTAINER_NAME}"}} {_metrics["error_count"]:.0f}',
        f'forge_queue_depth{{container="{CONTAINER_NAME}"}} {_metrics["queue_depth"]:.0f}',
        f'forge_uptime_seconds{{container="{CONTAINER_NAME}"}} {uptime:.2f}',
        f'forge_memory_bytes_used{{container="{CONTAINER_NAME}"}} {mem.used}',
        f'forge_run_count{{container="{CONTAINER_NAME}"}} {_metrics["run_count"]:.0f}',
    ]
    return "\n".join(lines) + "\n"

@app.post("/run", response_model=RunResponse)
async def run(request: ParaStellRequest):
    _metrics["request_count"] += 1
    _metrics["queue_depth"] += 1
    run_id = request.run_id or str(uuid.uuid4())
    request.run_id = run_id
    t0 = time.time()

    logger.info({
        "event": "run_start", "run_id": run_id,
        "has_vmec": request.vmec_file is not None or request.vmec_file_b64 is not None,
        "export_dagmc": request.export_dagmc,
    })

    try:
        def _sync_run():
            with tempfile.TemporaryDirectory(prefix="parastell_run_") as tmpdir:
                workdir = Path(tmpdir)
                return _run_parastell(request, workdir)

        loop = asyncio.get_event_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, _sync_run),
                timeout=FORGE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail=f"ParaStell timed out after {FORGE_TIMEOUT}s")

        duration_ms = (time.time() - t0) * 1000
        _metrics["run_count"] += 1
        _metrics["total_latency_seconds"] += duration_ms / 1000

        logger.info({"event": "run_complete", "run_id": run_id, "duration_ms": round(duration_ms, 2)})
        return RunResponse(result=result, duration_ms=round(duration_ms, 2), run_id=run_id)

    except HTTPException:
        raise
    except Exception as exc:
        _metrics["error_count"] += 1
        logger.exception({"event": "run_error", "run_id": run_id, "error": str(exc)})
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        _metrics["queue_depth"] = max(0, _metrics["queue_depth"] - 1)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("FORGE_PORT", "8007")))
