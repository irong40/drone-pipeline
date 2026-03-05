# Architecture Research: v3.0 Package Router & End-to-End Automation

**Domain:** n8n workflow orchestration, event-driven pipeline triggers, multi-path processing routing
**Researched:** 2026-03-05
**Confidence:** HIGH (based on direct audit of all 18 scripts, 2 n8n workflow JSONs, folder watcher, ingest pipeline, and Supabase schema)

---

## System Overview

v3.0 adds three architectural layers on top of the existing v1.0/v2.0 pipeline:

1. **Package Router** -- a new n8n workflow that receives ingest webhooks and fans out to per-path sub-workflows based on `package_type`
2. **Path C Automation** -- MipMap photogrammetry launch, output harvesting, and ortho delivery to `mapping/`
3. **Event-Driven Triggers** -- folder watcher and ingest sorter fire webhooks that replace manual CLI invocations

```
                        ┌────────────────────────────┐
                        │   SD Card / Copy Event     │
                        └─────────┬──────────────────┘
                                  │
                    ┌─────────────▼──────────────┐
                    │   folder_watcher.py         │
                    │   (watchdog + debounce)      │
                    └─────────────┬──────────────┘
                                  │ POST /webhook/folder-watcher
                                  │ {folder_path, photo_count, video_count, has_ppk}
                                  ▼
                    ┌─────────────────────────────┐
                    │   ingest_sorter.py           │
                    │   (sequence sort → mission   │
                    │    folders in Incoming/)      │
                    └─────────────┬───────────────┘
                                  │ POST /webhook/ingest
                                  │ {mission_id, package_type, photo_count, video_count}
                                  ▼
              ┌───────────────────────────────────────────────┐
              │              PACKAGE ROUTER (NEW)              │
              │   n8n workflow: sentinel-package-router         │
              │                                                 │
              │   1. Receive ingest webhook                     │
              │   2. Fetch mission from Supabase (drone_jobs)   │
              │   3. Fetch processing_templates by package_type │
              │   4. Create processing_jobs row with steps[]    │
              │   5. Switch on package_type → fan out           │
              └───────┬──────┬──────┬──────┬──────┬────────────┘
                      │      │      │      │      │
               ┌──────▼──┐ ┌─▼───┐ ┌▼────┐ ┌▼───┐ ┌▼────┐
               │ Path A  │ │Path │ │Path │ │Path│ │Path │
               │ RE Photo│ │  V  │ │  C  │ │ B  │ │  D  │
               │ grade + │ │Video│ │MipMap│ │Con-│ │ADIAT│
               │ deliver │ │pipe │ │ortho│ │str.│ │     │
               └────┬────┘ └──┬──┘ └──┬──┘ └──┬─┘ └──┬──┘
                    │         │       │       │      │
                    ▼         ▼       ▼       ▼      ▼
               delivery   delivery  ┌────────────────────┐
               _packaging _packaging│ MipMap Output       │
                                    │ Harvester (NEW)     │
                                    │ copy ortho →        │
                                    │ mapping/ folder     │
                                    └────────┬───────────┘
                                             │
                                    ┌────────▼───────────┐
                                    │ vegetation_enabled? │
                                    │ (from template)     │
                                    └───┬────────────┬───┘
                                   YES  │            │ NO
                                        ▼            ▼
                                  Path E workflow   delivery
                                  (existing v2.0)   _packaging
```

---

## Component Inventory: New vs Modified

### NEW Components

| Component | Type | Purpose |
|-----------|------|---------|
| Package Router workflow | n8n workflow | Receives ingest webhook, routes by `package_type`, creates `processing_jobs` row |
| Path A sub-workflow | n8n workflow | RE photo processing: color grade, delivery packaging |
| Path V sub-workflow | n8n workflow | Video pipeline: metadata, QA, proxy, color grade, manual edit gate, export, delivery |
| Path C sub-workflow | n8n workflow | MipMap launch, poll for completion, ortho harvest, status update |
| Path B sub-workflow | n8n workflow | Construction hybrid routing (photos + mapping) |
| Path D sub-workflow | n8n workflow | ADIAT routing (placeholder) |
| `mipmap_launcher.py` | Python script | Generate task.json from mission photos, launch `reconstruct_full_engine.exe`, track PID |
| `ortho_harvester.py` | Python script | Copy GeoTIFF from `D:/{uuid}/project/task/result/` to mission `mapping/` folder |
| Folder watcher → Package Router webhook | Integration | New webhook endpoint connecting watcher to router |

