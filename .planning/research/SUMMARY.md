# Project Research Summary

**Project:** Sentinel Drone Pipeline v3.0 -- Package Router & End-to-End Automation
**Domain:** n8n workflow orchestration, multi-path drone data processing, event-driven pipeline automation on Windows
**Researched:** 2026-03-05
**Confidence:** HIGH

## Executive Summary

v3.0 is an orchestration milestone, not a greenfield build. The 18 Python CLI scripts, Supabase schema, Path E n8n workflow (35 nodes), folder watcher, and ingest sorter are all deployed and tested (402 tests passing). The job is to wire these existing components together through a new n8n Package Router workflow that receives ingest webhooks, routes by `package_type` (real estate, site survey, environmental survey, construction hybrid), fans out to per-path sub-workflows (A/B/C/D/V/E), and tracks status in Supabase. One new Python script is needed: an ortho harvester that copies MipMap photogrammetry output from D:/ workspace to mission folders. No new pip dependencies are required.

The recommended architecture uses n8n sub-workflows (one per path) called from a central Package Router via Execute Sub-workflow nodes. This mirrors the proven Path E pattern and keeps each path independently testable. The most complex new integration is Path C (MipMap photogrammetry automation), which involves launching a long-running GPU process (20-90 minutes), detecting completion, and harvesting output. All four researchers converged on a fire-and-forget launch pattern with polling for completion, rather than blocking the n8n execution thread -- this is critical because n8n's Execute Command node has a 1MB stdout buffer that MipMap will overflow.

The top risks are: (1) n8n v2.0 disabling Execute Command nodes by default, which would silently break all automation; (2) MipMap stdout buffer overflow killing the photogrammetry process mid-run; (3) orphaned MipMap processes when n8n workflows are cancelled on Windows; and (4) GPU contention between concurrent Path C (MipMap), Path E (DeepForest), and Path V (FFmpeg NVENC). All are preventable with known mitigations documented in the pitfalls research. The estimated total effort is 10-14 days across 5 phases.

## Key Findings

### Recommended Stack

No new frameworks or dependencies are needed. v3.0 builds entirely on the existing stack with n8n built-in nodes and one new stdlib-only Python script.

**Core technologies:**
- **n8n Switch node (Rules Mode):** Routes by `package_type` to path-specific branches -- handles 4 package types + fallback within built-in 4-output limit
- **n8n Execute Sub-workflow:** Calls per-path workflows, supports "Wait for Completion" -- keeps paths isolated and independently testable
- **n8n Execute Command:** Runs Python scripts from n8n -- already proven in Path E with 5 nodes; MUST redirect MipMap stdout to file
- **mipmap_launcher.py (refactored from ingest.py):** Launches MipMap engine via subprocess.Popen, writes PID file, returns immediately -- stdlib only
- **ortho_harvester.py (new):** Copies GeoTIFF from D:/ to mission mapping/ folder with integrity verification -- stdlib + rasterio for validation
- **n8n environment variables (6 new):** MIPMAP_ENGINE_PATH, MIPMAP_WORKSPACE, SENTINEL_INCOMING, SENTINEL_SCRIPTS, VENV_PATH_E_PYTHON, N8N_BASE_URL

**What NOT to add:** Airflow/Prefect/Dagster (n8n is sufficient), WebODM (MipMap is superior), Redis/RabbitMQ (overkill for single-rig), Docker for scripts (need local drive access), community n8n nodes (compatibility risk).

### Expected Features

**Must have (table stakes):**
- Package Router webhook receiver + Switch by package_type
- Path C automation: MipMap launch, completion detection, ortho harvest
- Path A automation: photo color grade + delivery packaging (most common package)
- Path E trigger from Path C completion (connect ortho to existing vegetation workflow)
- Supabase status tracking per processing step (every script reports progress)
- Error handling: exit code 1 marks step failed and halts the path
- Template defaults per package_type from processing_templates table

**Should have (same release):**
- Path V automation: V1-V4 automated, V5 manual DaVinci gate (webhook-wait pattern), V6 automated
- Parallel path fan-out: site_survey runs Path A + Path C simultaneously
- Folder watcher to Package Router bridge (payload normalization)
- MipMap completion detection via polling (event-driven alternative deferred)

