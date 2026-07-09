#!/usr/bin/env python3
"""
Sentinel Aerial Inspections - Headless RGB Vegetation Analysis (QGIS)
====================================================================

Runs WITHOUT the QGIS GUI. Consumes a NodeODM RGB orthophoto (Mini 4 Pro is
RGB-only, no NIR) and produces:
  * <out>/vegetation.gpkg   - polygons of detected vegetation (VARI index)
  * <out>/vegetation.pdf    - auto-exported Print Layout (map + legend + title)
  * <out>/vegetation.tif    - the VARI index raster (float32, -1..1)
  * <out>/summary.json      - machine-readable run summary

Index used: VARI (Visible Atmospherically Resistant Index)
    VARI = (Green - Red) / (Green + Red - Blue)
VARI is an RGB-only greenness index. It needs NO near-infrared band, which is
why it is the correct choice for Mini 4 Pro output. Higher VARI ~= greener /
healthier visible vegetation. This script flags contiguous vegetation polygons
above a threshold (default 0.15) that exceed a minimum area (default 2 m2) -
useful for vegetation-encroachment / right-of-way inspection deliverables.

Run it with the QGIS Python (headless), e.g. on Windows:
    "C:\\Program Files\\QGIS 3.44.12\\bin\\python-qgis-ltr.bat" ^
        rgb_vegetation_analysis.py --ortho ortho.tif --out ./out

See run_veg_analysis.bat / run_veg_analysis.sh for the wrappers.
"""
from __future__ import annotations

import os
import sys
import json
import argparse
from datetime import datetime, timezone

# --- clean env that can break GDAL/PROJ inside QGIS python ------------------
# Only strip PROJ_LIB/PROJ_DATA (a stray global value breaks pyproj); leave
# GDAL_DATA alone because python-qgis-ltr.bat sets it correctly.
for _v in ("PROJ_LIB", "PROJ_DATA"):
    os.environ.pop(_v, None)

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()

# QGIS imports resolve only under the QGIS python (python-qgis-ltr.bat)
from qgis.core import (
    QgsApplication,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
    QgsField,
    QgsFeature,
    QgsFeatureRequest,
    QgsVectorFileWriter,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext,
    QgsDistanceArea,
    QgsUnitTypes,
    QgsPrintLayout,
    QgsLayoutItemMap,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemScaleBar,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsLayoutExporter,
    QgsRectangle,
    QgsSingleBandPseudoColorRenderer,
    QgsSimpleFillSymbolLayer,
    QgsFillSymbol,
    QgsSingleSymbolRenderer,
    QgsMultiBandColorRenderer,
    QgsLayoutMeasurement,
    QgsUnitTypes as _U,
)
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtCore import QVariant, QSizeF


# ----------------------------------------------------------------------------
def log(msg: str) -> None:
    print(f"[veg-analysis] {msg}", flush=True)


def init_qgis() -> QgsApplication:
    """Boot a headless QGIS application (no GUI, no display needed)."""
    # prefix path = QGIS install /apps/qgis-ltr ; derive from python exe folder
    prefix = os.environ.get("QGIS_PREFIX_PATH")
    if not prefix:
        # python-qgis-ltr.bat sets this; fall back to a best guess
        prefix = os.path.join(os.path.dirname(sys.executable), "..", "apps", "qgis-ltr")
    QgsApplication.setPrefixPath(prefix, True)
    app = QgsApplication([], False)  # GUIenabled=False
    app.initQgis()
    return app