### MODIFIED Components

| Component | Change | Risk |
|-----------|--------|------|
| `folder_watcher.py` | Change webhook URL from `/webhook/folder-watcher` to `/webhook/package-router` OR add second webhook to chain ingest_sorter automatically | LOW -- additive config change |
| `ingest_sorter.py` | Webhook payload already includes `package_type` and `mission_id` -- no change needed to the script itself; the n8n endpoint it fires at needs to be the Package Router | LOW -- URL config only |
| `delivery_packaging.py` | Already supports `--include-vegetation` and `--include-mapping` -- no changes needed for v3.0 | NONE |
| Path E workflow (`path_e_workflow.json`) | Currently standalone with own trigger webhook; needs to become callable as a sub-workflow from the Package Router after Path C completes, OR keep as separate workflow triggered via internal HTTP call | LOW -- routing change only |
| `ingest.py` | Refactor into `mipmap_launcher.py` -- extract task.json generation + engine launch into a script that follows the pipeline contract (argparse, JSON stdout, `PipelineStatusReporter`) | MEDIUM -- functional rewrite of existing code |

### UNCHANGED Components

| Component | Why Unchanged |
|-----------|---------------|
| All 4 Path E scripts (E1-E4) | Already have correct contracts; Package Router just triggers them via existing Path E workflow |
| `checkpoint.py` | Shared utility, no changes needed |
| `pipeline_status.py` | Already provides `PipelineStatusReporter` -- new scripts use it |
| `pipeline_utils.py` | Shared constants, no changes |
| `platform_detect.py` | Used by ingest_sorter, no changes |
| `gdrive_upload.py` | Called by delivery_packaging, no changes |
| `archive_sync.py` | Independent of pipeline routing |
| All video scripts (V1-V7) | Called via Execute Command from Path V sub-workflow |

---

## Integration Points

### Integration Point 1: folder_watcher.py → Package Router

**Current state:** `folder_watcher.py` fires POST to `/webhook/folder-watcher` with inventory JSON after 60s debounce. This webhook currently has no n8n workflow listening (Path E was triggered separately).

**v3.0 change:** Two options:

**Option A (Recommended): Two-stage webhook chain**
```
folder_watcher.py → POST /webhook/folder-watcher
                     └→ n8n: "Ingest Trigger" workflow
                        ├── runs ingest_sorter.py via Execute Command
                        │   (sorts files into mission folders)
                        └── for each mission sorted:
                            POST /webhook/package-router {mission_id, package_type, ...}
```

**Option B: Direct to Package Router**
```
folder_watcher.py → POST /webhook/package-router
```
Problem: folder_watcher.py does not know `mission_id` or `package_type` -- it only sees raw folder inventory. The ingest_sorter step is needed first.

**Decision: Option A.** The folder watcher fires the Ingest Trigger workflow, which runs `ingest_sorter.py`, and then the ingest_sorter's webhook fires the Package Router. This preserves the existing separation of concerns and does not require changing `folder_watcher.py` at all.

**Webhook contract -- Ingest Trigger (existing, unchanged):**
```json
POST /webhook/folder-watcher
{
  "folder_path": "E:\\Sentinel\\Incoming\\SAI_M0047_site_survey_20260218",
  "folder_name": "SAI_M0047_site_survey_20260218",
  "mission_number": 47,
  "photo_count": 250,
  "video_count": 8,
  "has_ppk_data": true,
  "total_size_bytes": 145382400,
  "detected_at": "2026-02-18T20:45:30Z"
}
```

### Integration Point 2: ingest_sorter.py → Package Router

**Current state:** `ingest_sorter.py` fires POST to `/webhook/ingest` with mission metadata after successful sort.

**v3.0 change:** Point this webhook at the Package Router endpoint.

**Webhook contract -- Package Router entry (from ingest_sorter.py):**
```json
POST /webhook/package-router
{
  "mission_id": "uuid-from-supabase",
  "mission_number": 47,
  "package_type": "site_survey",
  "photo_count": 250,
  "video_count": 8,
  "has_ppk_data": true,
  "source_platform": "m4e",
  "ingested_at": "2026-02-18T20:46:30Z"
}
```

The Package Router receives this and begins routing.

### Integration Point 3: Package Router → Path Sub-Workflows

**Routing logic (Switch node):**

