# Sentinel Drone Pipeline — Hardening & Testing

## What This Is

Post-flight processing pipeline for Sentinel Aerial Inspections (Faith & Harmony LLC). 14 Python CLI scripts handle everything from SD card ingest to client delivery for DJI drones (Mini 4 Pro, Matrice 4E, Mavic 3 Enterprise). v1.0 ships with all scripts hardened (logging, error handling, checkpoint resume) and a comprehensive 282-test suite.

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

### Active

(None — start next milestone with `/gsd:new-milestone`)

### Out of Scope

- Parallel FFmpeg processing — performance optimization, defer to v2
- n8n workflow configuration — separate system
- DaVinci Resolve integration — manual step (V5)
- New drone platform support — no new platforms planned
- GUI/web interface — CLI-only pipeline
- CI/CD pipeline — no remote repo yet

## Context

- **Business**: Faith & Harmony LLC DBA Sentinel Aerial Inspections, veteran-owned, Hampton Roads VA
- **Processing rig**: Windows 11, E:\ (incoming), F:\ (archive), Google Drive (warm)
- **Orchestrator**: n8n self-hosted, webhook-triggered from folder watcher
- **Supabase**: Project `qjpujskwqaehxnqypxzu`
- **Test suite**: 282 tests (266 unit + 16 integration), 0.92s runtime
- **3-agent review (2026-02-22)**: 16 fixes applied, QCheck PASS

## Constraints

- **Stack**: Python 3.8+, FFmpeg, Supabase, Google Drive API
- **Platform**: Windows 11 only
- **Testing**: pytest with mock external services
- **No breaking changes**: CLI interfaces and folder structures unchanged

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Checkpoint files for resume (GAP-11) | JSON manifest per mission dir, atomic writes | ✓ Good — reliable resume across all scripts |
| pytest for testing | Industry standard, fixture support | ✓ Good — 282 tests in 0.92s |
| Mock external services in tests | Can't call real Supabase/Drive/FFmpeg in CI | ✓ Good — sys.modules stubs for lazy imports |
| autouse stub per test file (not conftest) | Maintains no-autouse-in-conftest principle | ✓ Good — clean fixture isolation |
| Lazy-import patch targets | Scripts never bind at module level | ✓ Good — patch library source not call site |
| googleapiclient sys.modules stub | Lazy imports need importable module | ✓ Good — tests run without google packages |

---
*Last updated: 2026-02-24 after v1.0 milestone*
