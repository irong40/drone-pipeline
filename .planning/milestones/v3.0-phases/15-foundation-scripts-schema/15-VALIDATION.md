---
phase: 15
slug: foundation-scripts-schema
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-05
---

# Phase 15 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (existing, 402 tests) |
| **Config file** | `pytest.ini` |
| **Quick run command** | `pytest tests/test_mipmap_launcher.py tests/test_ortho_harvester.py -x` |
| **Full suite command** | `pytest tests/ -x` |
| **Estimated runtime** | ~25 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_mipmap_launcher.py tests/test_ortho_harvester.py -x`
- **After every plan wave:** Run `pytest tests/ -x`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 15-01-01 | 01 | 1 | SCH-01, SCH-02, SCH-03 | manual | SQL migration applied via Supabase dashboard | N/A | pending |
| 15-02-01 | 02 | 1 | MPC-01, MPC-02, MPC-07, TST-01 | unit | `pytest tests/test_mipmap_launcher.py -x` | Wave 0 | pending |
| 15-03-01 | 03 | 1 | MPC-04, MPC-05, TST-02 | unit | `pytest tests/test_ortho_harvester.py -x` | Wave 0 | pending |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_mipmap_launcher.py` — covers TST-01, MPC-01, MPC-02, MPC-07
- [ ] `tests/test_ortho_harvester.py` — covers TST-02, MPC-04, MPC-05
- [ ] psutil installation: `pip install psutil` (if not already installed)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| processing_jobs table exists | SCH-01 | Supabase migration applied via dashboard/CLI | Run `supabase migration list` or query `select * from processing_jobs limit 1` |
| mipmap_workspace JSONB column | SCH-02 | Schema change on remote DB | Query `select mipmap_workspace from drone_jobs limit 1` |
| processing_templates config columns | SCH-03 | Schema change on remote DB | Query `select * from processing_templates limit 1` |

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