| package_type | Paths Activated | Steps Created in processing_jobs |
|-------------|-----------------|----------------------------------|
| `re_standard` | A | photo_color_grade, delivery_packaging |
| `re_premium` | A + V | photo_color_grade, video_metadata, video_qa, video_proxy, video_color_grade, video_edit_gate, video_export, delivery_packaging |
| `site_survey` | C + (E if veg_enabled) + A | mipmap_launch, ortho_harvest, (veg E1-E4 + review), photo_color_grade, delivery_packaging |
| `environmental_survey` | C + E + A | mipmap_launch, ortho_harvest, veg E1-E4 + review, photo_color_grade, delivery_packaging |
| `construction_hybrid` | C + A + (V if video) | mipmap_launch, ortho_harvest, photo_color_grade, (video pipeline if video_count > 0), delivery_packaging |
| `adiat` | D + C + A | adiat_processing, mipmap_launch, ortho_harvest, photo_color_grade, delivery_packaging |

**Execution model:** Paths can run in parallel where independent. Path C must complete before Path E can start (ortho dependency). Path A (photo grading) and Path V (video) are independent of Path C and can run concurrently.

### Integration Point 4: Package Router → processing_jobs Creation

**New pattern:** The Package Router creates a `processing_jobs` row before dispatching to any path. This is the orchestration record that all scripts report status to via `PipelineStatusReporter`.

```json
// processing_jobs row created by Package Router
{
  "id": "uuid",
  "mission_id": "uuid",
  "package_type": "site_survey",
  "status": "running",
  "steps": [
    {"name": "photo_color_grade", "status": "pending"},
    {"name": "mipmap_launch", "status": "pending"},
    {"name": "ortho_harvest", "status": "pending"},
    {"name": "veg_canopy_detection", "status": "pending"},
    {"name": "veg_species_classification", "status": "pending"},
    {"name": "veg_health_assessment", "status": "pending"},
    {"name": "veg_report_generation", "status": "pending"},
    {"name": "veg_review_gate", "status": "pending"},
    {"name": "delivery_packaging", "status": "pending"}
  ],
  "created_at": "2026-03-05T...",
  "started_at": "2026-03-05T..."
}
```

Each script receives `--processing-job-id` from the n8n Execute Command node and uses `PipelineStatusReporter` to update its step status. This pattern is already established and used by all v1.0 scripts.

### Integration Point 5: Path C -- MipMap Launch and Output Harvesting

**This is the most complex new integration.** `ingest.py` already contains all the MipMap task.json generation logic but does NOT follow the pipeline contract. It needs to be refactored into two contract-compliant scripts:

**Step C1: `mipmap_launcher.py`** (refactored from `ingest.py`)
```
Input:  mission_path (with photos/jpeg/ populated by ingest_sorter)
Output: JSON stdout with workspace paths

1. Scan mission photos/jpeg/ for JPGs with EXIF/GPS
2. Build task.json (reuse ingest.py functions)
3. Create D:/ workspace (reuse ingest.py create_workspace)
4. Launch reconstruct_full_engine.exe --task_json=... (subprocess.Popen)
5. Write workspace metadata to mission folder (.mipmap_workspace.json)
6. JSON stdout: {task_dir, result_dir, workspace_id, pid, status: "launched"}
```

**Step C2: MipMap Completion Polling** (n8n workflow nodes, NOT a Python script)
```
n8n poll loop (same pattern as Path E ortho polling):
1. Wait N seconds
2. Check if result/ folder contains orthomosaic GeoTIFF
3. If found → proceed to C3
4. If not found and attempts < max → loop
5. If timeout → mark failed
```

**Step C3: `ortho_harvester.py`** (NEW script)
```
Input:  mission_path, workspace metadata from .mipmap_workspace.json
Output: JSON stdout with ortho path

1. Read .mipmap_workspace.json for result_dir
2. Find GeoTIFF in result_dir (glob for *.tif)
3. Copy to mission_path/mapping/orthomosaic.tif
4. Verify file integrity (rasterio.open, check bands/CRS)
5. Update Supabase drone_jobs.output_path
6. JSON stdout: {ortho_path, file_size_bytes, crs_epsg, status: "ok"}
```

**MipMap workspace structure (from ingest.py audit):**
```
D:/{user_uuid}/
├── {project_name}/
│   └── {task_name}/
│       ├── task.json         ← input to reconstruct_full_engine.exe
│       ├── info.json
│       └── result/
│           ├── orthomosaic.tif    ← OUTPUT: GeoTIFF to harvest
│           ├── 3d_tiles/
│           ├── point_cloud.las
│           └── ...
├── indexes.json
├── project_index.json
└── task_index.json
```

