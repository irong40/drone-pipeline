# Sentinel Drone Pipeline — System Documentation

> Complete technical reference for the Sentinel Aerial Inspections post-flight processing pipeline.
> Version: 3.0 (2026-03-16) | Business: Faith & Harmony LLC DBA Sentinel Aerial Inspections

---

## 1. What This System Does

Sentinel is an automated pipeline that takes raw drone media (photos, video, telemetry) from a DJI SD card and produces client-ready deliverables — color-graded video, orthomosaic maps, vegetation analysis reports, and packaged ZIP files uploaded to Google Drive.

**Input:** SD card from DJI Mini 4 Pro, Matrice 4E, or Mavic 3 Enterprise
**Output:** Client delivery ZIP on Google Drive containing photos, video exports, mapping products, and vegetation reports

### Processing Paths

| Path | Name | What It Does |
|------|------|--------------|
| V | Video | Color grade → metadata → telemetry parse → QA → proxy gen → manual edit → format export |
| C | Mapping | Submit photos to NodeODM → produce orthomosaic, DSM, DTM |
| E | Vegetation | Canopy detection → species classification → health assessment → PDF report |
| D | Delivery | Package ZIP with client-facing names → upload to Google Drive |

Not every mission runs every path. The Package Router determines which paths to run based on the mission's package type and processing template.

---

## 2. Architecture Overview

```
                          ┌─────────────────────────────────────┐
                          │         Operator Workflow            │
                          │                                     │
                          │  SD Card → Launcher GUI or CLI      │
                          │         → ingest_sorter.py          │
                          │         → fires n8n webhook         │
                          └──────────────┬──────────────────────┘
                                         │ POST /webhook/ingest
                                         ▼
                    ┌────────────────────────────────────────────┐
                    │          n8n Package Router                │
                    │                                           │
                    │  Lookup template → Route decision          │
                    │  Set output_path + vegetation flag         │
                    ├───────────┬──────────┬────────────────────┤
                    │           │          │                    │
                    ▼           ▼          ▼                    ▼
              ┌──────────┐ ┌────────┐ ┌────────┐       ┌────────────┐
              │ Path V   │ │ Path C │ │ Path E │       │ Response   │
              │ Video    │ │ Mapping│ │ Veg    │       │ to caller  │
              │ V1→V4   │ │ NodeODM│ │ E1→E4  │       └────────────┘
              └────┬─────┘ └───┬────┘ └───┬────┘
                   │           │          │
                   ▼           ▼          ▼
              V5 Manual    ortho.tif   PDF report
              Edit         DSM/DTM     GeoJSON, maps
                   │           │          │
                   └─────┬─────┘──────────┘
                         │ POST /webhook/delivery-ready
                         ▼
                  ┌──────────────────┐
                  │ Delivery Chain   │
                  │ Package → Upload │
                  │ → Mark Delivered │
                  └──────────────────┘
```

### Technology Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12 |
| GUI | Tkinter (launcher.py) |
| Orchestration | n8n (self-hosted, Docker) |
| Database | Supabase (PostgreSQL + REST API) |
| Photogrammetry | NodeODM/WebODM (Docker, GPU-enabled) |
| Video Processing | FFmpeg |
| ML/AI | DeepForest (canopy detection), OpenAI Vision (species), PlantNet (cross-validation) |
| Geospatial | rasterio, geopandas, shapely, pyproj, fiona |
| Reporting | ReportLab (PDF), matplotlib (charts), Folium (interactive maps) |
| File Delivery | Google Drive API (service account) |
| OS | Windows 11 only |

---

## 3. Directory Layout

