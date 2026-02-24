# Architecture Research

**Domain:** Path E — Vegetation Analysis Integration into Existing Drone Pipeline
**Researched:** 2026-02-24
**Confidence:** HIGH (based on direct codebase audit of all 14 existing scripts + planning docs)

---

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     n8n Orchestration Layer                      │
│  Package Router → Path C Complete? → Veg Enabled? → Path E      │
│                                               E5 Review Gate     │
└─────────────────────────────────────────────────────────────────┘
                              │ Execute Command nodes
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Path E Script Layer (NEW)                      │
│  ┌────────────┐  ┌───────────────────┐  ┌──────────────────┐   │
│  │ E1 canopy_ │→ │ E2 species_       │→ │ E3 health_       │   │
│  │ detection  │  │ classification    │  │ assessment       │   │
│  └────────────┘  └───────────────────┘  └──────────────────┘   │
│         └──────────────────────────────────────┘                │
│                             │ outputs feed E4                    │
│                     ┌───────────────┐                           │
│                     │ E4 vegetation_│                           │
│                     │ report        │                           │
│                     └───────────────┘                           │
└─────────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼────────────────────┐
          ▼                   ▼                    ▼
┌──────────────────┐  ┌──────────────┐  ┌──────────────────────┐
│ File System      │  │ Supabase DB  │  │ External APIs        │
│ vegetation/      │  │ (NEW tables) │  │ OpenAI Vision        │
│ ├─ canopy.gpkg   │  │ vegetation_  │  │ PlantNet             │
│ ├─ species/      │  │ detections   │  │ (E2, E3 only)        │
│ ├─ health/       │  │ vegetation_  │  └──────────────────────┘
│ └─ report/       │  │ analysis_    │
│                  │  │ summary      │
│ delivery/        │  │             │
│ └─ vegetation/   │  │ (MODIFIED)  │
│   ├─ Report.pdf  │  │ missions     │
│   ├─ Species.png │  │ processing_  │
│   ├─ Health.png  │  │ templates    │
│   ├─ Detect.json │  └──────────────┘
│   └─ Map.html*   │
└──────────────────┘
                        * premium tiers only
```

### Component Responsibilities

| Component | Responsibility | Follows Existing Pattern? |
|-----------|---------------|--------------------------|
| E1 `canopy_detection.py` | Tile ortho GeoTIFF, run DeepForest inference, output GeoPackage + GeoJSON polygons | YES — argparse, checkpoint, JSON stdout, supabase update |
| E2 `species_classification.py` | Crop canopy patches, call OpenAI Vision + PlantNet, tag species on detections rows | YES — same contract; checkpoint critical (API cost) |
| E3 `health_assessment.py` | Compute VARI/ExG on each canopy mask, optional Vision API, write health_score | YES — same contract; Vision API calls checkpointed |
| E4 `vegetation_report.py` | Read all prior outputs, generate PDF + maps + HTML, write summary row | YES — no checkpoint needed (single-pass, no loops) |
| `checkpoint.py` | Existing shared utility — E2/E3 use it for per-canopy resume | REUSE AS-IS |
| `delivery_packaging.py` | Existing script — needs `--include-vegetation` flag and `collect_vegetation()` function added | MODIFY (additive only) |
| Supabase migration | New tables + column additions | NEW migration file (never edit existing) |

---

## Recommended Project Structure

```
drone-pipeline/
├── canopy_detection.py        # E1 — NEW
├── species_classification.py  # E2 — NEW
├── health_assessment.py       # E3 — NEW
├── vegetation_report.py       # E4 — NEW
├── checkpoint.py              # shared utility — REUSE
├── delivery_packaging.py      # MODIFY (add collect_vegetation + --include-vegetation)
├── requirements.txt           # ADD: deepforest, torch, rasterio, geopandas, shapely,
│                              #       reportlab, matplotlib, folium, openai
├── tests/
│   ├── test_canopy_detection.py      # NEW
│   ├── test_species_classification.py # NEW
│   ├── test_health_assessment.py     # NEW
│   ├── test_vegetation_report.py     # NEW
│   └── test_delivery_packaging.py    # UPDATE (add vegetation tests)
└── .planning/
    └── milestones/
        └── v2.0-vegetation/
            └── migration_001_vegetation.sql   # NEW — never edit applied migrations
