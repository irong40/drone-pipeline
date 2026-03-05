# Feature Landscape

**Domain:** Drone pipeline orchestration -- Package Router, multi-path automation, event-driven triggers
**Researched:** 2026-03-05
**Milestone:** v3.0 Package Router & End-to-End Automation
**Confidence:** HIGH (patterns established by existing Path E workflow and ingest_sorter; extending proven architecture)

---

## Context: What Already Exists

Before defining v3.0 features, the existing pieces that v3.0 builds on:

| Component | Status | Relevance to v3.0 |
|-----------|--------|-------------------|
| `ingest_sorter.py` | Built | Fires webhook with `package_type`, `mission_id`, inventory -- this IS the Package Router's trigger |
| `folder_watcher.py` | Built | Detects new mission folders, fires webhook after debounce -- currently posts to `/webhook/folder-watcher` |
| `folder_watcher_service.py` | Built | Windows service wrapper for folder_watcher |
| Path E workflow (`path_e_workflow.json`) | Built | Pattern for n8n workflow: webhook trigger, Supabase status updates, Execute Command nodes, review gate |
| `package_router_patch.json` | Designed | Template defaults for 4 package types with vegetation_enabled routing |
| `ingest.py` | Built | MipMap task.json generation and `--run` flag for engine launch |
| Video pipeline (V1-V6) | Built | 6 scripts: color_grade, metadata, srt_telemetry, qa, proxy_gen, format_export |
| `delivery_packaging.py` | Built | Two-stage delivery with address renaming, vegetation subfolder support |
| `gdrive_upload.py` | Built | Google Drive upload |
| `archive_sync.py` | Built | Archive to F:\ |

**Key insight:** v3.0 is primarily an n8n orchestration milestone. The Python scripts already exist and work. The job is to wire them together through n8n workflows that route by package_type, execute scripts via Execute Command nodes, and track status in Supabase.

---

## Table Stakes

Features that are expected for a working Package Router and end-to-end automation. Without these, the pipeline still requires manual script invocation.

| Feature | Why Expected | Complexity | Dependencies |
|---------|--------------|------------|-------------|
| **Package Router webhook receiver** | Single entry point for all ingest webhooks; without it, each path needs manual triggering | LOW | n8n webhook node at `/webhook/ingest` |
| **Route by package_type** | Different packages need different processing paths; `real_estate` skips mapping, `site_survey` needs ortho + vegetation | MEDIUM | n8n Switch node reading `package_type` from webhook payload |
| **Path C automation (MipMap launch)** | Photogrammetry is the longest step (20-90 min); manual launch wastes operator time | MEDIUM | `ingest.py --run`, MipMap engine on D:/, task.json generation |
| **MipMap output harvester** | GeoTIFF output lands on D:/ workspace; needs copying to mission `mapping/` folder | MEDIUM | File existence polling or watcher on D:/ workspace directory |
| **Path C Supabase status tracking** | Operator needs to know mapping status without checking filesystem | LOW | `processing_steps` table: step_name=mapping, status=processing/complete/failed |
| **Path A automation (RE photos)** | Real estate is the most common package type; photos need color grade then delivery | LOW | `video_color_grade.py` (for photos -- reuses LUT logic) or direct to delivery |
| **Path V automation (video pipeline)** | Video packages need the full V1-V6 sequence automated | HIGH | 6 scripts in sequence, each with checkpoint resume and exit code handling |
| **Supabase status per processing step** | Every script's progress must be visible; operator should never wonder "where is this mission?" | LOW | INSERT/PATCH to `processing_steps` table before and after each Execute Command |
| **Error handling with status=failed** | Script exit code 1 must mark the step failed and halt the path | LOW | n8n IF node checking exitCode after each Execute Command |
| **Path E trigger from Path C completion** | When ortho is ready and vegetation_enabled=true, fire Path E automatically | LOW | Already designed in `package_router_patch.json` routing_condition |
| **Folder watcher to Package Router connection** | folder_watcher currently fires to `/webhook/folder-watcher`; needs to integrate with or trigger the Package Router | MEDIUM | Either folder_watcher fires the same `/webhook/ingest` endpoint, or a separate n8n workflow bridges the two |

---

## Differentiators

Features that go beyond basic routing and make the pipeline genuinely hands-off.

