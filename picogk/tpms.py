"""
picogk/tpms.py — Pure Python/NumPy TPMS Implicit Surface Library

Mirrors the C# TPMS_Implicits.cs from vpneoterra/PicoGK
(Extensions/TPMS/TPMS_Implicits.cs).

Provides 7 Triply Periodic Minimal Surface (TPMS) types as numpy-based
signed distance field samplers with marching-cubes STL export.

All formulas evaluated in normalised cell-space: coordinates are mapped
to [0, 2π) per cell before evaluating the periodic function, matching
the C# base class TpmsImplicit.fSignedDistance() convention exactly.

References:
  Schoen, A.H. (1970). "Infinite periodic minimal surfaces without
      self-intersections." NASA Technical Note D-5541.
  Al-Ketan, O. & Abu Al-Rub, R.K. (2019). "Multifunctional mechanical
      metamaterials based on TPMS architectures." Adv. Eng. Mater.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, Literal, Optional, Tuple

import numpy as np

# ── Optional heavy deps (imported lazily) ─────────────────────────────────
try:
    from skimage.measure import marching_cubes  # scikit-image >= 0.19
    _HAVE_SKIMAGE = True
except ImportError:
    _HAVE_SKIMAGE = False

try:
    import trimesh as _trimesh
    _HAVE_TRIMESH = True
except ImportError:
    _HAVE_TRIMESH = False


# ── Type aliases ───────────────────────────────────────────────────────────
TpmsType = Literal[
    "gyroid", "schwarz_p", "schwarz_d",
    "neovius", "fischer_koch", "iwp", "lidinoid",
]


# ══════════════════════════════════════════════════════════════════════════
# Raw TPMS field functions (operate on normalised coordinates 0..2π)
# Each matches the corresponding fRawField() in TPMS_Implicits.cs exactly.
# ══════════════════════════════════════════════════════════════════════════

def _raw_gyroid(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
    """Gyroid: sin(x)cos(y) + sin(y)cos(z) + sin(z)cos(x)"""
    return np.sin(x) * np.cos(y) + np.sin(y) * np.cos(z) + np.sin(z) * np.cos(x)


def _raw_schwarz_p(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
    """Schwarz Primitive (P-surface): cos(x) + cos(y) + cos(z)"""
    return np.cos(x) + np.cos(y) + np.cos(z)


def _raw_schwarz_d(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
    """Schwarz Diamond (D-surface):
    sin(x)sin(y)sin(z) + sin(x)cos(y)cos(z) +
    cos(x)sin(y)cos(z) + cos(x)cos(y)sin(z)
    """
    return (
        np.sin(x) * np.sin(y) * np.sin(z)
        + np.sin(x) * np.cos(y) * np.cos(z)
        + np.cos(x) * np.sin(y) * np.cos(z)
        + np.cos(x) * np.cos(y) * np.sin(z)
    )


def _raw_neovius(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
    """Neovius: 3(cos(x)+cos(y)+cos(z)) + 4cos(x)cos(y)cos(z)"""
    return (
        3.0 * (np.cos(x) + np.cos(y) + np.cos(z))
        + 4.0 * np.cos(x) * np.cos(y) * np.cos(z)
    )


def _raw_fischer_koch(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
    """Fischer-Koch S:
    cos(2x)sin(y)cos(z) + cos(x)cos(2y)sin(z) + sin(x)cos(y)cos(2z)
    """
    return (
        np.cos(2.0 * x) * np.sin(y) * np.cos(z)
        + np.cos(x) * np.cos(2.0 * y) * np.sin(z)
        + np.sin(x) * np.cos(y) * np.cos(2.0 * z)
    )


def _raw_iwp(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
    """IWP (I-graph and Wrapped Package):
    cos(x)cos(y) + cos(y)cos(z) + cos(z)cos(x) - cos(x)cos(y)cos(z)
    (matches IWP.fRawField in TPMS_Implicits.cs exactly)
    """
    cx, cy, cz = np.cos(x), np.cos(y), np.cos(z)
    return cx * cy + cy * cz + cz * cx - cx * cy * cz


def _raw_lidinoid(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
    """Lidinoid:
    0.5[sin(2x)cos(y)sin(z) + sin(2y)cos(z)sin(x) + sin(2z)cos(x)sin(y)]
    - 0.5[cos(2x)cos(2y) + cos(2y)cos(2z) + cos(2z)cos(2x)] + 0.15
    (matches Lidinoid.fRawField in TPMS_Implicits.cs exactly)
    """
    term1 = 0.5 * (
        np.sin(2.0 * x) * np.cos(y) * np.sin(z)
        + np.sin(2.0 * y) * np.cos(z) * np.sin(x)
        + np.sin(2.0 * z) * np.cos(x) * np.sin(y)
    )
    term2 = 0.5 * (
        np.cos(2.0 * x) * np.cos(2.0 * y)
        + np.cos(2.0 * y) * np.cos(2.0 * z)
        + np.cos(2.0 * z) * np.cos(2.0 * x)
    )
    return term1 - term2 + 0.15


# ── Registry ───────────────────────────────────────────────────────────────
_RAW_FIELD: dict[str, Callable] = {
    "gyroid":      _raw_gyroid,
    "schwarz_p":   _raw_schwarz_p,
    "schwarz_d":   _raw_schwarz_d,
    "neovius":     _raw_neovius,
    "fischer_koch": _raw_fischer_koch,
    "iwp":         _raw_iwp,
    "lidinoid":    _raw_lidinoid,
}

TPMS_TYPES: list[str] = list(_RAW_FIELD.keys())


# ══════════════════════════════════════════════════════════════════════════
# SDF sampling — mirrors TpmsImplicit.fSignedDistance()
# ══════════════════════════════════════════════════════════════════════════

def sample_tpms_sdf(
    tpms_type: str,
    cell_size: float,
    iso_level: float,
    wall_thickness: float,
    bounds_x: float,
    bounds_y: float,
    bounds_z: float,
    resolution: int = 64,
) -> Tuple[np.ndarray, Tuple[float, float, float]]:
    """
    Sample a TPMS signed distance field on a regular 3-D grid.

    Parameters
    ----------
    tpms_type : str
        One of TPMS_TYPES.
    cell_size : float
        Unit cell size in mm (isotropic).
    iso_level : float
        Iso-level offset for network-solid mode (ignored when
        wall_thickness > 0).
    wall_thickness : float
        Half-thickness for sheet-solid mode; 0 → network solid.
    bounds_x, bounds_y, bounds_z : float
        Bounding box dimensions in mm.
    resolution : int
        Number of voxels along the longest axis; other axes are
        scaled proportionally.

    Returns
    -------
    sdf : np.ndarray, shape (Nx, Ny, Nz)
        Signed distance field (negative inside solid).
    spacing : (dx, dy, dz)
        Voxel spacing in mm.
    """
    tpms_type = tpms_type.lower()
    if tpms_type not in _RAW_FIELD:
        raise ValueError(
            f"Unknown TPMS type '{tpms_type}'. "
            f"Valid types: {TPMS_TYPES}"
        )

    raw_fn = _RAW_FIELD[tpms_type]

    # Build voxel grid
    max_dim = max(bounds_x, bounds_y, bounds_z)
    nx = max(4, int(resolution * bounds_x / max_dim))
    ny = max(4, int(resolution * bounds_y / max_dim))
    nz = max(4, int(resolution * bounds_z / max_dim))

    xs = np.linspace(0.0, bounds_x, nx)
    ys = np.linspace(0.0, bounds_y, ny)
    zs = np.linspace(0.0, bounds_z, nz)

    dx = bounds_x / (nx - 1) if nx > 1 else bounds_x
    dy = bounds_y / (ny - 1) if ny > 1 else bounds_y
    dz = bounds_z / (nz - 1) if nz > 1 else bounds_z

    # World → normalised cell-space (0..2π per cell), matching C# convention:
    #   tx = vec.X / cellSize.X * 2π
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    TWO_PI = 2.0 * math.pi
    TX = X / cell_size * TWO_PI
    TY = Y / cell_size * TWO_PI
    TZ = Z / cell_size * TWO_PI

    fval = raw_fn(TX, TY, TZ)

    if wall_thickness > 0.0:
        # Sheet-solid: |f| - wall_thickness
        sdf = np.abs(fval) - wall_thickness
    else:
        # Network solid: f - iso_level
        sdf = fval - iso_level

    return sdf, (dx, dy, dz)


# ══════════════════════════════════════════════════════════════════════════
# STL export via marching cubes
# ══════════════════════════════════════════════════════════════════════════

def sdf_to_stl(
    sdf: np.ndarray,
    spacing: Tuple[float, float, float],
    output_path: str,
    level: float = 0.0,
) -> dict:
    """
    Convert a signed distance field to an STL file using marching cubes.

    Requires scikit-image (preferred) for marching_cubes.

    Parameters
    ----------
    sdf : np.ndarray
        3-D signed distance field.
    spacing : (dx, dy, dz)
        Voxel spacing in mm.
    output_path : str
        Destination STL file path.
    level : float
        Iso-surface level (default 0.0).

    Returns
    -------
    dict with keys: vertex_count, face_count, stl_file
    """
    if not _HAVE_SKIMAGE:
        raise ImportError(
            "scikit-image is required for STL export. "
            "Install with: pip install scikit-image"
        )

    verts, faces, normals, _ = marching_cubes(
        sdf,
        level=level,
        spacing=spacing,
        allow_degenerate=False,
    )

    if _HAVE_TRIMESH:
        mesh = _trimesh.Trimesh(vertices=verts, faces=faces, vertex_normals=normals)
        mesh.export(output_path)
    else:
        _write_ascii_stl(verts, faces, normals, output_path)

    return {
        "vertex_count": int(len(verts)),
        "face_count": int(len(faces)),
        "stl_file": output_path,
    }


def _write_ascii_stl(
    verts: np.ndarray,
    faces: np.ndarray,
    normals: np.ndarray,
    path: str,
) -> None:
    """Minimal ASCII STL writer (fallback when trimesh not available)."""
    lines = ["solid tpms"]
    for i, face in enumerate(faces):
        n = normals[i] if i < len(normals) else np.array([0.0, 0.0, 1.0])
        v0, v1, v2 = verts[face[0]], verts[face[1]], verts[face[2]]
        lines.append(f"  facet normal {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}")
        lines.append("    outer loop")
        lines.append(f"      vertex {v0[0]:.6f} {v0[1]:.6f} {v0[2]:.6f}")
        lines.append(f"      vertex {v1[0]:.6f} {v1[1]:.6f} {v1[2]:.6f}")
        lines.append(f"      vertex {v2[0]:.6f} {v2[1]:.6f} {v2[2]:.6f}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append("endsolid tpms")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════
# High-level convenience function
# ══════════════════════════════════════════════════════════════════════════

def generate_tpms(
    tpms_type: str,
    cell_size: float,
    wall_thickness: float,
    iso_level: float,
    bounds_x: float,
    bounds_y: float,
    bounds_z: float,
    output_path: str,
    resolution: int = 64,
) -> dict:
    """
    Generate a TPMS structure and write it to an STL file.

    Returns a dict with geometry statistics compatible with the
    /generate/tpms endpoint response schema.
    """
    sdf, spacing = sample_tpms_sdf(
        tpms_type=tpms_type,
        cell_size=cell_size,
        iso_level=iso_level,
        wall_thickness=wall_thickness,
        bounds_x=bounds_x,
        bounds_y=bounds_y,
        bounds_z=bounds_z,
        resolution=resolution,
    )

    voxel_count = int(sdf.size)
    solid_voxels = int(np.sum(sdf <= 0.0))

    mesh_stats = sdf_to_stl(sdf, spacing, output_path)

    return {
        "status": "success",
        "tpms_type": tpms_type,
        "cell_size_mm": cell_size,
        "wall_thickness": wall_thickness,
        "iso_level": iso_level,
        "bounds": [bounds_x, bounds_y, bounds_z],
        "grid_resolution": [sdf.shape[0], sdf.shape[1], sdf.shape[2]],
        "voxel_count": voxel_count,
        "solid_voxels": solid_voxels,
        "volume_fraction": round(solid_voxels / max(voxel_count, 1), 4),
        **mesh_stats,
    }
