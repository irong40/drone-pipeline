# Requirements: Sentinel Drone Pipeline v2.0

**Defined:** 2026-02-24
**Core Value:** Every script runs reliably, recovers from failures, and has tests proving it works — so the pipeline can be trusted in production without manual babysitting.

## v2.0 Requirements

Requirements for Path E Vegetation Analysis. Each maps to roadmap phases.

### Environment & Setup

- [x] **ENV-01**: Pipeline runs in a dedicated Python 3.12 virtual environment with CUDA-verified PyTorch 2.9.1+cu128 on the RTX 5070
- [x] **ENV-02**: Supabase migration creates vegetation_detections and vegetation_analysis_summary tables with RLS policies
- [x] **ENV-03**: Supabase migration adds vegetation_analysis and vegetation_status columns to missions table
- [x] **ENV-04**: Supabase migration adds vegetation_enabled and vegetation_config columns to processing_templates table
- [x] **ENV-05**: Processing steps enum extended with 4 new step_name values (veg_canopy_detection, veg_species_classification, veg_health_assessment, veg_report_generation)

### Canopy Detection (E1)

- [x] **DET-01**: canopy_detection.py tiles orthomosaic GeoTIFF into 1024px chunks with 128px overlap and runs DeepForest on each tile using CUDA acceleration
- [x] **DET-02**: Cross-tile non-maximum suppression (IoU 0.3) removes duplicate detections from overlap zones in full-ortho coordinate space
- [x] **DET-03**: Canopy polygons exported as GeoPackage and GeoJSON with area (sqm), width, height, centroid GPS, and detection confidence
- [x] **DET-04**: Each detected canopy written to vegetation_detections table in Supabase with geometry and dimensional attributes
- [x] **DET-05**: Detection parameters (tile_size, score_threshold, iou_threshold) are configurable via CLI args and processing_templates.vegetation_config
- [x] **DET-06**: Script clears PROJ_LIB/PROJ_DATA env vars at startup before importing rasterio to prevent QGIS conflicts
- [x] **DET-07**: Script sets GDAL_CACHEMAX=256 and manages tile memory to handle 1GB+ orthomosaics without OOM

### Species Classification (E2)

- [x] **SPE-01**: species_classification.py crops each canopy polygon from orthomosaic with 15% padding and resizes to 512px max dimension
- [x] **SPE-02**: Each crop sent to OpenAI Vision API (gpt-4o) with Hampton Roads species identification prompt covering 20 species
- [x] **SPE-03**: Each crop sent to PlantNet API for independent cross-validation (skippable via --skip-plantnet flag)
- [x] **SPE-04**: Confidence reconciliation: genus match between APIs boosts confidence +0.1, disagreement reduces -0.15
- [x] **SPE-05**: Per-canopy checkpoint resume prevents re-billing for already-classified canopies on script restart
- [x] **SPE-06**: max_canopies cap (default 200) limits API cost by selecting largest canopies by area
- [x] **SPE-07**: 0.5-second delay between API calls respects rate limits; PlantNet remainingIdentificationRequests checked and acted on
- [x] **SPE-08**: Species tag, confidence, vegetation type, cross-validation status, and classification details written to vegetation_detections

### Health Assessment (E3)

- [x] **HLT-01**: health_assessment.py calculates VARI, ExG, Green Fraction, and Stress Fraction indices for every detected canopy using rasterio and NumPy
- [x] **HLT-02**: Configurable sample (default 30%) of canopies sent to OpenAI Vision API for qualitative health assessment (skippable via --skip-vision)
- [x] **HLT-03**: Combined health score weights 40% index + 60% vision when both available; index-only when vision skipped
- [x] **HLT-04**: Health status categorized: healthy (0.80-1.00), moderate_stress (0.60-0.79), stressed (0.40-0.59), severe_decline (0.20-0.39), dead (0.00-0.19)
- [x] **HLT-05**: Health score, status, and details (VARI data, vision results, observations, recommended action) written to vegetation_detections
- [x] **HLT-06**: Per-canopy checkpoint resume prevents re-billing for already-assessed canopies