**Defer (v3.1+):**
- Path B/D full automation (stub routing sufficient for infrequent package types)
- Delivery auto-trigger after all paths complete (complex merge logic)
- n8n dashboard for mission status (use Trestle app or direct Supabase queries)
- Automatic DaVinci Resolve integration (no reliable CLI automation exists)
- Parallel FFmpeg processing, multi-rig distribution, real-time progress bars

### Architecture Approach

The system uses a hub-and-spoke architecture: the Package Router is the hub that receives all ingest webhooks and dispatches to per-path sub-workflows (spokes). Each sub-workflow receives `{mission_id, processing_job_id, mission_path}` and operates independently. Paths can run in parallel where independent (A + C + V), but Path E depends on Path C completing first (ortho dependency). The Package Router creates a `processing_jobs` row with all active steps before dispatching, giving operators a single query to see mission progress.

**Major components:**
1. **Package Router workflow (15-20 nodes)** -- webhook receiver, Supabase lookups, processing_jobs creation, Switch routing, sub-workflow dispatch
2. **Path C sub-workflow (15-20 nodes)** -- mipmap_launcher.py, Wait+Poll loop for completion, ortho_harvester.py, conditional Path E trigger
3. **Path V sub-workflow (20-25 nodes)** -- V1-V4 Execute Command chain, V5 Webhook Wait gate, V6+delivery
4. **Path A sub-workflow (5-8 nodes)** -- photo color grade, delivery_packaging.py
5. **Path B/D sub-workflows (5-8 nodes each)** -- stub routing, status=manual, operator alert
6. **Path E workflow (35 nodes, existing)** -- unchanged, triggered via existing webhook

### Critical Pitfalls

1. **n8n v2.0 disables Execute Command nodes** -- All automation silently breaks after upgrade. Set `NODES_EXCLUDE=[]` in n8n config BEFORE any development. Pin n8n to 1.x if uncertain. This is a Phase 0 blocker.

2. **MipMap stdout overflows n8n's 1MB buffer** -- Execute Command uses Node.js child_process.exec() which buffers all output. MipMap produces 50-200MB of progress text. Process gets killed mid-reconstruction (2-6 hours wasted). Prevention: NEVER run MipMap directly via Execute Command. Use a wrapper that redirects stdout to file and either returns immediately (fire-and-forget + poll) or waits and posts a callback webhook.

3. **Orphaned MipMap processes on Windows** -- When n8n workflow stops, MipMap keeps running as orphan (Windows does not cascade kill to child processes). GPU stays locked, disk fills, re-runs launch duplicate instances. Prevention: PID file tracking, pre-flight orphan check via psutil, CREATE_NEW_PROCESS_GROUP flag, atexit cleanup handler.

4. **GPU contention between concurrent paths** -- Path C (MipMap), Path E (DeepForest), and Path V (FFmpeg NVENC) all use GPU. Running simultaneously causes CUDA OOM. Prevention: sequential GPU scheduling -- ensure Path E only starts after MipMap completes, and video encoding finishes before Path E inference starts.

5. **GeoTIFF copy corruption on cross-drive transfer** -- shutil.copy2() is not atomic. Interrupted copies leave truncated files that pass existence checks but crash rasterio. Prevention: copy to .tmp, verify size + rasterio header validation, then atomic rename.

## Implications for Roadmap

Based on research, suggested phase structure:

### Phase 0: Environment Setup and n8n Configuration
**Rationale:** Must verify n8n compatibility and configure environment BEFORE writing any workflows. Pitfalls 1 and 3 are blockers.
**Delivers:** Validated n8n environment with Execute Command enabled, correct timeouts, environment variables configured.
**Addresses:** n8n v2.0 compatibility, execution timeout configuration, Windows long path support.
**Avoids:** Pitfall 1 (Execute Command disabled), Pitfall 3 (workflow timeout kills processing), Pitfall 9 (260-char path limit).
**Effort:** 0.5 days.

