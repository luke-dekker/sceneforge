"""Convert a Meshroom textured OBJ into an engine-ready GLB.

Steps: EXR textures -> sRGB JPG (Meshroom writes linear EXR), OBJ -> GLB via
trimesh, optional weld+simplify via gltf-transform (npx). The input run folder
is only touched additively (JPGs written next to the EXRs); the OBJ/MTL are
staged into the output folder via hardlink/copy so the source MTL keeps its
EXR references.

Usage: python scripts/mesh_convert.py --mesh <texturedMesh.obj> --out <dir> \
           [--name scene] [--ratio 0.35] [--jpg-quality 92]
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np


def read_exr_rgb(path):
    import OpenEXR
    with OpenEXR.File(str(path)) as f:
        ch = f.channels()
        if "RGB" in ch:
            return ch["RGB"].pixels[:, :, :3].astype(np.float32)
        if "RGBA" in ch:
            return ch["RGBA"].pixels[:, :, :3].astype(np.float32)
        return np.stack([ch[c].pixels for c in ("R", "G", "B")],
                        axis=-1).astype(np.float32)


def linear_to_srgb_u8(lin):
    lin = np.clip(lin, 0.0, 1.0)
    srgb = np.where(lin <= 0.0031308, lin * 12.92,
                    1.055 * np.power(lin, 1 / 2.4) - 0.055)
    return (np.clip(srgb, 0, 1) * 255).astype(np.uint8)


def convert_textures(src_dir, jpg_quality):
    """EXR -> JPG next to the source (additive). Returns exr->jpg name map."""
    import cv2
    mapping = {}
    for exr in sorted(src_dir.glob("*.exr")):
        jpg = exr.with_suffix(".jpg")
        if not jpg.exists():
            img = linear_to_srgb_u8(read_exr_rgb(exr))[:, :, ::-1]  # RGB->BGR
            cv2.imwrite(str(jpg), img, [cv2.IMWRITE_JPEG_QUALITY, jpg_quality])
            print(f"converted {exr.name} -> {jpg.name}")
        mapping[exr.name] = jpg.name
    return mapping


def stage(mesh_path, out_dir, tex_map):
    """Hardlink/copy the OBJ and write a JPG-referencing MTL into out_dir."""
    staged_obj = out_dir / mesh_path.name
    if staged_obj.exists():
        staged_obj.unlink()
    try:
        os.link(mesh_path, staged_obj)
    except OSError:
        shutil.copy2(mesh_path, staged_obj)
    for mtl in mesh_path.parent.glob("*.mtl"):
        text = mtl.read_text()
        for exr_name, jpg_name in tex_map.items():
            text = text.replace(exr_name, jpg_name)
        (out_dir / mtl.name).write_text(text)
    for jpg in mesh_path.parent.glob("*.jpg"):
        target = out_dir / jpg.name
        if not target.exists():
            try:
                os.link(jpg, target)
            except OSError:
                shutil.copy2(jpg, target)
    return staged_obj


def simplify(glb_in, glb_out, ratio):
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        print("WARNING: npx not found - skipping simplify", file=sys.stderr)
        shutil.copy2(glb_in, glb_out)
        return
    welded = glb_in.with_name(glb_in.stem + "_welded.glb")
    subprocess.run([npx, "--yes", "@gltf-transform/cli", "weld",
                    str(glb_in), str(welded)], check=True, shell=False)
    subprocess.run([npx, "--yes", "@gltf-transform/cli", "simplify",
                    str(welded), str(glb_out), "--ratio", str(ratio),
                    "--error", "0.001"], check=True, shell=False)
    welded.unlink()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mesh", type=Path, required=True,
                    help="Meshroom texturedMesh.obj (or any OBJ with MTL)")
    ap.add_argument("--out", type=Path, required=True, help="output folder")
    ap.add_argument("--name", type=str, default=None,
                    help="output glb name (default: parent folder name)")
    ap.add_argument("--ratio", type=float, default=0.35,
                    help="simplify ratio (0 or 1 = keep full resolution)")
    ap.add_argument("--jpg-quality", type=int, default=92)
    args = ap.parse_args()

    name = args.name or args.mesh.parent.name
    args.out.mkdir(parents=True, exist_ok=True)

    tex_map = convert_textures(args.mesh.parent, args.jpg_quality)
    staged_obj = stage(args.mesh, args.out, tex_map)

    import trimesh
    print("loading OBJ...")
    scene = trimesh.load(str(staged_obj))
    geoms = (scene.geometry.values()
             if hasattr(scene, "geometry") else [scene])
    tris = sum(len(g.faces) for g in geoms)
    print(f"triangles: {tris:,}  extents: {np.round(scene.extents, 1).tolist()}")

    full_glb = args.out / f"{name}_full.glb"
    scene.export(str(full_glb))

    out_glb = args.out / f"{name}.glb"
    if 0 < args.ratio < 1:
        simplify(full_glb, out_glb, args.ratio)
        full_glb.unlink()
    else:
        full_glb.rename(out_glb)

    # Staged intermediates are only needed during the trimesh load
    staged_obj.unlink()
    for mtl in args.out.glob("*.mtl"):
        mtl.unlink()
    for jpg in args.out.glob("*.jpg"):
        jpg.unlink()

    report = {"name": name, "triangles_in": tris, "ratio": args.ratio,
              "glb": out_glb.name, "size_mb": round(out_glb.stat().st_size / 1e6, 1)}
    (args.out / "convert_report.json").write_text(json.dumps(report, indent=2))
    print(f"wrote {out_glb} ({report['size_mb']} MB)")


if __name__ == "__main__":
    main()
