"""SceneForge scene importer for Blender.

Imports a sceneforge scene (scene.json + sibling glb) with real-world scale,
stores the georeference as custom properties, and adds a sun positioned
accurately for the scene's lat/lon at a chosen date/time.

Install: Edit > Preferences > Add-ons > Install from Disk > this file.
Use: File > Import > SceneForge Scene (scene.json).

Frame convention after import (Blender is Z-up; the glTF importer converts
the scene's Y-up glTF automatically):
    X = east, Y = north, Z = up, meters.
    utm_e = X + utm_offset[0];  utm_n = Y + utm_offset[1];  elev = Z + z_offset

Scriptable helpers: blender_to_utm(v, props) / utm_to_blender(e, n, elev, props),
solar_position(lat, lon, dt_utc).
"""
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bpy
from bpy.props import FloatProperty, StringProperty
from bpy_extras.io_utils import ImportHelper
from mathutils import Vector

bl_info = {
    "name": "SceneForge Scene Import",
    "author": "sceneforge",
    "version": (0, 1, 0),
    "blender": (4, 0, 0),
    "location": "File > Import > SceneForge Scene (scene.json)",
    "description": "Import georeferenced sceneforge scenes with accurate sun",
    "category": "Import-Export",
}


def solar_position(lat_deg, lon_deg, dt_utc):
    """Sun azimuth (deg from north, clockwise) and elevation (deg) via the
    compact NOAA-style algorithm; ~0.1 deg accuracy, plenty for lighting."""
    if dt_utc.tzinfo is not None:
        dt_utc = dt_utc.astimezone(timezone.utc).replace(tzinfo=None)
    d = (dt_utc - datetime(2000, 1, 1, 12)).total_seconds() / 86400.0
    g = math.radians((357.529 + 0.98560028 * d) % 360)  # mean anomaly
    q = (280.459 + 0.98564736 * d) % 360                # mean longitude
    L = math.radians(q + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    e = math.radians(23.439 - 0.00000036 * d)           # obliquity
    ra = math.degrees(math.atan2(math.cos(e) * math.sin(L), math.cos(L))) % 360
    dec = math.asin(math.sin(e) * math.sin(L))
    gmst = (18.697374558 + 24.06570982441908 * d) % 24
    ha = math.radians((gmst * 15 + lon_deg - ra + 540) % 360 - 180)
    lat = math.radians(lat_deg)
    elev = math.asin(math.sin(lat) * math.sin(dec)
                     + math.cos(lat) * math.cos(dec) * math.cos(ha))
    az = math.atan2(math.sin(ha),
                    math.cos(ha) * math.sin(lat) - math.tan(dec) * math.cos(lat))
    return (math.degrees(az) + 180.0) % 360.0, math.degrees(elev)


def sun_direction_enu(azimuth_deg, elevation_deg):
    """Unit vector pointing TOWARD the sun in X=east, Y=north, Z=up."""
    az, el = math.radians(azimuth_deg), math.radians(elevation_deg)
    return Vector((math.sin(az) * math.cos(el),
                   math.cos(az) * math.cos(el),
                   math.sin(el)))


def blender_to_utm(v, props):
    off = props["utm_offset"]
    return (v[0] + off[0], v[1] + off[1], v[2] + props["z_offset"])


def utm_to_blender(easting, northing, elev, props):
    off = props["utm_offset"]
    return Vector((easting - off[0], northing - off[1], elev - props["z_offset"]))


def load_scene(scene_json_path, dt_local=None, utc_offset_hours=-7.0):
    """Core import, usable headless. Returns (root_empty, sun_object)."""
    scene_json_path = Path(scene_json_path)
    meta = json.loads(scene_json_path.read_text(encoding="utf-8-sig"))
    glb = scene_json_path.parent / meta["source"]["asset"]
    if not glb.exists():
        # Older scene.json files recorded the pre-wrap input mesh name.
        fallback = scene_json_path.parent / f"{meta['name']}.glb"
        if not fallback.exists():
            raise FileNotFoundError(f"asset not found next to scene.json: {glb}")
        glb = fallback

    scn = bpy.context.scene
    scn.unit_settings.system = "METRIC"
    scn.unit_settings.scale_length = 1.0

    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    imported = [o for o in bpy.data.objects if o not in before]
    roots = [o for o in imported if o.parent is None or o.parent not in imported]

    root = bpy.data.objects.new(meta["name"], None)
    scn.collection.objects.link(root)
    for o in roots:
        o.parent = root

    root["sceneforge"] = json.dumps(meta)
    root["proj4"] = meta["crs"]["proj4"]
    root["utm_offset"] = list(meta["crs"]["utm_offset"])
    root["z_offset"] = float(meta["crs"]["z_offset"])
    pos = meta["origin_geopose"]["position"]
    root["origin_lat"], root["origin_lon"] = pos["lat"], pos["lon"]

    if dt_local is None:
        dt_local = datetime.now()
    dt_utc = dt_local - timedelta(hours=utc_offset_hours)
    az, el = solar_position(pos["lat"], pos["lon"], dt_utc)

    light = bpy.data.lights.new(f"{meta['name']}_sun", type="SUN")
    light.energy = 3.0 if el > 0 else 0.5
    sun = bpy.data.objects.new(f"{meta['name']}_sun", light)
    scn.collection.objects.link(sun)
    sun.parent = root
    sun.location = (0, 0, 50)
    # Sun lamp shines along its local -Z; aim +Z at the sun's sky position.
    sun.rotation_euler = sun_direction_enu(az, el).to_track_quat("Z", "Y").to_euler()
    sun["azimuth_deg"], sun["elevation_deg"] = az, el
    sun["datetime_local"] = dt_local.isoformat(timespec="minutes")
    return root, sun


class IMPORT_OT_sceneforge(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.sceneforge"
    bl_label = "Import SceneForge Scene"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})
    datetime_local: StringProperty(
        name="Local date/time", description="YYYY-MM-DD HH:MM at the scene",
        default=datetime.now().strftime("%Y-%m-%d %H:%M"))
    utc_offset: FloatProperty(
        name="UTC offset (h)", description="Local timezone offset from UTC",
        default=-7.0, min=-12.0, max=14.0)

    def execute(self, context):
        try:
            dt = datetime.strptime(self.datetime_local, "%Y-%m-%d %H:%M")
        except ValueError:
            self.report({"ERROR"}, "Date/time must be YYYY-MM-DD HH:MM")
            return {"CANCELLED"}
        try:
            root, sun = load_scene(self.filepath, dt, self.utc_offset)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"},
                    f"{root.name}: sun az {sun['azimuth_deg']:.1f} deg, "
                    f"el {sun['elevation_deg']:.1f} deg")
        return {"FINISHED"}


def menu_func(self, context):
    self.layout.operator(IMPORT_OT_sceneforge.bl_idname,
                         text="SceneForge Scene (scene.json)")


def register():
    bpy.utils.register_class(IMPORT_OT_sceneforge)
    bpy.types.TOPBAR_MT_file_import.append(menu_func)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func)
    bpy.utils.unregister_class(IMPORT_OT_sceneforge)


if __name__ == "__main__":
    register()
