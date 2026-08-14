__version__ = "0.1"

import os
import subprocess
from pathlib import Path

from meshroom.core import desc

_SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"


class RtlToUtmGeotiff(desc.Node):
    category = "SceneForge"
    documentation = """
Convert a MicMac RTL-frame raster (ortho or DSM) to a UTM GeoTIFF using the
RTLFromExif.xml local-frame definition. Writes a georef sidecar json with
EPSG, GSD and the affine fit residual.
"""

    inputs = [
        desc.File(
            name="raster",
            label="MicMac Raster",
            description="MicMac raster (stub or monolithic .tif, .tfw beside it).",
            value="",
        ),
        desc.File(
            name="rtl",
            label="RTLFromExif.xml",
            description="MicMac RTL definition (Ori-RTLFromExif/RTLFromExif.xml).",
            value="",
        ),
        desc.BoolParam(
            name="addOriginAlt",
            label="Add Origin Altitude",
            description="Add the RTL origin altitude to pixel values (for DSMs; leave off for imagery).",
            value=False,
        ),
        desc.StringParam(
            name="pythonBin",
            label="Python",
            description="Python interpreter with the sceneforge dependencies (rasterio, pyproj).",
            value="python",
            advanced=True,
        ),
    ]

    outputs = [
        desc.File(
            name="output",
            label="UTM GeoTIFF",
            description="Georeferenced GeoTIFF in the local UTM zone.",
            value="{nodeCacheFolder}/utm.tif",
        ),
        desc.File(
            name="sidecar",
            label="Georef Sidecar",
            description="Sidecar json with EPSG, GSD and fit residual.",
            value="{nodeCacheFolder}/utm.json",
        ),
    ]

    def processChunk(self, chunk):
        try:
            chunk.logManager.start("info")
            n = chunk.node
            cmd = [
                n.pythonBin.value, str(_SCRIPTS / "rtl_to_utm_geotiff.py"),
                n.raster.value,
                "--rtl", n.rtl.value,
                "-o", n.output.value,
            ]
            if n.addOriginAlt.value:
                cmd += ["--add-origin-alt"]
            chunk.logger.info("run: %s", " ".join(cmd))
            # Meshroom's frozen runtime exports PYTHONHOME/PYTHONPATH pointing at its
            # own stdlib, which breaks any other Python it spawns - scrub them.
            env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
            proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
            if proc.stdout:
                chunk.logger.info(proc.stdout)
            if proc.returncode != 0:
                chunk.logger.error(proc.stderr)
                raise RuntimeError(f"rtl_to_utm_geotiff.py failed (exit {proc.returncode})")
            if proc.stderr:
                chunk.logger.warning(proc.stderr)
        finally:
            chunk.logManager.end()
