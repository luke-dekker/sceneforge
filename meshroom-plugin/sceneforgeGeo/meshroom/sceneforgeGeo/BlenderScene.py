__version__ = "0.1"

import os
import subprocess
from pathlib import Path

from meshroom.core import desc

_SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"


class BlenderScene(desc.Node):
    category = "SceneForge"
    documentation = """
Build a Blender project from a sceneforge scene (GodotScenePrep output):
imports the glb at real-world scale with the georef stored as custom
properties, adds a physically-placed sun + sky for the scene's lat/lon at a
chosen local time, and saves a ready-to-open .blend. Optionally renders an
auto-framed descending-orbit flythrough mp4 (Eevee).
Requires a Blender install (4.x/5.x); newest found is used unless set.
"""

    inputs = [
        desc.File(
            name="sceneJson",
            label="Scene JSON",
            description="scene.json from GodotScenePrep (glb expected alongside).",
            value="",
        ),
        desc.StringParam(
            name="dateTime",
            label="Local Date/Time",
            description="Sun position time, 'YYYY-MM-DD HH:MM' local (empty = now).",
            value="",
        ),
        desc.FloatParam(
            name="utcOffset",
            label="UTC Offset (h)",
            description="Local timezone offset from UTC at the scene.",
            value=-7.0,
            range=(-12.0, 14.0, 0.5),
        ),
        desc.BoolParam(
            name="renderFlythrough",
            label="Render Flythrough",
            description="Also render an auto-framed orbit flythrough mp4.",
            value=False,
        ),
        desc.FloatParam(
            name="seconds",
            label="Flythrough Seconds",
            description="Flythrough duration.",
            value=12.0,
            range=(2.0, 120.0, 1.0),
            advanced=True,
        ),
        desc.StringParam(
            name="resolution",
            label="Resolution",
            description="Render resolution WxH.",
            value="1920x1080",
            advanced=True,
        ),
        desc.StringParam(
            name="blenderBin",
            label="Blender",
            description="Path to blender.exe (empty = newest installed).",
            value="",
            advanced=True,
        ),
        desc.StringParam(
            name="pythonBin",
            label="Python",
            description="Python interpreter for the launcher script.",
            value="python",
            advanced=True,
        ),
    ]

    outputs = [
        desc.File(
            name="output",
            label="Blender Folder",
            description="Folder holding the .blend (and flythrough mp4 if rendered).",
            value="{nodeCacheFolder}",
        ),
    ]

    def processChunk(self, chunk):
        try:
            chunk.logManager.start("info")
            n = chunk.node
            cmd = [
                n.pythonBin.value, str(_SCRIPTS / "blender_scene.py"),
                "--scene-json", n.sceneJson.value,
                "--out", n.output.value,
                "--utc-offset", str(n.utcOffset.value),
                "--seconds", str(n.seconds.value),
                "--res", n.resolution.value,
            ]
            if n.dateTime.value:
                cmd += ["--datetime", n.dateTime.value]
            if n.renderFlythrough.value:
                cmd += ["--render"]
            if n.blenderBin.value:
                cmd += ["--blender", n.blenderBin.value]
            chunk.logger.info("run: %s", " ".join(cmd))
            # Meshroom's frozen runtime exports PYTHONHOME/PYTHONPATH pointing at its
            # own stdlib, which breaks any other Python it spawns - scrub them.
            env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
            proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
            if proc.stdout:
                chunk.logger.info(proc.stdout)
            if proc.returncode != 0:
                chunk.logger.error(proc.stderr)
                raise RuntimeError(f"blender_scene.py failed (exit {proc.returncode})")
            if proc.stderr:
                chunk.logger.warning(proc.stderr)
        finally:
            chunk.logManager.end()
