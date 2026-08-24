"""Export a georeferenced local-frame mesh as a full-coordinate OBJ for ArcGIS Pro.

ArcGIS Pro's *Import 3D Files* tool reads Wavefront OBJ and, when no
placement points are given, uses the coordinates inside the file directly in
the spatial reference you pick. So: take a <mesh>_geo.glb (local UTM metres,
Z-up, offset origin from the sidecar json) and write an OBJ whose vertices are
absolute UTM E/N/Z, with textures alongside as JPG + an .mtl.

In Pro: Import 3D Files -> Input Files = this .obj, Output Feature Class in a
file geodatabase (keeps textures), Spatial Reference = the EPSG in the sidecar
(e.g. WGS 84 / UTM zone 10N = 32610), leave "Y is up" UNCHECKED (Z-up).
Heights are whatever the georef used (DJI RTK: WGS84 ellipsoid) — set the
vertical coordinate system accordingly or accept a constant offset.

Usage:
  python scripts/export_arcgis_obj.py runs/site/georef/site_geo.glb -o runs/site/arcgis/site
"""
import argparse
import json
import re
from pathlib import Path

import numpy as np
import trimesh


def epsg_from_proj4(proj4):
    m = re.search(r"\+zone=(\d+)", proj4)
    if m and "+proj=utm" in proj4:
        return (32700 if "+south" in proj4 else 32600) + int(m.group(1))
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mesh", type=Path, help="georeferenced glb (local UTM metres, Z-up)")
    ap.add_argument("--sidecar", type=Path, default=None,
                    help="georef json {proj4, utm_offset} (default <mesh>.json)")
    ap.add_argument("-o", "--out", required=True, help="output stem, e.g. runs/site/arcgis/site")
    args = ap.parse_args()

    sidecar = args.sidecar or args.mesh.with_suffix(".json")
    geo = json.loads(sidecar.read_text())
    off = np.array([geo["utm_offset"][0], geo["utm_offset"][1], 0.0])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    scene = trimesh.load(str(args.mesh), force="scene")
    for name, g in scene.geometry.items():
        g.apply_transform(scene.graph.get(name)[0])   # bake node transforms
        g.vertices = g.vertices + off
        uv = getattr(g.visual, "uv", None)
        if uv is not None and len(uv):
            # Meshroom UDIM tiles offset u by the tile index; each geometry has
            # its own texture, so drop the offset — Pro shouldn't need to wrap
            g.visual.uv = uv - np.floor(uv.min(0))
    scene = trimesh.Scene(list(scene.geometry.values()))

    obj_path = out.with_suffix(".obj")
    # trimesh writes textures + .mtl next to the obj when given a resolver
    resolver = trimesh.resolvers.FilePathResolver(str(obj_path.parent))
    text = trimesh.exchange.obj.export_obj(
        scene, include_texture=True, mtl_name=obj_path.stem + ".mtl", resolver=resolver,
        digits=3)
    obj_path.write_text(text)

    # trimesh writes PNG textures; swap for JPG (Pro reads both, ~5x smaller)
    from PIL import Image
    mtl_path = obj_path.parent / (obj_path.stem + ".mtl")
    if mtl_path.exists():
        mtl = mtl_path.read_text()
        for png in sorted(obj_path.parent.glob("*.png")):
            if png.name not in mtl:
                continue
            jpg = png.with_suffix(".jpg")
            Image.open(png).convert("RGB").save(jpg, quality=90)
            png.unlink()
            mtl = mtl.replace(png.name, jpg.name)
        mtl_path.write_text(mtl)

    meta = {
        "epsg": epsg_from_proj4(geo["proj4"]),
        "proj4": geo["proj4"],
        "vertical": geo.get("vertical_datum", "see georef_transform.json"),
        "axes": "Z-up, absolute UTM metres (Import 3D Files: leave 'Y is up' unchecked)",
        "vertices": int(sum(len(g.vertices) for g in scene.geometry.values())),
        "faces": int(sum(len(g.faces) for g in scene.geometry.values())),
    }
    out.with_suffix(".arcgis.json").write_text(json.dumps(meta, indent=2))
    print(f"wrote {obj_path} ({meta['faces']:,} faces) EPSG:{meta['epsg']}, sidecar {out.with_suffix('.arcgis.json').name}")


if __name__ == "__main__":
    main()
