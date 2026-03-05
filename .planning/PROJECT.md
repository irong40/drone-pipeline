# Sentinel Drone Pipeline

## What This Is

Post-flight processing pipeline for Sentinel Aerial Inspections (Faith & Harmony LLC). 18+ Python CLI scripts handle everything from SD card ingest to client delivery for DJI drones (Mini 4 Pro, Matrice 4E, Mavic 3 Enterprise). v1.0 shipped 14 hardened scripts with 282 tests. v2.0 added Path E — automated vegetation analysis from orthomosaic imagery (18 scripts, 402 tests). v3.0 added n8n Package Router for end-to-end automation: webhook-driven routing across 5 processing paths (A/B/C/D/V), MipMap photogrammetry automation, video pipeline with DaVinci Resolve gate, and Supabase status tracking (21+ scripts, 494 tests).

## Core Value

Every script runs reliably, recovers from failures, and has tests proving it works — so the pipeline can be trusted in production without manual babysitting.

## Requirements

### Validated

- ✓ GAP-10: graded_path Supabase update — v1.0
- ✓ GAP-11: Checkpoint-based resume across all scripts — v1.0
- ✓ GAP-13: File logging for video pipeline scripts — v1.0
- ✓ DEPR-01: datetime.utcnow() deprecation fixes — v1.0
- ✓ ERR-01: Standardized error handling and exit codes — v1.0
- ✓ TEST-01/02/03: pytest framework with fixtures and stubs — v1.0
- ✓ UNIT-01 through UNIT-14: Unit tests for all 14 scripts — v1.0
- ✓ INTG-01 through INTG-04: Integration tests for pipeline flows — v1.0
- ✓ ENV-01 through ENV-05: Path E environment, Supabase schema, GPU verification — v2.0
- ✓ DET-01 through DET-07: Canopy detection with tiling, NMS, GeoPackage export — v2.0
- ✓ SPE-01 through SPE-08: Species classification with dual-API, reconciliation, cost gate — v2.0
- ✓ HLT-01 through HLT-06: Health assessment with VARI/ExG indices, Vision API — v2.0
- ✓ RPT-01 through RPT-09: PDF report, maps, GeoJSON, Folium, Supabase summary — v2.0
- ✓ INT-01 through INT-07: n8n workflow, review gate, delivery packaging — v2.0
- ✓ TST-01 through TST-06: E1-E4 unit and integration tests — v2.0

- ✓ ENV-01 through ENV-03: n8n environment setup, Execute Command, timeout config — v3.0
- ✓ RTR-01 through RTR-05: Package Router webhook, Switch routing, normalizer, dedup, job creation — v3.0
- ✓ MPC-01 through MPC-07: MipMap launcher, ortho harvester, Path C sub-workflow, PID detection — v3.0
- ✓ PHA-01 through PHA-03: Path A sub-workflow, color grade + delivery, status reporting — v3.0
- ✓ PHV-01 through PHV-05: Path V sub-workflow, V1-V6 automation, Wait gate, status reporting — v3.0
- ✓ PBD-01, PBD-02: Path B/D manual sub-workflow, operator email — v3.0
- ✓ SCH-01 through SCH-03: processing_jobs, mipmap_workspace, processing_templates schema — v3.0
- ✓ FWI-01, FWI-02: Folder watcher normalization, unified Package Router entry — v3.0
- ✓ TST-01 through TST-04: MipMap/ortho tests, workflow validation, integration tests — v3.0

### Active

(No active requirements — next milestone not yet defined)

### Out of Scope

- Parallel FFmpeg processing — performance optimization, defer to v3
- DaVinci Resolve integration — manual step (V5)
- New drone platform support — no new platforms planned
- GUI/web interface — CLI-only pipeline
- CI/CD pipeline — no remote repo yet
- Multispectral NDVI analysis — requires hardware not yet acquired
- Invasive species treatment recommendations — outside aviation service scope
- Certified arborist report certification — requires licensed arborist
- Tree risk assessment (TRA) ratings — requires ground-level assessment
- Ground level trunk diameter measurements — cannot measure from aerial imagery
- Historical growth tracking / change detection — requires repeat surveys (v3.0)
- Client-facing vegetation portal UI — Trestle app scope, not pipeline
- Local fine-tuned classification model — requires 50+ ground truth missions (v3.0)

## Context

