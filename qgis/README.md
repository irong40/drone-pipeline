# Headless RGB Vegetation Analysis (QGIS)

Deliverable 2 of the QGIS setup. A GUI-free `qgis_process` / PyQGIS analysis that
turns a NodeODM RGB orthophoto into flagged vegetation polygons + an auto PDF.

## Why VARI (not NDVI)

The Mini 4 Pro is **RGB-only** (no near-infrared), so NDVI is impossible.
**VARI** (Visible Atmospherically Resistant Index) is the correct RGB greenness
index:

```
VARI = (Green - Red) / (Green + Red - Blue)
```

Higher VARI = greener / healthier visible vegetation. The script flags contiguous
vegetation above a threshold (default `0.15`) larger than a minimum area
(default `2 m2`) - useful for vegetation-encroachment / right-of-way work.

## Files

| File | Purpose |
|------|---------|
| `rgb_vegetation_analysis.py` | The headless PyQGIS analysis (VARI -> polygons -> GeoPackage + PDF) |
| `run_veg_analysis.bat` | Windows wrapper - invokes QGIS-LTR python, no GUI |
| `run_veg_analysis.sh` | POSIX wrapper - Git Bash **or** WSL (shells to Windows QGIS) |
| `veg_watch.py` | Filesystem watcher that fires the analysis on new orthophotos |
| `make_sample_ortho.py` | Generates a synthetic RGB ortho for smoke-testing |

## Run it

```bat
run_veg_analysis.bat "C:\path\to\odm_orthophoto.tif" ".\out" ZV-0142
```

or directly with the QGIS python:

```bat
"C:\Program Files\QGIS 3.44.12\bin\python-qgis-ltr.bat" ^
    rgb_vegetation_analysis.py --ortho ortho.tif --out .\out --mission-id ZV-0142
```

Options: `--threshold 0.15`, `--min-area 2.0`, `--dsm dsm.tif` (reserved for
future height-gating; the DSM is accepted but not yet used in the index).

### Outputs (written to `--out`)

- `vegetation.gpkg` - polygons with `id, area_m2, mean_vari, flag` (dense/moderate)
- `vegetation.pdf` - Print Layout: ortho + red veg overlay + title + legend + scalebar
- `vegetation.tif` - the VARI float raster (-1..1, nodata -9999)
- `summary.json` - machine-readable run summary

## Smoke test (verified 2026-07-09 on QGIS 3.44.12)

```bash
"C:\Program Files\QGIS 3.44.12\bin\python-qgis-ltr.bat" make_sample_ortho.py sample/sample_ortho.tif
"C:\Program Files\QGIS 3.44.12\bin\python-qgis-ltr.bat" rgb_vegetation_analysis.py \
    --ortho sample/sample_ortho.tif --out out --mission-id SMOKE-TEST
```

Actual result: VARI computed (12.1% veg pixels), **2 polygons** flagged
(63.6 m2 @ VARI 0.53, 15.9 m2 @ VARI 0.42), a sub-2 m2 speck correctly filtered,
`vegetation.pdf` (1.2 MB) + `vegetation.gpkg` (EPSG:32618) exported. Exit 0.

> The `sample/` and `out/` folders are throwaway test artifacts and are
> git-ignored (see repo `.gitignore` addition). Delete them anytime.

## qgis_process CLI equivalents (reference)

The script does everything in one headless PyQGIS process (needed for the
`QgsLayoutExporter` PDF step). The raster/vector steps map to these
`qgis_process` calls if you ever want them standalone:

```bat
set QP="C:\Program Files\QGIS 3.44.12\bin\qgis_process-qgis-ltr.bat"

REM 1) VARI via GDAL raster calculator (bands A=Red B=Green C=Blue)
%QP% run gdal:rastercalculator ^
  --INPUT_A ortho.tif --BAND_A 1 --INPUT_B ortho.tif --BAND_B 2 ^
  --INPUT_C ortho.tif --BAND_C 3 ^
  --FORMULA "(B-A)/(B+A-C)" --OUTPUT vari.tif

REM 2) threshold -> mask (native raster calc)
%QP% run native:rastercalc --LAYERS vari.tif ^
  --EXPRESSION "\"vari@1\" > 0.15" --OUTPUT mask.tif

REM 3) polygonize
%QP% run gdal:polygonize --INPUT mask.tif --FIELD DN --OUTPUT veg.gpkg

REM 4) area filter
%QP% run native:extractbyexpression --INPUT veg.gpkg ^
  --EXPRESSION "$area > 2" --OUTPUT veg_flagged.gpkg
```

The Print Layout PDF has no clean `qgis_process` equivalent, which is why the
production path is the single PyQGIS script.

## Triggering on NodeODM completion

NodeODM runs in WSL2 docker (`localhost:3000`); QGIS is a Windows install. So
fire the analysis **after** the ortho lands on the Windows side. Two options:

### Option A - n8n Execute Command node (recommended; n8n is the orchestrator)

Add an **Execute Command** node after the step that downloads the ODM ortho:

```
Command: cmd /c "C:\Users\redle.SOULAAN\Documents\drone-pipeline\qgis\run_veg_analysis.bat" "{{$json.orthoPath}}" "{{$json.outDir}}" "{{$json.missionId}}"
```

Wire it off the same completion event the pipeline already uses (the existing
`folder_watcher.py` -> n8n webhook path). It runs synchronously and returns the
exit code so n8n can branch on success/failure.

### Option B - standalone filesystem watcher (no n8n)

```bat
python veg_watch.py --watch-dir "I:\My Drive\Drone Facility Plans" ^
                    --pattern "*orthophoto*.tif" --debounce 30
```

Register as a Scheduled Task (logon trigger) if you want it always-on. It
debounces 30 s so the ortho is fully written before analysis, then drops a
`vegetation/` output folder next to each ortho.

> If you would rather trigger from **inside WSL** the moment a NodeODM task
> reports complete, call `run_veg_analysis.sh` from your WSL post-task hook - it
> auto-detects WSL and shells out to the Windows QGIS python via `cmd.exe`.

## A Processing model (.model3)?

A `.model3` was **not** shipped. Hand-authoring valid model JSON is error-prone
and can only be validated in the GUI (which this environment cannot drive). The
single PyQGIS script is the reliable, reproducible artifact. If you want a
`.model3`, build it in the Graphical Modeler - that is exactly the exercise in
`../LEARN_QGIS.md` step 5, and the CLI block above gives you the algorithm chain
to reproduce.
