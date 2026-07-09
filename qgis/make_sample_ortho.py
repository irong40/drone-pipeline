#!/usr/bin/env python3
"""Generate a synthetic georeferenced RGB orthophoto for smoke-testing.

Creates a 512x512 3-band UTM 18N GeoTIFF: a green vegetation patch (high VARI)
plus bare-soil / gravel background (low VARI). Run with QGIS python:
    python-qgis-ltr.bat make_sample_ortho.py <out.tif>
"""
import sys
import numpy as np
from osgeo import gdal, osr

gdal.UseExceptions()

out = sys.argv[1] if len(sys.argv) > 1 else "sample_ortho.tif"
W = H = 512

rng = np.random.default_rng(42)
# bare soil background: brownish (R>G>B)
red = np.full((H, W), 150, np.float32) + rng.normal(0, 6, (H, W))
grn = np.full((H, W), 110, np.float32) + rng.normal(0, 6, (H, W))
blu = np.full((H, W), 80, np.float32) + rng.normal(0, 6, (H, W))

# vegetation patch (circle) -> green dominant, VARI high
yy, xx = np.mgrid[0:H, 0:W]
veg = ((xx - 170) ** 2 + (yy - 200) ** 2) < 90 ** 2
red[veg] = 70 + rng.normal(0, 5, veg.sum())
grn[veg] = 165 + rng.normal(0, 5, veg.sum())
blu[veg] = 60 + rng.normal(0, 5, veg.sum())

# a second smaller vegetation blob (tests multi-polygon + area filter)
veg2 = ((xx - 360) ** 2 + (yy - 330) ** 2) < 45 ** 2
red[veg2] = 80
grn[veg2] = 150
blu[veg2] = 65

# a tiny speck that should be filtered out by min-area
speck = ((xx - 450) ** 2 + (yy - 60) ** 2) < 3 ** 2
red[speck] = 80; grn[speck] = 150; blu[speck] = 65

bands = [np.clip(b, 0, 255).astype(np.uint8) for b in (red, grn, blu)]

drv = gdal.GetDriverByName("GTiff")
ds = drv.Create(out, W, H, 3, gdal.GDT_Byte, options=["COMPRESS=DEFLATE"])
# UTM 18N, ~Chesapeake VA; 0.05 m/px GSD, origin arbitrary
gsd = 0.05
ds.SetGeoTransform([400000.0, gsd, 0, 4080000.0, 0, -gsd])
srs = osr.SpatialReference()
srs.ImportFromEPSG(32618)
ds.SetProjection(srs.ExportToWkt())
for i, b in enumerate(bands, 1):
    ds.GetRasterBand(i).WriteArray(b)
ds.FlushCache()
ds = None
print(f"wrote {out}")
