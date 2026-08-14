__version__ = "0.1"

import os
import subprocess
from pathlib import Path

from meshroom.core import desc

_SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"


class CollisionPrep(desc.Node):
    category = "SceneForge"
    documentation = """
Convex-decompose a visual mesh into physics-ready collision hulls with CoACD
(MIT). Outputs one glb with all hulls as separate meshes (Godot: one convex
shape per mesh) plus per-hull obj files (MuJoCo / obj2mjcf) and a manifest.

Meant for object-scale meshes — terrain wants a heightfield collider, so
decompose the props, not the site.
"""

    inputs = [
        desc.File(
            name="mesh",
            label="Mesh",
            description="Visual mesh to decompose (glb/obj/ply, non-Draco).",
            value="",
        ),
        desc.FloatParam(
            name="threshold",
            label="Concavity Threshold",
            description="CoACD concavity threshold; lower = more, tighter hulls.",
            value=0.05,
            range=(0.01, 1.0, 0.01),
        ),
        desc.IntParam(
            name="maxHulls",
            label="Max Hulls",
            description="Hard cap on the number of convex hulls.",
            value=64,
            range=(1, 512, 1),
        ),
        desc.IntParam(
            name="resolution",
            label="Sampling Resolution",
            description="CoACD sampling resolution.",
            value=2000,
            range=(500, 10000, 100),
        ),
        desc.StringParam(
            name="pythonBin",
            label="Python",
            description="Python interpreter with the sceneforge dependencies (coacd, trimesh).",
            value="python",
            advanced=True,
        ),
    ]

    outputs = [
        desc.File(
            name="collision",
            label="Collision GLB",
            description="All hulls as separate meshes in one scene.",
            value="{nodeCacheFolder}/collision_collision.glb",
        ),
        desc.File(
            name="hulls",
            label="Hull OBJs",
            description="Folder of per-hull obj files.",
            value="{nodeCacheFolder}/collision_hulls",
        ),
        desc.File(
            name="manifest",
            label="Manifest",
            description="Hull count, volumes, and parameters.",
            value="{nodeCacheFolder}/collision_manifest.json",
        ),
    ]

    def processChunk(self, chunk):
        try:
            chunk.logManager.start("info")
            n = chunk.node
            cmd = [
                n.pythonBin.value, str(_SCRIPTS / "collision_prep.py"),
                n.mesh.value,
                "-o", str(Path(n.collision.value).parent / "collision"),
                "--threshold", str(n.threshold.value),
                "--max-hulls", str(n.maxHulls.value),
                "--resolution", str(n.resolution.value),
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
                raise RuntimeError(f"collision_prep.py failed (exit {proc.returncode})")
            if proc.stderr:
                chunk.logger.warning(proc.stderr)
        finally:
            chunk.logManager.end()
