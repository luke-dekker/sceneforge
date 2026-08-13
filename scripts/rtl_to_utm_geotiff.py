"""Export a MicMac RTL-frame raster as a UTM GeoTIFF.

MicMac products (Tawny orthomosaics, Malt DSMs) come out in the local
tangent frame (RTL) defined by RTLFromExif.xml, with a plain .tfw world
file. This script re-georeferences them into UTM so they drop into
QGIS/ArcGIS next to anything else.

The transform is done honestly rather than by naive offset: the four
raster corners go RTL(ENU) -> ECEF -> WGS84 -> UTM through pyproj, and
an affine is least-squares fitted through them. Over sub-km extents the
affine absorbs meridian convergence and UTM scale factor to sub-mm;
the fit residual is printed so you can see that claim checked.

MicMac writes big rasters as a stub .tif plus <name>_Tile_<x>_<y>.tif
strips; these are stitched on the fly with windowed IO.

Heights (DSM values, --add-origin-alt) become WGS84 ellipsoidal by
adding the RTL origin altitude - flat-earth approx, fine below ~1km.

Usage:
  python scripts/rtl_to_utm_geotiff.py runs/farm-micmac/proj/Ortho-MEC-Malt/Orthophotomosaic.tif \
      --rtl runs/farm-micmac/proj/RTLFromExif.xml -o runs/farm-micmac/farm_ortho_utm10.tif
"""
import argparse
import json
import math
import re
from pathlib import Path

import numpy as np
import pyproj
import rasterio
from rasterio.windows import Window


def parse_rtl_origin(path):
    """RTLFromExif.xml -> (lon, lat, alt) of the tangent-plane origin."""
    text = Path(path).read_text()
    block = re.search(r"<TypeCoord>eTC_RTL</TypeCoord>(.*?)</BSC>", text, re.S).group(1)
    lon, lat, alt = [float(v) for v in re.findall(r"<AuxR>([^<]+)</AuxR>", block)]
    if lon > 180:
        lon -= 360
    return lon, lat, alt


def parse_tfw(path):
    px, _, _, py, x_ul, y_ul = [float(l) for l in Path(path).read_text().split()]
    return px, py, x_ul, y_ul


def tile_layout(stub):
    """MicMac stub tif -> sorted [(path, x_index, y_index)] or [] if monolithic."""
    tiles = []
    for p in stub.parent.glob(f"{stub.stem}_Tile_*_*.tif"):
        m = re.match(rf"{re.escape(stub.stem)}_Tile_(\d+)_(\d+)$", p.stem)
        tiles.append((p, int(m.group(1)), int(m.group(2))))
    return sorted(tiles, key=lambda t: (t[2], t[1]))


def enu_to_utm(origin, pts_enu):
    """(N,2) east/north metres in the tangent plane -> (N,2) UTM, plus epsg."""
    lon0, lat0, alt0 = origin
    zone = int((lon0 + 180) // 6) + 1
    epsg = (32600 if lat0 >= 0 else 32700) + zone
    geod2ecef = pyproj.Transformer.from_crs("EPSG:4979", "EPSG:4978", always_xy=True)
    ecef2geod = pyproj.Transformer.from_crs("EPSG:4978", "EPSG:4979", always_xy=True)
    geod2utm = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)

    lam, phi = math.radians(lon0), math.radians(lat0)
    e = np.array([-math.sin(lam), math.cos(lam), 0.0])
    n = np.array([-math.sin(phi) * math.cos(lam), -math.sin(phi) * math.sin(lam), math.cos(phi)])
    o = np.array(geod2ecef.transform(lon0, lat0, alt0))

    ecef = o + np.outer(pts_enu[:, 0], e) + np.outer(pts_enu[:, 1], n)
    lon, lat, _ = ecef2geod.transform(*ecef.T)
    x, y = geod2utm.transform(lon, lat)
    return np.column_stack([x, y]), epsg


