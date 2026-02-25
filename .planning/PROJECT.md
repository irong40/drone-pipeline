# Sentinel Drone Pipeline

## What This Is

Post-flight processing pipeline for Sentinel Aerial Inspections (Faith & Harmony LLC). 18 Python CLI scripts handle everything from SD card ingest to client delivery for DJI drones (Mini 4 Pro, Matrice 4E, Mavic 3 Enterprise). v1.0 shipped 14 hardened scripts with 282 tests. v2.0 added Path E — automated vegetation analysis (canopy detection, species classification, health assessment, branded PDF reporting) from orthomosaic imagery, bringing the total to 18 scripts and 402 tests.

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

### Active

(None — next milestone not yet planned)

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
- **Scripts**: 18 total (14 v1.0 pipeline + 4 Path E vegetation)
- **Test suite**: 402 tests (282 v1.0 + 120 v2.0 Path E), ~1s + 21s runtime
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

---
*Last updated: 2026-02-25 after v2.0 milestone*
