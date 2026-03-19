"""
picogk/scientific_implicits.py — Pure Python Scientific Implicit Functions

Mirrors the C# ScientificImplicits.cs from vpneoterra/PicoGK
(Extensions/ScientificImplicits/ScientificImplicits.cs).

Provides fusion-energy and scientific geometry implicit functions
as pure Python/NumPy signed distance field samplers with STL export.

Implemented primitives:
  - TorusImplicit       : standard torus (tokamak vacuum vessel shape)
  - DShapedPlasmaImplicit : D-shaped plasma cross-section (κ, δ parameterized)
  - ToroidalSectorImplicit: angular wedge of a torus (blanket module, TF coil)

References:
  Wesson, J. (2011). "Tokamaks," 4th ed., Oxford University Press.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

# ── Optional heavy deps (imported lazily) ─────────────────────────────────
try:
    from skimage.measure import marching_cubes
    _HAVE_SKIMAGE = True
except ImportError:
    _HAVE_SKIMAGE = False

try:
    import trimesh as _trimesh
    _HAVE_TRIMESH = True
except ImportError:
    _HAVE_TRIMESH = False


# ══════════════════════════════════════════════════════════════════════════
# Torus SDF — mirrors TorusImplicit.fSignedDistance() in ScientificImplicits.cs
# ══════════════════════════════════════════════════════════════════════════

def torus_sdf(
    X: np.ndarray,
    Y: np.ndarray,
    Z: np.ndarray,
    major_radius: float,
    minor_radius: float,
    center: Tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> np.ndarray:
    """
    Signed distance field for a torus aligned with the Z axis.

    f(x,y,z) = sqrt((sqrt(x²+y²) - R)² + z²) - r

    where R = major_radius, r = minor_radius.

    Matches TorusImplicit.fSignedDistance() with default Z-up axis
    and zero center offset.

    Parameters
    ----------
    X, Y, Z : np.ndarray
        Coordinate grids (e.g. from np.meshgrid).
    major_radius : float
        Distance from the torus axis to the tube centre (mm).
    minor_radius : float
        Tube radius (mm).
    center : (cx, cy, cz)
        World-space center of the torus.

    Returns
    -------
    np.ndarray
        Signed distance field (negative inside solid).
    """
    cx, cy, cz = center
    vx = X - cx
    vy = Y - cy
    vz = Z - cz

    # Radial distance from the Z axis in the XY plane
    radial = np.sqrt(vx * vx + vy * vy)

    # Distance from the torus tube centre
    q = radial - major_radius
    sdf = np.sqrt(q * q + vz * vz) - minor_radius
    return sdf


# ══════════════════════════════════════════════════════════════════════════
# D-shaped plasma SDF — mirrors DShapedPlasmaImplicit.fSignedDistance()
# ══════════════════════════════════════════════════════════════════════════

def d_shaped_plasma_sdf(
    X: np.ndarray,
    Y: np.ndarray,
    Z: np.ndarray,
    R0: float,
    minor_radius: float,
    elongation: float = 1.7,
    triangularity: float = 0.33,
    wall_thickness: float = 0.0,
) -> np.ndarray:
    """
    Signed distance field for a D-shaped plasma cross-section, toroidally
    symmetric around the Z axis.

    Parameterised by standard tokamak plasma shape descriptors:
      R0            — major radius (mm)
      minor_radius  — horizontal half-width a (mm)
      elongation κ  — vertical stretch (typically 1.4–1.9)
      triangularity δ — inboard point shift (typically 0.2–0.5)

    Matches DShapedPlasmaImplicit.fSignedDistance() in ScientificImplicits.cs.

    Parameters
    ----------
    X, Y, Z : np.ndarray
        Coordinate grids.
    R0 : float
        Major radius in mm.
    minor_radius : float
        Plasma minor radius a in mm.
    elongation : float
        Plasma elongation κ.
    triangularity : float
        Plasma triangularity δ.
    wall_thickness : float
        If > 0, creates a shell of this thickness around the plasma surface.

    Returns
    -------
    np.ndarray
        Signed distance field.
    """
    # Cylindrical coordinates: R = sqrt(x²+y²), Z = z
    R = np.sqrt(X * X + Y * Y)

    # Normalised coordinates relative to plasma centre
    r_norm = (R - R0) / minor_radius
    z_norm = Z / (minor_radius * elongation)

    # D-shape deformation via triangularity (matches C# implementation)
    r_adj = r_norm + triangularity * (1.0 - z_norm * z_norm)

    # Implicit function: unit circle in adjusted coordinates
    f_dist = r_adj * r_adj + z_norm * z_norm - 1.0

    # Scale back to mm (approximate characteristic length = minor_radius)
    sdf = f_dist * minor_radius * 0.5

    if wall_thickness > 0.0:
        return np.abs(sdf) - wall_thickness * 0.5

    return sdf


# ══════════════════════════════════════════════════════════════════════════
# Toroidal sector SDF — mirrors ToroidalSectorImplicit.fSignedDistance()
# ══════════════════════════════════════════════════════════════════════════

def toroidal_sector_sdf(
    X: np.ndarray,
    Y: np.ndarray,
    Z: np.ndarray,
    major_radius: float,
    minor_radius: float,
    start_angle_deg: float,
    end_angle_deg: float,
) -> np.ndarray:
    """
    Signed distance field for an angular wedge of a torus.

    Useful for modeling individual blanket modules, port cells, or
    toroidal field coil segments.

    Matches ToroidalSectorImplicit.fSignedDistance() in ScientificImplicits.cs.

    Parameters
    ----------
    X, Y, Z : np.ndarray
        Coordinate grids.
    major_radius : float
        Torus major radius (mm).
    minor_radius : float
        Torus minor radius (mm).
    start_angle_deg : float
        Start of angular wedge in degrees.
    end_angle_deg : float
        End of angular wedge in degrees.

    Returns
    -------
    np.ndarray
        Signed distance field.
    """
    # Base torus SDF
    torus = torus_sdf(X, Y, Z, major_radius, minor_radius)

    # Toroidal angle in [0, 2π]
    angle = np.arctan2(Y, X)
    angle = np.where(angle < 0, angle + 2.0 * math.pi, angle)

    start_rad = math.radians(start_angle_deg)
    end_rad = math.radians(end_angle_deg)

    # Approximate linear distance for angular half-planes
    R = np.sqrt(X * X + Y * Y)
    lin_dist1 = R * (angle - start_rad)
    lin_dist2 = R * (end_rad - angle)

    # Wedge SDF: outside the wedge is positive
    wedge = -np.minimum(lin_dist1, lin_dist2)

    # Intersection: inside both torus and wedge
    return np.maximum(torus, wedge)


# ══════════════════════════════════════════════════════════════════════════
# SDF sampling helpers
# ══════════════════════════════════════════════════════════════════════════

def _build_grid(
    bounds_x: float,
    bounds_y: float,
    bounds_z: float,
    resolution: int,
    center_at_origin: bool = True,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Tuple[float, float, float]]:
    """Build a coordinate meshgrid centred at the origin."""
    max_dim = max(bounds_x, bounds_y, bounds_z)
    nx = max(4, int(resolution * bounds_x / max_dim))
    ny = max(4, int(resolution * bounds_y / max_dim))
    nz = max(4, int(resolution * bounds_z / max_dim))

    if center_at_origin:
        xs = np.linspace(-bounds_x / 2.0, bounds_x / 2.0, nx)
        ys = np.linspace(-bounds_y / 2.0, bounds_y / 2.0, ny)
        zs = np.linspace(-bounds_z / 2.0, bounds_z / 2.0, nz)
    else:
        xs = np.linspace(0.0, bounds_x, nx)
        ys = np.linspace(0.0, bounds_y, ny)
        zs = np.linspace(0.0, bounds_z, nz)

    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")

    dx = bounds_x / (nx - 1) if nx > 1 else bounds_x
    dy = bounds_y / (ny - 1) if ny > 1 else bounds_y
    dz = bounds_z / (nz - 1) if nz > 1 else bounds_z

    return X, Y, Z, (dx, dy, dz)


def _sdf_to_stl(
    sdf: np.ndarray,
    spacing: Tuple[float, float, float],
    output_path: str,
    level: float = 0.0,
) -> dict:
    """Convert SDF to STL via marching cubes (same logic as tpms.py)."""
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
    lines = ["solid implicit"]
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
    lines.append("endsolid implicit")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════
# High-level generate functions
# ══════════════════════════════════════════════════════════════════════════

IMPLICIT_TYPES = ["torus", "d_shaped_plasma", "toroidal_sector"]


def generate_implicit(
    implicit_type: str,
    parameters: dict,
    bounds_x: float,
    bounds_y: float,
    bounds_z: float,
    output_path: str,
    resolution: int = 64,
) -> dict:
    """
    Generate geometry from a scientific implicit function and write to STL.

    Parameters
    ----------
    implicit_type : str
        One of: 'torus', 'd_shaped_plasma', 'toroidal_sector'
    parameters : dict
        Type-specific parameters (see individual SDF functions).
    bounds_x, bounds_y, bounds_z : float
        Bounding box size in mm (centred at origin).
    output_path : str
        Destination STL file path.
    resolution : int
        Voxel resolution along longest axis.

    Returns
    -------
    dict
        Geometry statistics.
    """
    implicit_type = implicit_type.lower()

    X, Y, Z, spacing = _build_grid(
        bounds_x, bounds_y, bounds_z, resolution, center_at_origin=True
    )

    if implicit_type == "torus":
        sdf = torus_sdf(
            X, Y, Z,
            major_radius=float(parameters.get("major_radius", 100.0)),
            minor_radius=float(parameters.get("minor_radius", 30.0)),
            center=(
                float(parameters.get("center_x", 0.0)),
                float(parameters.get("center_y", 0.0)),
                float(parameters.get("center_z", 0.0)),
            ),
        )

    elif implicit_type == "d_shaped_plasma":
        sdf = d_shaped_plasma_sdf(
            X, Y, Z,
            R0=float(parameters.get("R0", 100.0)),
            minor_radius=float(parameters.get("minor_radius", 30.0)),
            elongation=float(parameters.get("elongation", 1.7)),
            triangularity=float(parameters.get("triangularity", 0.33)),
            wall_thickness=float(parameters.get("wall_thickness", 0.0)),
        )

    elif implicit_type == "toroidal_sector":
        sdf = toroidal_sector_sdf(
            X, Y, Z,
            major_radius=float(parameters.get("major_radius", 100.0)),
            minor_radius=float(parameters.get("minor_radius", 30.0)),
            start_angle_deg=float(parameters.get("start_angle_deg", 0.0)),
            end_angle_deg=float(parameters.get("end_angle_deg", 90.0)),
        )

    else:
        raise ValueError(
            f"Unknown implicit_type '{implicit_type}'. "
            f"Valid types: {IMPLICIT_TYPES}"
        )

    voxel_count = int(sdf.size)
    solid_voxels = int(np.sum(sdf <= 0.0))

    mesh_stats = _sdf_to_stl(sdf, spacing, output_path)

    return {
        "status": "success",
        "implicit_type": implicit_type,
        "parameters": parameters,
        "bounds": [bounds_x, bounds_y, bounds_z],
        "grid_resolution": [sdf.shape[0], sdf.shape[1], sdf.shape[2]],
        "voxel_count": voxel_count,
        "solid_voxels": solid_voxels,
        **mesh_stats,
    }