### Phase 1: Foundation Scripts + Supabase Schema
**Rationale:** Python scripts must exist before n8n can call them. Database schema must support all path tracking. This phase has zero n8n dependency and can be fully unit tested.
**Delivers:** mipmap_launcher.py (refactored from ingest.py), ortho_harvester.py (new), Supabase migration (processing_templates columns, mipmap_workspace JSONB on drone_jobs), updated processing step names.
**Addresses:** Path C automation prerequisites, MipMap output harvesting, status tracking schema.
**Avoids:** Pitfall 2 (stdout buffer -- launcher redirects to file), Pitfall 5 (orphan process -- PID tracking), Pitfall 6 (GeoTIFF corruption -- safe copy with verification).
**Effort:** 3-4 days.

### Phase 2: Package Router Core + Path A
**Rationale:** Start with the simplest end-to-end flow. Path A (RE photos) is the most common package type and the simplest path (2 scripts). This proves the Router + sub-workflow pattern before tackling complex paths.
**Delivers:** Package Router n8n workflow (webhook, Supabase lookup, template merge, Switch routing, processing_jobs creation), Path A sub-workflow (photo grade + delivery).
**Addresses:** Package Router webhook receiver, route by package_type, Path A automation, template defaults, Supabase status tracking.
**Avoids:** Pitfall 13 (static data sharing -- use execution-scoped polling from the start).
**Effort:** 2-3 days.

### Phase 3: Path C (MipMap Automation) + Path E Connection
**Rationale:** Path C is the highest-value automation (saves 20-90 minutes of operator time per mapping mission). It also unblocks Path E by placing the ortho automatically. This is the most technically complex phase due to long-running subprocess management.
**Delivers:** Path C sub-workflow (mipmap_launcher, poll loop, ortho_harvester), Path C to Path E trigger wiring (fire existing vegetation webhook after ortho confirmed).
**Addresses:** MipMap launch automation, completion detection, ortho harvesting, vegetation trigger connection.
**Avoids:** Pitfall 2 (stdout buffer), Pitfall 5 (orphan MipMap), Pitfall 8 (GPU contention -- sequential scheduling).
**Effort:** 3-4 days.

### Phase 4: Path V (Video Pipeline)
**Rationale:** Independent of Path C. Can be built in parallel or after Phase 3. Wraps 6 existing scripts with a V5 manual edit gate using the proven webhook-wait pattern from Path E.
**Delivers:** Path V sub-workflow (V1-V4 automation, V5 DaVinci Resolve gate, V6 + delivery automation).
**Addresses:** Video pipeline automation, manual edit gate, video delivery.
**Avoids:** Pitfall 8 (GPU contention -- schedule FFmpeg NVENC around Path E inference).
**Effort:** 2-3 days.

### Phase 5: Remaining Paths + Integration + Hardening
**Rationale:** Path B/D are infrequent and need only stubs. Folder watcher bridge and webhook reliability are polish items. End-to-end testing validates the full flow.
**Delivers:** Path B/D stub workflows, folder watcher to Package Router bridge, webhook retry with persistent queue, end-to-end integration testing (SD card to delivery).
**Addresses:** Path B/D stub routing, folder watcher integration, webhook reliability, stale job cleanup.
**Avoids:** Pitfall 4 (premature folder watcher trigger -- use ingest_sorter as primary), Pitfall 7 (lost webhooks -- retry queue), Pitfall 10 (duplicate watcher events -- separate Observers), Pitfall 12 (stuck status -- stale job cron).
**Effort:** 2-3 days.

### Phase Ordering Rationale

- Phase 0 before everything: n8n configuration mistakes break all subsequent work. Five minutes of verification prevents days of debugging.
- Phase 1 before Phase 2: Scripts must exist before n8n can call them. Phase 1 is pure Python with full test coverage, no n8n coupling.
- Phase 2 before Phase 3: Prove the Router + sub-workflow pattern on the simplest path (A) before tackling the complex Path C with long-running subprocesses.
- Phase 3 before Phase 4: Path C is higher value (saves 20-90 min/mission) and more technically risky. Solve the hard problem early.
- Phase 4 is independent: Can be built alongside Phase 3 if two developers are available. No dependency on Path C.
- Phase 5 last: Polish, stubs, and reliability hardening. The core automation works after Phase 4.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 1 (mipmap_launcher.py):** Needs careful audit of ingest.py to identify which functions to extract vs. leave. The refactoring risk is MEDIUM -- functional rewrite of existing code that works.
- **Phase 3 (Path C poll loop):** The MipMap completion detection pattern needs validation. Options: poll for result/ files, check info.json status, or use a MipMap completion marker. Test with a real small-dataset MipMap run before building the full workflow.

