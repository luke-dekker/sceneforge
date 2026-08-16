"""Build a Blender project from a sceneforge scene, headless.

Runs INSIDE Blender:
  blender --background --python sceneforge_blend.py -- \
      --scene-json <scene.json> --out-blend <out.blend> \
      [--datetime "YYYY-MM-DD HH:MM"] [--utc-offset -7] \
      [--render <out.mp4> --seconds 12 --fps 24 --res 1920x1080 --samples 32]

Imports the scene with the sceneforge_import addon (real scale, georef props,
accurate sun), adds a sky, saves a .blend, and optionally renders an
auto-framed descending orbit flythrough. Version-tolerant across the
Blender 4.x -> 5.x enum renames (sky model, Eevee engine, video output).
"""
import argparse
import math
import sys
from datetime import datetime
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sceneforge_import as sf


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene-json", required=True)
    ap.add_argument("--out-blend", required=True)
    ap.add_argument("--datetime", default=None, help="local YYYY-MM-DD HH:MM")
    ap.add_argument("--utc-offset", type=float, default=-7.0)
    ap.add_argument("--render", default=None, help="flythrough mp4 path")
    ap.add_argument("--seconds", type=float, default=12.0)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--res", default="1920x1080")
    ap.add_argument("--samples", type=int, default=32)
    ap.add_argument("--orbit-degrees", type=float, default=300.0)
    return ap.parse_args(argv)


def add_sky(scn, sun):
    world = bpy.data.worlds.new("sceneforge_sky")
    scn.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    sky = nt.nodes.new("ShaderNodeTexSky")
    for wanted in ("MULTIPLE_SCATTERING", "NISHITA", "HOSEK_WILKIE"):
        if wanted in sky.bl_rna.properties["sky_type"].enum_items.keys():
            sky.sky_type = wanted
            break
    if hasattr(sky, "sun_disc"):
        sky.sun_disc = False  # the sun lamp does the lighting
    if hasattr(sky, "sun_elevation"):
        sky.sun_elevation = math.radians(sun["elevation_deg"])
        sky.sun_rotation = math.radians(-sun["azimuth_deg"])
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = 0.6
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])


def scene_bounds():
    lo = Vector((1e18, 1e18, 1e18))
    hi = -lo
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        for corner in o.bound_box:
            w = o.matrix_world @ Vector(corner)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    return lo, hi


def add_flythrough_camera(scn, seconds, fps, orbit_degrees):
    lo, hi = scene_bounds()
    center = (lo + hi) / 2
    extent = max(hi.x - lo.x, hi.y - lo.y)
    target = bpy.data.objects.new("flythrough_target", None)
    target.location = (center.x, center.y, lo.z + 0.25 * (hi.z - lo.z))
    scn.collection.objects.link(target)

    cam_data = bpy.data.cameras.new("flythrough_cam")
    cam_data.lens = 28
    cam_data.clip_end = max(2000.0, extent * 6)
    cam = bpy.data.objects.new("flythrough_cam", cam_data)
    scn.collection.objects.link(cam)
    scn.camera = cam
    track = cam.constraints.new(type="TRACK_TO")
    track.target = target
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"

    frames = max(int(fps * seconds), 2)
    scn.frame_start, scn.frame_end = 1, frames
    scn.render.fps = fps
    r_far, r_near = 0.65 * extent, 0.42 * extent
    h_hi, h_lo = 0.30 * extent, 0.13 * extent
    for f in range(1, frames + 1, 8):
        t = (f - 1) / (frames - 1)
        ang = math.radians(210 + orbit_degrees * t)
        r = r_far + (r_near - r_far) * t
        h = h_hi + (h_lo - h_hi) * (0.5 - 0.5 * math.cos(math.pi * t))
        cam.location = (center.x + r * math.cos(ang),
                        center.y + r * math.sin(ang), h)
        cam.keyframe_insert("location", frame=f)


def setup_render(scn, res, samples, mp4_path):
    engines = scn.render.bl_rna.properties["engine"].enum_items.keys()
    scn.render.engine = ("BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines
                         else "BLENDER_EEVEE")
    w, h = (int(v) for v in res.lower().split("x"))
    scn.render.resolution_x, scn.render.resolution_y = w, h
    if hasattr(scn, "eevee") and hasattr(scn.eevee, "taa_render_samples"):
        scn.eevee.taa_render_samples = samples
    # Photogrammetry textures carry baked real-world light; AgX washes them out.
    scn.view_settings.view_transform = "Standard"
    img = scn.render.image_settings
    if hasattr(img, "media_type"):  # Blender 5.x gate for video formats
        img.media_type = "VIDEO"
    if "FFMPEG" in img.bl_rna.properties["file_format"].enum_items.keys():
        img.file_format = "FFMPEG"
        scn.render.ffmpeg.format = "MPEG4"
        scn.render.ffmpeg.codec = "H264"
        scn.render.ffmpeg.constant_rate_factor = "HIGH"
        scn.render.filepath = mp4_path
        return True
    print("WARNING: no FFMPEG output in this Blender; rendering PNG frames")
    img.file_format = "PNG"
    scn.render.filepath = str(Path(mp4_path).with_suffix("")) + "_f_"
    return False


def main():
    args = parse_args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    dt = (datetime.strptime(args.datetime, "%Y-%m-%d %H:%M")
          if args.datetime else datetime.now())
    root, sun = sf.load_scene(args.scene_json, dt, args.utc_offset)
    print(f"imported {root.name}: sun az {sun['azimuth_deg']:.1f} "
          f"el {sun['elevation_deg']:.1f}")
    scn = bpy.context.scene
    add_sky(scn, sun)
    add_flythrough_camera(scn, args.seconds, args.fps, args.orbit_degrees)

    Path(args.out_blend).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.out_blend))
    print("saved", args.out_blend)

    if args.render:
        setup_render(scn, args.res, args.samples, args.render)
        Path(args.render).parent.mkdir(parents=True, exist_ok=True)
        print(f"rendering {scn.frame_end} frames...")
        bpy.ops.render.render(animation=True)
        print("rendered", args.render)


if __name__ == "__main__":
    main()
