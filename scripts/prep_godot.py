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


def vertical_bounds(gltf: GLTF2):
    zs = []
    for mesh in gltf.meshes:
        for prim in mesh.primitives:
            acc = gltf.accessors[prim.attributes.POSITION]
            if acc.min and acc.max:
                zs.extend([acc.min[2], acc.max[2]])
    return min(zs), max(zs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=None,
                    help="output dir (default: <run_dir>/godot)")
    args = ap.parse_args()
    out = args.out or args.run_dir / "godot"
    out.mkdir(parents=True, exist_ok=True)
    name = args.run_dir.name

    proj, east_off, north_off = read_coords(args.run_dir)
    glb_path = ensure_uncompressed(args.run_dir / "odm_texturing" / "odm_textured_model_geo.glb")
    gltf = GLTF2().load_binary(str(glb_path))

    z_min, z_max = vertical_bounds(gltf)
    z0 = round(z_min, 3)

    # Root node: p' = R p + t with R = Rx(-90deg) (east->X, up->Y, north->-Z),
    # t = (0, -z0, 0) so the lowest ground point lands at Y=0.
    # glTF matrices are column-major.
    root = Node(
        name=f"{name}_enu_to_engine",
        matrix=[1, 0, 0, 0,
                0, 0, -1, 0,
                0, 1, 0, 0,
                0, -z0, 0, 1],
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
        "source": {"pipeline": "ODM", "asset": str(glb_path.name)},
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
