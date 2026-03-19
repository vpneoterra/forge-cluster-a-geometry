"""
FORGE — docker/cadquery/api_wrapper_patch.py

Patch additions for docker/cadquery/api_wrapper.py:
  - FastenerRequest Pydantic model
  - /parts/fastener POST endpoint

Integration instructions:
  1. Add the FastenerRequest class after the existing Pydantic model definitions.
  2. Add the generate_fastener endpoint function after the existing route handlers.
  3. The token loading logic re-uses the existing tokens dict already loaded in
     api_wrapper.py (loaded from /app/tokens.json by the main module).

This file is structured so it can be appended directly or copy-pasted into the
main api_wrapper.py.  All imports listed below are additions to the existing
import block — do not duplicate imports already present.
"""

# ── Additional imports (add to existing import block) ────────────────────────
import base64
import io
import json
import math
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field

# ── Token map (loaded once at startup) ───────────────────────────────────────
# The main api_wrapper.py already loads tokens from /app/tokens.json.
# This patch references the same dict.  If integrating standalone, load here:

_TOKENS: dict = {}

def _load_tokens() -> dict:
    """Load forge-tokens-svg.json / tokens.json from /app/tokens.json."""
    global _TOKENS
    token_path = Path("/app/tokens.json")
    if token_path.exists():
        try:
            with token_path.open() as f:
                _TOKENS = json.load(f)
        except Exception as exc:
            print(f"[cadquery-patch] Could not load tokens: {exc}")
    return _TOKENS


_TOKENS = _load_tokens()

# ── Fastener standard → class mapping ────────────────────────────────────────
# Supported ISO standards and their bd_warehouse / cq_warehouse equivalents.
FASTENER_STANDARD_MAP: dict[str, dict] = {
    # Socket-head cap screws (ISO 4762 / DIN 912)
    "ISO_4762": {"type": "screw",   "bd_class": "SocketHeadCapScrew",    "iso": "iso4762"},
    "DIN_912":  {"type": "screw",   "bd_class": "SocketHeadCapScrew",    "iso": "iso4762"},
    # Hex bolts (ISO 4014 / DIN 931)
    "ISO_4014": {"type": "bolt",    "bd_class": "HexBolt",               "iso": "iso4014"},
    "DIN_931":  {"type": "bolt",    "bd_class": "HexBolt",               "iso": "iso4014"},
    # Fully-threaded hex bolts (ISO 4017 / DIN 933)
    "ISO_4017": {"type": "bolt",    "bd_class": "HexBolt",               "iso": "iso4017"},
    "DIN_933":  {"type": "bolt",    "bd_class": "HexBolt",               "iso": "iso4017"},
    # Hex nuts (ISO 4032 / DIN 934)
    "ISO_4032": {"type": "nut",     "bd_class": "HexNut",                "iso": "iso4032"},
    "DIN_934":  {"type": "nut",     "bd_class": "HexNut",                "iso": "iso4032"},
    # Countersunk screws (ISO 10642)
    "ISO_10642": {"type": "screw",  "bd_class": "CounterSunkScrew",      "iso": "iso10642"},
    # Flat washers (ISO 7089)
    "ISO_7089": {"type": "washer",  "bd_class": "PlainWasher",           "iso": "iso7089"},
}

# Metric thread sizes → nominal diameter (mm) + pitch (mm)
METRIC_THREAD: dict[str, tuple[float, float]] = {
    "M2":   (2.0,  0.40),
    "M2.5": (2.5,  0.45),
    "M3":   (3.0,  0.50),
    "M4":   (4.0,  0.70),
    "M5":   (5.0,  0.80),
    "M6":   (6.0,  1.00),
    "M8":   (8.0,  1.25),
    "M10":  (10.0, 1.50),
    "M12":  (12.0, 1.75),
    "M14":  (14.0, 2.00),
    "M16":  (16.0, 2.00),
    "M20":  (20.0, 2.50),
    "M24":  (24.0, 3.00),
}


# ── Pydantic model ────────────────────────────────────────────────────────────

