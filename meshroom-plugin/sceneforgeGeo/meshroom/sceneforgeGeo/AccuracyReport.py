__version__ = "0.1"

import os
import subprocess
from pathlib import Path

from meshroom.core import desc

_SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"


class AccuracyReport(desc.Node):
    category = "SceneForge"
    documentation = """
Grade a solve against surveyed ground control: triangulate every tagged GCP
from the solved camera poses and compare with its surveyed coordinates.
Reports per-point residuals, constraint/checkpoint horizontal RMSE, and flags
GCPs whose image tags are mutually inconsistent (bad clicks) or whose survey
coordinate disagrees with all tag sets. Constraint GCPs were in the solve, so
their residuals double as a sanity check on the projection math.

The solve source is an ODM run dir (cameras.json + odm_report/shots.geojson)
or an AliceVision sfmData json (cameras.sfm).
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
            description="Full gcp_list.txt with every tag, including held-out checkpoints.",
            value="",
        ),
        desc.StringParam(
            name="checkpoints",
            label="Checkpoints",
            description="Space-separated GCP names that were held out of the solve.",
            value="",
        ),
        desc.FloatParam(
            name="maxRayMiss",
            label="Max Ray Miss (m)",
            description="Flag GCPs whose tags disagree by more than this and drop them from the RMSE.",
            value=0.5,
            range=(0.01, 10.0, 0.01),
        ),
        desc.StringParam(
            name="pythonBin",
            label="Python",
            description="Python interpreter with the sceneforge dependencies (numpy).",
            value="python",
            advanced=True,
        ),
    ]

    outputs = [
        desc.File(
            name="residuals",
            label="Residuals JSON",
            description="Per-GCP residuals and tag-consistency data.",
            value="{nodeCacheFolder}/gcp_residuals.json",
        ),
        desc.File(
            name="report",
            label="Report",
            description="Human-readable residual table and RMSE summary.",
            value="{nodeCacheFolder}/report.txt",
        ),
    ]

    def processChunk(self, chunk):
        try:
            chunk.logManager.start("info")
            n = chunk.node
            cmd = [
                n.pythonBin.value, str(_SCRIPTS / "gcp_residuals.py"),
                n.solve.value,
                "--gcp", n.gcpList.value,
                "--max-ray-miss", str(n.maxRayMiss.value),
                "-o", n.residuals.value,
            ]
            if n.checkpoints.value.strip():
                cmd += ["--checkpoints"] + n.checkpoints.value.split()
            chunk.logger.info("run: %s", " ".join(cmd))
            # Meshroom's frozen runtime exports PYTHONHOME/PYTHONPATH pointing at its
            # own stdlib, which breaks any other Python it spawns - scrub them.
            env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
            proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
            if proc.stdout:
                chunk.logger.info(proc.stdout)
                Path(n.report.value).write_text(proc.stdout)
            if proc.returncode != 0:
                chunk.logger.error(proc.stderr)
                raise RuntimeError(f"gcp_residuals.py failed (exit {proc.returncode})")
            if proc.stderr:
                chunk.logger.warning(proc.stderr)
        finally:
            chunk.logManager.end()
