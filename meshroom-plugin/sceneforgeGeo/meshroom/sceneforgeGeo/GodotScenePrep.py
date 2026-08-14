__version__ = "0.1"

import os
import subprocess
from pathlib import Path

from meshroom.core import desc

_SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"


class GodotScenePrep(desc.Node):
    category = "SceneForge"
    documentation = """
Wrap a georeferenced mesh for Godot: lossless ENU-to-engine root transform
(Z-up to Y-up), ground rebase, and a scene.json GeoPose sidecar with the full
georeference. Output drops straight into the sceneforge walker's scenes folder.
Georef comes from a sidecar json (proj4 + utm_offset) or explicit parameters.
"""

    inputs = [
        desc.File(
            name="mesh",
            label="Mesh",
            description="Georeferenced mesh (glb/gltf/obj/ply), local metres.",
            value="",
        ),
        desc.File(
            name="sidecar",
            label="Georef Sidecar",
            description="Georef sidecar json (proj4 + utm_offset). If empty, <mesh>.json is tried, then the proj/offset parameters.",
            value="",
        ),
        desc.StringParam(
            name="proj",
            label="Proj4 CRS",
            description="Proj4 string of the mesh CRS (only needed without a sidecar).",
            value="",
        ),
        desc.FloatParam(
            name="offsetE",
            label="Offset East",
            description="Easting offset already subtracted from mesh coords (only needed without a sidecar).",
            value=0.0,
            range=(-100000000.0, 100000000.0, 1.0),
        ),
        desc.FloatParam(
            name="offsetN",
            label="Offset North",
            description="Northing offset already subtracted from mesh coords (only needed without a sidecar).",
            value=0.0,
            range=(-100000000.0, 100000000.0, 1.0),
        ),
        desc.StringParam(
            name="sceneName",
            label="Scene Name",
            description="Scene name (default: mesh filename stem).",
            value="",
        ),
        desc.BoolParam(
            name="yUp",
            label="Already Y-Up",
            description="Mesh is already Y-up; skip the Z-up rotation.",
            value=False,
        ),
        desc.StringParam(
            name="pythonBin",
            label="Python",
            description="Python interpreter with the sceneforge dependencies (pygltflib, pyproj).",
            value="python",
            advanced=True,
        ),
    ]

    outputs = [
        desc.File(
            name="output",
            label="Scene Folder",
            description="Folder holding <name>.glb + scene.json, ready for the walker.",
            value="{nodeCacheFolder}",
        ),
        desc.File(
            name="sceneJson",
            label="Scene JSON",
            description="GeoPose georef sidecar for the engine.",
            value="{nodeCacheFolder}/scene.json",
        ),
    ]

    def processChunk(self, chunk):
        try:
            chunk.logManager.start("info")
            n = chunk.node
            cmd = [
                n.pythonBin.value, str(_SCRIPTS / "prep_godot.py"),
                "--mesh", n.mesh.value,
                "-o", n.output.value,
            ]
            if n.sidecar.value:
                cmd += ["--sidecar", n.sidecar.value]
            if n.proj.value:
                cmd += ["--proj", n.proj.value,
                        "--offset", str(n.offsetE.value), str(n.offsetN.value)]
            if n.sceneName.value:
                cmd += ["--name", n.sceneName.value]
            if n.yUp.value:
                cmd += ["--y-up"]
            chunk.logger.info("run: %s", " ".join(cmd))
            # Meshroom's frozen runtime exports PYTHONHOME/PYTHONPATH pointing at its
            # own stdlib, which breaks any other Python it spawns - scrub them.
            env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
            proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
            if proc.stdout:
                chunk.logger.info(proc.stdout)
            if proc.returncode != 0:
                chunk.logger.error(proc.stderr)
                raise RuntimeError(f"prep_godot.py failed (exit {proc.returncode})")
            if proc.stderr:
                chunk.logger.warning(proc.stderr)
        finally:
            chunk.logManager.end()