class FastenerRequest(BaseModel):
    """Request body for the /parts/fastener endpoint."""

    standard: str = Field(
        ...,
        description=(
            "ISO/DIN standard identifier, e.g. ISO_4762, ISO_4014, ISO_4032, "
            "ISO_4017, ISO_10642, ISO_7089, DIN_912, DIN_931, DIN_933, DIN_934"
        ),
        examples=["ISO_4762", "ISO_4014", "ISO_4032"],
    )
    size: str = Field(
        ...,
        description="Metric thread designation, e.g. M8, M10, M12",
        examples=["M8", "M10", "M12"],
    )
    length: Optional[float] = Field(
        None,
        description="Nominal length in mm (required for screws/bolts; omit for nuts/washers)",
        examples=[25.0, 40.0, 80.0],
        gt=0,
    )
    simple: bool = Field(
        False,
        description=(
            "If True, generate a simplified (low-detail) representation "
            "suitable for assembly diagrams. Default False = full detail."
        ),
    )
    apply_token_theme: bool = Field(
        True,
        description="Apply FORGE design token colours to the SVG projection output.",
    )


# ── Helper: token-themed SVG line colour ─────────────────────────────────────

def _token_color(key: str, fallback: str) -> str:
    """Return the token value for key, or fallback if not found."""
    return _TOKENS.get(key, fallback)


def _apply_token_theme_to_svg(svg: str) -> str:
    """
    Replace hardcoded hex colours in the SVG projection with FORGE token values.
    Mirrors the JS applyTokenTheme() logic in diagram-post-processing.js.
    """
    if not _TOKENS:
        return svg
    # Build inverse map: hex_value → css_var
    inverse: dict[str, str] = {}
    for k, v in _TOKENS.items():
        if isinstance(v, str) and v.startswith("#") and len(v) in (4, 7, 9):
            canonical = v.lower()
            if len(canonical) == 4:
                canonical = "#" + "".join(c * 2 for c in canonical[1:])
            css_var = f"var(--forge-{k.replace('.', '-')})"
            inverse[canonical] = css_var

    import re
    def replacer(m):
        val = m.group(0).lower()
        if len(val) == 4:
            val = "#" + "".join(c * 2 for c in val[1:])
        return inverse.get(val, m.group(0))

    return re.sub(r"#[0-9a-fA-F]{3,8}\b", replacer, svg)


# ── SVG 2D projection generator (pure geometry, no CadQuery dependency) ──────