```
C:\Users\redle.SOULAAN\Documents\drone-pipeline\   ← Git repo (all scripts)
├── .venv-path-e\              ← Python 3.12 venv for Path E (GPU deps)
├── logs\                      ← All script log files
├── n8n\                       ← n8n workflow JSON files
│   ├── package_router_workflow.json
│   ├── path_e_workflow.json
│   └── package_router_patch.json
├── db_migrations\             ← Supabase migration SQL files
├── tests\                     ← pytest suite (400+ tests)
├── start-all.bat              ← One-click pipeline startup
├── install-scheduled-tasks.bat
├── launcher.py                ← Desktop GUI entry point
├── ingest_sorter.py           ← SD card file sorting
├── photogrammetry_submit.py   ← Path C (NodeODM)
├── canopy_detection.py        ← Path E step 1
├── species_classification.py  ← Path E step 2
├── health_assessment.py       ← Path E step 3
├── vegetation_report.py       ← Path E step 4
├── video_color_grade.py       ← V1
├── video_metadata.py          ← V1.5
├── srt_telemetry_parser.py    ← V2
├── video_qa.py                ← V3
├── video_proxy_gen.py         ← V4
├── video_format_export.py     ← V6
├── delivery_packaging.py      ← ZIP packaging
├── gdrive_upload.py           ← Google Drive upload
├── folder_watcher.py          ← Filesystem monitor
├── archive_sync.py            ← Weekly Drive → local archive
├── pipeline_utils.py          ← Shared utilities
├── checkpoint.py              ← Resume-on-failure system
├── pipeline_status.py         ← Status monitoring
├── platform_detect.py         ← DJI drone identification
└── ingest.py                  ← MipMap photogrammetry ingest (legacy)

E:\incoming\                   ← Raw mission folders from SD card
    SAI_M0047_re_standard_20260218\
    ├── photos\
    │   ├── raw\               ← DNG files
    │   └── jpeg\              ← JPG files
    ├── video\
    │   ├── full\              ← Original 4K MP4
    │   ├── graded\            ← Color-graded output (V1)
    │   ├── proxy\             ← 1080p editing proxies (V4)
    │   ├── telemetry\         ← SRT subtitle files
    │   ├── master\            ← Final edited video (V5)
    │   └── exports\           ← Delivery format encodes (V6)
    └── ppk\                   ← RTK/PPK correction data

E:\output\                     ← Processed outputs per mission
    {mission-uuid}\
    ├── mapping\
    │   ├── orthomosaic.tif    ← Path C output (Path E input)
    │   ├── orthophoto.tif     ← NodeODM native name
    │   ├── dsm.tif            ← Digital Surface Model
    │   └── dtm.tif            ← Digital Terrain Model
    └── vegetation\
        ├── canopy_detections.gpkg
        ├── species_map.png
        ├── health_map.png
        ├── delivery.geojson
        ├── vegetation_report.pdf
        ├── interactive_map.html
        └── .status             ← "complete" sentinel file

F:\Sentinel_Archive\           ← Cold storage (weekly archive sync)
```

---

## 4. Services & Ports

| Service | Port | Container Name | Purpose |
|---------|------|---------------|---------|
| n8n | 5678 | n8n_app | Workflow orchestration |
| n8n Postgres | 5432 | n8n_postgres | n8n internal database |
| NodeODM | 3000 | sentinel-nodeodm | Photogrammetry processing (GPU) |
| WebODM Webapp | 8000 | webapp | WebODM web interface |
| WebODM Worker | — | worker | Background processing |
| WebODM DB | — | db | WebODM internal database |
| Supabase | — | Cloud-hosted | `qjpujskwqaehxnqypxzu.supabase.co` |

All Docker containers run independently (no docker-compose in repo). Start them before running `start-all.bat`.

---

## 5. Environment Variables

Create a `.env` file in the repo root:

```env
# Supabase (required for all database operations)
SUPABASE_URL=https://qjpujskwqaehxnqypxzu.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGci...

# Google Drive (required for delivery upload and archive sync)
GOOGLE_SERVICE_ACCOUNT_JSON=C:\path\to\service-account.json

# OpenAI (required for Path E species classification + health assessment)
OPENAI_API_KEY=sk-...

# PlantNet (required for Path E species cross-validation)
PLANTNET_API_KEY=...

# n8n (optional — defaults shown)
N8N_WEBHOOK_URL=http://localhost:5678/webhook/ingest

# NodeODM (optional — defaults shown)
NODEODM_URL=http://localhost:3000
```

n8n also needs `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` set in its own environment (Docker env vars or n8n settings).

---

## 6. Database Schema

Supabase project: `qjpujskwqaehxnqypxzu`

### Tables

#### `drone_jobs` — Mission records
The central table. One row per mission/job.

