# ParaStell ARM64 Build Notes

## ARM64 Status: DEPENDENT ON DAGMC (complex)

ParaStell depends on CadQuery and DAGMC. CadQuery has ARM64 wheels; DAGMC is the challenge.

## DAGMC ARM64

DAGMC (Direct Accelerated Geometry Monte Carlo) requires MOAB and HDF5:
- MOAB: C++ library, must compile from source on ARM64
- HDF5: Available as Debian package `libhdf5-dev`

### Building DAGMC on ARM64
```bash
# Install MOAB first
git clone https://bitbucket.org/fathomteam/moab.git
cd moab
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release -DENABLE_HDF5=ON
make -j$(nproc) && make install

# Then build DAGMC
git clone https://github.com/svalinn/DAGMC.git
cd DAGMC && mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release -DMOAB_DIR=/usr/local
make -j$(nproc) && make install
```

### Build time: ~45 minutes on ARM64 Graviton3

## x86 Fallback

```dockerfile
FROM --platform=linux/amd64 python:3.11-slim
```

Or use the OpenMC Docker image which bundles DAGMC:
```bash
docker pull openmc/openmc:latest  # Includes DAGMC, MOAB
```

## pystell Dependency

`pystell` provides VMEC equilibrium parameterization for stellarator coil design.
It installs cleanly via pip on ARM64.

## Recommended Alternative: Conda Environment
```yaml
# conda-environment.yml
name: parastell
channels:
  - conda-forge
  - cadquery
dependencies:
  - python=3.11
  - cadquery
  - dagmc  # may not be available for ARM64 conda-forge
  - pystell
  - parastell
```

## References
- https://github.com/svalinn/parastell
- https://github.com/svalinn/DAGMC
- https://bitbucket.org/fathomteam/moab