**Key finding from ingest.py:** The workspace root is `D:/` with UUID subdirectories. The result directory is `D:/{user_uuid}/{project_name}/{task_name}/result/`. The GeoTIFF output filename from MipMap is not fixed -- it could be `orthomosaic.tif`, `dom.tif`, or similar. The harvester must glob for `*.tif` and identify the orthomosaic by file size (largest TIF) or metadata.

### Integration Point 6: Path C Complete → Path E Trigger

**Current state:** Path E workflow (`path_e_workflow.json`) has its own webhook trigger at `/sentinel-vegetation-trigger` and polls for ortho existence internally (E0 poll loop).

**v3.0 change:** The Package Router's Path C branch should fire the Path E trigger AFTER ortho harvesting completes, eliminating the need for E0 polling. Two approaches:

**Option A (Recommended): Package Router fires Path E webhook after C3**
```
Package Router
  └── Path C branch
      ├── C1: mipmap_launcher.py
      ├── C2: Poll for MipMap completion (n8n Wait + Check loop)
      ├── C3: ortho_harvester.py (copies ortho to mapping/)
      └── IF vegetation_enabled:
          └── POST /sentinel-vegetation-trigger {mission_id}
              └── Path E workflow runs E0-E5 (E0 ortho check succeeds immediately)
```

This keeps the Path E workflow fully independent and testable. The E0 ortho polling still works as a safety net but will find the ortho on the first check since C3 already placed it.

**Option B: Merge Path E into Package Router as inline nodes**
Not recommended -- Path E is already 35 nodes and works independently. Merging creates a monolithic workflow.

### Integration Point 7: Path V -- Video Pipeline Orchestration

**The video pipeline has 7 existing scripts that run sequentially:**

```
V1: video_metadata.py → V2: video_qa.py → V3: video_proxy_gen.py →
V4: video_color_grade.py → V5: [DaVinci Resolve manual edit] →
V6: video_format_export.py → V7: delivery_packaging.py --video-addendum
```

**v3.0 approach:** Wrap each as an Execute Command node in the Path V sub-workflow, with a Webhook Wait gate at V5 (manual edit step).

**V5 gate pattern:**
```
V4 completes → n8n sets processing_jobs step "video_edit_gate" to "awaiting_manual_edit"
             → Webhook Wait at /sentinel-video-resume
             → Operator edits in DaVinci Resolve, exports to video/master/
             → POST /sentinel-video-resume {mission_id, approved: true}
             → V6 resumes
```

This mirrors the existing E5 review gate pattern.

### Integration Point 8: Path A -- Photo Processing

**Simplest path.** RE photos need only color grading and delivery packaging.

```
A1: video_color_grade.py (handles photos too via --mode photo) OR
    just skip if package already has graded JPEGs from DJI
A2: delivery_packaging.py --address "..." --city "..."
```

**Note:** `video_color_grade.py` is misnamed -- audit shows it processes both video and photo LUT application. For RE packages with no video, Path A is just delivery packaging of the sorted photos.

---

## Data Flow by Path

### Path A (RE Photos)

```
ingest_sorter → photos sorted to photos/jpeg/
                     │
                     ▼
              delivery_packaging.py
              --address "..." --city "..."
                     │
                     ▼
              Sentinel_{address}_{date}.zip → Google Drive
```

### Path V (Video)

```
ingest_sorter → video sorted to video/full/, video/proxy/
                     │
        ┌────────────▼────────────────────────────────┐
        │ V1: video_metadata.py                       │
        │ V2: video_qa.py                             │
        │ V3: video_proxy_gen.py                      │
        │ V4: video_color_grade.py                    │
        │ ── V5 GATE: DaVinci Resolve manual edit ──  │
        │ V6: video_format_export.py                  │
        │ V7: delivery_packaging.py --video-addendum  │
        └─────────────────────────────────────────────┘
```

### Path C (Mapping/MipMap)