- **Business**: Faith & Harmony LLC DBA Sentinel Aerial Inspections, veteran-owned, Hampton Roads VA
- **Processing rig**: Windows 11, RTX 5070 (CUDA sm_120), E:\ (incoming), F:\ (archive), Google Drive (warm)
- **Orchestrator**: n8n self-hosted, webhook-triggered from folder watcher
- **Supabase**: Project `qjpujskwqaehxnqypxzu`
- **Scripts**: 21+ total (14 v1.0 pipeline + 4 Path E vegetation + 3 v3.0: mipmap_launcher, ortho_harvester, payload_normalizer)
- **Test suite**: 494 tests (282 v1.0 + 120 v2.0 + 92 v3.0), ~1s + 21s runtime
- **n8n workflows**: 8 JSON files (package_router, path_a, path_c, path_v, manual_path, path_e, normalizer, patch)
- **Python**: System 3.14 (v1.0 scripts) + .venv-path-e 3.12 (Path E — DeepForest requires <3.13)
- **3-agent review (2026-02-22)**: 16 fixes applied, QCheck PASS
- **Species accuracy**: 30-55% top-1 — methodology disclaimer in PDF is non-negotiable

## Constraints

- **Stack**: Python 3.14 (system) + 3.12 (Path E venv), FFmpeg, Supabase, Google Drive API
- **GPU**: RTX 5070, CUDA 12.8, PyTorch 2.9.1+cu128, DeepForest 2.0
- **Platform**: Windows 11 only
- **Testing**: pytest with mock external services (sys.modules stub injection for GPU/API deps)
- **No breaking changes**: CLI interfaces and folder structures unchanged

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Checkpoint files for resume (GAP-11) | JSON manifest per mission dir, atomic writes | ✓ Good — reliable resume across all scripts |
| pytest for testing | Industry standard, fixture support | ✓ Good — 402 tests, fast runtime |
| Mock external services in tests | Can't call real Supabase/Drive/FFmpeg/GPU in CI | ✓ Good — sys.modules stubs for lazy imports |
| autouse stub per test file (not conftest) | Maintains no-autouse-in-conftest principle | ✓ Good — clean fixture isolation |
| Separate Python 3.12 venv for Path E | DeepForest requires <3.13; system is 3.14 | ✓ Good — isolated GPU stack |
| DeepForest predict_image() per tile | Pre-tile for overlap control, NMS in geo space | ✓ Good — accurate cross-tile deduplication |
| Dual-API species classification | OpenAI Vision primary + PlantNet cross-validation | ✓ Good — genus match boosts confidence |
| VARI/ExG index-based health scoring | RGB-only indices; Vision API for qualitative supplement | ✓ Good — works with standard cameras |
| Folium map tier-gated | Extended/comprehensive tiers only; standard skips | ✓ Good — controls file size for standard delivery |
| vegetation/.status sentinel file | E4 writes status; delivery_packaging reads before including | ✓ Good — two-gate safety (CLI flag + status) |
| n8n Webhook Wait for review gate | Workflow thread pauses; operator reviews PDF externally | ✓ Good — no custom UI needed yet |
| Package router default vegetation_enabled | site_survey + environmental_survey auto-enable; others opt-in | ✓ Good — no manual config for common cases |
| Module-level sys.modules stub injection | E1/E2 tests install stubs before source imports | ✓ Good — 113 tests run on system Python without GPU |
| Native Windows n8n (not Docker) | Python/GPU access, Windows paths unchanged | ✓ Good — scripts run directly without container overhead |
| Sub-workflow per path | Mirrors proven Path E pattern, independent scaling | ✓ Good — clean isolation, easy to test |
| Fire-and-forget MipMap with polling | Avoid n8n stdout buffer overflow (50-200MB) | ✓ Good — PID file + polling is robust |
| Single shared B/D manual sub-workflow | package_type as parameter distinguishes them | ✓ Good — no code duplication |
| V5 Wait node (not Webhook) | Sub-workflow can't own webhooks; Wait resumes within execution | ✓ Good — operator POSTs to resume URL |
| --step-name CLI override | video_color_grade.py serves both Path A and Path V | ✓ Good — context-aware step reporting |
| Sequential GPU scheduling | Path E after MipMap, not concurrent | — Pending — file-based lock deferred to v3.1 |

---
*Last updated: 2026-03-05 after v3.0 milestone*
