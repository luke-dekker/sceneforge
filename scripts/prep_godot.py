"""Prepare an ODM run for Godot: wrap the geo glb in an ENU->engine transform
and emit a scene.json georef sidecar.

The ODM *_geo.glb is local-ENU (UTM minus the coords.txt offset), Z-up, meters.
Godot/glTF want Y-up. We add a lossless root-node transform (east->X, up->Y,
north->-Z) plus a vertical rebase so the ground sits near Y=0; the full
georeference, including the removed elevation, goes in scene.json.

Usage: python scripts/prep_godot.py runs/aukerman-smoke [-o godot/scenes/aukerman]
"""
import argparse
import json
import subprocess
from pathlib import Path

from pygltflib import GLTF2, Node, Scene
from pyproj import CRS, Transformer


def ensure_uncompressed(glb_path: Path) -> Path:
    """ODM writes Draco-compressed glbs; Godot's importer can't read Draco.
    Decode once via gltf-transform and cache the result next to the source."""
    gltf = GLTF2().load_binary(str(glb_path))
    if "KHR_draco_mesh_compression" not in (gltf.extensionsRequired or []):
        return glb_path
    decoded = glb_path.with_name(glb_path.stem + "_decoded.glb")
    if not decoded.exists():
        subprocess.run(["npx", "--yes", "@gltf-transform/cli", "copy",
                        str(glb_path), str(decoded)], check=True, shell=True)
    return decoded


def read_coords(run_dir: Path):
    lines = (run_dir / "odm_georeferencing" / "coords.txt").read_text().splitlines()
    proj = (run_dir / "odm_georeferencing" / "proj.txt").read_text().strip()
    east_off, north_off = (float(v) for v in lines[1].split())
    return proj, east_off, north_off


def bounds(gltf: GLTF2):
    """Per-axis (min, max) over every primitive's POSITION accessor."""
    lo, hi = [], []
    for mesh in gltf.meshes:
        for prim in mesh.primitives:
            acc = gltf.accessors[prim.attributes.POSITION]
            if acc.min and acc.max:
                lo.append(acc.min)
                hi.append(acc.max)
    lo, hi = list(zip(*lo)), list(zip(*hi))
    return [(min(a), max(b)) for a, b in zip(lo, hi)]


def vertical_bounds(gltf: GLTF2, axis: int = 2):
    return bounds(gltf)[axis]