```
ingest_sorter → photos sorted to photos/jpeg/
                     │
        ┌────────────▼───────────────────────────────────────┐
        │ C1: mipmap_launcher.py                             │
        │     - Scan photos, extract EXIF/XMP/GPS            │
        │     - Build task.json with camera calibration       │
        │     - Create D:/ workspace                          │
        │     - Launch reconstruct_full_engine.exe            │
        │     - Write .mipmap_workspace.json to mission dir   │
        │                                                      │
        │ C2: n8n Poll Loop (Wait 60s + check result/)        │
        │     - Check D:/{uuid}/.../result/ for *.tif         │
        │     - MipMap processing takes 15-90 min              │
        │     - Max 120 attempts = 2 hour timeout              │
        │                                                      │
        │ C3: ortho_harvester.py                               │
        │     - Copy GeoTIFF from D:/ workspace → mapping/    │
        │     - Verify CRS and band count via rasterio         │
        │     - Update drone_jobs.output_path in Supabase      │
        │     - JSON stdout: {ortho_path, crs_epsg, size_mb}  │
        └──────────────────┬─────────────────────────────────┘
                           │
                ┌──────────▼──────────┐
                │ vegetation_enabled? │
                │ (processing_templates│
                │  .vegetation_enabled)│
                └───┬────────────┬────┘
               YES  │            │ NO
                    ▼            ▼
              POST to Path E   continue to
              webhook          delivery
```

### Path C → E Combined Flow

```
C3 ortho in mapping/
        │
        ▼
E0: Check ortho exists (immediate success since C3 placed it)
E1: canopy_detection.py
E2: species_classification.py
E3: health_assessment.py
E4: vegetation_report.py
E5: Review Gate (Webhook Wait at /sentinel-vegetation-resume)
        │ approved
        ▼
delivery_packaging.py --include-mapping --include-vegetation
```

---

## Webhook URL Registry

All webhook endpoints in the v3.0 system:

| Webhook Path | Sender | Receiver | Payload |
|-------------|--------|----------|---------|
| `/webhook/folder-watcher` | `folder_watcher.py` | Ingest Trigger workflow (NEW) | `{folder_path, folder_name, mission_number, photo_count, video_count, has_ppk_data, total_size_bytes}` |
| `/webhook/package-router` | `ingest_sorter.py` (retarget) | Package Router workflow (NEW) | `{mission_id, mission_number, package_type, photo_count, video_count, has_ppk_data, source_platform}` |
| `/sentinel-vegetation-trigger` | Package Router (after C3) | Path E workflow (EXISTING) | `{mission_id}` |
| `/sentinel-vegetation-resume` | Operator (review) | Path E workflow (EXISTING) | `{mission_id, decisions: [{detection_id, action}]}` |
| `/sentinel-video-resume` | Operator (after V5 edit) | Path V sub-workflow (NEW) | `{mission_id, approved: bool}` |

**Environment variables for webhook URLs:**
```
N8N_BASE_URL=http://localhost:5678
N8N_WEBHOOK_URL=http://localhost:5678/webhook/package-router  (ingest_sorter target)
```

---

## Supabase Schema Integration

### Existing Tables Used by Package Router

| Table | How Router Uses It |
|-------|-------------------|
| `drone_jobs` (aka missions) | Fetch mission metadata (package_type, vegetation_analysis, output_path) |
| `processing_templates` | Fetch template by package_type (vegetation_enabled, vegetation_config, video_formats) |
| `processing_jobs` | CREATE new row with steps[] array; all scripts update via PipelineStatusReporter |
| `processing_steps` | Path E inserts step rows (existing pattern from v2.0) |
| `vegetation_detections` | Written by E1-E3, read by E4 (existing, no changes) |
| `vegetation_analysis_summary` | Written by E4 (existing, no changes) |
| `video_assets` | Written by V1, updated by V2/V6 (existing, no changes) |

### New Supabase Additions for v3.0

**`processing_templates` -- add columns for all paths:**
```sql
ALTER TABLE processing_templates
    ADD COLUMN IF NOT EXISTS photo_steps JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS video_steps JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS mapping_enabled BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS mapping_config JSONB DEFAULT '{}'::jsonb;

-- mapping_config example:
-- {
--   "quality_level": 2,      -- 1=Ultra, 2=High, 3=Medium (maps to resolution_level)
--   "generate_3d_tiles": true,
--   "generate_las": true,
--   "generate_geotiff": true,
--   "timeout_minutes": 120
-- }
```

**`drone_jobs` -- add MipMap workspace tracking:**
```sql
ALTER TABLE drone_jobs
    ADD COLUMN IF NOT EXISTS mipmap_workspace JSONB;

-- Stores: {user_id, project_name, task_name, task_dir, result_dir, pid, launched_at}
-- Written by mipmap_launcher.py, read by ortho_harvester.py
```

---

## New Script Contracts

### mipmap_launcher.py (Step C1)

