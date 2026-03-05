---
phase: 19
slug: remaining-paths-integration-hardening
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-05
---

# Phase 19 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (configured in pytest.ini) |
| **Config file** | `pytest.ini` at project root |
| **Quick run command** | `pytest tests/ -x -q` |
| **Full suite command** | `pytest tests/ -ra --tb=short` |
| **Estimated runtime** | ~25 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/ -x -q`
- **After every plan wave:** Run `pytest tests/ -ra --tb=short`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 25 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 19-01-01 | 01 | 1 | PBD-01, PBD-02 | unit | `pytest tests/test_manual_path_workflow.py -x` | No - W0 | pending |
| 19-01-02 | 01 | 1 | FWI-01 | unit | `pytest tests/test_payload_normalization.py -x` | No - W0 | pending |
| 19-01-03 | 01 | 1 | TST-03 | unit | `pytest tests/test_n8n_workflow_validation.py -x` | No - W0 | pending |
| 19-02-01 | 02 | 2 | FWI-02 | integration | `pytest tests/integration/test_package_router_integration.py -x` | No - W0 | pending |
| 19-02-02 | 02 | 2 | TST-04 | integration | `pytest tests/integration/test_package_router_integration.py -x` | No - W0 | pending |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_n8n_workflow_validation.py` — stubs for TST-03 (JSON syntax + structure checks)
- [ ] `tests/test_payload_normalization.py` — stubs for FWI-01 (folder_watcher payload normalization logic)
- [ ] `tests/test_manual_path_workflow.py` — stubs for PBD-01, PBD-02 (if Python helper involved)
- [ ] `tests/integration/test_package_router_integration.py` — stubs for FWI-02, TST-04 (webhook routing + processing_jobs creation)

*Note: PBD-01/PBD-02 are primarily n8n workflow JSON. If purely n8n (no Python), validation is covered by TST-03 (valid JSON) plus manual smoke test of email delivery.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| SMTP email delivery | PBD-01, PBD-02 | Requires live SMTP server and n8n running | Import workflow into n8n, configure SMTP credentials, trigger test payload, verify email arrives |
| n8n workflow import | TST-03 | Requires running n8n instance | `n8n import:workflow --input=<file>` for each JSON, verify no import errors |

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 25s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
