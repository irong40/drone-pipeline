---
phase: 11-report-generation
plan: 01
subsystem: reporting
tags: [matplotlib, rasterio, folium, geopandas, shapely, geojson, png-maps, interactive-map]

# Dependency graph
requires:
  - phase: 10-health-assessment
    provides: health_score, health_status, health_details per vegetation_detections row
  - phase: 09-species-classification
    provides: species_tag, species_confidence per vegetation_detections row
  - phase: 08-canopy-detection
    provides: geometry_wkt, detection_index, canopy_area_sqm per vegetation_detections row
provides:
  - generate_species_map(): 20-species color-coded PNG overlay at 300 DPI
  - generate_health_map(): 5-status health color-coded PNG overlay at 300 DPI
  - export_geojson(): EPSG:4326 GeoJSON with all canopy attributes, 6-decimal precision
  - generate_folium_map(): Esri satellite interactive HTML map with clickable canopy popups
  - generate_all_outputs(): tier-aware orchestrator writing vegetation_analysis_summary to Supabase
affects: [12-integration-and-delivery, 13-test-suite-and-acceptance]

# Tech tracking
tech-stack:
  added: [matplotlib (Agg backend), rasterio.plot, folium, geopandas, shapely.set_precision, pyproj]
  patterns:
    - ENV cleanup block before rasterio/pyproj imports (PROJ_LIB/PROJ_DATA pop)
    - matplotlib.use("Agg") set before pyplot import for headless rendering
    - SPECIES_COLORS and HEALTH_COLORS dicts as single source of truth for palette
    - style_function closure for Folium GeoJson layer coloring
    - File size guard with two-pass simplification (FOLIUM_SIMPLIFY_INITIAL -> FOLIUM_SIMPLIFY_AGGRESSIVE)

key-files:
  created:
    - vegetation_report.py — E4 map generation: species PNG, health PNG, GeoJSON, Folium HTML, Supabase summary write
  modified: []

key-decisions:
  - "matplotlib Agg backend set before pyplot import — headless servers have no display; Agg must be set first to avoid TkAgg or Qt errors"
  - "Folium two-pass simplification: FOLIUM_SIMPLIFY_INITIAL=5e-6 first, then FOLIUM_SIMPLIFY_AGGRESSIVE=2e-5 only if file > 10MB — avoids over-simplification for small missions"
  - "Folium GeoJson popup uses parse_html=True with popup_html property — richer HTML popups than GeoJsonPopup fields allow"
  - "GeoJSON export uses shapely.set_precision(grid_size=1e-6) for 6-decimal coordinate rounding — falls back gracefully if shapely version lacks set_precision"
  - "Folium interactive map is tier-gated (extended/comprehensive only) — standard tier generates PNG + GeoJSON only per PRD"
  - "generate_folium_map() accepts ortho_bounds tuple (left,bottom,right,top) in WGS84 — caller reprojects if ortho CRS is not EPSG:4326"

patterns-established:
  - "Tier gating: check tier in ('extended', 'comprehensive') before generating premium outputs"
  - "Graceful ortho bounds fallback: reproject to WGS84 from ortho CRS using pyproj.Transformer"
  - "Recommended action extraction: _recommended_action_from_det() traverses det -> health_details.vision -> health_status fallback"
  - "North arrow + scale bar + Sentinel branding decorations applied to every PNG map"

requirements-completed: [RPT-02, RPT-03, RPT-04, RPT-09]

# Metrics
duration: 3min
completed: 2026-02-25
---

# Phase 11 Plan 01: Map Generation Summary

**Species overlay PNG, health overlay PNG, EPSG:4326 delivery GeoJSON, and interactive Folium map with Esri satellite basemap and clickable canopy popups**

## Performance

- **Duration:** ~3 min 25 sec
- **Started:** 2026-02-25T16:06:31Z
- **Completed:** 2026-02-25T16:09:56Z
- **Tasks:** 2
- **Files created:** 1

## Accomplishments

- `generate_species_map()`: renders orthomosaic basemap via rasterio.plot.show(), overlays canopy polygons with 20-species color palette (SPECIES_COLORS), adds legend, north arrow, scale bar, Sentinel branding, saves at 300 DPI
- `generate_health_map()`: same rendering pattern but colors by health_status (healthy=#22C55E through dead=#000000), legend ordered by severity
- `export_geojson()`: builds GeoDataFrame, reprojects to EPSG:4326 if needed, reduces coordinate precision with shapely.set_precision(1e-6), exports via geopandas to_file(driver="GeoJSON")
- `generate_folium_map()`: Esri World Imagery satellite tile layer, single GeoJson layer with style_function coloring by species, clickable HTML popups (species/confidence/health score/recommended action), LayerControl, 10MB file size guard with 2-pass simplification
- `generate_all_outputs()`: tier-aware orchestrator, fetches detections from Supabase, builds safe filename from job_name, writes vegetation_analysis_summary row

## Task Commits

Each task was committed atomically:

1. **Task 1: Species and health overlay map PNGs** - `edafcae` (feat) — included in combined commit with Task 2
2. **Task 2: GeoJSON export and Folium interactive map** - `edafcae` (feat) — same file, combined commit

**Plan metadata:** (docs commit to follow)

## Files Created/Modified

- `C:/Users/redle/drone-pipeline/vegetation_report.py` — E4 step: map PNGs, GeoJSON, Folium HTML, Supabase summary write, argparse CLI, PipelineStatusReporter integration

## Decisions Made

- **matplotlib Agg backend:** Must be set before pyplot import on headless systems — avoids display errors in server/n8n context. `matplotlib.use("Agg")` placed immediately after matplotlib import.
- **Folium two-pass simplification:** Initial simplify(5e-6) is subtle (~0.5m); only aggressive simplify(2e-5) (~2m) runs if file exceeds 10MB. Avoids over-simplification for small missions with few canopies.
- **Folium popup via parse_html=True:** Using `GeoJsonPopup(fields=["popup_html"], parse_html=True)` allows full HTML table styling in popups — richer than raw field aliases.
- **GeoJSON coordinate precision:** `shapely.set_precision(grid_size=1e-6)` with graceful fallback for older shapely versions that lack `set_precision`.
- **Folium tier gate:** `extended` and `comprehensive` tiers generate HTML; `standard` generates PNG + GeoJSON only — matches PRD delivery spec.
- **Recommended action extraction:** `_recommended_action_from_det()` checks `det.recommended_action` -> `health_details.vision.recommended_action` -> inferred from `health_status` — handles missing data from skipped vision calls.

## Deviations from Plan

None — plan executed exactly as written. Both tasks completed in a single file with all specified functions.

## Issues Encountered

None. Script imported cleanly, all 20 species colors loaded, all 5 health status colors loaded, all 5 public functions verified callable.

## User Setup Required

None — no external service configuration required. Supabase credentials (SUPABASE_URL, SUPABASE_SERVICE_KEY) are already configured from prior phases.

## Next Phase Readiness

- `vegetation_report.py` (E4) is complete for map generation. Phase 11-02 (PDF report) can now build the ReportLab PDF layer using the same `fetch_detections()` and `generate_all_outputs()` orchestration pattern.
- All 4 map/export functions are independently callable — can be tested against a real orthomosaic without the full pipeline.
- Folium map verified importable; rendering requires real detections with valid WKT geometry.

---
*Phase: 11-report-generation*
*Completed: 2026-02-25*