```python
"""
Sentinel Aerial Inspections -- MipMap Photogrammetry Launch (Step C1)

Generates task.json from mission photos and launches MipMap reconstruct engine.

Usage:
    python mipmap_launcher.py path/to/mission --mission-id UUID
    python mipmap_launcher.py path/to/mission --mission-id UUID --quality 1
    python mipmap_launcher.py path/to/mission --mission-id UUID --dry-run
"""

# Required argparse: mission_path (positional), --mission-id, --dry-run, --force
# Optional: --quality (1/2/3), --workspace (default D:/)
# Exit codes: 0=launched, 1=no valid photos, 2=engine not found

# JSON stdout on success:
{
    "mission_id": "uuid",
    "step": "mipmap_launch",
    "task_dir": "D:\\{uuid}\\{project}\\{task}",
    "result_dir": "D:\\{uuid}\\{project}\\{task}\\result",
    "task_json_path": "D:\\{uuid}\\{project}\\{task}\\task.json",
    "workspace_id": "uuid",
    "pid": 12345,
    "photo_count": 250,
    "quality_level": 2,
    "status": "launched"
}
```

### ortho_harvester.py (Step C3)

```python
"""
Sentinel Aerial Inspections -- MipMap Output Harvester (Step C3)

Copies orthomosaic GeoTIFF from MipMap workspace to mission mapping/ folder.

Usage:
    python ortho_harvester.py path/to/mission --mission-id UUID
    python ortho_harvester.py path/to/mission --mission-id UUID --dry-run
"""

# Required argparse: mission_path (positional), --mission-id, --dry-run
# Exit codes: 0=success, 1=ortho not found, 2=copy failed

# JSON stdout on success:
{
    "mission_id": "uuid",
    "step": "ortho_harvest",
    "ortho_path": "E:\\Sentinel\\Incoming\\SAI_M0047_...\\mapping\\orthomosaic.tif",
    "source_path": "D:\\{uuid}\\...\\result\\dom.tif",
    "file_size_mb": 847.3,
    "crs_epsg": 32618,
    "band_count": 4,
    "width_px": 25600,
    "height_px": 19200,
    "gsd_cm": 2.4,
    "status": "ok"
}
```

---

## n8n Workflow Architecture

### Package Router Workflow -- Node Layout

```
[Webhook Trigger] ─── /webhook/package-router
        │
        ▼
[Fetch Mission] ─── GET drone_jobs WHERE id = mission_id
        │
        ▼
[Fetch Template] ─── GET processing_templates WHERE preset_name = package_type
        │
        ▼
[Build Steps Array] ─── Code node: construct steps[] based on template flags
        │
        ▼
[Create processing_jobs] ─── POST processing_jobs with steps[]
        │
        ▼
[Switch on package_type] ─── Switch node (6 outputs)
    ├── re_standard → Path A nodes
    ├── re_premium  → Path A + Path V (parallel branches via n8n "Execute Workflow" or inline)
    ├── site_survey → Path C nodes → (optional Path E trigger) → Path A
    ├── environmental_survey → Path C nodes → Path E trigger → Path A
    ├── construction_hybrid → Path C + Path A (+ Path V if video_count > 0)
    └── adiat → Path D + Path C + Path A
```

### Sub-Workflow Strategy

**Two viable approaches:**

**Option A: Monolithic Package Router with inline paths**
- All path nodes live in the Package Router workflow
- Simpler to deploy (single workflow import)
- Hard to maintain at 80+ nodes

**Option B (Recommended): Package Router + separate sub-workflows**
- Package Router: 15-20 nodes (routing + processing_jobs creation)
- Path A workflow: 5-8 nodes (photo grade + delivery)
- Path V workflow: 20-25 nodes (V1-V7 + V5 gate)
- Path C workflow: 15-20 nodes (C1 launch + C2 poll + C3 harvest + E trigger)
- Path B workflow: 10-12 nodes (construction variant of C + A)
- Path D workflow: 5-8 nodes (ADIAT stub)
- Path E workflow: 35 nodes (EXISTING, unchanged)
- Uses n8n "Execute Workflow" node to call sub-workflows
- Each sub-workflow receives `{mission_id, processing_job_id, mission_path}` as input

**Decision: Option B.** The Path E workflow is already 35 nodes and standalone. Maintaining consistency across all paths as separate workflows enables independent testing, version control, and n8n workflow versioning.

### n8n Execute Workflow Pattern