```

**Mission folder structure additions:**

```
SAI_M0047_site_survey_20260218/
├── photos/raw/
├── photos/jpeg/
├── mapping/
│   └── odm_orthophoto.tif          # INPUT to E1 (from Path C output)
├── vegetation/                      # NEW top-level subfolder
│   ├── canopy_detections.gpkg       # E1 output (GeoPackage, source of truth)
│   ├── canopy_detections.geojson    # E1 output (delivery copy)
│   ├── species/
│   │   └── crops/                  # E2 canopy patch crops (PNG tiles)
│   ├── health/
│   │   └── indices/                # E3 per-canopy VARI/ExG rasters (optional)
│   └── report/
│       ├── Sentinel_{address}_Vegetation_Report.pdf
│       ├── Sentinel_{address}_Species_Map.png
│       ├── Sentinel_{address}_Health_Map.png
│       └── Sentinel_{address}_Interactive_Map.html  (premium)
├── .checkpoint_canopy_detection.json    # tile-level resume
├── .checkpoint_species_classification.json # per-canopy resume (API calls)
└── .checkpoint_health_assessment.json   # per-canopy resume (Vision API calls)
```

### Structure Rationale

- **`vegetation/` subfolder:** Mirrors existing conventions — `video/`, `photos/`, `mapping/` are top-level sibling folders. Keeps E outputs isolated from Path C ortho inputs.
- **`canopy_detections.gpkg` as source of truth:** GeoPackage is the authoritative polygon store, updated by E2 and E3. The GeoJSON is a delivery copy written at the end, not the working file.
- **`vegetation/report/` subfolder:** Isolates the 3-5 large output files from working data. delivery_packaging.py walks `vegetation/report/` for the delivery ZIP, not the full `vegetation/` tree.
- **Checkpoint files in mission root:** Matches the established pattern (`.checkpoint_{script_name}.json` in mission folder root).

---

## Architectural Patterns

### Pattern 1: Script Contract (E1-E4 must match exactly)

**What:** Every Path E script follows the same structural contract as the 14 existing scripts.

**Contract requirements:**
```python
"""
Sentinel Aerial Inspections — [Script Title] (Step E[N])

[Description]

Usage:
    python script.py path/to/mission --mission-id UUID
    python script.py path/to/mission --mission-id UUID --dry-run
    python script.py path/to/mission --mission-id UUID --force
"""

# ─── CONFIG ───────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
LOG_DIR = r"E:\Sentinel\logs"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")   # E2, E3 only

# Required argparse flags:
# mission_path     (positional)
# --mission-id     (required, Supabase UUID)
# --dry-run        (action="store_true")
# --force          (action="store_true", clears checkpoint)

# Required exit codes:
# 0 = success
# 1 = partial failure (some canopies failed, others succeeded)
# 2 = fatal failure (no output produced)

# Required JSON stdout on success:
# print(json.dumps({...summary...}))
# n8n reads this via "Parse JSON" node
```

**JSON stdout shape for E1-E4:**
```python
# E1 output — n8n reads canopy_count to decide if E2 should run
print(json.dumps({
    "mission_id": mission_id,
    "step": "veg_canopy_detection",
    "canopy_count": int,
    "gpkg_path": str,
    "geojson_path": str,
    "site_area_sqm": float,
    "processing_time_seconds": float,
    "status": "ok" | "partial" | "failed"
}))

# E2 output
print(json.dumps({
    "mission_id": mission_id,
    "step": "veg_species_classification",
    "classified_count": int,
    "skipped_count": int,       # over max_canopies threshold
    "api_calls_used": int,
    "status": "ok" | "partial" | "failed"
}))

# E3 output
print(json.dumps({
    "mission_id": mission_id,
    "step": "veg_health_assessment",
    "assessed_count": int,
    "needs_attention_count": int,
    "avg_health_score": float,
    "status": "ok" | "partial" | "failed"
}))

# E4 output
print(json.dumps({
    "mission_id": mission_id,
    "step": "veg_report_generation",
    "pdf_path": str,
    "species_map_path": str,
    "health_map_path": str,
    "geojson_path": str,
    "interactive_map_path": str | None,
    "status": "ok" | "failed"
}))
```

**When to use:** All 4 Path E scripts without exception.
**Trade-offs:** Slightly more boilerplate per script, but n8n can use identical node patterns to parse all 4 outputs.

---

### Pattern 2: Checkpoint Strategy (per-item key, atomic write)

**What:** Use the existing `checkpoint.py` module unchanged. The checkpoint "completed items set" stores unique keys per item processed.

**E1 — Tile-level checkpoint (moderate granularity):**
```python
from checkpoint import load_checkpoint, save_checkpoint, clear_checkpoint

SCRIPT_NAME = "canopy_detection"
completed = load_checkpoint(mission_path, SCRIPT_NAME)

# Key = tile identifier (row_col or tile index)
for tile_idx, tile in enumerate(tiles):
    item_key = f"tile_{tile_idx}"
    if item_key in completed:
        log.info(f"  Skip (checkpoint): {item_key}")
        continue

    polygons = run_deepforest_on_tile(tile)
    save_detections_to_gpkg(polygons, tile_idx)   # append to GeoPackage

    completed.add(item_key)
    save_checkpoint(mission_path, SCRIPT_NAME, completed)
```

**E2 — Per-canopy checkpoint (CRITICAL — API calls expensive):**
```python
SCRIPT_NAME = "species_classification"
completed = load_checkpoint(mission_path, SCRIPT_NAME)

# Key = detection_id (UUID from Supabase vegetation_detections)
for detection in fetch_unclassified_canopies(client, mission_id):
    item_key = detection["id"]
    if item_key in completed:
        continue

    crop = extract_crop(ortho, detection["geometry_wkt"])
    result = call_openai_vision(crop)
    result = cross_validate_plantnet(crop, result)   # if not skipped

    update_detection(client, detection["id"], species_tag=result)

    completed.add(item_key)
    save_checkpoint(mission_path, SCRIPT_NAME, completed)   # write after EVERY canopy
```

**E3 — Per-canopy checkpoint (Vision API calls):**
```python
SCRIPT_NAME = "health_assessment"
completed = load_checkpoint(mission_path, SCRIPT_NAME)