| Feature | Value Proposition | Complexity | Dependencies |
|---------|-------------------|------------|-------------|
| **Template defaults per package_type** | Operators do not configure per-mission; `site_survey` auto-enables vegetation, `real_estate` auto-disables -- config comes from `processing_templates` table | LOW | `package_router_patch.json` template_defaults already designed |
| **Parallel path fan-out** | `site_survey` needs both Path A (photos) and Path C (mapping) simultaneously; n8n can run both branches in parallel | MEDIUM | n8n parallel execution after Switch node; merge at delivery |
| **MipMap completion detection via folder watcher** | Instead of polling D:/ workspace every 60s (Path E pattern), use folder_watcher to detect GeoTIFF appearance and fire webhook | MEDIUM | New watcher instance on D:/ workspace or MipMap output dir |
| **Processing time estimation** | Based on photo_count from ingest, estimate MipMap duration (e.g., 200 photos ~ 30 min, 500 photos ~ 90 min) and set appropriate n8n timeout | LOW | Empirical table from past missions |
| **Delivery auto-trigger** | After all paths complete for a mission, automatically run delivery_packaging.py instead of manual invocation | MEDIUM | n8n merge/join node waiting for all active paths to reach "complete" |
| **Path B/D stub routing** | Construction and ADIAT packages route to placeholder workflows that log "manual processing required" and set status=manual | LOW | n8n Set node + Supabase PATCH; no script automation yet |
| **Mission progress dashboard query** | Supabase processing_steps table enables a single query to show all steps and their status for any mission | LOW | Already exists from Path E; extend to cover all paths |
| **Webhook retry on failure** | If n8n is down when ingest fires webhook, retry 3x with exponential backoff | LOW | Already pattern in `fire_webhook()` -- extend with retry logic |
| **Batch ingest support** | Multiple missions from one SD card (already supported by ingest_sorter.py) should fire multiple router invocations | LOW | ingest_sorter already iterates missions; each fires webhook |

---

## Anti-Features

Features to explicitly NOT build in v3.0.

| Anti-Feature | Why Requested | Why Avoid | What to Do Instead |
|--------------|---------------|-----------|-------------------|
| **n8n web dashboard for mission status** | Operators want a visual status board | n8n is orchestration, not UI; building a dashboard in n8n creates maintenance burden | Query Supabase processing_steps directly via Trestle app or SQL; add dashboard to Trestle backlog |
| **Automatic DaVinci Resolve integration (V5)** | Completes the video pipeline end-to-end | DaVinci Resolve has no reliable CLI automation for color grading projects; manual creative step | Keep V5 as manual operator step; Path V automates V1-V4 + V6 around the manual gap |
| **Parallel FFmpeg processing** | Multiple video files could process simultaneously | Performance optimization, not orchestration; deferred per PROJECT.md scope | v4.0 optimization milestone |
| **Dynamic package_type creation** | Operators might want custom package types | Adds schema complexity and routing edge cases for 4 well-defined types | Hardcode the 4 types (real_estate, site_survey, environmental_survey, construction_hybrid); add new types via migration when needed |
| **Real-time processing progress bars** | Operators want to see MipMap's 45%/60%/80% progress | MipMap engine stdout is not machine-parseable for progress; polling its log file is fragile | Use step-level granularity (processing/complete/failed) not sub-step progress |
| **Automatic retry of failed scripts** | If V1 fails, auto-retry before marking failed | Retry without understanding the failure cause can corrupt checkpoints or waste API credits | Mark failed, alert operator, let them diagnose and re-run manually or via n8n "retry" button |
| **Multi-rig distributed processing** | Scale across multiple machines | Single-operator business with one processing rig; distributed orchestration is massive complexity for no current need | Design for single-rig; revisit if business scales to multiple operators |
| **MipMap task.json customization per mission** | Different reconstruction settings per package | `ingest.py` already has sensible defaults; per-mission tuning is rare and operator can manually edit task.json | Use `ingest.py` defaults; document how to override for edge cases |

---

## Feature Dependencies

