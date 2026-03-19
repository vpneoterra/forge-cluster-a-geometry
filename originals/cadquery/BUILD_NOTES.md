# CadQuery ARM64 Build Notes

## ARM64 Status: SUPPORTED (with caveats)

CadQuery relies on `cadquery-ocp` (Open CASCADE Technology Python bindings). As of 2024,
ARM64 wheels are available on PyPI for both `cadquery` and `cadquery-ocp`.

## Known Issues

### OpenGL/Mesa
- Headless rendering requires `libgl1-mesa-glx` or `libgl1`.
- On ARM64 containers, use `DISPLAY=:99` with Xvfb if visual rendering is needed.
- For STEP/STL export (our use case), no display is required.

### OCC Version Compatibility
- `cadquery-ocp 7.7.x` maps to Open CASCADE 7.7.x.
- Do NOT mix cadquery and cadquery-ocp versions.

## x86 Fallback

If ARM64 wheels are unavailable for a specific version:

```dockerfile
FROM --platform=linux/amd64 python:3.11-slim
# Runs via QEMU emulation on ARM64 host
```

Or use conda:
```dockerfile
FROM condaforge/miniforge3:latest
RUN conda install -c conda-forge cadquery
```

## conda-forge Alternative (Most Reliable)
```dockerfile
FROM --platform=linux/arm64 condaforge/miniforge3
RUN conda install -c conda-forge -c cadquery cadquery=master
```

## References
- https://github.com/CadQuery/cadquery
- https://cadquery.readthedocs.io
- https://github.com/CadQuery/cadquery-ocp