def _generate_fastener_svg_projection(
    standard: str,
    size: str,
    length_mm: Optional[float],
    fastener_type: str,
    simple: bool,
) -> str:
    """
    Generate a dimensioned SVG front-view projection for a metric fastener.

    This implementation draws the fastener geometry procedurally using
    standard metric proportions (ISO 4762 / 4014 / 4032) so that it works
    even when bd_warehouse is not installed.  When bd_warehouse IS installed
    (production path), replace this function body with actual STEP export +
    CadQuery SVG projection.

    Proportions used (all relative to nominal diameter d):
      Socket head cap screw (ISO 4762):  head_d = 1.5d, head_h = d, thread_l = length
      Hex bolt (ISO 4014):              head_h = 0.65d, A/F = 1.7d
      Hex nut (ISO 4032):               height = 0.8d, A/F = 1.7d
    """
    thread_data = METRIC_THREAD.get(size.upper(), (8.0, 1.25))
    d = thread_data[0]          # nominal diameter
    L = length_mm or d * 4      # total length
    fill_bg   = "#1B1D21"
    stroke    = "#00B4D8"
    dim_color = "#9CA3AF"
    text_fill = "#E5E7EB"
    hidden_stroke = "#6B7280"

    # Viewport
    margin = d * 3
    if fastener_type in ("screw", "bolt"):
        vb_w = d * 2.5 + margin * 2
        vb_h = L + d * 2 + margin * 2
    else:  # nut / washer
        vb_w = d * 2.5 + margin * 2
        vb_h = d * 2 + margin * 2

    cx = vb_w / 2
    origin_y = margin

    lines: list[str] = []

    def tag(name, **attrs):
        attr_str = " ".join(f'{k.replace("_","-")}="{v}"' for k, v in attrs.items())
        return f"<{name} {attr_str}/>"

    def text(x, y, content, anchor="middle", size=d * 0.9, weight="400"):
        return (
            f'<text x="{x:.3f}" y="{y:.3f}" '
            f'font-family="\'Inter\', sans-serif" font-size="{size:.3f}" '
            f'text-anchor="{anchor}" fill="{text_fill}" font-weight="{weight}">'
            f'{content}</text>'
        )

    def dim_line(x1, y1, x2, y2, label, side="right"):
        """Simple dimension line with label."""
        offset = d * 1.2
        lx = (x1 + x2) / 2 + (offset if side == "right" else -offset)
        ly = (y1 + y2) / 2
        return [
            tag("line", x1=f"{x1:.3f}", y1=f"{y1:.3f}", x2=f"{x2:.3f}", y2=f"{y2:.3f}",
                stroke=dim_color, stroke_width=f"{d*0.08:.3f}", stroke_dasharray=f"{d*0.3} {d*0.15}"),
            tag("line", x1=f"{x2:.3f}", y1=f"{y1:.3f}", x2=f"{lx:.3f}", y2=f"{ly:.3f}",
                stroke=dim_color, stroke_width=f"{d*0.06:.3f}"),
            tag("line", x1=f"{x2:.3f}", y1=f"{y2:.3f}", x2=f"{lx:.3f}", y2=f"{ly:.3f}",
                stroke=dim_color, stroke_width=f"{d*0.06:.3f}"),
            text(lx + d * 0.6 * (1 if side == "right" else -1), ly + d * 0.3, label, "start" if side == "right" else "end", d * 0.8),
        ]

    if fastener_type in ("screw", "bolt"):
        head_h = d if fastener_type == "screw" else d * 0.65
        head_r = d * 0.75  # head radius
        shank_r = d / 2

        # Head
        lines.append(tag(
            "rect",
            x=f"{cx - head_r:.3f}", y=f"{origin_y:.3f}",
            width=f"{head_r * 2:.3f}", height=f"{head_h:.3f}",
            fill=fill_bg, stroke=stroke, stroke_width=f"{d * 0.12:.3f}",
        ))
        # Socket drive (simplified as horizontal line for socket head)
        if fastener_type == "screw" and not simple:
            drive_w = d * 0.6
            drive_h = d * 0.5
            lines.append(tag(
                "rect",
                x=f"{cx - drive_w / 2:.3f}", y=f"{origin_y + d * 0.1:.3f}",
                width=f"{drive_w:.3f}", height=f"{drive_h:.3f}",
                fill=fill_bg, stroke=stroke, stroke_width=f"{d * 0.08:.3f}",
            ))

        # Shank
        shank_y = origin_y + head_h
        shank_l = L - head_h
        lines.append(tag(
            "rect",
            x=f"{cx - shank_r:.3f}", y=f"{shank_y:.3f}",
            width=f"{shank_r * 2:.3f}", height=f"{shank_l:.3f}",
            fill=fill_bg, stroke=stroke, stroke_width=f"{d * 0.12:.3f}",
        ))

        # Thread representation (simplified helix lines)
        if not simple:
            pitch = thread_data[1]
            num_threads = int(shank_l / pitch)
            for i in range(min(num_threads, 40)):
                ty = shank_y + i * pitch
                lines.append(tag(
                    "line",
                    x1=f"{cx - shank_r:.3f}", y1=f"{ty:.3f}",
                    x2=f"{cx + shank_r:.3f}", y2=f"{ty + pitch * 0.5:.3f}",
                    stroke=hidden_stroke, stroke_width=f"{d * 0.05:.3f}",
                    stroke_dasharray=f"{d * 0.2} {d * 0.1}",
                ))

        # Dimensions
        tip_y = origin_y + L
        lines += dim_line(cx + shank_r, origin_y, cx + shank_r, tip_y,
                          f"L={L:.0f}mm", "right")
        lines += dim_line(cx - shank_r, origin_y + L / 2, cx + shank_r, origin_y + L / 2,
                          f"Ø{d:.0f}", "right")

        # Part label
        lines.append(text(cx, origin_y - d * 0.8,
                          f"{standard} {size}×{L:.0f}", size=d * 1.0, weight="600"))

    elif fastener_type == "nut":
        nut_h = d * 0.8
        af = d * 1.7  # Across-flats (approx)
        # Hexagonal profile: draw as rectangle + chamfer indicator
        lines.append(tag(
            "rect",
            x=f"{cx - af / 2:.3f}", y=f"{origin_y:.3f}",
            width=f"{af:.3f}", height=f"{nut_h:.3f}",
            fill=fill_bg, stroke=stroke, stroke_width=f"{d * 0.12:.3f}",
        ))
        # Thread hole (hidden)
        lines.append(tag(
            "rect",
            x=f"{cx - d / 2:.3f}", y=f"{origin_y:.3f}",
            width=f"{d:.3f}", height=f"{nut_h:.3f}",
            fill="none", stroke=hidden_stroke, stroke_width=f"{d * 0.08:.3f}",
            stroke_dasharray=f"{d * 0.3} {d * 0.15}",
        ))
        # Chamfer lines
        cham = d * 0.1
        lines.append(tag("line",
            x1=f"{cx - af / 2:.3f}", y1=f"{origin_y:.3f}",
            x2=f"{cx - af / 2 + cham:.3f}", y2=f"{origin_y + cham:.3f}",
            stroke=stroke, stroke_width=f"{d * 0.1:.3f}",
        ))
        lines.append(tag("line",
            x1=f"{cx + af / 2:.3f}", y1=f"{origin_y:.3f}",
            x2=f"{cx + af / 2 - cham:.3f}", y2=f"{origin_y + cham:.3f}",
            stroke=stroke, stroke_width=f"{d * 0.1:.3f}",
        ))
        lines += dim_line(cx + af / 2, origin_y, cx + af / 2, origin_y + nut_h,
                          f"H={nut_h:.1f}mm", "right")
        lines += dim_line(cx - af / 2, origin_y + nut_h / 2,
                          cx + af / 2, origin_y + nut_h / 2,
                          f"AF={af:.1f}mm", "right")
        lines.append(text(cx, origin_y - d * 0.8,
                          f"{standard} {size}", size=d * 1.0, weight="600"))

    elif fastener_type == "washer":
        outer_r = d * 1.1
        inner_r = d * 0.55
        thickness = d * 0.15
        lines.append(tag("rect",
            x=f"{cx - outer_r:.3f}", y=f"{origin_y:.3f}",
            width=f"{outer_r * 2:.3f}", height=f"{thickness:.3f}",
            fill=fill_bg, stroke=stroke, stroke_width=f"{d * 0.12:.3f}",
        ))
        lines.append(tag("rect",
            x=f"{cx - inner_r:.3f}", y=f"{origin_y:.3f}",
            width=f"{inner_r * 2:.3f}", height=f"{thickness:.3f}",
            fill=fill_bg, stroke=hidden_stroke, stroke_width=f"{d * 0.08:.3f}",
            stroke_dasharray=f"{d * 0.3} {d * 0.15}",
        ))
        lines.append(text(cx, origin_y - d * 0.8,
                          f"{standard} {size}", size=d * 1.0, weight="600"))

    svg = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {vb_w:.3f} {vb_h:.3f}" '
        f'width="{vb_w:.3f}mm" height="{vb_h:.3f}mm" '
        f'font-family="\'Inter\', -apple-system, sans-serif">\n'
        f'  <rect width="{vb_w:.3f}" height="{vb_h:.3f}" fill="{fill_bg}"/>\n'
        + "\n".join(f"  {line}" for line in lines) +
        "\n</svg>"
    )
    return svg