```
[Folder Watcher] ──fires──> [/webhook/folder-watcher]
                                 │
                                 v
[Ingest Sorter] ──fires──> [/webhook/ingest]
                                 │
                                 v
                     ┌─── Package Router (n8n) ───┐
                     │   Switch on package_type    │
                     └────────┬──────┬──────┬──────┘
                              │      │      │
                    ┌─────────┘      │      └─────────┐
                    v                v                v
              [Path A: Photos]  [Path C: Mapping]  [Path V: Video]
              color_grade.py    ingest.py --run     V1→V1.5→V2→V3→V4→V6
              delivery_pkg.py   MipMap engine       delivery_pkg.py
                    │           ortho harvester          │
                    │                │                   │
                    │                v                   │
                    │         [Ortho Ready?]             │
                    │           │         │              │
                    │      YES──┘    NO───┘              │
                    │           │  (poll/wait)           │
                    │           v                        │
                    │    [Path E trigger?]               │
                    │      │ vegetation_enabled          │
                    │      v                             │
                    │  [Path E workflow]                 │
                    │  (already built)                   │
                    │           │                        │
                    v           v                        v
              ┌─────────────────────────────────────────┐
              │        All Paths Complete?               │
              │   (merge/join on mission_id)             │
              └────────────────┬────────────────────────┘
                               v
                    [delivery_packaging.py]
                    [gdrive_upload.py]
                    [archive_sync.py]

Path B/D: ──> [Stub: manual processing]
              Set status=manual, alert operator
```

### Critical Dependency Chain

1. **Package Router requires ingest_sorter webhook** -- the payload shape (`mission_id`, `package_type`, `photo_count`, `video_count`, `has_ppk_data`, `source_platform`) is already defined in `fire_webhook()`
2. **Path C requires ingest.py** -- task.json generation depends on photos being in the mission folder (ingest_sorter places them)
3. **MipMap output harvester requires Path C** -- cannot copy GeoTIFF until photogrammetry completes
4. **Path E requires Path C ortho** -- already handled by ortho polling in path_e_workflow.json
5. **Delivery requires all active paths complete** -- the merge/join logic must know which paths are active for this package_type
6. **Path V depends on video files existing** -- only activate for missions where `video_count > 0`

### Path Activation Matrix

| package_type | Path A (Photos) | Path C (Mapping) | Path V (Video) | Path E (Vegetation) | Path B/D (Manual) |
|-------------|----------------|-----------------|---------------|--------------------|--------------------|
| real_estate | YES | NO | if video_count > 0 | NO | NO |
| site_survey | YES | YES | if video_count > 0 | if vegetation_enabled | NO |
| environmental_survey | YES | YES | if video_count > 0 | YES (auto) | NO |
| construction_hybrid | YES | YES | if video_count > 0 | NO (opt-in) | YES (ADIAT) |

---

## Feature Breakdown by Path

### Package Router (Core Orchestration)

| Feature | Script/Node | Inputs | Outputs | Complexity |
|---------|------------|--------|---------|------------|
| Webhook receiver | n8n Webhook node | POST from ingest_sorter | mission_id, package_type, inventory | LOW |
| Supabase mission lookup | n8n HTTP Request | mission_id | Full mission record + processing_template | LOW |
| Template merge | n8n Code node | package_type + template_defaults | Resolved config (vegetation_enabled, etc.) | LOW |
| Switch by package_type | n8n Switch node | package_type | Routes to path-specific branches | LOW |
| Processing steps insert | n8n HTTP Request | mission_id, active paths | INSERT rows for all active steps | LOW |

### Path A: Real Estate Photo Processing

| Feature | Script | CLI Args | Exit Codes | Notes |
|---------|--------|----------|------------|-------|
| Color grade photos | `video_color_grade.py` | `--mission-dir`, `--platform` | 0/1/2 | Reuses same LUT logic for photo color grading |
| Package for delivery | `delivery_packaging.py` | `--address`, `--city`, `--photos-only` | 0/1 | Two-stage: photos first |

**Total scripts in Path A:** 2 (or 1 if photos skip color grading for some packages)

### Path C: Photogrammetry (MipMap)

| Feature | Script/Tool | Inputs | Outputs | Duration |
|---------|------------|--------|---------|----------|
| Generate task.json | `ingest.py` | mission photos dir | D:/workspace/task.json | Seconds |
| Launch MipMap engine | `ingest.py --run` | task.json | GeoTIFF, 3D tiles, point cloud on D:/ | 20-90 min |
| Harvest outputs | New: `mipmap_harvester.py` or n8n watcher | D:/workspace outputs | Copy to mission/mapping/ | Seconds |
| Update Supabase status | n8n HTTP Request | mission_id | processing_steps.mapping = complete | Seconds |

**Key complexity:** MipMap runs 20-90 minutes. n8n Execute Command node will block the workflow thread. Options:
1. **Long timeout on Execute Command** -- simple, wastes an n8n worker thread
2. **Fire-and-forget + folder watcher on output** -- more complex but does not block n8n
3. **Subprocess launch + poll** -- `ingest.py --run` already returns after launching MipMap; poll for completion file