```javascript
// In Package Router, for each path:
// Execute Workflow node calls the sub-workflow

// Input passed to sub-workflow:
{
  "mission_id": "{{ $json.mission_id }}",
  "processing_job_id": "{{ $json.processing_job_id }}",
  "mission_path": "{{ $json.mission_path }}",
  "package_type": "{{ $json.package_type }}",
  "template_config": { /* from processing_templates */ }
}
```

---

## Build Order (Dependency-First)

Build in this order to allow incremental testing at each step:

### Phase 1: Foundation (No n8n Changes)

1. **`mipmap_launcher.py`** -- Refactor `ingest.py` into pipeline-contract script. All the logic exists; it needs argparse contract, JSON stdout, `PipelineStatusReporter`, and `.mipmap_workspace.json` output.

2. **`ortho_harvester.py`** -- New script. Reads `.mipmap_workspace.json`, finds GeoTIFF, copies to `mapping/`, validates with rasterio. Simple script, testable in isolation.

3. **Supabase migration** -- Add `mapping_config`, `mapping_enabled` columns to `processing_templates`; add `mipmap_workspace` JSONB to `drone_jobs`. Seed template configs.

4. **Tests for C1 and C3** -- Mock subprocess for MipMap engine, mock rasterio for ortho validation.

### Phase 2: Package Router Core

5. **Package Router n8n workflow** -- Webhook trigger, fetch mission/template, create processing_jobs, Switch node routing. Start with just `re_standard` path (simplest).

6. **Path A sub-workflow** -- Execute `delivery_packaging.py` for RE photo packages. Test end-to-end with manual webhook POST.

### Phase 3: Path C Integration

7. **Path C sub-workflow** -- Execute `mipmap_launcher.py`, poll loop for completion, execute `ortho_harvester.py`. Test with a real MipMap run on small dataset.

8. **Path C → Path E trigger** -- After C3 completes, fire POST to `/sentinel-vegetation-trigger` if `vegetation_enabled`. Integration test with existing Path E workflow.

### Phase 4: Path V Integration

9. **Path V sub-workflow** -- Wire V1-V7 Execute Command nodes with V5 manual edit gate (Webhook Wait). Test with an RE Premium mission.

### Phase 5: Remaining Paths and Polish

10. **Path B sub-workflow** -- Construction hybrid (C + A + optional V).
11. **Path D sub-workflow** -- ADIAT placeholder.
12. **Folder Watcher → Ingest Trigger** -- Wire folder_watcher webhook to run ingest_sorter automatically, then fire Package Router.
13. **End-to-end integration test** -- SD card → folder_watcher → ingest_sorter → Package Router → all paths.

**Key dependencies:**
- Phase 2 depends on Phase 1 (scripts must exist before n8n can call them)
- Phase 3 depends on Phase 2 (Package Router must route to Path C)
- Phase 4 is independent of Phase 3 (Path V does not depend on Path C)
- Phase 5 depends on all prior phases

---

## Error Handling Architecture

### Global Error Strategy

Every path sub-workflow should have an error handler node that:
1. Sets `processing_jobs.status = 'failed'`
2. Sets the failing step's status to `'failed'` with error message
3. Sends operator notification (email or log)
4. Does NOT block other independent paths (Path A failure should not block Path C)

### Script Failure Recovery

| Scenario | Detection | Recovery |
|----------|-----------|----------|
| MipMap engine crash (C1) | Process PID not running, no output files | Re-run `mipmap_launcher.py --force` (clears workspace, re-launches) |
| MipMap timeout (C2) | Poll count exceeds max | Operator checks D:/ workspace manually; re-trigger Package Router |
| Ortho harvest fails (C3) | File not found or rasterio validation fails | Check MipMap output manually; run `ortho_harvester.py` standalone |
| Path E script fails (E1-E4) | Non-zero exit code | Existing: checkpoint resume + n8n retry |
| Video script fails (V1-V7) | Non-zero exit code | Script-level checkpoint resume |
| delivery_packaging fails | Non-zero exit code | Operator runs manually with same args |

### Parallel Path Isolation

```
Package Router creates processing_jobs
    │
    ├── Path A (photos)  ─── independent, can complete even if C fails
    ├── Path C (mapping)  ─── independent of A and V
    │     └── Path E (vegetation) ─── depends on C only
    └── Path V (video)   ─── independent, can complete even if C fails
```

If Path C fails, Path A and Path V should still complete and produce a partial delivery (photos + video without mapping/vegetation). The `delivery_packaging.py` `--include-mapping` and `--include-vegetation` flags are only passed when those paths completed successfully.

