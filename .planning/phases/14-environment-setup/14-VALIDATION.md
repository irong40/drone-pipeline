---
phase: 14
slug: environment-setup
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-05
---

# Phase 14 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (existing, 402 tests) |
| **Config file** | `pytest.ini` |
| **Quick run command** | `python -m pytest tests/ -x --timeout=30` |
| **Full suite command** | `python -m pytest tests/ -v` |
| **Estimated runtime** | ~22 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/ -x --timeout=30`
- **After every plan wave:** Run `python -m pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 14-01-01 | 01 | 1 | ENV-01 | manual + smoke | Import verification workflow in n8n, execute, check JSON output | N/A (n8n UI) | pending |
| 14-01-02 | 01 | 1 | ENV-02 | manual | Check EXECUTIONS_TIMEOUT and EXECUTIONS_TIMEOUT_MAX values | N/A (config) | pending |
| 14-01-03 | 01 | 1 | ENV-03 | manual + smoke | Run Code node that reads all 6 vars, verify none are MISSING | N/A (n8n UI) | pending |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

- [ ] `verify_n8n.py` — minimal Python script that outputs JSON (for ENV-01 verification)
- [ ] `n8n/14-env-verification.json` — n8n workflow JSON that tests Execute Command + env vars
- [ ] Docker vs Native architecture decision must be resolved before any configuration work

*Note: This phase is primarily configuration — most verification is manual via n8n UI execution.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Execute Command runs Python | ENV-01 | Requires n8n UI execution | Import verification workflow, execute Manual Trigger, verify JSON output shows python_version |
| 2-hour timeout configured | ENV-02 | Config value check, no long-running test | Check n8n Settings > Executions or verify env var via `docker exec n8n env | grep TIMEOUT` (Docker) or `echo %EXECUTIONS_TIMEOUT%` (native) |
| Six env vars accessible | ENV-03 | Requires n8n Code node execution | Execute verification workflow Code node, verify all 6 vars show values (not MISSING) |

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