def compute_vari(ortho_path: str, vari_path: str, threshold: float):
    """Compute VARI index + binary veg mask from an RGB(A) orthophoto.

    Returns (mask_path, geotransform, wkt_srs, veg_pixel_count, total_valid).
    """
    ds = gdal.Open(ortho_path, gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError(f"cannot open ortho: {ortho_path}")
    nb = ds.RasterCount
    if nb < 3:
        raise RuntimeError(f"ortho has {nb} band(s); need >=3 (R,G,B)")

    red = ds.GetRasterBand(1).ReadAsArray().astype(np.float32)
    grn = ds.GetRasterBand(2).ReadAsArray().astype(np.float32)
    blu = ds.GetRasterBand(3).ReadAsArray().astype(np.float32)

    # validity mask: alpha band if present, else non-zero pixels
    if nb >= 4:
        alpha = ds.GetRasterBand(4).ReadAsArray()
        valid = alpha > 0
    else:
        valid = (red + grn + blu) > 0

    denom = (grn + red - blu)
    denom[denom == 0] = np.nan
    vari = (grn - red) / denom
    vari = np.clip(vari, -1.0, 1.0)
    vari[~valid] = np.nan

    gt = ds.GetGeoTransform()
    srs_wkt = ds.GetProjection()

    # write VARI float raster
    drv = gdal.GetDriverByName("GTiff")
    out = drv.Create(vari_path, ds.RasterXSize, ds.RasterYSize, 1, gdal.GDT_Float32,
                     options=["COMPRESS=DEFLATE", "TILED=YES"])
    out.SetGeoTransform(gt)
    out.SetProjection(srs_wkt)
    ob = out.GetRasterBand(1)
    ob.SetNoDataValue(-9999.0)
    filled = np.where(np.isnan(vari), -9999.0, vari)
    ob.WriteArray(filled)
    ob.FlushCache()
    out = None

    veg_mask = (vari > threshold) & valid & ~np.isnan(vari)
    veg_count = int(veg_mask.sum())
    total_valid = int(valid.sum())

    # write binary mask raster (1 = veg, nodata elsewhere) for polygonize
    mask_path = vari_path.replace(".tif", "_mask.tif")
    mds = drv.Create(mask_path, ds.RasterXSize, ds.RasterYSize, 1, gdal.GDT_Byte,
                     options=["COMPRESS=DEFLATE", "TILED=YES"])
    mds.SetGeoTransform(gt)
    mds.SetProjection(srs_wkt)
    mb = mds.GetRasterBand(1)
    mb.SetNoDataValue(0)
    mb.WriteArray(veg_mask.astype(np.uint8))
    mb.FlushCache()
    mds = None
    ds = None
    return mask_path, srs_wkt, veg_count, total_valid


def polygonize(mask_path: str, srs_wkt: str, gpkg_path: str, min_area_m2: float,
               vari_path: str) -> int:
    """Polygonize the veg mask, filter by area, enrich attrs, save to GeoPackage.

    Returns the number of flagged polygons written.
    """
    mds = gdal.Open(mask_path, gdal.GA_ReadOnly)
    band = mds.GetRasterBand(1)

    srs = osr.SpatialReference()
    srs.ImportFromWkt(srs_wkt)

    mem_drv = ogr.GetDriverByName("Memory")
    mem_ds = mem_drv.CreateDataSource("mem")
    mem_lyr = mem_ds.CreateLayer("veg", srs=srs, geom_type=ogr.wkbPolygon)
    mem_lyr.CreateField(ogr.FieldDefn("dn", ogr.OFTInteger))
    gdal.Polygonize(band, band, mem_lyr, 0, [], callback=None)
    mds = None

    # area filter via QGIS distance-area (ellipsoidal, correct in any CRS)
    qcrs = QgsCoordinateReferenceSystem.fromWkt(srs_wkt)
    da = QgsDistanceArea()
    da.setSourceCrs(qcrs, QgsCoordinateTransformContext())
    if not qcrs.isGeographic():
        da.setEllipsoid(qcrs.ellipsoidAcronym() or "WGS84")
    else:
        da.setEllipsoid("WGS84")

    # sample mean VARI per polygon from the VARI raster
    vds = gdal.Open(vari_path, gdal.GA_ReadOnly)
    vgt = vds.GetGeoTransform()
    vband = vds.GetRasterBand(1)
    inv_gt = gdal.InvGeoTransform(vgt)

    fields = ogr.FeatureDefn

    # build QGIS vector layer for output
    qlayer = QgsVectorLayer(f"Polygon?crs={qcrs.authid() or 'EPSG:4326'}", "vegetation", "memory")
    dp = qlayer.dataProvider()
    dp.addAttributes([
        QgsField("id", QVariant.Int),
        QgsField("area_m2", QVariant.Double),
        QgsField("mean_vari", QVariant.Double),
        QgsField("flag", QVariant.String),
    ])
    qlayer.updateFields()

    from qgis.core import QgsGeometry
    kept = 0
    fid = 0
    for feat in mem_lyr:
        geom = feat.GetGeometryRef()
        if geom is None:
            continue
        wkb = geom.ExportToWkb()
        qgeom = QgsGeometry()
        qgeom.fromWkb(bytes(wkb))
        area = da.measureArea(qgeom)
        area_m2 = da.convertAreaMeasurement(area, QgsUnitTypes.AreaSquareMeters)
        if area_m2 < min_area_m2:
            continue
        # centroid VARI sample
        c = qgeom.centroid().asPoint()
        px = int(inv_gt[0] + inv_gt[1] * c.x() + inv_gt[2] * c.y())
        py = int(inv_gt[3] + inv_gt[4] * c.x() + inv_gt[5] * c.y())
        mean_vari = None
        try:
            arr = vband.ReadAsArray(max(px, 0), max(py, 0), 1, 1)
            if arr is not None and arr[0][0] != -9999.0:
                mean_vari = float(arr[0][0])
        except Exception:
            mean_vari = None
        flag = "dense" if (mean_vari or 0) > 0.35 else "moderate"
        fid += 1
        qf = QgsFeature(qlayer.fields())
        qf.setGeometry(qgeom)
        qf.setAttributes([fid, round(area_m2, 3),
                          round(mean_vari, 4) if mean_vari is not None else None, flag])
        dp.addFeature(qf)
        kept += 1
    qlayer.updateExtents()
    vds = None
    mem_ds = None

    # save to GeoPackage
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    opts.layerName = "vegetation"
    QgsVectorFileWriter.writeAsVectorFormatV3(
        qlayer, gpkg_path, QgsCoordinateTransformContext(), opts)
    return kept, qlayer


def build_pdf(ortho_path: str, gpkg_path: str, pdf_path: str, mission_id: str,
              n_polys: int) -> None:
    """Load ortho + veg polygons, build a Print Layout, export to PDF."""
    project = QgsProject.instance()
    ortho = QgsRasterLayer(ortho_path, "Orthophoto")
    if not ortho.isValid():
        raise RuntimeError("ortho failed to load into QGIS project")
    project.addMapLayer(ortho)

    veg = QgsVectorLayer(f"{gpkg_path}|layername=vegetation", "Vegetation", "ogr")
    if veg.isValid():
        # red semi-transparent fill
        fill = QgsSimpleFillSymbolLayer.create({
            "color": "255,0,0,120",
            "outline_color": "200,0,0,255",
            "outline_width": "0.4",
        })
        sym = QgsFillSymbol()
        sym.changeSymbolLayer(0, fill)
        veg.setRenderer(QgsSingleSymbolRenderer(sym))
        project.addMapLayer(veg)

    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    layout.setName("VegetationReport")

    # map item
    m = QgsLayoutItemMap(layout)
    m.attemptMove(QgsLayoutPoint(15, 30, _U.LayoutMillimeters))
    m.attemptResize(QgsLayoutSize(180, 160, _U.LayoutMillimeters))
    m.setExtent(ortho.extent())
    m.setLayers([lyr for lyr in project.mapLayers().values()])
    layout.addLayoutItem(m)

    # title
    title = QgsLayoutItemLabel(layout)
    ts = (f"Sentinel Aerial Inspections - RGB Vegetation Analysis (VARI)\n"
          f"Mission: {mission_id}   Flagged polygons: {n_polys}   "
          f"Generated: {datetime.now(timezone.utc):%Y-%m-%d %H:%MZ}")
    title.setText(ts)
    title.setFont(QFont("Arial", 10))
    title.attemptMove(QgsLayoutPoint(15, 8, _U.LayoutMillimeters))
    title.attemptResize(QgsLayoutSize(180, 18, _U.LayoutMillimeters))
    layout.addLayoutItem(title)

    # legend
    legend = QgsLayoutItemLegend(layout)
    legend.setTitle("Legend")
    legend.setLinkedMap(m)
    legend.attemptMove(QgsLayoutPoint(200, 30, _U.LayoutMillimeters))
    layout.addLayoutItem(legend)

    # scalebar
    sb = QgsLayoutItemScaleBar(layout)
    sb.setStyle("Single Box")
    sb.setLinkedMap(m)
    sb.applyDefaultSize()
    sb.attemptMove(QgsLayoutPoint(15, 195, _U.LayoutMillimeters))
    layout.addLayoutItem(sb)

    exporter = QgsLayoutExporter(layout)
    settings = QgsLayoutExporter.PdfExportSettings()
    res = exporter.exportToPdf(pdf_path, settings)
    if res != QgsLayoutExporter.Success:
        raise RuntimeError(f"PDF export failed with code {res}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Headless RGB vegetation analysis (VARI)")
    ap.add_argument("--ortho", required=True, help="NodeODM orthophoto.tif (RGB)")
    ap.add_argument("--dsm", default=None, help="optional dsm.tif (reserved for future height gating)")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--mission-id", default="ad-hoc", help="mission label for the report")
    ap.add_argument("--threshold", type=float, default=0.15, help="VARI veg threshold (default 0.15)")
    ap.add_argument("--min-area", type=float, default=2.0, help="min polygon area m2 (default 2.0)")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    vari_path = os.path.join(args.out, "vegetation.tif")
    gpkg_path = os.path.join(args.out, "vegetation.gpkg")
    pdf_path = os.path.join(args.out, "vegetation.pdf")
    summary_path = os.path.join(args.out, "summary.json")

    app = init_qgis()
    try:
        log(f"computing VARI (threshold={args.threshold}) ...")
        mask_path, srs_wkt, veg_px, tot_px = compute_vari(args.ortho, vari_path, args.threshold)
        pct = (100.0 * veg_px / tot_px) if tot_px else 0.0
        log(f"veg pixels: {veg_px}/{tot_px} ({pct:.1f}% of valid area)")

        log(f"polygonizing + area filter (min {args.min_area} m2) ...")
        n_polys, _ = polygonize(mask_path, srs_wkt, gpkg_path, args.min_area, vari_path)
        log(f"flagged polygons: {n_polys} -> {gpkg_path}")

        log("building Print Layout PDF ...")
        build_pdf(args.ortho, gpkg_path, pdf_path, args.mission_id, n_polys)
        log(f"PDF -> {pdf_path}")

        summary = {
            "mission_id": args.mission_id,
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "ortho": os.path.abspath(args.ortho),
            "index": "VARI",
            "threshold": args.threshold,
            "min_area_m2": args.min_area,
            "veg_pixels": veg_px,
            "valid_pixels": tot_px,
            "veg_pct": round(pct, 2),
            "flagged_polygons": n_polys,
            "outputs": {
                "geopackage": os.path.abspath(gpkg_path),
                "pdf": os.path.abspath(pdf_path),
                "vari_raster": os.path.abspath(vari_path),
            },
        }
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)
        log(f"summary -> {summary_path}")
        log("DONE")
        return 0
    finally:
        app.exitQgis()


if __name__ == "__main__":
    sys.exit(main())
