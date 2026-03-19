# PicoGK Repository Reference

**Source:** `vpneoterra/PicoGK` (GitHub)

This file documents that the TPMS (Triply Periodic Minimal Surface) and
Scientific Implicits implementations added to this cluster are derived from
the mathematical specifications in the PicoGK Extensions repository.

---

## Source Repository

| Field | Value |
|---|---|
| GitHub repo | `vpneoterra/PicoGK` |
| Language | C# / .NET |
| License | Apache-2.0 |

---

## Extensions Referenced

### Extensions/TPMS/TPMS_Implicits.cs

Source for the 7 TPMS implicit surface formulas implemented in
`picogk/tpms.py`.

The C# classes `Gyroid`, `SchwarzP`, `SchwarzD`, `Neovius`, `FischerKochS`,
`IWP`, and `Lidinoid` each implement a `fRawField(x, y, z)` method that
evaluates the periodic function in normalised cell-space coordinates
(scaled by `2π / cellSize`). The base class `TpmsImplicit.fSignedDistance()`
applies either:

- **Network solid mode** (`fWallThickness == 0`): `f(x) - isoLevel`
- **Sheet solid mode** (`fWallThickness > 0`): `|f(x)| - wallThickness`

The Python implementation in `picogk/tpms.py` mirrors this convention exactly
using NumPy broadcasting for vectorised SDF evaluation.

| C# Class | Python function | Formula |
|---|---|---|
| `Gyroid` | `_raw_gyroid` | `sin(x)cos(y) + sin(y)cos(z) + sin(z)cos(x)` |
| `SchwarzP` | `_raw_schwarz_p` | `cos(x) + cos(y) + cos(z)` |
| `SchwarzD` | `_raw_schwarz_d` | `sin(x)sin(y)sin(z) + sin(x)cos(y)cos(z) + cos(x)sin(y)cos(z) + cos(x)cos(y)sin(z)` |
| `Neovius` | `_raw_neovius` | `3(cos(x)+cos(y)+cos(z)) + 4cos(x)cos(y)cos(z)` |
| `FischerKochS` | `_raw_fischer_koch` | `cos(2x)sin(y)cos(z) + cos(x)cos(2y)sin(z) + sin(x)cos(y)cos(2z)` |
| `IWP` | `_raw_iwp` | `cos(x)cos(y) + cos(y)cos(z) + cos(z)cos(x) - cos(x)cos(y)cos(z)` |
| `Lidinoid` | `_raw_lidinoid` | `0.5[sin(2x)cos(y)sin(z)+sin(2y)cos(z)sin(x)+sin(2z)cos(x)sin(y)] - 0.5[cos(2x)cos(2y)+cos(2y)cos(2z)+cos(2z)cos(2x)] + 0.15` |

### Extensions/ScientificImplicits/ScientificImplicits.cs

Source for the fusion-energy geometry implicit functions implemented in
`picogk/scientific_implicits.py`.

| C# Class | Python function | Description |
|---|---|---|
| `TorusImplicit` | `torus_sdf` | `sqrt((sqrt(x²+y²)-R)²+z²) - r` |
| `DShapedPlasmaImplicit` | `d_shaped_plasma_sdf` | D-shaped tokamak plasma (κ, δ parameterised) |
| `ToroidalSectorImplicit` | `toroidal_sector_sdf` | Angular wedge of torus (blanket module / TF coil) |

---

## Why Pure Python (not C#)

The C# implementations require the .NET runtime and the native PicoGK bridge
library (`picogk.1.7.dylib` / `picogk.1.7.dll`). Neither is available in the
FORGE Docker containers. The Python re-implementations use NumPy for
vectorised SDF sampling and scikit-image marching cubes for STL export,
achieving the same mathematical results without any native dependencies.

---

## References

- Schoen, A.H. (1970). "Infinite periodic minimal surfaces without
  self-intersections." NASA Technical Note D-5541.
- Al-Ketan, O. & Abu Al-Rub, R.K. (2019). "Multifunctional mechanical
  metamaterials based on TPMS architectures." Adv. Eng. Mater.
- Wesson, J. (2011). "Tokamaks," 4th ed., Oxford University Press.
