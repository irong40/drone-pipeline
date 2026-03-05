---
phase: 16
slug: package-router-core-path-a
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-05
---

# Phase 16 — Validation Strategy

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

- **After every task commit:** Run `python -m pytest tests/test_n8n_workflow_validation.py tests/test_payload_normalization.py -x`
- **After every plan wave:** Run `python -m pytest tests/ -x --ignore=tests/integration`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 16-01-01 | 01 | 1 | RTR-01, RTR-02, RTR-03, RTR-04, RTR-05 | unit+integration | `python -m pytest tests/test_n8n_workflow_validation.py -x` | Yes (existing) | pending |
| 16-02-01 | 02 | 1 | PHA-01, PHA-02, PHA-03 | unit+manual | `python -m pytest tests/test_n8n_workflow_validation.py -x` | Yes (existing) | pending |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

- [ ] package_router.json must pass test_n8n_workflow_validation.py
- [ ] path_a_workflow.json must pass test_n8n_workflow_validation.py
- [ ] delivery_packaging.py may need --processing-job-id support for PHA-03

*Existing test infrastructure covers workflow JSON validation via parametrized tests.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Path A color grade execution | PHA-01 | Requires n8n running + real mission folder | Import path_a_workflow.json, trigger with real_estate payload, verify color_grade step completes |
| Path A delivery packaging | PHA-02 | Requires n8n running + real mission folder | Verify delivery ZIP produced in mission delivery/ folder |
| Step status updates in Supabase | PHA-03 | Requires live n8n + Supabase connection | Query processing_jobs after Path A run, verify step statuses are running->complete |

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