**Recommendation:** Option 3. `ingest.py --run` launches MipMap as a subprocess and returns immediately. A new watcher (or the existing folder_watcher with a second watch directory) detects the GeoTIFF output and fires a `/webhook/mipmap-complete` webhook to resume the workflow. This matches the event-driven architecture and does not block n8n.

### Path V: Video Pipeline

| Step | Script | Duration | Notes |
|------|--------|----------|-------|
| V1 Color Grade | `video_color_grade.py` | 2-10 min per file | FFmpeg LUT application |
| V1.5 Metadata | `video_metadata.py` | Seconds | Embed flight metadata |
| V2 SRT Telemetry | `srt_telemetry_parser.py` | Seconds | Parse telemetry overlay data |
| V3 QA | `video_qa.py` | Seconds | Quality checks |
| V4 Proxy Gen | `video_proxy_gen.py` | 1-5 min per file | Lower-res proxy for review |
| V5 DaVinci Resolve | MANUAL | Hours | Creative color grade -- NOT automated |
| V6 Format Export | `video_format_export.py` | 2-10 min per file | Multi-format export |

**Total automated steps:** 6 (V1, V1.5, V2, V3, V4, V6)
**Manual gap:** V5 (DaVinci Resolve) breaks the automation chain

**Recommendation for V5 gap:** Path V automates V1-V4, then pauses at a review/wait node (same pattern as Path E review gate). Operator does V5 manually, then fires a `/webhook/video-resume` POST to continue with V6 + delivery. This uses the proven webhook-wait pattern from Path E.

### Path B/D: Construction & ADIAT

| Feature | What It Does | Complexity |
|---------|-------------|------------|
| Route to stub | Switch node sends construction_hybrid to placeholder branch | LOW |
| Log manual step | n8n Set node marks processing_steps with status=manual | LOW |
| Alert operator | Optional: n8n notification (email/Slack) that manual processing is needed | LOW |

**Recommendation:** Stub only in v3.0. These package types are infrequent and have specialized processing requirements. Route them, log them, alert the operator, but do not automate the processing.

---

## Event-Driven Triggers

### Current State

| Trigger | Source | Target | Status |
|---------|--------|--------|--------|
| SD card ingest complete | `ingest_sorter.py --webhook` | `/webhook/ingest` | Built |
| New folder detected | `folder_watcher.py` | `/webhook/folder-watcher` | Built |
| Path E vegetation trigger | Package Router | `/webhook/sentinel-vegetation-trigger` | Built |
| Path E review resume | Operator POST | `/webhook/sentinel-vegetation-resume` | Built |

### New Triggers Needed for v3.0

| Trigger | Source | Target | Purpose | Complexity |
|---------|--------|--------|---------|------------|
| MipMap complete | Folder watcher or new watcher on D:/ | `/webhook/mipmap-complete` | Resume Path C after photogrammetry | MEDIUM |
| Video V5 resume | Operator POST | `/webhook/video-resume` | Resume Path V after manual DaVinci step | LOW |
| All paths complete | n8n merge logic | Internal (same workflow) | Trigger delivery_packaging | MEDIUM |
| Folder watcher to router bridge | folder_watcher.py | `/webhook/ingest` or bridge workflow | Connect auto-detection to Package Router | LOW |

### Folder Watcher Architecture Decision

The current `folder_watcher.py` fires to `/webhook/folder-watcher` with a basic inventory (photo_count, video_count, etc.) but NOT with `mission_id` or `package_type` -- those come from the Supabase `drone_jobs` table via `ingest_sorter.py`.

**Two usage patterns exist:**

1. **Manual ingest flow:** Operator runs `ingest_sorter.py` with missions.json, which creates folders AND fires webhook with full payload including mission_id and package_type. Folder watcher is redundant here.

2. **Auto-detection flow:** Operator copies folder to Incoming/ manually (or via launcher GUI). Folder watcher detects it, fires webhook. But the webhook payload lacks mission_id/package_type -- needs Supabase lookup by folder name pattern.

**Recommendation:** Keep both paths. The Package Router webhook should handle two payload shapes:
- **Full payload** (from ingest_sorter): Has mission_id, package_type -- route immediately
- **Minimal payload** (from folder_watcher): Has folder_name only -- look up mission in Supabase drone_jobs by mission_number extracted from folder name, then route

This is a single n8n Code node that normalizes the payload before the Switch node.

---

## MVP Recommendation for v3.0

### Must Have (Launch)

