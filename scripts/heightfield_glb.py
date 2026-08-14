"""Bake a walkable heightfield GLB from a DSM + orthomosaic GeoTIFF pair.

The fast path from a flight to a scene: terrain-only geometry (a decimated
DSM grid) draped with the orthophoto. Trees and buildings come out as lumpy
terrain — good enough to walk a site minutes after processing; use the full
dense-mesh route when vertical surfaces matter.

Vertices are local metres (UTM minus the printed offset), Z-up, so the
output feeds prep_godot.py generic mode:

  python scripts/heightfield_glb.py runs/farm-micmac/farm_dsm_utm10.tif \
      runs/farm-micmac/farm_ortho_utm10.tif -o runs/farm-micmac/farm.glb
  python scripts/prep_godot.py --mesh runs/farm-micmac/farm.glb \
      --proj "+proj=utm +zone=10 +datum=WGS84 +units=m" --offset <E0> <N0> --name farm
"""
import argparse
from pathlib import Path

import numpy as np
import rasterio
import trimesh
from PIL import Image


def read_grid(path, max_dim):
    with rasterio.open(path) as src:
        scale = max_dim / max(src.width, src.height)
        shape = (max(1, round(src.height * scale)), max(1, round(src.width * scale)))
        data = src.read(out_shape=(src.count,) + shape)
        return data, src.bounds


def clean_heights(z, mask=None):
    """Heights outside Malt's correlation mask are garbage — replace each
    invalid pixel with its nearest valid neighbour. Without a mask, only
    non-finite values are treated as invalid."""
    from scipy.ndimage import distance_transform_edt
    valid = np.isfinite(z)
    if mask is not None:
        valid &= mask > 0
    if not valid.all():
        _, (ri, ci) = distance_transform_edt(~valid, return_indices=True)
        z = z[ri, ci]
    # Despike: single-pixel correlation blunders dive/spike tens of metres;
    # 0.2% tail clip removes them without flattening real canopy.
    lo, hi = np.percentile(z[valid] if valid.any() else z, [0.2, 99.8])
    return np.clip(z, lo, hi)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dsm", help="DSM GeoTIFF (heights in metres)")
    ap.add_argument("ortho", help="orthomosaic GeoTIFF, same extent")
    ap.add_argument("-o", "--out", required=True, help="output .glb")
    ap.add_argument("--grid", type=int, default=1000, help="max grid dimension (default 1000)")
    ap.add_argument("--tex", type=int, default=8192, help="max texture dimension (default 8192)")
    ap.add_argument("--mask", help="validity mask raster (e.g. MicMac Masq_*.tif), same grid as the DSM")
    args = ap.parse_args()

    z, bounds = read_grid(args.dsm, args.grid)
    mask = read_grid(args.mask, args.grid)[0][0] if args.mask else None
    z = clean_heights(z[0].astype(np.float64), mask)
    h, w = z.shape

    rgb, obounds = read_grid(args.ortho, args.tex)
    tex = Image.fromarray(np.moveaxis(rgb[:3], 0, -1).astype(np.uint8))

    # Center the mesh: engines (and the walker's spawn) put the player at the
    # local origin, so that origin must be mid-scene, not the SW corner.
    e0 = np.floor((bounds.left + bounds.right) / 2)
    n0 = np.floor((bounds.bottom + bounds.top) / 2)
    xs = np.linspace(bounds.left - e0, bounds.right - e0, w)
    ys = np.linspace(bounds.top - n0, bounds.bottom - n0, h)  # row 0 = north
    xx, yy = np.meshgrid(xs, ys)
    verts = np.column_stack([xx.ravel(), yy.ravel(), z.ravel()])

    idx = np.arange(h * w).reshape(h, w)
    a, b, c, d = idx[:-1, :-1], idx[:-1, 1:], idx[1:, :-1], idx[1:, 1:]
    faces = np.concatenate([
        np.column_stack([a.ravel(), c.ravel(), b.ravel()]),
        np.column_stack([b.ravel(), c.ravel(), d.ravel()]),
    ])

    uu = (xx.ravel() - xs[0]) / (xs[-1] - xs[0])
    vv = 1.0 - (ys[0] - yy.ravel()) / (ys[0] - ys[-1])  # v=0 at image bottom
    uv = np.column_stack([uu, vv])

    material = trimesh.visual.material.PBRMaterial(
        baseColorTexture=tex, metallicFactor=0.0, roughnessFactor=1.0)
    mesh = trimesh.Trimesh(
        vertices=verts, faces=faces,
        visual=trimesh.visual.TextureVisuals(uv=uv, material=material),
        process=False)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(out)
    print(f"{out}: {len(verts):,} verts, {len(faces):,} tris, "
          f"{tex.size[0]}x{tex.size[1]} texture")
    print(f"extent {bounds.right-bounds.left:.0f}m x {bounds.top-bounds.bottom:.0f}m, "
          f"height range {z.min():.1f}..{z.max():.1f}")
    print(f"prep_godot offset: --offset {e0:.0f} {n0:.0f}")


if __name__ == "__main__":
    main()
