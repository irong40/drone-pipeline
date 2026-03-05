---
phase: 17
slug: path-c-mipmap-path-e
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-05
---

# Phase 17 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (existing) |
| **Config file** | `pytest.ini` |
| **Quick run command** | `python -m pytest tests/test_n8n_workflow_validation.py -x` |
| **Full suite command** | `python -m pytest tests/ -x --ignore=tests/integration` |
| **Estimated runtime** | ~25 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_n8n_workflow_validation.py -x`
- **After every plan wave:** Run `python -m pytest tests/ -x --ignore=tests/integration`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 17-01-01 | 01 | 1 | MPC-03, MPC-06 | unit | `python -m pytest tests/test_n8n_workflow_validation.py -x` | Yes | pending |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

- [ ] path_c_workflow.json must pass test_n8n_workflow_validation.py

*Existing test infrastructure covers workflow JSON validation.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Path C polls MipMap output directory | MPC-03 | Requires live n8n + MipMap running | Import path_c_workflow.json, trigger with mapping mission, verify polling loop detects GeoTIFF |
| Path C fires Path E trigger | MPC-06 | Requires live n8n + Supabase + Path E webhook | Verify POST to /sentinel-vegetation-trigger fires after ortho confirmed when vegetation_analysis=true |

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