---

## Scalability Considerations

This is a single-rig, single-mission processing system. Concurrency means one mission at a time on the GPU (MipMap uses GPU for photogrammetry, Path E uses GPU for DeepForest). However, multiple missions can be in different pipeline stages simultaneously:

| Resource | Constraint | Mitigation |
|----------|-----------|------------|
| GPU (MipMap) | 1 job at a time | n8n workflow should check if MipMap is already running before launching C1 |
| GPU (Path E) | 1 job at a time | Path E already handles this; runs after MipMap completes |
| Disk (D:/) | MipMap workspace can be 10-50GB per mission | ortho_harvester cleans workspace after successful harvest (configurable) |
| n8n concurrent executions | Default 20 | Adequate for single-rig operation |
| Supabase connections | Service role, single connection | No concern |

---

## Anti-Patterns

### Anti-Pattern 1: Monolithic n8n Workflow

**What people do:** Put all paths in one giant workflow (100+ nodes).
**Why it's wrong:** Impossible to test individual paths. Any edit risks breaking unrelated paths. n8n editor slows down above ~50 nodes.
**Do this instead:** Separate sub-workflows per path, called via Execute Workflow node.

### Anti-Pattern 2: MipMap Blocking the n8n Execution Thread

**What people do:** Use Execute Command with `subprocess.run()` (blocking) to launch MipMap, tying up the n8n worker for 30-90 minutes.
**Why it's wrong:** Blocks the n8n execution slot. If n8n restarts, the tracking is lost.
**Do this instead:** Launch MipMap with `subprocess.Popen()` (non-blocking), record PID in `.mipmap_workspace.json`, use n8n Wait + Poll loop to check for completion. The `mipmap_launcher.py` script returns immediately after launch.

### Anti-Pattern 3: Hardcoding Webhook URLs in Python Scripts

**What people do:** Embed `http://localhost:5678/webhook/...` directly in scripts.
**Why it's wrong:** Cannot change n8n URL without editing scripts.
**Do this instead:** All webhook URLs come from `N8N_WEBHOOK_URL` environment variable or `--webhook-url` CLI argument. This is already the pattern in `folder_watcher.py` and `ingest_sorter.py`.

### Anti-Pattern 4: Polling Ortho When the Router Knows It's Ready

**What people do:** Every downstream consumer (Path E, delivery) independently polls for ortho existence.
**Why it's wrong:** Wastes time and creates race conditions.
**Do this instead:** Package Router fires downstream triggers ONLY after `ortho_harvester.py` confirms the file is in place. Path E's E0 poll is a safety net, not the primary trigger.

### Anti-Pattern 5: Re-running ingest.py Instead of Refactoring

**What people do:** Call `ingest.py` from n8n as-is without the pipeline contract.
**Why it's wrong:** `ingest.py` prints to stdout with human-readable text (not JSON), has no `--processing-job-id`, and `subprocess.Popen` in `--run` mode blocks until completion.
**Do this instead:** Create `mipmap_launcher.py` that extracts the reusable functions from `ingest.py` but follows the pipeline contract. `ingest.py` remains as a standalone manual tool.

---

## Sources

- Direct codebase audit: all 18 Python scripts + n8n workflow JSON files (2026-03-05)
- `folder_watcher.py` -- watchdog Observer + debounce handler, POST `/webhook/folder-watcher`
- `ingest_sorter.py` -- sequence-range sorting, POST `/webhook/ingest` with mission_id + package_type
- `ingest.py` -- MipMap task.json generation, workspace creation, engine launch via subprocess
- `delivery_packaging.py` -- `collect_vegetation()`, `--include-vegetation`, `--include-mapping` flags already present
- `pipeline_status.py` -- `PipelineStatusReporter` + `add_pipeline_args()` pattern
- `n8n/path_e_workflow.json` -- 35-node workflow with E0 ortho polling, E1-E4 Execute Command, E5 review gate
- `n8n/package_router_patch.json` -- template_defaults for routing conditions, vegetation_enabled per package_type
- `.planning/codebase/INTEGRATIONS.md` -- webhook contracts, Supabase schema, env vars
- `.planning/research/ARCHITECTURE.md` (v2.0) -- Path E architecture patterns, script contracts, Supabase tables

---

*Architecture research for: v3.0 Package Router & End-to-End Automation*
*Researched: 2026-03-05*
*Confidence: HIGH -- based on direct audit of all source files, n8n workflows, and Supabase schema*
