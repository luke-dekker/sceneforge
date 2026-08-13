"""Convert an ODM gcp_list.txt into MicMac GCP XML files.

MicMac's GCP nodes (GCPBascule, GCPCtrl, Campari) take two XML files:
a ground-coordinate dictionary (DicoAppuisFlottant) and per-image pixel
measurements (SetOfMesureAppuisFlottants). ODM packs the same data into
one flat gcp_list.txt (proj4 header, then "X Y Z px py image [name]"
rows), so this script is a pure format translation — same numbers, same
CRS. The proj4 header is written to a sidecar JSON so downstream export
steps know what frame the solve lives in.

--checkpoints splits the named points into a second XML pair that is
kept out of the solve and fed to GCPCtrl instead, mirroring the holdout
grading we do for ODM runs with gcp_residuals.py.

Ground coordinates are shifted to a local origin by default (MicMac v1's
adjustment goes numerically unstable on raw UTM-magnitude values —
NaN residuals, non-rotation warnings). The offset is stored in the CRS
sidecar; add it back when exporting products to real-world coordinates.

Usage:
  python scripts/gcp_to_micmac.py data/copr/gcp_list.txt -o runs/copr-micmac/gcp \
      --checkpoints gcp05 gcp06
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path


def parse_gcp_list(path):
    """Return (proj4, rows) where rows are dicts with x,y,z,px,py,image,name."""
    lines = [ln.strip() for ln in Path(path).read_text().splitlines() if ln.strip()]
    proj4 = lines[0]
    rows = []
    auto_names = {}
    for ln in lines[1:]:
        parts = ln.split()
        x, y, z, px, py = map(float, parts[:5])
        image = parts[5]
        if len(parts) > 6:
            name = parts[6]
        else:
            # No name column: identical ground coords = same physical point.
            key = (x, y, z)
            name = auto_names.setdefault(key, f"gcp{len(auto_names) + 1:02d}")
        rows.append(dict(x=x, y=y, z=z, px=px, py=py, image=image, name=name))
    return proj4, rows


def ground_xml(rows, sigma_xy, sigma_z):
    points = {}
    for r in rows:
        points[r["name"]] = (r["x"], r["y"], r["z"])
    out = ['<?xml version="1.0" ?>', "<DicoAppuisFlottant>"]
    for name, (x, y, z) in sorted(points.items()):
        out += [
            "     <OneAppuisDAF>",
            f"          <Pt>{x} {y} {z}</Pt>",
            f"          <NamePt>{name}</NamePt>",
            f"          <Incertitude>{sigma_xy} {sigma_xy} {sigma_z}</Incertitude>",
            "     </OneAppuisDAF>",
        ]
    out.append("</DicoAppuisFlottant>")
    return "\n".join(out) + "\n"


def measures_xml(rows):
    by_image = defaultdict(list)
    for r in rows:
        by_image[r["image"]].append(r)
    out = ['<?xml version="1.0" ?>', "<SetOfMesureAppuisFlottants>"]
    for image in sorted(by_image):
        out.append("     <MesureAppuiFlottant1Im>")
        out.append(f"          <NameIm>{image}</NameIm>")
        for r in by_image[image]:
            out += [
                "          <OneMesureAF1I>",
                f"               <NamePt>{r['name']}</NamePt>",
                f"               <PtIm>{r['px']} {r['py']}</PtIm>",
                "          </OneMesureAF1I>",
            ]
        out.append("     </MesureAppuiFlottant1Im>")
    out.append("</SetOfMesureAppuisFlottants>")
    return "\n".join(out) + "\n"


def write_pair(rows, stem, suffix, sigma_xy, sigma_z):
    ground = stem.parent / f"{stem.name}{suffix}-GroundPts.xml"
    measures = stem.parent / f"{stem.name}{suffix}-Measures-S2D.xml"
    ground.write_text(ground_xml(rows, sigma_xy, sigma_z))
    measures.write_text(measures_xml(rows))
    names = sorted({r["name"] for r in rows})
    print(f"  {ground.name} / {measures.name}: {len(names)} points "
          f"({', '.join(names)}), {len(rows)} measurements")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("gcp_list", help="ODM gcp_list.txt (proj4 header + rows)")
    ap.add_argument("-o", "--out", required=True,
                    help="output stem, e.g. runs/copr-micmac/gcp")
    ap.add_argument("--checkpoints", nargs="*", default=[],
                    help="point names held out of the solve (written as -Ctrl pair)")
    ap.add_argument("--sigma-xy", type=float, default=0.02,
                    help="horizontal uncertainty in ground units (default 0.02)")
    ap.add_argument("--sigma-z", type=float, default=0.04,
                    help="vertical uncertainty in ground units (default 0.04)")
    ap.add_argument("--offset", nargs=3, type=float, metavar=("X", "Y", "Z"),
                    help="local origin to subtract from ground coords "
                         "(default: auto, floor of the min corner to 100m)")
    ap.add_argument("--no-offset", action="store_true",
                    help="keep raw ground coordinates")
    args = ap.parse_args()

    proj4, rows = parse_gcp_list(args.gcp_list)
    if args.no_offset:
        offset = (0.0, 0.0, 0.0)
    elif args.offset:
        offset = tuple(args.offset)
    else:
        offset = tuple(
            float(int(min(r[k] for r in rows) // 100) * 100) for k in "xy") + (0.0,)
    for r in rows:
        r["x"] -= offset[0]
        r["y"] -= offset[1]
        r["z"] -= offset[2]
    stem = Path(args.out)
    stem.parent.mkdir(parents=True, exist_ok=True)

    held = set(args.checkpoints)
    known = {r["name"] for r in rows}
    missing = held - known
    if missing:
        ap.error(f"checkpoints not in {args.gcp_list}: {', '.join(sorted(missing))}")

    solve_rows = [r for r in rows if r["name"] not in held]
    ctrl_rows = [r for r in rows if r["name"] in held]

    print(f"{args.gcp_list}: {len(known)} points, {len(rows)} measurements")
    write_pair(solve_rows, stem, "", args.sigma_xy, args.sigma_z)
    if ctrl_rows:
        write_pair(ctrl_rows, stem, "-Ctrl", args.sigma_xy, args.sigma_z)

    crs = stem.parent / f"{stem.name}-crs.json"
    crs.write_text(json.dumps({"proj4": proj4, "offset": list(offset),
                               "source": str(args.gcp_list)}, indent=2) + "\n")
    print(f"  {crs.name}: {proj4}  offset={offset}")


if __name__ == "__main__":
    main()
