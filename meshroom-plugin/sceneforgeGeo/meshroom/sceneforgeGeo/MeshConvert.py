__version__ = "0.1"

import os
import subprocess
from pathlib import Path

from meshroom.core import desc

_SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"


class MeshConvert(desc.Node):
    category = "SceneForge"
    documentation = """
Convert a Meshroom textured OBJ into an engine-ready GLB: linear EXR textures
become sRGB JPG, the mesh is welded and simplified (gltf-transform), and the
result is a single self-contained glb sized for realtime walkers/VR.
Feed Texturing.outputMesh in; wire the glb to GodotScenePrep and/or BlenderScene.
"""

    inputs = [
        desc.File(
            name="mesh",
            label="Textured Mesh",
            description="Meshroom Texturing output (texturedMesh.obj).",
            value="",
        ),
        desc.StringParam(
            name="sceneName",
            label="Scene Name",
            description="Output glb name.",
            value="scene",
        ),
        desc.FloatParam(
            name="ratio",
            label="Simplify Ratio",
            description="Triangle keep-ratio for simplification (0 or 1 keeps full resolution).",
            value=0.35,
            range=(0.0, 1.0, 0.05),
        ),
        desc.IntParam(
            name="jpgQuality",
            label="JPEG Quality",
            description="Quality for the converted textures.",
            value=92,
            range=(50, 100, 1),
            advanced=True,
        ),
        desc.StringParam(
            name="pythonBin",
            label="Python",
            description="Python interpreter with the sceneforge dependencies (numpy, openexr, opencv, trimesh) plus npx on PATH.",
            value="python",
            advanced=True,
        ),
    ]

    outputs = [
        desc.File(
            name="output",
            label="GLB Folder",
            description="Folder holding the converted glb + convert_report.json.",
            value="{nodeCacheFolder}",
        ),
        desc.File(
            name="glb",
            label="GLB",
            description="Engine-ready glb.",
            value="{nodeCacheFolder}/{sceneNameValue}.glb",
        ),
    ]

    def processChunk(self, chunk):
        try:
            chunk.logManager.start("info")
            n = chunk.node
            name = n.sceneName.value or "scene"
            cmd = [
                n.pythonBin.value, str(_SCRIPTS / "mesh_convert.py"),
                "--mesh", n.mesh.value,
                "--out", n.output.value,
                "--name", name,
                "--ratio", str(n.ratio.value),
                "--jpg-quality", str(n.jpgQuality.value),
            ]
            chunk.logger.info("run: %s", " ".join(cmd))
            # Meshroom's frozen runtime exports PYTHONHOME/PYTHONPATH pointing at its
            # own stdlib, which breaks any other Python it spawns - scrub them.
            env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
            proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
            if proc.stdout:
                chunk.logger.info(proc.stdout)
            if proc.returncode != 0:
                chunk.logger.error(proc.stderr)
                raise RuntimeError(f"mesh_convert.py failed (exit {proc.returncode})")
            if proc.stderr:
                chunk.logger.warning(proc.stderr)
        finally:
            chunk.logManager.end()
