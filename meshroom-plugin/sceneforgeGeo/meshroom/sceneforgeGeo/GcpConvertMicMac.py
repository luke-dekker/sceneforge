__version__ = "0.1"

import os
import subprocess
from pathlib import Path

from meshroom.core import desc

_SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"


class GcpConvertMicMac(desc.Node):
    category = "SceneForge"
    documentation = """
Convert an ODM gcp_list.txt into MicMac DicoAppuisFlottant +
SetOfMesureAppuisFlottants XML, with an optional held-out checkpoint split
and automatic local-origin offset (raw UTM coordinates make MicMac's solver
go singular). Pass sigma=1 to Campari — the per-point uncertainty lives in
the XML and Campari multiplies the two.
"""

    inputs = [
        desc.File(
            name="gcpList",
            label="GCP List",
            description="ODM gcp_list.txt (proj4 header + rows).",
            value="",
        ),
        desc.StringParam(
            name="checkpoints",
            label="Checkpoints",
            description="Space-separated point names held out of the solve (written as -Ctrl pair).",
            value="",
        ),
        desc.FloatParam(
            name="sigmaXy",
            label="Sigma XY",
            description="Horizontal uncertainty in ground units.",
            value=0.02,
            range=(0.001, 10.0, 0.001),
        ),
        desc.FloatParam(
            name="sigmaZ",
            label="Sigma Z",
            description="Vertical uncertainty in ground units.",
            value=0.04,
            range=(0.001, 10.0, 0.001),
        ),
        desc.BoolParam(
            name="noOffset",
            label="Keep Raw Coordinates",
            description="Skip the local-origin offset (NOT recommended for UTM coords — singular solves).",
            value=False,
        ),
        desc.StringParam(
            name="pythonBin",
            label="Python",
            description="Python interpreter with the sceneforge dependencies.",
            value="python",
            advanced=True,
        ),
    ]

    outputs = [
        desc.File(
            name="output",
            label="Output Folder",
            description="Folder holding the generated MicMac XML files and CRS sidecar (stem 'gcp').",
            value="{nodeCacheFolder}",
        ),
    ]

    def processChunk(self, chunk):
        try:
            chunk.logManager.start("info")
            n = chunk.node
            cmd = [
                n.pythonBin.value, str(_SCRIPTS / "gcp_to_micmac.py"),
                n.gcpList.value,
                "-o", str(Path(n.output.value) / "gcp"),
                "--sigma-xy", str(n.sigmaXy.value),
                "--sigma-z", str(n.sigmaZ.value),
            ]
            if n.checkpoints.value.strip():
                cmd += ["--checkpoints"] + n.checkpoints.value.split()
            if n.noOffset.value:
                cmd += ["--no-offset"]
            chunk.logger.info("run: %s", " ".join(cmd))
            # Meshroom's frozen runtime exports PYTHONHOME/PYTHONPATH pointing at its
            # own stdlib, which breaks any other Python it spawns - scrub them.
            env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
            proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
            if proc.stdout:
                chunk.logger.info(proc.stdout)
            if proc.returncode != 0:
                chunk.logger.error(proc.stderr)
                raise RuntimeError(f"gcp_to_micmac.py failed (exit {proc.returncode})")
            if proc.stderr:
                chunk.logger.warning(proc.stderr)
        finally:
            chunk.logManager.end()
