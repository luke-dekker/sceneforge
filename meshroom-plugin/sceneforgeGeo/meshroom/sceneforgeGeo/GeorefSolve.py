__version__ = "0.1"

import os
import subprocess
from pathlib import Path

from meshroom.core import desc

_SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"


class GeorefSolve(desc.Node):
    category = "SceneForge"
    documentation = """
Georeference a solve from ground control: triangulate the tagged GCPs from
the solved camera poses, fit a 7-DOF similarity (scale/rotation/translation)
onto the surveyed coordinates with a local origin offset, and optionally
apply it to a mesh. Held-out checkpoints are excluded from the fit and
reported after transformation — that number is the honest accuracy.

Remember the shape caveat: this anchors pose, not shape. A domed
reconstruction stays domed (the fit absorbs the rigid tilt only) — see
docs/doming-investigation.md for the capture doctrine that actually fixes it.
"""

    inputs = [
        desc.File(
            name="solve",
            label="Solve",
            description="ODM run dir or AliceVision cameras.sfm.",
            value="",
        ),
        desc.File(
            name="gcpList",
            label="GCP List",
            description="gcp_list.txt (proj4 header + rows).",
            value="",
        ),
        desc.File(
            name="mesh",
            label="Mesh To Transform",
            description="Optional mesh to carry into the georeferenced local frame (glb/obj/ply, non-Draco).",
            value="",
        ),
        desc.StringParam(
            name="checkpoints",
            label="Checkpoints",
            description="Space-separated GCP names held out of the fit.",
            value="",
        ),
        desc.FloatParam(
            name="maxRayMiss",
            label="Max Ray Miss (m)",
            description="Drop GCPs whose tags disagree by more than this.",
            value=0.5,
            range=(0.01, 10.0, 0.01),
        ),
        desc.StringParam(
            name="pythonBin",
            label="Python",
            description="Python interpreter with the sceneforge dependencies (numpy, trimesh).",
            value="python",
            advanced=True,
        ),
    ]

    outputs = [
        desc.File(
            name="output",
            label="Output Folder",
            description="Folder holding georef_transform.json and any transformed mesh.",
            value="{nodeCacheFolder}",
        ),
        desc.File(
            name="transform",
            label="Transform JSON",
            description="Similarity transform + residual report.",
            value="{nodeCacheFolder}/georef_transform.json",
        ),
        desc.File(
            name="geoMesh",
            label="Georeferenced Mesh",
            description="Transformed mesh (only when a mesh input is given).",
            value=lambda attr: "{nodeCacheFolder}/" + (
                Path(attr.node.mesh.value).stem + "_geo.glb" if attr.node.mesh.value else ""),
        ),
        desc.File(
            name="sidecar",
            label="Georef Sidecar",
            description="proj4 + utm_offset sidecar for the transformed mesh.",
            value=lambda attr: "{nodeCacheFolder}/" + (
                Path(attr.node.mesh.value).stem + "_geo.json" if attr.node.mesh.value else ""),
        ),
    ]

    def processChunk(self, chunk):
        try:
            chunk.logManager.start("info")
            n = chunk.node
            cmd = [
                n.pythonBin.value, str(_SCRIPTS / "georef_solve.py"),
                n.solve.value,
                "--gcp", n.gcpList.value,
                "--max-ray-miss", str(n.maxRayMiss.value),
                "-o", n.output.value,
            ]
            if n.checkpoints.value.strip():
                cmd += ["--checkpoints"] + n.checkpoints.value.split()
            if n.mesh.value:
                cmd += ["--apply", n.mesh.value]
            chunk.logger.info("run: %s", " ".join(cmd))
            # Meshroom's frozen runtime exports PYTHONHOME/PYTHONPATH pointing at its
            # own stdlib, which breaks any other Python it spawns - scrub them.
            env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
            proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
            if proc.stdout:
                chunk.logger.info(proc.stdout)
            if proc.returncode != 0:
                chunk.logger.error(proc.stderr)
                raise RuntimeError(f"georef_solve.py failed (exit {proc.returncode})")
            if proc.stderr:
                chunk.logger.warning(proc.stderr)
        finally:
            chunk.logManager.end()