def mesh_to_glb(mesh_path: Path) -> Path:
    """Accept a glb directly, or convert OBJ/PLY via trimesh (experimental —
    developed against ODM output; other tools' texture setups may need work)."""
    if mesh_path.suffix.lower() in (".glb", ".gltf"):
        return ensure_uncompressed(mesh_path)
    import trimesh
    converted = mesh_path.with_suffix(".converted.glb")
    trimesh.load(str(mesh_path)).export(str(converted))
    return converted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path, nargs="?", default=None,
                    help="ODM run folder (omit when using --mesh)")
    ap.add_argument("--mesh", type=Path, help="generic mode: any georeferenced mesh (glb/gltf/obj/ply)")
    ap.add_argument("--proj", type=str, help="generic mode: proj4 string of the mesh CRS")
    ap.add_argument("--offset", type=float, nargs=2, metavar=("E", "N"),
                    help="generic mode: offset already subtracted from mesh coords (use 0 0 "
                         "if the mesh carries full CRS coordinates)")
    ap.add_argument("--sidecar", type=Path, default=None,
                    help="generic mode: georef sidecar json with proj4 + utm_offset "
                         "(default: <mesh>.json if it exists)")
    ap.add_argument("--name", type=str, default=None, help="scene name override")
    ap.add_argument("--y-up", action="store_true",
                    help="generic mode: mesh is already Y-up; skip the Z-up rotation")
    ap.add_argument("--no-center", action="store_true",
                    help="keep the mesh's own origin instead of recentring on its footprint")
    ap.add_argument("-o", "--out", type=Path, default=None,
                    help="output dir (default: <run_dir>/godot)")
    args = ap.parse_args()

    if args.mesh:
        proj, offset = args.proj, args.offset
        sidecar = args.sidecar or args.mesh.with_suffix(".json")
        if (proj is None or offset is None) and sidecar.exists():
            sc = json.loads(sidecar.read_text())
            proj = proj or sc["proj4"]
            offset = offset if offset is not None else sc["utm_offset"]
        if not (proj and offset is not None):
            ap.error("--mesh requires --proj and --offset, or a georef sidecar json")
        name = args.name or args.mesh.stem
        out = args.out or args.mesh.parent / "godot"
        east_off, north_off = offset[0], offset[1]
        glb_path = mesh_to_glb(args.mesh)
        source_pipeline = "generic"
    elif args.run_dir:
        name = args.name or args.run_dir.name
        out = args.out or args.run_dir / "godot"
        proj, east_off, north_off = read_coords(args.run_dir)
        glb_path = ensure_uncompressed(args.run_dir / "odm_texturing" / "odm_textured_model_geo.glb")
        source_pipeline = "ODM"
    else:
        ap.error("give an ODM run_dir or --mesh/--proj/--offset")
    out.mkdir(parents=True, exist_ok=True)
    gltf = GLTF2().load_binary(str(glb_path))

    bb = bounds(gltf)
    z_min, z_max = bb[1] if args.y_up else bb[2]
    z0 = round(z_min, 3)

    # Horizontal recentre: the walker spawns at engine (0, *, 0), so put the
    # origin at the mesh's footprint centre and fold the shift into utm_offset
    # (ODM offsets are near the centre anyway; georef_solve offsets are a
    # floored corner, which left the spawn point off the mesh).
    if args.no_center:
        cx = cn = 0.0
    elif args.y_up:                  # mesh frame already X=east, Z=south
        cx = round((bb[0][0] + bb[0][1]) / 2, 3)
        cn = -round((bb[2][0] + bb[2][1]) / 2, 3)
    else:                            # mesh frame X=east, Y=north, Z=up
        cx = round((bb[0][0] + bb[0][1]) / 2, 3)
        cn = round((bb[1][0] + bb[1][1]) / 2, 3)
    east_off, north_off = east_off + cx, north_off + cn

    # Root node: p' = R p + t with R = Rx(-90deg) (east->X, up->Y, north->-Z),
    # t = (-cx, -z0, +cn) so the footprint centre lands at X=Z=0 and the
    # lowest ground point at Y=0. glTF matrices are column-major. With
    # --y-up, skip the rotation (engine Z = -north, so t_z = +cn).
    matrix = ([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -cx, -z0, cn, 1] if args.y_up else
              [1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, -cx, -z0, cn, 1])
    root = Node(
        name=f"{name}_enu_to_engine",
        matrix=matrix,
        children=list(gltf.scenes[gltf.scene or 0].nodes),
    )
    gltf.nodes.append(root)
    gltf.scenes[gltf.scene or 0] = Scene(nodes=[len(gltf.nodes) - 1])
    out_glb = out / f"{name}.glb"
    gltf.save_binary(str(out_glb))

    crs = CRS.from_proj4(proj)
    to_wgs84 = Transformer.from_crs(crs, CRS.from_epsg(4326), always_xy=True)
    lon, lat = to_wgs84.transform(east_off, north_off)
    # Local linearization so the engine can show lat/lon without projection math.
    # Error over a few hundred meters is far below reconstruction accuracy.
    lon_e, lat_e = to_wgs84.transform(east_off + 1.0, north_off)
    lon_n, lat_n = to_wgs84.transform(east_off, north_off + 1.0)
    jacobian = {"dlat_de": lat_e - lat, "dlat_dn": lat_n - lat,
                "dlon_de": lon_e - lon, "dlon_dn": lon_n - lon}

    scene = {
        "name": name,
        "source": {"pipeline": source_pipeline, "asset": out_glb.name},
        "crs": {"proj4": proj, "utm_offset": [east_off, north_off], "z_offset": z0},
        "origin_geopose": {  # GeoPose-shaped anchor of the engine origin
            "position": {"lat": lat, "lon": lon, "h": z0},
            "angles": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0},
        },
        "engine_frame": {"convention": "gltf-Y-up", "x": "east", "y": "up", "z": "south",
                         "units": "meters"},
        "wgs84_jacobian": jacobian,  # deg per meter of easting/northing at the origin
        "terrain_elevation_range_m": [round(z_min, 2), round(z_max, 2)],
        "to_utm": "utm_e = x + utm_offset[0]; utm_n = -z + utm_offset[1]; elev = y + z_offset",
    }
    (out / "scene.json").write_text(json.dumps(scene, indent=2))

    print(f"wrote {out_glb} ({out_glb.stat().st_size / 1e6:.1f} MB)")
    print(f"wrote {out / 'scene.json'}  origin lat/lon/h = {lat:.6f}, {lon:.6f}, {z0}")


if __name__ == "__main__":
    main()