# Key = detection_id
for detection in fetch_canopies_without_health(client, mission_id):
    item_key = detection["id"]
    if item_key in completed:
        continue

    health = compute_vari_exg(ortho, detection["geometry_wkt"])
    if not args.skip_vision and should_sample_vision(detection, sample_pct):
        health = enrich_with_vision(crop, health)

    update_detection(client, detection["id"], health_score=health)

    completed.add(item_key)
    save_checkpoint(mission_path, SCRIPT_NAME, completed)
```

**E4 — No checkpoint needed:**
E4 is a single-pass aggregation + render job. It reads all prior outputs (already persisted in Supabase) and generates the report files. No per-item loop to resume. If E4 fails mid-render, it re-renders from scratch. The detection data in Supabase is the durable state.

**When to use:** E1 for tile loops, E2 and E3 for every external API call, E4 skip.
**Trade-offs:** Checkpoint file on every single canopy in E2/E3 adds small I/O overhead but the cost of an OpenAI Vision call (~$0.02/image) far outweighs the cost of a JSON write.

---

### Pattern 3: Supabase as Accumulating State (E1 seeds, E2/E3 update, E4 reads)

**What:** The `vegetation_detections` table is the shared state store for the E pipeline. Each step adds columns to the same row rather than creating new tables per step.

```
E1 writes:  id, mission_id, detection_index, geometry_wkt, centroid_lat/lon,
            canopy_area_sqm, canopy_width_m, canopy_height_m, detection_confidence

E2 updates: species_tag, species_confidence, vegetation_type,
            cross_validated, classification_details (JSONB)

E3 updates: health_score, health_status, health_details (JSONB)

E4 reads all columns, writes vegetation_analysis_summary
```

**Pattern for E2/E3 fetch (only unprocessed rows):**
```python
# E2 — fetch rows that have detection but no species_tag yet
detections = (client.table("vegetation_detections")
    .select("id, geometry_wkt, centroid_lat, centroid_lon")
    .eq("mission_id", mission_id)
    .is_("species_tag", "null")   # only unclassified
    .execute())

# This makes E2/E3 naturally idempotent regardless of checkpoint state:
# if re-run, already-classified rows are simply not returned
```

**When to use:** Consistent with how video_qa.py fetches video_assets and updates qa_status.
**Trade-offs:** Requires mission_id passed to every script. Double-protection: both checkpoint file (local) and Supabase null-column filter (remote) guard against redundant API calls.

---

### Pattern 4: vegetation_config JSONB via processing_templates

**What:** Mirror the `video_qa_thresholds` pattern already used by `video_qa.py`. Store E pipeline configuration as JSONB in `processing_templates.vegetation_config`, fetched at startup with hardcoded defaults as fallback.

```python
# Default config — matches PRD Section 8 configurable parameters
DEFAULT_VEGETATION_CONFIG = {
    "tile_size": 1024,           # E1
    "score_threshold": 0.3,      # E1
    "iou_threshold": 0.3,        # E1
    "max_canopies": 200,         # E2
    "skip_plantnet": False,       # E2
    "vision_sample_pct": 0.3,    # E3
    "skip_vision": False,         # E3
}

def fetch_vegetation_config(client, mission_id):
    """Fetch vegetation config from processing_templates.
    Falls back to DEFAULT_VEGETATION_CONFIG if not found.
    """
    mission = client.table("missions").select("package_type").eq("id", mission_id).single().execute()
    if not mission.data:
        return DEFAULT_VEGETATION_CONFIG
    package_type = mission.data.get("package_type")
    template = (client.table("processing_templates")
                .select("vegetation_config")
                .eq("preset_name", package_type)
                .single()
                .execute())
    if template.data and template.data.get("vegetation_config"):
        return {**DEFAULT_VEGETATION_CONFIG, **template.data["vegetation_config"]}
    return DEFAULT_VEGETATION_CONFIG
```

**Each E script accepts `--config` JSON override** (same as `--thresholds` in video_qa.py):
```bash
python canopy_detection.py path/to/mission --mission-id UUID \
  --config '{"tile_size": 512, "score_threshold": 0.4}'
```

**When to use:** All 4 scripts, though E4 only needs `vision_sample_pct` and `skip_vision` for report coverage decisions.
**Trade-offs:** Consistent with existing templates pattern. Operators adjust per-package behavior without touching scripts.

---

## Data Flow

### End-to-End Path E Flow

```
Ortho GeoTIFF (from Path C output)
    │ mapping/odm_orthophoto.tif
    ▼
E1: canopy_detection.py
    ├── Tile into 1024x1024 px overlapping windows
    ├── Run DeepForest on each tile (GPU)
    ├── Merge predictions, deduplicate via NMS
    ├── Write → vegetation/canopy_detections.gpkg
    ├── Upsert N rows → vegetation_detections (geometry, confidence, area)
    ├── Update processing_steps: veg_canopy_detection = running → complete
    └── stdout → JSON {canopy_count, gpkg_path, ...}
    │
    ▼ (n8n checks canopy_count > 0, else skip E2-E4)
    │
E2: species_classification.py
    ├── Fetch unclassified rows from vegetation_detections (species_tag IS NULL)
    ├── For each (up to max_canopies):
    │   ├── Crop canopy patch from ortho (rasterio mask by geometry)
    │   ├── Encode PNG to base64
    │   ├── Call OpenAI Vision API (gpt-4o, structured output)
    │   ├── Optionally call PlantNet API for cross-validation
    │   └── Update vegetation_detections.species_tag, species_confidence, cross_validated
    ├── Checkpoint after each detection (API call expensive)
    └── stdout → JSON {classified_count, api_calls_used, ...}
    │
    ▼