def fit_affine(pix, utm):
    """Least-squares pixel->UTM affine; returns rasterio.Affine and max residual."""
    A = np.column_stack([pix, np.ones(len(pix))])
    (ax, bx, cx), _, _, _ = np.linalg.lstsq(A, utm[:, 0], rcond=None)
    (ay, by, cy), _, _, _ = np.linalg.lstsq(A, utm[:, 1], rcond=None)
    pred = np.column_stack([A @ [ax, bx, cx], A @ [ay, by, cy]])
    resid = float(np.abs(pred - utm).max())
    return rasterio.Affine(ax, bx, cx, ay, by, cy), resid


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("raster", help="MicMac raster (stub or monolithic .tif, .tfw beside it)")
    ap.add_argument("--rtl", required=True, help="RTLFromExif.xml defining the local frame")
    ap.add_argument("-o", "--out", required=True, help="output GeoTIFF path")
    ap.add_argument("--add-origin-alt", action="store_true",
                    help="add RTL origin altitude to band values (DSM -> ellipsoidal height)")
    args = ap.parse_args()

    stub = Path(args.raster)
    origin = parse_rtl_origin(args.rtl)
    px, py, x_ul, y_ul = parse_tfw(stub.with_suffix(".tfw"))

    tiles = tile_layout(stub)
    if tiles:
        widths = {xi: rasterio.open(p).width for p, xi, yi in tiles if yi == 0}
        heights = {yi: rasterio.open(p).height for p, xi, yi in tiles if xi == 0}
        W, H = sum(widths.values()), sum(heights.values())
        ref = rasterio.open(tiles[0][0])
    else:
        ref = rasterio.open(stub)
        W, H = ref.width, ref.height

    # four pixel corners -> RTL ENU -> UTM, then fit
    pix = np.array([[0, 0], [W, 0], [0, H], [W, H]], dtype=float)
    enu = np.column_stack([x_ul + pix[:, 0] * px, y_ul + pix[:, 1] * py])
    utm, epsg = enu_to_utm(origin, enu)
    transform, resid = fit_affine(pix, utm)
    print(f"origin lon/lat/alt: {origin}")
    print(f"raster: {W}x{H}  GSD {px}m  ->  EPSG:{epsg}, affine fit residual {resid*1000:.2f} mm")

    profile = dict(
        driver="GTiff", width=W, height=H, count=ref.count, dtype=ref.dtypes[0],
        crs=f"EPSG:{epsg}", transform=transform, tiled=True, blockxsize=512,
        blockysize=512, compress="lzw", bigtiff="IF_SAFER", nodata=ref.nodata,
    )
    z_off = origin[2] if args.add_origin_alt else 0.0

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(args.out, "w", **profile) as dst:
        sources = tiles or [(stub, 0, 0)]
        x_off = {xi: sum(widths[i] for i in range(xi)) for _, xi, _ in tiles} if tiles else {0: 0}
        y_off = {yi: sum(heights[i] for i in range(yi)) for _, _, yi in tiles} if tiles else {0: 0}
        for path, xi, yi in sources:
            with rasterio.open(path) as src:
                for _, win in src.block_windows(1):
                    data = src.read(window=win)
                    if z_off:
                        data = data + z_off
                    dst.write(data, window=Window(
                        win.col_off + x_off[xi], win.row_off + y_off[yi],
                        win.width, win.height))

    sidecar = Path(args.out).with_suffix(".json")
    sidecar.write_text(json.dumps({
        "epsg": epsg, "gsd_m": px, "affine_fit_residual_m": resid,
        "rtl_origin_lon_lat_alt": list(origin),
        "vertical_datum": "WGS84 ellipsoid (origin-alt offset)" if z_off else "n/a (image)",
        "source": str(stub),
    }, indent=2) + "\n")
    print(f"wrote {args.out} + sidecar")


if __name__ == "__main__":
    main()