| Column | Type | Purpose |
|--------|------|---------|
| id | UUID | Primary key (= mission_id everywhere) |
| job_number | TEXT | Human-readable ID (DJ-2026-0047) |
| status | TEXT | uploaded → processing → delivered |
| photo_count | INT | Photos ingested |
| has_ppk_data | BOOL | Has RTK/PPK correction data |
| scheduled_date | DATE | Mission flight date |
| mission_number | INT | Sequence number |
| output_path | TEXT | E:\output\{id} |
| property_address | TEXT | Street address (for delivery naming) |
| property_city | TEXT | City (for delivery naming) |
| photogrammetry_status | TEXT | pending → processing → complete/failed |
| vegetation_analysis | BOOL | Whether Path E should run |
| vegetation_status | TEXT | pending → detecting → classifying → assessing → generating_report → review → complete/failed |
| ingested_at | TIMESTAMPTZ | When files were ingested |

#### `drone_assets` — Individual file records
| Column | Type | Purpose |
|--------|------|---------|
| job_id | UUID | FK → drone_jobs.id |
| file_name | TEXT | Original filename |
| file_path | TEXT | Absolute path on disk |
| file_type | TEXT | photo, raw, video |
| processing_status | TEXT | raw → processed |
| qa_status | TEXT | pending → pass/fail |
| sort_order | INT | Display ordering |

#### `video_assets` — Video metadata and QA
| Column | Type | Purpose |
|--------|------|---------|
| mission_id | UUID | FK → drone_jobs.id |
| filename | TEXT | Video filename |
| resolution | TEXT | 3840x2160 |
| codec | TEXT | h264, h265 |
| graded_path | TEXT | Path to graded version |
| qa_status | TEXT | pending → pass/warn/fail |
| qa_flags | JSONB | Specific QA issues found |

#### `processing_templates` — Workflow configuration
| Column | Type | Purpose |
|--------|------|---------|
| preset_name | TEXT | re_standard, site_survey, etc. |
| path_code | TEXT | Processing path identifier |
| default_steps | JSONB | Ordered step list |
| vegetation_enabled | BOOL | Auto-enable Path E |
| vegetation_config | JSONB | Path E parameters (max_canopies, tier, etc.) |

#### `processing_steps` — Step execution log
| Column | Type | Purpose |
|--------|------|---------|
| mission_id | UUID | FK → drone_jobs.id |
| step_name | TEXT | Free text (e.g., veg_canopy_detection) |
| status | TEXT | waiting → running → complete/failed |

#### `vegetation_detections` — Per-canopy results (Path E)
| Column | Type | Purpose |
|--------|------|---------|
| mission_id | UUID | FK → drone_jobs.id |
| detection_index | INT | Canopy sequence number |
| geometry_wkt | TEXT | Polygon in WKT format |
| centroid_lat/lon | FLOAT | Center point |
| canopy_area_sqm | FLOAT | Area in square meters |
| species_tag | TEXT | Identified species |
| species_confidence | FLOAT | 0.0-1.0 |
| health_score | FLOAT | 0.0-1.0 composite score |
| health_status | TEXT | healthy/moderate/stressed/critical |
| excluded | BOOL | Operator excluded from report |

#### `vegetation_analysis_summary` — Per-mission summary (Path E)
| Column | Type | Purpose |
|--------|------|---------|
| mission_id | UUID | One row per mission (UNIQUE) |
| total_canopy_count | INT | Canopies detected |
| unique_species_count | INT | Distinct species |
| species_distribution | JSONB | Species → count mapping |
| avg_health_score | FLOAT | Site-wide average |
| pdf_report_path | TEXT | Path to generated PDF |

RLS: Service role has full access. Authenticated users have read-only access to vegetation tables.

---

## 7. Script Reference

### Ingest Layer

| Script | Purpose | Key Args |
|--------|---------|----------|
| `launcher.py` | Desktop GUI for ingest | (none — double-click) |
| `ingest_sorter.py` | Sort SD card files into mission folders | `source --missions config.json` |
| `folder_watcher.py` | Auto-detect new missions via filesystem monitoring | `--watch-dir E:\incoming` |
| `platform_detect.py` | Identify drone model from EXIF/filename | `path` |
| `ingest.py` | Legacy MipMap photogrammetry ingest | `source --mission --run` |

### Path V — Video Processing

Runs sequentially: V1 → V1.5 → V2 → V3 → V4 → V5 (manual) → V6