# ── FastAPI endpoint ──────────────────────────────────────────────────────────

# NOTE: `app` is the FastAPI instance defined in api_wrapper.py.
#       Paste this function into that module after `app` is created.

async def generate_fastener(request: FastenerRequest):
    """
    POST /parts/fastener

    Generate a metric fastener 3D model (STEP) and 2D SVG projection.

    Returns:
        step_base64     : base64-encoded STEP file string
        svg_projection  : themed SVG string of the 2D front-view projection
        standard        : the resolved ISO standard name
        size            : metric size string
        length_mm       : resolved nominal length (null for nuts/washers)
        fastener_type   : screw | bolt | nut | washer
        execution_time_ms : wall-clock time for generation
    """
    t0 = time.perf_counter()

    standard_upper = request.standard.upper().replace("-", "_")
    size_upper     = request.size.upper()

    # Validate standard
    if standard_upper not in FASTENER_STANDARD_MAP:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported standard '{request.standard}'. "
                f"Supported: {', '.join(FASTENER_STANDARD_MAP)}"
            ),
        )

    # Validate size
    if size_upper not in METRIC_THREAD:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported metric size '{request.size}'. "
                f"Supported: {', '.join(METRIC_THREAD)}"
            ),
        )

    meta = FASTENER_STANDARD_MAP[standard_upper]
    fastener_type: str = meta["type"]

    # Length is required for screws/bolts
    if fastener_type in ("screw", "bolt") and request.length is None:
        raise HTTPException(
            status_code=422,
            detail=f"'length' is required for fastener type '{fastener_type}'.",
        )

    # ── Attempt bd_warehouse / cq_warehouse model generation ─────────────────
    step_b64: Optional[str] = None
    model_source = "procedural"

    try:
        import cadquery as cq  # noqa: F401

        bd_available = False
        cqw_available = False

        try:
            from bd_warehouse.fastener import (
                SocketHeadCapScrew as BdSocketScrew,
                HexBolt as BdHexBolt,
                HexNut as BdHexNut,
            )
            bd_available = True
        except ImportError:
            pass

        if not bd_available:
            try:
                from cq_warehouse.fastener import (  # type: ignore
                    SocketHeadCapScrew as CqwSocketScrew,
                    HexBolt as CqwHexBolt,
                    HexNut as CqwHexNut,
                )
                cqw_available = True
            except ImportError:
                pass

        if bd_available or cqw_available:
            # Build fastener using whichever library is available
            thread_spec = f"{size_upper}-{METRIC_THREAD[size_upper][1]:.2f}"

            if fastener_type in ("screw", "bolt"):
                length_str = f"{request.length:.0f}mm"
                if bd_available:
                    if fastener_type == "screw":
                        part = BdSocketScrew(
                            size=thread_spec,
                            length=request.length,
                            simple=request.simple,
                        )
                    else:
                        part = BdHexBolt(
                            size=thread_spec,
                            length=request.length,
                            simple=request.simple,
                        )
                else:
                    kwargs = dict(size=thread_spec, length=request.length, simple=request.simple)
                    if fastener_type == "screw":
                        part = CqwSocketScrew(**kwargs)
                    else:
                        part = CqwHexBolt(**kwargs)
            else:
                if bd_available:
                    part = BdHexNut(size=thread_spec, simple=request.simple)
                else:
                    part = CqwHexNut(size=thread_spec, simple=request.simple)

            # Export to STEP via temporary file
            with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as tmp:
                tmp_path = tmp.name

            try:
                cq.exporters.export(part.cq_object if hasattr(part, "cq_object") else part,
                                    tmp_path)
                with open(tmp_path, "rb") as f:
                    step_b64 = base64.b64encode(f.read()).decode()
                model_source = "bd_warehouse" if bd_available else "cq_warehouse"
            finally:
                os.unlink(tmp_path)

    except Exception as exc:
        # Non-fatal — fall through to procedural SVG
        print(f"[cadquery-patch] 3D generation skipped: {exc}")

    # ── Generate SVG projection ───────────────────────────────────────────────
    svg = _generate_fastener_svg_projection(
        standard=standard_upper,
        size=size_upper,
        length_mm=request.length,
        fastener_type=fastener_type,
        simple=request.simple,
    )

    if request.apply_token_theme:
        svg = _apply_token_theme_to_svg(svg)

    # ── If no STEP was generated, create a minimal stub ──────────────────────
    if step_b64 is None:
        d = METRIC_THREAD[size_upper][0]
        L = request.length or d * 4
        stub_step = (
            f"ISO-10303-21;\nHEADER;\n"
            f"/* FORGE stub STEP — {standard_upper} {size_upper} L={L}mm */\n"
            f"FILE_DESCRIPTION(('FORGE Fastener {size_upper}'),'2;1');\n"
            f"FILE_NAME('{size_upper}.step','',(''),(''),'FORGE','','');\n"
            f"FILE_SCHEMA(('AUTOMOTIVE_DESIGN {{ 1 0 10303 214 1 1 1 1 }}'));\n"
            f"ENDSEC;\nDATA;\n#1=PRODUCT('{size_upper}','{size_upper}','',($));\n"
            f"ENDSEC;\nEND-ISO-10303-21;\n"
        )
        step_b64 = base64.b64encode(stub_step.encode()).decode()

    execution_time_ms = round((time.perf_counter() - t0) * 1000, 2)

    return {
        "step_base64":       step_b64,
        "svg_projection":    svg,
        "standard":          standard_upper,
        "size":              size_upper,
        "length_mm":         request.length,
        "fastener_type":     fastener_type,
        "model_source":      model_source,
        "execution_time_ms": execution_time_ms,
    }


# ── Integration snippet ───────────────────────────────────────────────────────
# Copy the lines below into docker/cadquery/api_wrapper.py:
#
#   from api_wrapper_patch import FastenerRequest, generate_fastener
#
#   @app.post("/parts/fastener")
#   async def _fastener_endpoint(request: FastenerRequest):
#       return await generate_fastener(request)