E3: health_assessment.py
    ├── Fetch all detections for mission (with geometry)
    ├── For each canopy:
    │   ├── Mask ortho to canopy polygon (rasterio)
    │   ├── Compute VARI = (G - R) / (G + R - B) per-pixel, average
    │   ├── Compute ExG = 2G - R - B per-pixel, average
    │   ├── Map indices → health_score (0-100), health_status (healthy/stressed/poor)
    │   └── Optionally call OpenAI Vision (vision_sample_pct % of canopies)
    ├── Update vegetation_detections.health_score, health_status, health_details
    ├── Checkpoint after each detection
    └── stdout → JSON {assessed_count, avg_health_score, needs_attention_count, ...}
    │
    ▼
E4: vegetation_report.py
    ├── Fetch all vegetation_detections for mission (complete, with species + health)
    ├── Load canopy_detections.gpkg for map overlays
    ├── Generate species_map.png (GeoPandas choropleth, colored by species)
    ├── Generate health_map.png (GeoPandas choropleth, colored by health_status)
    ├── Generate Interactive_Map.html (Folium, GeoJSON layer + species/health popups)
    ├── Generate Vegetation_Report.pdf (ReportLab — cover, stats, maps, table, appendix)
    ├── Copy canopy_detections.geojson from GeoPackage export
    ├── Upsert 1 row → vegetation_analysis_summary
    ├── Update missions.vegetation_status = 'complete'
    └── stdout → JSON {pdf_path, species_map_path, health_map_path, ...}
    │
    ▼
E5: n8n Review Gate
    ├── Webhook wait node pauses workflow
    ├── Operator reviews report in staging
    └── POST /sentinel-vegetation-resume → n8n resumes → delivery_packaging.py