| Step | Script | Purpose | Key Args |
|------|--------|---------|----------|
| V1 | `video_color_grade.py` | Apply Sentinel LUT via FFmpeg | `mission_path --platform` |
| V1.5 | `video_metadata.py` | Extract ffprobe metadata | `mission_path --mission-id --upload` |
| V2 | `srt_telemetry_parser.py` | Parse DJI SRT telemetry | `mission_path --mission-id --upload` |
| V3 | `video_qa.py` | Automated quality checks | `--mission-id UUID` |
| V4 | `video_proxy_gen.py` | Generate 1080p editing proxies | `mission_path` |
| V5 | (manual) | DaVinci Resolve editing | — |
| V6 | `video_format_export.py` | Encode delivery formats | `mission_path --mission-id` |

### Path C — Photogrammetry

| Script | Purpose | Key Args |
|--------|---------|----------|
| `photogrammetry_submit.py` | Submit to NodeODM, poll, download ortho | `--mission-id --photos-dir` |

Submits photos to NodeODM REST API (`POST /task/new`), polls status every 30s (up to 6 hours), downloads orthophoto.tif/dsm.tif/dtm.tif, copies orthophoto as orthomosaic.tif for Path E compatibility.

### Path E — Vegetation Analysis

Runs sequentially: E1 → E2 → E3 → E4, orchestrated by n8n Path E workflow.

**Requires `.venv-path-e` virtual environment** (Python 3.12, PyTorch CUDA, DeepForest).

| Step | Script | Purpose | Key Args |
|------|--------|---------|----------|
| E1 | `canopy_detection.py` | DeepForest GPU canopy detection | `--mission-id --ortho-path` |
| E2 | `species_classification.py` | OpenAI Vision + PlantNet species ID | `--mission-id --ortho-path --max-canopies 200` |
| E3 | `health_assessment.py` | VARI/ExG health indices + Vision API | `--mission-id --ortho-path --vision-sample-pct 0.3` |
| E4 | `vegetation_report.py` | PDF report, maps, GeoJSON | `--mission-id --ortho-path --tier standard` |

E1 outputs: GeoPackage + GeoJSON of canopy polygons
E2 outputs: Species tags + confidence scores per canopy in Supabase
E3 outputs: Health scores + NDVI-style indices per canopy in Supabase
E4 outputs: Branded PDF, species/health PNGs, delivery GeoJSON, optional Folium HTML map

### Delivery & Archive

| Script | Purpose | Key Args |
|--------|---------|----------|
| `delivery_packaging.py` | Create client-facing ZIP | `mission_path --mission-id` or `--address --city` |
| `gdrive_upload.py` | Upload to Google Drive | `file_path` |
| `archive_sync.py` | Weekly Drive → local cold storage | `--archive-dir F:\Sentinel_Archive` |

### Utilities

| Script | Purpose |
|--------|---------|
| `pipeline_utils.py` | Shared: logging, Supabase client, Drive client, validation, preflight checks |
| `checkpoint.py` | JSON-based checkpoint/resume for file-by-file operations |
| `pipeline_status.py` | Pipeline status monitoring |

---

## 8. n8n Workflows

### Package Router (`/webhook/ingest`)

**Trigger:** POST from `ingest_sorter.py` after file sorting
**Payload:** `{ mission_id, mission_number, package_type, photo_count, video_count, has_ppk_data, source_platform, mission_folder_path, ingested_at }`

**Flow:**
1. Lookup processing template from Supabase by package_type
2. Build routing decision (which paths to run)
3. Update drone_jobs: status=processing, set output_path + vegetation flag
4. Fan out to: Has Video? → V1-V4 chain | Run Mapping? → Path C | Run Vegetation? → Fire Path E webhook
5. Return routing summary to caller

### Path E Vegetation (`/webhook/sentinel-vegetation-trigger`)

**Trigger:** POST from Package Router (or manual)
**Payload:** `{ mission_id }`

**Flow:**
1. E0: Verify vegetation_analysis=true, poll for orthomosaic (30min timeout)
2. E1: Canopy detection (DeepForest GPU)
3. E2: Species classification (OpenAI + PlantNet)
4. E3: Health assessment (VARI/ExG + Vision API)
5. E4: Report generation (PDF, maps, GeoJSON)
6. Review Gate: Webhook wait for operator decisions
7. Apply exclusions/flags → optionally regenerate E4
8. Set vegetation_status=complete

### Delivery (`/webhook/delivery-ready`)

**Trigger:** POST when operator is ready to package and deliver
**Payload:** `{ mission_id, mission_folder_path, include_vegetation, include_mapping }`