1. **Package Router n8n workflow** -- webhook receiver, Switch by package_type, Supabase status tracking
2. **Path C automation** -- ingest.py launch, MipMap completion detection, ortho harvester
3. **Path A automation** -- photo processing through delivery (simplest path, most common package)
4. **Path E trigger from Path C** -- connect ortho completion to existing Path E workflow
5. **Template defaults in Supabase** -- processing_templates table populated from package_router_patch.json
6. **Folder watcher to router bridge** -- normalize folder_watcher payload for Package Router consumption

### Should Have (Same Release)

7. **Path V automation (V1-V4)** -- automate pre-DaVinci steps
8. **Path V resume webhook** -- webhook-wait pattern for V5 manual gap
9. **Path V completion (V6 + delivery)** -- automate post-DaVinci steps
10. **MipMap output watcher** -- event-driven detection instead of polling

### Defer (v3.1 or Later)

11. **Path B/D full automation** -- stub routing is sufficient for v3.0
12. **Delivery auto-trigger after all paths** -- complex merge logic; manual delivery trigger is acceptable initially
13. **Processing time estimation** -- nice-to-have, not blocking
14. **Batch mission orchestration** -- ingest_sorter already handles batch; router processes them sequentially

---

## Processing Step Names (Supabase Schema)

For consistency with existing Path E steps, all processing_steps entries should follow this naming:

| Path | step_name | Notes |
|------|-----------|-------|
| A | `photo_color_grade` | Photo LUT application |
| A | `photo_delivery` | delivery_packaging --photos-only |
| C | `mapping_taskgen` | ingest.py task.json generation |
| C | `mapping_engine` | MipMap photogrammetry processing |
| C | `mapping_harvest` | Copy outputs from D:/ to mission/mapping/ |
| V | `video_color_grade` | V1 |
| V | `video_metadata` | V1.5 |
| V | `video_srt_telemetry` | V2 |
| V | `video_qa` | V3 |
| V | `video_proxy_gen` | V4 |
| V | `video_manual_grade` | V5 -- status=manual (DaVinci) |
| V | `video_format_export` | V6 |
| V | `video_delivery` | delivery_packaging --video-addendum |
| E | `veg_canopy_detection` | Already exists |
| E | `veg_species_classification` | Already exists |
| E | `veg_health_assessment` | Already exists |
| E | `veg_report_generation` | Already exists |
| B/D | `construction_review` | Manual -- status=manual |
| Final | `gdrive_upload` | Google Drive delivery |
| Final | `archive_sync` | F:\ archive |

---

## Complexity Assessment

| Feature Group | Estimated Effort | Risk Level | Rationale |
|--------------|-----------------|------------|-----------|
| Package Router (webhook + switch + status) | 1-2 days | LOW | Follows exact Path E workflow pattern; 90% copy-paste from path_e_workflow.json |
| Path A automation | 0.5 days | LOW | 2 scripts, simple sequence, no long-running steps |
| Path C automation (MipMap launch) | 1 day | MEDIUM | ingest.py --run is built, but MipMap completion detection is new |
| MipMap output harvester | 1-2 days | MEDIUM | File discovery on D:/ workspace, copy logic, error handling for partial outputs |
| Path V automation | 2-3 days | MEDIUM | 6 scripts in sequence, V5 manual gap requires webhook-wait pattern |
| Path E trigger connection | 0.5 days | LOW | Already designed in package_router_patch.json; just wire the IF node |
| Folder watcher bridge | 0.5 days | LOW | Payload normalization Code node |
| Path B/D stubs | 0.5 days | LOW | Set node + Supabase PATCH |
| Supabase schema (processing_templates + steps) | 0.5 days | LOW | Migration file + seed data |
| Testing | 2-3 days | LOW | n8n workflow testing is manual; Python script tests already exist |

**Total estimated effort:** 10-14 days

---

## Sources

- Existing codebase analysis: `ingest_sorter.py`, `folder_watcher.py`, `ingest.py`, `video_color_grade.py`, `delivery_packaging.py` -- HIGH confidence (direct code review)
- Existing n8n patterns: `path_e_workflow.json` -- HIGH confidence (proven in production)
- Package router design: `package_router_patch.json` -- HIGH confidence (already designed with template_defaults and routing_condition)
- n8n Execute Command node behavior: known from Path E workflow pattern -- HIGH confidence
- MipMap engine behavior: `ingest.py` config shows `WORKSPACE = "D:/"` and engine path -- HIGH confidence (code review)

---

*Feature research for: Sentinel drone pipeline v3.0 Package Router & End-to-End Automation*
*Researched: 2026-03-05*
