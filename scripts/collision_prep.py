"""Convex-decompose a mesh into physics-ready collision hulls (CoACD).

Visual meshes from photogrammetry are non-convex triangle soups — game and
robot physics engines want a small set of convex hulls instead. CoACD
(MIT, SIGGRAPH 2022) produces tight decompositions that preserve concave
functional features (openings, handles) far better than plain V-HACD.

Outputs, from `-o <stem>`:
  <stem>_collision.glb   all hulls as separate meshes in one scene (Godot:
                         import and generate one convex shape per mesh)
  <stem>_hulls/hull_NNN.obj  one obj per hull (MuJoCo / obj2mjcf style)
  <stem>_manifest.json   hull count, volumes, parameters

Meant for object-scale meshes (props, furniture, equipment). Terrain wants a
heightfield collider, not hulls — decompose the objects, not the site.

Usage:
  python scripts/collision_prep.py runs/site/bench.glb -o runs/site/physics/bench
"""
import argparse
import json
from pathlib import Path

import numpy as np
import trimesh


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mesh", type=Path, help="visual mesh (glb/obj/ply, non-Draco)")
    ap.add_argument("-o", "--out", required=True, help="output stem")
    ap.add_argument("--threshold", type=float, default=0.05,
                    help="CoACD concavity threshold, lower = more hulls (default 0.05)")
    ap.add_argument("--max-hulls", type=int, default=64,
                    help="hard cap on hull count (default 64)")
    ap.add_argument("--resolution", type=int, default=2000,
                    help="CoACD sampling resolution (default 2000)")
    args = ap.parse_args()

    import coacd

    mesh = trimesh.load(str(args.mesh), force="mesh")
    extent = mesh.extents
    if max(extent) > 100:
        print(f"WARNING: mesh spans {max(extent):.0f} m — this looks like terrain. "
              "Hulls suit object-scale meshes; use a heightfield collider for ground.")

    parts = coacd.run_coacd(
        coacd.Mesh(np.asarray(mesh.vertices), np.asarray(mesh.faces)),
        threshold=args.threshold,
        max_convex_hull=args.max_hulls,
        resolution=args.resolution,
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    hulls_dir = out.parent / f"{out.name}_hulls"
    hulls_dir.mkdir(exist_ok=True)

    scene = trimesh.Scene()
    manifest = []
    for i, (verts, faces) in enumerate(parts):
        hull = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
        hull.export(hulls_dir / f"hull_{i:03d}.obj")
        scene.add_geometry(hull, node_name=f"hull_{i:03d}")
        manifest.append({"hull": i, "verts": len(verts), "faces": len(faces),
                         "volume_m3": float(hull.volume) if hull.is_volume else None})

    glb_path = out.parent / f"{out.name}_collision.glb"
    scene.export(str(glb_path))
    (out.parent / f"{out.name}_manifest.json").write_text(json.dumps({
        "source": str(args.mesh), "n_hulls": len(parts),
        "params": {"threshold": args.threshold, "max_hulls": args.max_hulls,
                   "resolution": args.resolution},
        "source_extent_m": [float(e) for e in extent],
        "hulls": manifest,
    }, indent=2))
    print(f"{len(parts)} hulls -> {glb_path} + {hulls_dir}/")


if __name__ == "__main__":
    main()