### Report Generation (E4)

- [x] **RPT-01**: vegetation_report.py generates branded PDF report with executive summary, species distribution table, health overview, annotated maps, attention list, and methodology disclaimer
- [x] **RPT-02**: Species overlay map PNG rendered on orthomosaic with color-coded canopy polygons by species
- [x] **RPT-03**: Health overlay map PNG rendered on orthomosaic with color-coded canopy polygons by health status
- [x] **RPT-04**: GeoJSON export with all canopy attributes for QGIS/ArcGIS/web mapping import
- [x] **RPT-05**: Interactive Folium HTML map with satellite basemap, clickable canopy popups (species, confidence, health, action), layer toggle, under 10MB
- [x] **RPT-06**: PDF carries Sentinel branding, FAA Part 107 statement, veteran-owned designation, forest green (#1B4332) headers
- [x] **RPT-07**: Methodology disclaimer states classifications are AI-generated and do not replace ground-level arborist assessment
- [x] **RPT-08**: vegetation_analysis_summary row written to Supabase with aggregate statistics (canopy count, coverage, species distribution, health distribution, API costs, processing time, file paths)
- [x] **RPT-09**: Folium map uses single GeoJson layer, smooth_factor=1, coordinate precision reduced to 6 decimals, geometry simplified for performance

### Integration & Delivery

- [ ] **INT-01**: n8n Path E workflow triggers when mission.vegetation_analysis=true AND Path C orthomosaic exists
- [ ] **INT-02**: Package Router updated: site_survey and environmental_survey enable vegetation by default; construction_hybrid optional
- [x] **INT-03**: Operator review gate pauses processing after E4 with approve/exclude/flag-for-arborist actions per detection
- [x] **INT-04**: Review resume webhook (POST /sentinel-vegetation-resume) accepts decisions array and regenerates report excluding excluded detections
- [x] **INT-05**: delivery_packaging.py adds vegetation/ subfolder to client ZIP with PDF, species map, health map, GeoJSON, and optional interactive map
- [x] **INT-06**: Path E failure never blocks main delivery package; --include-vegetation flag gated on vegetation_status='complete'
- [ ] **INT-07**: All 4 scripts follow v1.0 contract: argparse inputs, processing_steps row updates, JSON stdout, exit codes 0/1/2, setup_logging()

### Testing

- [x] **TST-01**: Unit tests for canopy_detection.py covering tiling, NMS, polygon export, and Supabase writes with mocked GPU/rasterio
- [x] **TST-02**: Unit tests for species_classification.py covering crop extraction, API calls, confidence reconciliation, checkpoint resume with mocked APIs
- [x] **TST-03**: Unit tests for health_assessment.py covering VARI/ExG calculation, vision sampling, score combination with mocked APIs
- [x] **TST-04**: Unit tests for vegetation_report.py covering PDF generation, map rendering, Folium output, summary writes
- [x] **TST-05**: Integration test: E1 → E2 → E3 → E4 end-to-end with sample orthomosaic and mocked APIs
- [x] **TST-06**: Integration test: delivery_packaging.py includes vegetation subfolder when --include-vegetation is set

## v3.0 Requirements (Deferred)

### Local Classifier

- **LC-01**: Fine-tuned EfficientNet/ResNet classifier trained on 50+ ground truth missions for Hampton Roads species
- **LC-02**: Local model runs on RTX 5070 with zero API cost per canopy
- **LC-03**: OpenAI Vision becomes fallback for low-confidence predictions

### Advanced Analysis

- **ADV-01**: Multispectral NDVI health mapping (requires multispectral camera)
- **ADV-02**: Change detection between repeat surveys of same property
- **ADV-03**: 3D canopy height models from photogrammetric DSM/DTM
- **ADV-04**: ADIAT Color Range for invasive species detection

## Out of Scope

| Feature | Reason |
|---------|--------|
| Multispectral NDVI analysis | Requires hardware not yet acquired |
| Invasive species treatment recommendations | Outside aviation service scope |
| Certified arborist report certification | Requires licensed arborist, not an AI capability |
| Tree risk assessment (TRA) ratings | Requires ground-level and structural assessment |
| Ground level trunk diameter measurements | Cannot measure from aerial imagery |
| Historical growth tracking | Requires repeat surveys — v3.0 |
| Client-facing vegetation portal UI | Trestle app scope, not pipeline |
| Local fine-tuned classification model | Requires 50+ ground truth missions first — v3.0 |
| Change detection between surveys | Requires repeat data — v3.0 |
| GUI/web interface for pipeline | CLI-only pipeline architecture |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| ENV-01 | Phase 7 | Complete |
| ENV-02 | Phase 7 | Complete (07-02) |
| ENV-03 | Phase 7 | Complete (07-02) |
| ENV-04 | Phase 7 | Complete (07-02) |
| ENV-05 | Phase 7 | Complete (07-02) |
| DET-01 | Phase 8 | Complete |
| DET-02 | Phase 8 | Complete |
| DET-03 | Phase 8 | Complete |
| DET-04 | Phase 8 | Complete |
| DET-05 | Phase 8 | Complete |
| DET-06 | Phase 8 | Complete |
| DET-07 | Phase 8 | Complete |
| SPE-01 | Phase 9 | Complete |
| SPE-02 | Phase 9 | Complete |
| SPE-03 | Phase 9 | Complete |
| SPE-04 | Phase 9 | Complete |
| SPE-05 | Phase 9 | Complete |
| SPE-06 | Phase 9 | Complete |
| SPE-07 | Phase 9 | Complete |
| SPE-08 | Phase 9 | Complete |
| HLT-01 | Phase 10 | Complete (10-01) |
| HLT-02 | Phase 10 | Complete (10-01) |
| HLT-03 | Phase 10 | Complete (10-01) |
| HLT-04 | Phase 10 | Complete (10-01) |
| HLT-05 | Phase 10 | Complete (10-01) |
| HLT-06 | Phase 10 | Complete (10-01) |
| RPT-01 | Phase 11 | Complete (11-02) |
| RPT-02 | Phase 11 | Complete (11-01) |
| RPT-03 | Phase 11 | Complete (11-01) |
| RPT-04 | Phase 11 | Complete (11-01) |
| RPT-05 | Phase 11 | Complete (11-01) |
| RPT-06 | Phase 11 | Complete (11-02) |
| RPT-07 | Phase 11 | Complete (11-02) |
| RPT-08 | Phase 11 | Complete (11-02) |
| RPT-09 | Phase 11 | Complete (11-01) |
| INT-01 | Phase 12 | Pending |
| INT-02 | Phase 12 | Pending |
| INT-03 | Phase 12 | Complete |
| INT-04 | Phase 12 | Complete |
| INT-05 | Phase 12 | Complete |
| INT-06 | Phase 12 | Complete |
| INT-07 | Phase 12 | Pending |
| TST-01 | Phase 13 | Complete |
| TST-02 | Phase 13 | Complete |
| TST-03 | Phase 13 | Complete |
| TST-04 | Phase 13 | Complete |
| TST-05 | Phase 13 | Complete |
| TST-06 | Phase 13 | Complete |

**Coverage:**
- v2.0 requirements: 48 total (ENV×5 + DET×7 + SPE×8 + HLT×6 + RPT×9 + INT×7 + TST×6)
- Mapped to phases: 48
- Unmapped: 0

*Note: REQUIREMENTS.md originally stated 37 total. Actual count after enumerating all defined requirements is 48. The stated count was a pre-write placeholder.*

---
*Requirements defined: 2026-02-24*
*Last updated: 2026-02-25 — ENV-02/03/04/05 marked complete (07-02 Supabase migration)*