**Flow:**
1. Run delivery_packaging.py with --mission-id (fetches address from Supabase)
2. Parse ZIP output
3. Upload to Google Drive
4. Mark drone_jobs.status=delivered

---

## 9. Startup & Operations

### First-Time Setup

```bash
# 1. Clone repo
git clone https://github.com/irong40/drone-pipeline.git
cd drone-pipeline

# 2. Install system Python deps
pip install -r requirements.txt

# 3. Create Path E venv (Python 3.12, needs CUDA GPU)
python -m venv .venv-path-e
.venv-path-e\Scripts\pip install --index-url https://download.pytorch.org/whl/cu128 torch torchvision
.venv-path-e\Scripts\pip install -r requirements-path-e.txt

# 4. Copy .env.example to .env and fill in credentials
copy .env.example .env

# 5. Ensure Docker services are running (WebODM, NodeODM, n8n)

# 6. Install scheduled tasks (run as Administrator)
install-scheduled-tasks.bat

# 7. Import n8n workflows
#    Open http://localhost:5678 → Import from file:
#    - n8n/package_router_workflow.json
#    - n8n/path_e_workflow.json
```

### Daily Startup

```bash
# Ensure Docker Desktop is running, then:
start-all.bat
```

This verifies all services, creates missing directories, and starts the folder watcher.

### Processing a Mission

1. Insert SD card
2. Open **Sentinel Ingest** (desktop shortcut) or run `python launcher.py`
3. Browse to SD card folder (e.g., `E:\DCIM\DJI_001`)
4. Define missions (number, package type, date, sequence range)
5. Click **Start Ingest**
6. Pipeline runs automatically via n8n webhooks
7. For video missions: complete manual edit (V5) in DaVinci Resolve, then trigger delivery via `POST http://localhost:5678/webhook/delivery-ready`

### Health Check

```bash
start-all.bat --check
```

---

## 10. Testing

**Test suite:** 400+ tests across 28 test files
**Framework:** pytest with pytest-mock fixtures
**Runtime:** ~2 seconds (unit) + ~20 seconds (Path E stubs)

```bash
# Run all tests
python -m pytest tests/ -q

# Run specific test file
python -m pytest tests/test_delivery_packaging.py -v

# Run with coverage
python -m pytest tests/ --cov=. --cov-report=html
```

Tests mock all external services (Supabase, Google Drive, FFmpeg, GPU, OpenAI, PlantNet) via `sys.modules` stub injection. No real API calls during testing.

**Known:** `test_vegetation_report.py` has pre-existing failures (13 failed, 4 errors) unrelated to pipeline wiring — these are PDF rendering test issues.

---

## 11. Checkpoint & Resume

Every file-processing script uses `checkpoint.py` for atomic resume:

- Checkpoint file: `.checkpoint_{script}.json` in the mission folder
- Contains set of completed item keys (file paths)
- On restart, completed items are skipped
- `--force` flag clears checkpoint to reprocess from scratch
- Checkpoint writes are atomic (write to temp, rename)

---

## 12. Known Constraints

- **Windows 11 only** — paths, batch files, and Windows service code are Windows-specific
- **Species accuracy 30-55%** — methodology disclaimer in PDF is non-negotiable
- **DJI Terra free version** — limited to 500 photos, 8GB LiDAR; pipeline uses WebODM instead
- **No CI/CD** — no remote test runner; tests run locally
- **Single processing rig** — not designed for distributed processing (except NodeODM cluster mode)
- **Path E requires GPU** — RTX 5060 Ti / CUDA 12.8; DeepForest won't run on CPU efficiently

---

## 13. Hardware Requirements

| Component | Minimum | Current Rig |
|-----------|---------|-------------|
| CPU | 8 cores | i7 14700F |
| GPU | NVIDIA RTX (CUDA) | RTX 5060 Ti |
| RAM | 16 GB | 32 GB DDR5 |
| Storage | 1 TB NVMe | 3 TB (1TB + 2TB Samsung 990 EVO Plus) |
| OS | Windows 11 | Windows 11 Home |

---

## 14. Version History

| Version | Date | Scope |
|---------|------|-------|
| v1.0 | 2026-02-24 | Code hardening + 282 tests for 14 scripts |
| v2.0 | 2026-02-25 | Path E vegetation analysis (4 scripts, 120 tests, n8n workflow) |
| v3.0 | 2026-03-16 | Pipeline wiring: Package Router, Path C, delivery automation, startup scripts |