```

### Intermediate File Summary

| File | Written By | Read By | Format |
|------|-----------|---------|--------|
| `mapping/odm_orthophoto.tif` | Path C (WebODM) | E1, E2, E3 | Cloud-optimized GeoTIFF |
| `vegetation/canopy_detections.gpkg` | E1 | E4 (map overlays) | GeoPackage (local source of truth) |
| `vegetation/canopy_detections.geojson` | E4 (export) | delivery_packaging.py | GeoJSON (delivery copy) |
| `vegetation/species/crops/` | E2 (optional) | none after E2 | PNG tiles (temp, not delivered) |
| `vegetation/report/Vegetation_Report.pdf` | E4 | delivery_packaging.py | PDF |
| `vegetation/report/Species_Map.png` | E4 | delivery_packaging.py | PNG |
| `vegetation/report/Health_Map.png` | E4 | delivery_packaging.py | PNG |
| `vegetation/report/Interactive_Map.html` | E4 | delivery_packaging.py | HTML |
| `.checkpoint_canopy_detection.json` | E1 (checkpoint.py) | E1 | JSON |
| `.checkpoint_species_classification.json` | E2 (checkpoint.py) | E2 | JSON |
| `.checkpoint_health_assessment.json` | E3 (checkpoint.py) | E3 | JSON |

**Key insight:** The ortho GeoTIFF is potentially 500MB-5GB. E1, E2, and E3 all open it via `rasterio` with windowed reads (not loading fully into RAM). Never copy it — read in place from `mapping/`.

---

## Supabase Integration

### New Tables

**`vegetation_detections`** — written by E1, updated by E2 and E3

```sql
CREATE TABLE vegetation_detections (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id              UUID NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    detection_index         INTEGER NOT NULL,  -- ordered 0..N within mission
    geometry_wkt            TEXT NOT NULL,     -- WKT polygon (EPSG:4326)
    centroid_lat            DOUBLE PRECISION,
    centroid_lon            DOUBLE PRECISION,

    -- E1 outputs
    canopy_area_sqm         DOUBLE PRECISION,
    canopy_width_m          DOUBLE PRECISION,
    canopy_height_m         DOUBLE PRECISION,
    detection_confidence    DOUBLE PRECISION,

    -- E2 outputs (NULL until classified)
    species_tag             TEXT,
    species_confidence      DOUBLE PRECISION,
    vegetation_type         TEXT,             -- 'tree' | 'shrub' | 'groundcover'
    cross_validated         BOOLEAN DEFAULT FALSE,
    classification_details  JSONB,

    -- E3 outputs (NULL until assessed)
    health_score            DOUBLE PRECISION, -- 0.0 to 100.0
    health_status           TEXT,             -- 'healthy' | 'stressed' | 'poor'
    health_details          JSONB,            -- vari, exg, vision_notes, etc.

    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_veg_detections_mission ON vegetation_detections(mission_id);
CREATE INDEX idx_veg_detections_species ON vegetation_detections(mission_id, species_tag);
CREATE INDEX idx_veg_detections_health  ON vegetation_detections(mission_id, health_status);
```

**`vegetation_analysis_summary`** — written by E4, one row per mission

```sql
CREATE TABLE vegetation_analysis_summary (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id              UUID NOT NULL UNIQUE REFERENCES missions(id) ON DELETE CASCADE,

    -- Site metrics
    site_area_sqm           DOUBLE PRECISION,
    site_area_acres         DOUBLE PRECISION,
    total_canopy_count      INTEGER,
    canopy_coverage_pct     DOUBLE PRECISION,

    -- Species summary
    unique_species_count    INTEGER,
    species_distribution    JSONB,  -- {"oak": 12, "pine": 8, "unknown": 5}

    -- Health summary
    avg_health_score        DOUBLE PRECISION,
    health_distribution     JSONB,  -- {"healthy": 18, "stressed": 5, "poor": 2}
    needs_attention_count   INTEGER,

    -- API usage (for cost tracking)
    api_calls_total         INTEGER,
    processing_time_seconds DOUBLE PRECISION,

    -- Output file paths
    pdf_report_path         TEXT,
    species_map_path        TEXT,
    health_map_path         TEXT,
    geojson_path            TEXT,
    interactive_map_path    TEXT,   -- NULL for standard tier

    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### Schema Modifications

**`missions` table additions:**
```sql
ALTER TABLE missions
    ADD COLUMN vegetation_analysis BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN vegetation_status   TEXT     CHECK (vegetation_status IN
        ('pending', 'running', 'review', 'complete', 'failed'));
```

**`processing_templates` table additions:**
```sql
ALTER TABLE processing_templates
    ADD COLUMN vegetation_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN vegetation_config  JSONB;

-- Seed config for site_survey and environmental_survey
UPDATE processing_templates
SET    vegetation_enabled = TRUE,
       vegetation_config  = '{
           "tile_size": 1024,
           "score_threshold": 0.3,
           "iou_threshold": 0.3,
           "max_canopies": 200,
           "skip_plantnet": false,
           "vision_sample_pct": 0.3,
           "skip_vision": false
       }'::jsonb
WHERE  preset_name IN ('site_survey', 'environmental_survey');
```

**`processing_steps` — new step_name values (no schema change needed, just new values inserted by scripts):**
- `veg_canopy_detection`
- `veg_species_classification`
- `veg_health_assessment`
- `veg_report_generation`

**Note on processing_steps usage:** The existing codebase does NOT currently write to `processing_steps` from Python scripts (no grep hits). The table is referenced in the PRD as planned. Path E should be the first pipeline layer to actively write step status. Each E script should upsert a `processing_steps` row with `status = 'running'` at startup and `status = 'complete'` or `'failed'` on exit. This establishes the pattern for future scripts.

**processing_steps upsert pattern for E scripts:**
```python
def upsert_processing_step(client, mission_id, step_name, status, details=None):
    """Update processing step status. Non-fatal if Supabase unavailable."""
    try:
        client.table("processing_steps").upsert({
            "mission_id": mission_id,
            "step_name": step_name,
            "status": status,
            "details": details or {},
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="mission_id,step_name").execute()
    except Exception as e:
        logging.getLogger(__name__).warning(f"processing_steps update failed (non-fatal): {e}")
```

---

## n8n Workflow Integration

### Path E Attachment to Package Router

The existing n8n Package Router node inspects `package_type` from the ingest webhook and routes to Paths A, B, C, D, or V. Path E attaches **after Path C completes** (ortho exists) as a conditional branch, not as a new top-level route.

```
Package Router
  ├── Path A (RE photos)
  ├── Path B (construction)
  ├── Path C (mapping/WebODM) ──→ [C Complete?] ──→ [Veg Enabled?] ──→ Path E
  ├── Path D (ADIAT)
  └── Path V (video)
```

**n8n Path E node sequence:**

```
E0: Check Ortho
    IF: missions.vegetation_analysis = TRUE
    AND: mapping/odm_orthophoto.tif exists (file system check)
    → trigger Path E | else: skip

E1: Execute Command
    cmd: python canopy_detection.py {{mission_path}} --mission-id {{mission_id}}
    → Parse JSON output → store canopy_count

E1 Gate: IF canopy_count == 0
    → Set missions.vegetation_status = 'failed' (no canopies found)
    → Send operator notification "No canopy detected"
    → End Path E (do not run E2-E4)

E2: Execute Command
    cmd: python species_classification.py {{mission_path}} --mission-id {{mission_id}}
    → Parse JSON output → store classified_count

E3: Execute Command
    cmd: python health_assessment.py {{mission_path}} --mission-id {{mission_id}}
    → Parse JSON output → store avg_health_score

E4: Execute Command
    cmd: python vegetation_report.py {{mission_path}} --mission-id {{mission_id}}
    → Parse JSON output → store pdf_path

E5: Review Gate (Webhook Wait)
    → Send operator notification with pdf_path (link to report)
    → Webhook: POST /sentinel-vegetation-resume {mission_id, approved: true|false}
    IF approved:
        → delivery_packaging.py --include-vegetation
    ELSE:
        → Set missions.vegetation_status = 'failed'
        → Log rejection reason
```

**Review gate pattern:** Follows n8n's native "Wait" node capability. The workflow pauses after E4, n8n sends an operator notification (email or Slack), and the operator reviews the PDF report before approving delivery inclusion. The resume webhook re-enters the workflow at the approved/rejected branch.

**On E script failure (non-zero exit code from Execute Command):**
- n8n treats non-zero exit as step failure
- Workflow should catch error path, set `missions.vegetation_status = 'failed'`, notify operator
- Path E failure must NOT block delivery of the main package (photos/video) — Path E is an addendum

---

## Delivery Packaging Integration

### Strategy: Additive modification to delivery_packaging.py

Add a `collect_vegetation()` function and `--include-vegetation` flag. No changes to existing collection logic. Matches the same pattern used by `--include-mapping` and `--include-reports`.

**New function:**
```python
def collect_vegetation(mission_path):
    """Collect vegetation analysis outputs for delivery.

    Returns list of (source_path, archive_name) tuples for vegetation/ subfolder.
    Always included: PDF, Species Map, Health Map, GeoJSON.
    Conditionally included: Interactive HTML (if present = premium tier).
    """
    report_dir = os.path.join(mission_path, "vegetation", "report")
    if not os.path.isdir(report_dir):
        return []

    results = []
    # Ordered by expected client value
    for fname in sorted(os.listdir(report_dir)):
        src = os.path.join(report_dir, fname)
        if not os.path.isfile(src):
            continue
        # Include all files in vegetation/report/ — E4 only writes the 4-5 expected files
        archive_name = f"vegetation/{fname}"
        results.append((src, archive_name))

    # Also include GeoJSON from vegetation/ root (not in report/)
    geojson = os.path.join(mission_path, "vegetation", "canopy_detections.geojson")
    if os.path.isfile(geojson):
        results.append((geojson, "vegetation/canopy_detections.geojson"))

    return results
```

**New argparse flag:**
```python
parser.add_argument("--include-vegetation", action="store_true",
                    help="Include vegetation analysis outputs (PDF, maps, GeoJSON)")
```

**Integration in full delivery mode:**
```python
# In existing full delivery block:
if args.include_vegetation:
    vegetation = collect_vegetation(mission_path)
    veg_count = len(vegetation)
    for vpath, archive_name in vegetation:
        manifest.append((vpath, archive_name))
```

**ZIP structure with vegetation:**
```
Sentinel_123_Main_St_Virginia_Beach_20260218.zip
├── photos/
│   └── Sentinel_123_Main_St_Virginia_Beach_001.jpg
├── video/
│   └── Sentinel_123_Main_St_Virginia_Beach_PropertyTour_YouTube.mp4
├── mapping/
│   └── Sentinel_123_Main_St_Virginia_Beach_Orthophoto.tif
└── vegetation/
    ├── Sentinel_123_Main_St_Virginia_Beach_Vegetation_Report.pdf
    ├── Sentinel_123_Main_St_Virginia_Beach_Species_Map.png
    ├── Sentinel_123_Main_St_Virginia_Beach_Health_Map.png
    ├── Sentinel_123_Main_St_Virginia_Beach_Interactive_Map.html  (premium)
    └── canopy_detections.geojson
```

**Note on naming:** E4 writes report files using the address prefix at generation time (it receives `--address` and `--city` as arguments, same as delivery_packaging.py). The `collect_vegetation()` function collects them as-is — no renaming needed inside delivery_packaging.py.

**Alternative approach:** delivery_packaging.py passes `--address` to E4 (or E4 reads it from Supabase `missions.address`). Confirm which approach at implementation time. Recommend reading from Supabase to avoid requiring extra CLI args on E4.

---

## Error Handling (Path E Unique Failure Modes)

### Critical: GPU OOM (E1 DeepForest inference)

**What goes wrong:** RTX 5070 has 12GB VRAM. Large orthomosaics (>200MP) may OOM during tile inference if tiles are too large or batch size is too high.

**Prevention pattern:**
```python
# E1 — catch CUDA OOM, retry with smaller tile
try:
    predictions = model.predict_tile(raster_path, patch_size=tile_size, ...)
except RuntimeError as e:
    if "CUDA out of memory" in str(e) or "CUDA" in str(e):
        torch.cuda.empty_cache()
        log.warning(f"GPU OOM on tile {tile_idx}, retrying with half patch_size")
        try:
            predictions = model.predict_tile(raster_path, patch_size=tile_size // 2, ...)
        except RuntimeError:
            log.error(f"GPU OOM persists on tile {tile_idx} after retry — skipping tile")
            # Mark tile as failed but continue pipeline (partial result is better than abort)
```

**Exit behavior:** If >50% of tiles OOM, exit code 2 (fatal). If <50% OOM (partial result), exit code 1, still write partial GeoPackage, let n8n operator decide.

---

### Critical: API Rate Limits (E2 PlantNet, E2/E3 OpenAI)

**What goes wrong:**
- PlantNet free tier: 500 requests/day. 200-canopy mission = 200 PlantNet calls. Could hit daily limit mid-mission.
- OpenAI Vision: Rate limits are per-minute (TPM/RPM). 200 canopies at ~2s each = ~7 minutes. Should stay within limits but burst protection needed.

**Prevention pattern for E2:**
```python
import time

PLANTNET_DAILY_LIMIT = 500
OPENAI_RETRY_DELAYS = [1, 2, 4, 8]  # exponential backoff, seconds

def call_openai_vision_with_retry(crop_b64, max_retries=4):
    for attempt, delay in enumerate(OPENAI_RETRY_DELAYS):
        try:
            return call_openai_vision(crop_b64)
        except openai.RateLimitError:
            if attempt < max_retries - 1:
                log.warning(f"OpenAI rate limit, retrying in {delay}s...")
                time.sleep(delay)
            else:
                raise
        except openai.APIError as e:
            log.error(f"OpenAI API error: {e}")
            return None   # non-fatal: continue with unknown species

def call_plantnet_with_limit_check(crop_path, calls_used):
    if calls_used >= PLANTNET_DAILY_LIMIT:
        log.warning("PlantNet daily limit reached — skipping cross-validation for remaining canopies")
        return None
    try:
        return call_plantnet(crop_path)
    except Exception as e:
        log.warning(f"PlantNet call failed (non-fatal): {e}")
        return None
```

**Checkpoint is the safety net:** If rate-limited mid-run, E2 exits with code 1 (partial). n8n can retry E2 the next day and the checkpoint will skip already-classified canopies.

---

### Moderate: No Canopies Detected (E1 returns count=0)

**What goes wrong:** Mission has low-GSD imagery, non-vegetated site, or DeepForest score_threshold too high. E1 completes successfully but writes 0 rows to `vegetation_detections`.

**Prevention pattern:**
```python
# E1 stdout includes canopy_count
# n8n reads canopy_count and branches:
# IF canopy_count == 0:
#   → update missions.vegetation_status = 'failed'
#   → notify operator: "No canopy detected. Check GSD and score_threshold."
#   → skip E2, E3, E4
#   → do NOT include vegetation/ in delivery ZIP
```

**This is not an error in E1** — E1 exits 0 (success) with canopy_count=0. The zero count is informational. The n8n workflow gate decides whether to continue.

---

### Moderate: Ortho Not Found (E0 pre-check fails)

**What goes wrong:** Path E triggered but Path C has not finished, or ortho file is in a non-standard location.

**E0 pre-check in n8n:**
```python
# canopy_detection.py validates ortho exists before doing anything:
ortho_candidates = [
    os.path.join(mission_path, "mapping", "odm_orthophoto.tif"),
    os.path.join(mission_path, "mapping", "orthophoto.tif"),
]
ortho_path = next((p for p in ortho_candidates if os.path.isfile(p)), None)
if not ortho_path:
    log.error("No orthophoto found in mapping/. Run Path C (WebODM) first.")
    sys.exit(2)
```

---

### Moderate: Corrupt or Low-GSD Ortho

**What goes wrong:** Ortho opens successfully but GSD is too large (>5cm/px) for reliable DeepForest detection. This is OQ2 from the PRD.

**Prevention:**
```python
# E1 — check GSD before inference
with rasterio.open(ortho_path) as src:
    pixel_size_m = abs(src.transform.a)  # x-resolution in meters
    gsd_cm = pixel_size_m * 100

    if gsd_cm > MAX_GSD_CM:  # recommend 5cm threshold from research
        log.warning(f"Ortho GSD {gsd_cm:.1f}cm exceeds recommended {MAX_GSD_CM}cm. "
                    f"Detection accuracy may be reduced.")
        # Continue with warning — operator decides at review gate
```

---

### Minor: Report Generation Failures (E4 font/library issues)

**What goes wrong:** ReportLab PDF generation can fail on missing fonts or Folium map tile fetch failures.

**Prevention:** E4 should use embedded fonts (no system font dependency) and generate Folium with local tile provider (OSM tiles, or offline leaflet via CDN in HTML). If interactive map generation fails, E4 logs warning and continues — the PDF and PNG maps are the minimum deliverable.

---

## Integration Points Summary

### New vs Modified

| Item | New or Modified | Notes |
|------|----------------|-------|
| `canopy_detection.py` | NEW | E1 script |
| `species_classification.py` | NEW | E2 script |
| `health_assessment.py` | NEW | E3 script |
| `vegetation_report.py` | NEW | E4 script |
| `delivery_packaging.py` | MODIFIED | Add `collect_vegetation()` + `--include-vegetation` flag. Additive only. |
| `requirements.txt` | MODIFIED | Add deepforest, torch, rasterio, geopandas, shapely, shapely, openai, reportlab, matplotlib, folium |
| `vegetation_detections` table | NEW | Supabase — new migration file |
| `vegetation_analysis_summary` table | NEW | Supabase — same migration file |
| `missions.vegetation_analysis` column | NEW | Supabase — same migration |
| `missions.vegetation_status` column | NEW | Supabase — same migration |
| `processing_templates.vegetation_enabled` column | NEW | Supabase — same migration |
| `processing_templates.vegetation_config` column | NEW | Supabase — same migration |
| `checkpoint.py` | REUSE AS-IS | No changes needed |
| n8n Package Router | MODIFIED | Add Path E branch after Path C completion |
| n8n — new Path E workflow | NEW | E0-E5 nodes with review gate webhook |

### External Service Boundaries

| Service | Integration Pattern | Unique to Path E? | Notes |
|---------|---------------------|------------------|-------|
| Supabase | Existing: `supabase` Python client, service role key | NO — same as video pipeline | Add `OPENAI_API_KEY` env var |
| OpenAI Vision API | HTTP via `openai` Python SDK, gpt-4o | YES — new | E2 (species) + E3 (health qualitative). Rate limit: per-minute. Retry with backoff. |
| PlantNet API | HTTP via `requests`, multipart form | YES — new | E2 only, cross-validation. 500/day limit. Non-fatal if unavailable. |
| DeepForest (local) | Python library, GPU inference via PyTorch | YES — new | E1 only. No network call. CUDA OOM risk. |
| Google Drive | Existing: `gdrive_upload.py` | NO | Unchanged — `delivery_packaging.py --include-vegetation` adds vegetation/ to ZIP before upload |

---

## Build Order (Dependency-First)

Build in this order to allow incremental testing at each step:

1. **Supabase migration** — required by all E scripts; write once, validate schema
2. **E1 `canopy_detection.py`** — no external API dependency, GPU-only; testable with stub ortho
3. **E2 `species_classification.py`** — depends on E1 (reads vegetation_detections); OpenAI/PlantNet can be mocked
4. **E3 `health_assessment.py`** — depends on E1 (reads vegetation_detections); Vision API optional
5. **E4 `vegetation_report.py`** — depends on E1+E2+E3 (reads all columns); no external APIs
6. **`delivery_packaging.py` modification** — depends on E4 outputs being in `vegetation/report/`; additive-only change
7. **n8n Path E workflow** — depends on all E scripts being correct; wire up last
8. **Tests** — write alongside each script (not at end)

**Key dependency:** E2 and E3 can be built in parallel once E1 is done. E4 requires both E2 and E3 to have valid test data in Supabase.

---

## Scaling Considerations

Path E is a single-rig, single-mission processing system. Scaling is not a concern for v2.0. The relevant limits are:

| Constraint | Current Limit | Mitigation |
|------------|--------------|------------|
| GPU VRAM | 12GB RTX 5070 | Tile-based inference; retry with smaller tiles on OOM |
| PlantNet API | 500 req/day | checkpoint resume; `skip_plantnet` flag for large missions |
| OpenAI Vision cost | ~$0.02/image | `max_canopies` limit (200 default); `vision_sample_pct` for E3 |
| Ortho file size | 500MB–5GB | Windowed rasterio reads; never load full ortho into RAM |
| n8n timeout | 10 min default for Execute Command | Increase n8n Execute Command timeout to 60 min for E1/E4 |

---

## Anti-Patterns

### Anti-Pattern 1: Loading the Full Ortho into RAM

**What people do:** `image = rasterio.open(path).read()` — reads entire raster into a numpy array.
**Why it's wrong:** A 5cm GSD orthomosaic of a 5-acre site is ~1.5GB uncompressed. Doing this in E1, E2, and E3 would consume 4.5GB+ RAM simultaneously.
**Do this instead:** Use `rasterio.open()` with windowed reads and mask by geometry for each canopy crop:
```python
with rasterio.open(ortho_path) as src:
    for detection in detections:
        geom = shape(wkt.loads(detection["geometry_wkt"]))
        crop, transform = rasterio.mask.mask(src, [geom], crop=True)
        # process crop, then release
```

---

### Anti-Pattern 2: Writing GeoJSON as Working State (use GeoPackage)

**What people do:** Write polygons to GeoJSON after each tile and append.
**Why it's wrong:** GeoJSON is a text format; concurrent appends corrupt it. No spatial indexing for E2/E3 geometry queries.
**Do this instead:** GeoPackage (GPKG) as the working format — GeoPandas supports append mode, SQLite provides ACID transactions. Export GeoJSON from GeoPackage only for delivery.

---

### Anti-Pattern 3: Blocking Delivery on Path E Failure

**What people do:** delivery_packaging.py raises an error if `--include-vegetation` is specified but `vegetation/report/` doesn't exist.
**Why it's wrong:** Path E failure should never block the primary RE package delivery. Client photos and video should ship regardless.
**Do this instead:** `collect_vegetation()` returns empty list if `vegetation/report/` doesn't exist. n8n controls whether `--include-vegetation` is passed based on `missions.vegetation_status == 'complete'`.

---

### Anti-Pattern 4: Re-Calling OpenAI for Already-Classified Canopies

**What people do:** E2 runs from scratch, re-classifying all canopies.
**Why it's wrong:** 200 canopies × $0.02 = $4/run. Accidental re-runs cost money.
**Do this instead:** Double protection — checkpoint file (local) + Supabase null-column filter (`species_tag IS NULL`). Both guards must be in place. Even if checkpoint is deleted, Supabase filter prevents re-classification.

---

### Anti-Pattern 5: Separate SQL Migration for Each Column Addition

**What people do:** Create one migration per ALTER TABLE statement.
**Why it's wrong:** Supabase migrations are append-only; 4+ tiny migration files for related schema work is noisy.
**Do this instead:** One migration file for all v2.0 vegetation schema changes (both new tables + 4 column additions). File naming: `migration_00N_vegetation_analysis.sql` where N follows the existing highest number.

---

## Sources

- Direct codebase audit: all 14 scripts in `C:/Users/redle/drone-pipeline/` (2026-02-24)
- `.planning/codebase/ARCHITECTURE.md` — existing pipeline architecture (2026-02-23)
- `.planning/codebase/CONVENTIONS.md` — coding patterns established in v1.0 (2026-02-23)
- `.planning/codebase/INTEGRATIONS.md` — Supabase schema, n8n webhook patterns (2026-02-23)
- `.planning/PRD-vegetation-analysis.md` — v2.0 feature spec (2026-02-24)
- `checkpoint.py` — shared resume utility examined directly
- `delivery_packaging.py` — existing ZIP creation logic examined directly
- `video_qa.py` — processing_templates pattern and Supabase update pattern examined directly

---

*Architecture research for: Path E Vegetation Analysis Pipeline Integration*
*Researched: 2026-02-24*
*Confidence: HIGH — based on direct codebase audit, not inference*