Phases with standard patterns (skip research-phase):
- **Phase 0:** Pure configuration. Just verify and set env vars.
- **Phase 2:** Direct copy of Path E workflow pattern. Router + Switch + sub-workflow is well-documented in n8n docs.
- **Phase 4:** Wrapping existing scripts in Execute Command nodes is the exact pattern used in Path E. The V5 webhook-wait gate copies the E5 review gate pattern.
- **Phase 5:** Stubs are trivial. Webhook retry is a standard pattern.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | No new dependencies; all n8n nodes are built-in and documented. Patterns verified against official docs and existing Path E workflow. |
| Features | HIGH | Features derived from direct codebase audit of all 18 scripts. Package router design already documented in package_router_patch.json. |
| Architecture | HIGH | Based on direct audit of all source files, n8n workflows, and Supabase schema. Sub-workflow pattern proven by Path E (35 nodes in production). |
| Pitfalls | HIGH/MEDIUM | n8n timeout/buffer/v2.0 issues verified against official docs and community reports (HIGH). MipMap process lifecycle inferred from ingest.py source, not MipMap docs (MEDIUM). |

**Overall confidence:** HIGH

### Gaps to Address

- **MipMap output filename:** The GeoTIFF output filename is not fixed (could be `orthomosaic.tif`, `dom.tif`, or other). The harvester must glob for `*.tif` and identify the orthomosaic by size or metadata. Validate during Phase 1 by running MipMap on a test dataset.
- **n8n current version:** Need to verify whether the deployed n8n is v1.x or v2.x before Phase 0. If v2.x, Execute Command re-enabling is the first task.
- **ingest.py refactoring scope:** STACK.md recommends a simpler mipmap_harvester.py (file copy only); ARCHITECTURE.md recommends a fuller refactor into mipmap_launcher.py (C1) + ortho_harvester.py (C3). Resolution: follow ARCHITECTURE.md -- refactor into two pipeline-contract-compliant scripts. Keep ingest.py as a standalone manual tool.
- **GPU scheduling mechanism:** The exact mechanism (file-based lock vs. n8n concurrency control vs. sequential workflow design) needs a decision during Phase 3 planning. Recommendation: start with sequential design (Path E only fires after MipMap + FFmpeg complete), add file-based GPU lock only if concurrent scheduling is needed later.
- **re_premium package type:** ARCHITECTURE.md references `re_premium` as a distinct type; other research files list only 4 types. Clarify whether this is a 5th type or handled as re_standard with video_count > 0.
- **Delivery merge logic:** How the system knows "all paths are complete" before triggering final delivery. Deferred to v3.1 per feature research; manual delivery trigger is acceptable initially.

## Sources

### Primary (HIGH confidence)
- n8n official documentation: Switch node, Sub-workflows, Execute Sub-workflow, Execute Command, Execution Timeout, Blocking Nodes, Concurrency Control
- Existing codebase: all 18 Python scripts (402 tests), path_e_workflow.json (35 nodes), package_router_patch.json, folder_watcher.py, ingest_sorter.py, ingest.py
- n8n community forums: stdout maxBuffer issues, Execute Command removal in v2.0, long-running workflow failures

### Secondary (MEDIUM confidence)
- MipMap SDK documentation (software overview) -- CLI specifics verified from ingest.py source code rather than MipMap docs
- watchdog GitHub issues: duplicate event behavior on Windows, large file modified events

### Tertiary (LOW confidence)
- n8n internal memory behavior under multi-hour executions -- no official documentation, inferred from community reports
- MipMap process lifecycle on crash/timeout -- inferred from subprocess behavior, not from MipMap documentation

---
*Research completed: 2026-03-05*
*Ready for roadmap: yes*
