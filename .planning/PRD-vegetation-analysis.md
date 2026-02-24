# Sentinel Aerial Inspections — Vegetation Analysis Service PRD v1.0

> Saved from user input on 2026-02-24. Source of truth for v2.0 milestone requirements.

<!-- Full PRD content preserved for reference by research and planning agents -->

## 1. Executive Summary

Path E of the Sentinel post-flight processing pipeline. Automated vegetation identification, species classification, and health assessment. Extends existing pipeline without modifying Paths A through V.

Input: Completed orthomosaic from Path C (WebODM or MipMap Desktop).
Output: Branded vegetation analysis report with species distribution, health indicators, annotated map overlays, and optional interactive web map.

**Business case:** Manual arborist surveys cost $800-$2,000/visit, 5-10 day turnaround. Sentinel delivers comparable results in 24-48 hours. $200-$500 addon per mission, $1-$5 API cost, 95%+ margins.

## 2. Processing Flow

| Step | Script | Input | Output | Tools |
|------|--------|-------|--------|-------|
| E1 | canopy_detection.py | Orthomosaic GeoTIFF | GeoPackage + GeoJSON with canopy polygons | DeepForest, rasterio, GeoPandas |
| E2 | species_classification.py | Canopy polygons + ortho crops | Species tags with confidence scores | OpenAI Vision API, PlantNet API |
| E3 | health_assessment.py | Canopy polygons + ortho | Health scores and status per canopy | VARI/ExG indices, OpenAI Vision API |
| E4 | vegetation_report.py | All prior outputs | PDF, maps, charts, interactive HTML | ReportLab, matplotlib, Folium |

## 3. Dependencies

- DeepForest (pretrained canopy detection, CUDA accelerated)
- PyTorch 2.7+ with CUDA 12.8+ (RTX 5070 sm_120)
- rasterio (GeoTIFF reading, tiling, masking)
- GeoPandas + Shapely (spatial operations)
- OpenAI Vision API (gpt-4o) for species classification and health assessment
- PlantNet API (free research tier) for cross-validation
- ReportLab (PDF generation)
- matplotlib (charts)
- Folium (interactive Leaflet.js maps)

## 4. Database Schema

### New Tables

**vegetation_detections** — One row per detected canopy (populated across E1-E3)
- id, mission_id, detection_index, geometry_wkt, centroid_lat/lon
- canopy_area_sqm, canopy_width_m, canopy_height_m, detection_confidence
- species_tag, species_confidence, vegetation_type, cross_validated, classification_details (JSONB)
- health_score, health_status, health_details (JSONB)

**vegetation_analysis_summary** — One row per mission (written by E4)
- mission_id, site_area_sqm/acres, total_canopy_count, canopy_coverage_pct
- unique_species_count, species_distribution (JSONB), avg_health_score, health_distribution (JSONB)
- needs_attention_count, api_calls_total, processing_time_seconds
- pdf_report_path, species_map_path, health_map_path, geojson_path, interactive_map_path

### Schema Modifications
- missions: +vegetation_analysis (BOOLEAN), +vegetation_status (enum)
- processing_templates: +vegetation_enabled (BOOLEAN), +vegetation_config (JSONB)
- processing_steps: +4 new step_name values (veg_canopy_detection, veg_species_classification, veg_health_assessment, veg_report_generation)

## 5. n8n Integration

Path E triggered when mission.vegetation_analysis = true AND Path C ortho exists.
Default enabled for: site_survey, environmental_survey.
Optional for: construction_hybrid.

Workflow nodes: E0 (Check Ortho) → E1 → E2 → E3 → E4 → E5 (Review Gate)
Review resume webhook: POST /sentinel-vegetation-resume

## 6. Delivery

Output in delivery ZIP under vegetation/ subfolder:
- Sentinel_{address}_Vegetation_Report.pdf (always)
- Sentinel_{address}_Species_Map.png (always)
- Sentinel_{address}_Health_Map.png (always)
- Sentinel_{address}_Canopy_Detections.geojson (always)
- Sentinel_{address}_Interactive_Map.html (premium tiers only)

## 7. Pricing

| Tier | Price |
|------|-------|
| Standard | $200 |
| Extended (+ interactive map) | $350 |
| Comprehensive (+ ground truth walk) | $500 |
| Processing Only (client provides ortho) | $200-$350 |
| Arborist Partnership (flight + analysis) | $400-$600 |

## 8. Configurable Parameters

| Parameter | Default | Script |
|-----------|---------|--------|
| tile_size | 1024 | E1 |
| score_threshold | 0.3 | E1 |
| iou_threshold | 0.3 | E1 |
| max_canopies | 200 | E2 |
| skip_plantnet | false | E2 |
| vision_sample_pct | 0.3 | E3 |
| skip_vision | false | E3 |

## 9. Open Questions

| ID | Question | Status |
|----|----------|--------|
| OQ1 | environmental_survey: new package_type or flag on site_survey? | OPEN |
| OQ2 | Minimum orthomosaic GSD for reliable canopy detection? | OPEN |
| OQ3 | Interactive map measurement tools (area, distance)? | OPEN |
| OQ4 | PlantNet 500 req/day limit sufficient? | OPEN |
| OQ5 | Standalone vegetation analysis without ortho package? | OPEN |
| OQ6 | Arborist-supplied imagery intake workflow? | OPEN |
| OQ7 | Arborist partnership flat rate vs acreage tiered? | OPEN |

## 10. Implementation Phases (from PRD)

1. Core Pipeline (Week 1-2): DeepForest install, E1-E3 standalone testing
2. Report and Review (Week 2-3): E4 report gen, Supabase migration, review UI
3. n8n Integration (Week 3-4): Workflow, package router, end-to-end test
4. Ground Truth Baseline (Ongoing): First 5-10 missions, accuracy tracking

## 11. Out of Scope (v2.0)

- Multispectral NDVI analysis
- Invasive species treatment recommendations
- Certified arborist report certification
- Tree risk assessment (TRA) ratings
- Ground level trunk diameter measurements
- Historical growth tracking across missions
- Client-facing vegetation portal UI
- Local fine-tuned classification model
- Change detection between repeat surveys
