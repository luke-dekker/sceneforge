__version__ = "0.1"

import os
import subprocess
from pathlib import Path

from meshroom.core import desc

# meshroom-plugin/sceneforgeGeo/meshroom/sceneforgeGeo/<this file> -> repo root
_SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"


class HeightfieldScene(desc.Node):
    category = "SceneForge"
    documentation = """
Bake a walkable heightfield GLB from a DSM + orthomosaic GeoTIFF pair.
Terrain-only geometry draped with the orthophoto — the fast path from a
flight to a scene. Writes a georef sidecar json (proj4 + utm_offset) that
GodotScenePrep consumes directly.
"""

    inputs = [
        desc.File(
            name="dsm",
            label="DSM GeoTIFF",
            description="Digital surface model raster, heights in metres.",
            value="",
        ),
        desc.File(
            name="ortho",
            label="Orthomosaic GeoTIFF",
            description="Orthomosaic covering the same extent as the DSM.",
            value="",
        ),
        desc.File(
            name="mask",
            label="Validity Mask",
            description="Optional validity mask raster (e.g. MicMac Masq_*.tif), same grid as the DSM.",
            value="",
        ),
        desc.IntParam(
            name="grid",
            label="Max Grid Dimension",
            description="Maximum heightfield grid dimension in vertices.",
            value=1000,
            range=(64, 8000, 50),
        ),
        desc.IntParam(
            name="tex",
            label="Max Texture Dimension",
            description="Maximum texture dimension in pixels.",
            value=8192,
            range=(512, 16384, 512),
        ),
        desc.StringParam(
            name="pythonBin",
            label="Python",
            description="Python interpreter with the sceneforge dependencies (rasterio, trimesh, scipy).",
            value="python",
            advanced=True,
        ),
    ]

    outputs = [
        desc.File(
            name="output",
            label="Scene GLB",
            description="Walkable heightfield mesh, local metres, Z-up.",
            value="{nodeCacheFolder}/heightfield.glb",
        ),
        desc.File(
            name="sidecar",
            label="Georef Sidecar",
            description="Georeference sidecar json (proj4 + utm_offset).",
            value="{nodeCacheFolder}/heightfield.json",
        ),
    ]

    def processChunk(self, chunk):
        try:
            chunk.logManager.start("info")
            n = chunk.node
            cmd = [
                n.pythonBin.value, str(_SCRIPTS / "heightfield_glb.py"),
                n.dsm.value, n.ortho.value,
                "-o", n.output.value,
                "--grid", str(n.grid.value),
                "--tex", str(n.tex.value),
            ]
            if n.mask.value:
                cmd += ["--mask", n.mask.value]
            chunk.logger.info("run: %s", " ".join(cmd))
            # Meshroom's frozen runtime exports PYTHONHOME/PYTHONPATH pointing at its
            # own stdlib, which breaks any other Python it spawns - scrub them.
            env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
            proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
            if proc.stdout:
                chunk.logger.info(proc.stdout)
            if proc.returncode != 0:
                chunk.logger.error(proc.stderr)
                raise RuntimeError(f"heightfield_glb.py failed (exit {proc.returncode})")
            if proc.stderr:
                chunk.logger.warning(proc.stderr)
        finally:
            chunk.logManager.end()
