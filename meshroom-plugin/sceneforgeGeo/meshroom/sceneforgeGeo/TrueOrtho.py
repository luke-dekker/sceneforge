__version__ = "0.1"

import os
import subprocess
from pathlib import Path

from meshroom.core import desc

_SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"


class TrueOrtho(desc.Node):
    category = "SceneForge"
    documentation = """
True orthophoto + DSM rendered straight from the textured mesh with a
per-pixel z-buffer — buildings and trees keep their footprints instead of
smearing, and the ortho reflects whatever mesh you consider final (e.g. the
GeorefSolve output). Both GeoTIFFs carry full CRS coordinates and open
directly in QGIS. Placement comes from the mesh's georef sidecar json.
"""

    inputs = [
        desc.File(
            name="mesh",
            label="Mesh",
            description="Textured georeferenced mesh, local metres, Z-up (glb/obj, non-Draco).",
            value="",
        ),
        desc.File(
            name="sidecar",
            label="Georef Sidecar",
            description="Georef sidecar json (proj4 + utm_offset). If empty, <mesh>.json is used.",
            value="",
        ),
        desc.FloatParam(
            name="gsd",
            label="GSD (m/px)",
            description="Ground sample distance of the output rasters.",
            value=0.10,
            range=(0.01, 5.0, 0.01),
        ),
        desc.IntParam(
            name="maxDim",
            label="Max Raster Dimension",
            description="Refuse rasters larger than this (raise GSD instead).",
            value=16384,
            range=(1024, 65536, 1024),
        ),
        desc.StringParam(
            name="pythonBin",
            label="Python",
            description="Python interpreter with the sceneforge dependencies (numpy, rasterio, trimesh).",
            value="python",
            advanced=True,
        ),
    ]

    outputs = [
        desc.File(
            name="ortho",
            label="True Ortho GeoTIFF",
            description="RGBA orthophoto in the site CRS.",
            value="{nodeCacheFolder}/ortho.tif",
        ),
        desc.File(
            name="dsm",
            label="DSM GeoTIFF",
            description="Digital surface model from the same z-buffer.",
            value="{nodeCacheFolder}/ortho_dsm.tif",
        ),
        desc.File(
            name="sidecarOut",
            label="Raster Sidecar",
            description="Raster georef summary json.",
            value="{nodeCacheFolder}/ortho.json",
        ),
    ]

    def processChunk(self, chunk):
        try:
            chunk.logManager.start("info")
            n = chunk.node
            cmd = [
                n.pythonBin.value, str(_SCRIPTS / "true_ortho.py"),
                n.mesh.value,
                "--gsd", str(n.gsd.value),
                "--max-dim", str(n.maxDim.value),
                "-o", str(Path(n.ortho.value).with_suffix("")),
            ]
            if n.sidecar.value:
                cmd += ["--sidecar", n.sidecar.value]
            chunk.logger.info("run: %s", " ".join(cmd))
            # Meshroom's frozen runtime exports PYTHONHOME/PYTHONPATH pointing at its
            # own stdlib, which breaks any other Python it spawns - scrub them.
            env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
            proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
            if proc.stdout:
                chunk.logger.info(proc.stdout)
            if proc.returncode != 0:
                chunk.logger.error(proc.stderr)
                raise RuntimeError(f"true_ortho.py failed (exit {proc.returncode})")
            if proc.stderr:
                chunk.logger.warning(proc.stderr)
        finally:
            chunk.logManager.end()
