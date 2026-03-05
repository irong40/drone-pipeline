# Roadmap: Sentinel Drone Pipeline

## Milestones

- [x] **v1.0 Hardening and Testing** — Phases 1-6 (shipped 2026-02-24)
- [x] **v2.0 Vegetation Analysis Pipeline** — Phases 7-13 (shipped 2026-02-25)
- [ ] **v3.0 Package Router & End-to-End Automation** — Phases 14-19 (in progress)

## Phases

<details>
<summary>v1.0 Hardening and Testing (Phases 1-6) — SHIPPED 2026-02-24</summary>

- [x] Phase 1: Code Hardening (4/4 plans) — completed 2026-02-24
- [x] Phase 2: Test Infrastructure (2/2 plans) — completed 2026-02-24
- [x] Phase 3: Ingest Layer Tests (3/3 plans) — completed 2026-02-24
- [x] Phase 4: Video Pipeline Tests (3/3 plans) — completed 2026-02-24
- [x] Phase 5: Delivery Layer Tests (2/2 plans) — completed 2026-02-24
- [x] Phase 6: Integration Tests (3/3 plans) — completed 2026-02-24

</details>

<details>
<summary>v2.0 Vegetation Analysis Pipeline (Phases 7-13) — SHIPPED 2026-02-25</summary>

- [x] Phase 7: Environment and Foundation (2/2 plans) — completed 2026-02-25
- [x] Phase 8: Canopy Detection E1 (2/2 plans) — completed 2026-02-25
- [x] Phase 9: Species Classification E2 (2/2 plans) — completed 2026-02-25
- [x] Phase 10: Health Assessment E3 (1/1 plan) — completed 2026-02-25
- [x] Phase 11: Report Generation E4 (2/2 plans) — completed 2026-02-25
- [x] Phase 12: Integration and Delivery (2/2 plans) — completed 2026-02-25
- [x] Phase 13: Test Suite and Acceptance (3/3 plans) — completed 2026-02-25

</details>

### v3.0 Package Router & End-to-End Automation (In Progress)

**Milestone Goal:** Build the n8n Package Router workflow that receives ingest webhooks, routes missions by package_type through all processing paths (A/B/C/D/V), automates Path C (MipMap launch, ortho copy, Supabase status), and connects folder watcher events to trigger downstream workflows including Path E.

**Phase Numbering:**
- Integer phases (14, 15, 16...): Planned milestone work
- Decimal phases (15.1, 15.2): Urgent insertions (marked with INSERTED)

- [x] **Phase 14: Environment Setup** - Verify n8n compatibility and configure environment variables before any workflow development (completed 2026-03-05)
- [x] **Phase 15: Foundation Scripts + Schema** - Build Python scripts and Supabase schema that all n8n workflows depend on (completed 2026-03-05)
- [ ] **Phase 16: Package Router Core + Path A** - Build the central router and prove the pattern with the simplest end-to-end path
- [ ] **Phase 17: Path C MipMap Automation + Path E Connection** - Automate photogrammetry and wire ortho output to vegetation analysis
- [ ] **Phase 18: Path V Video Pipeline** - Automate the 6-script video pipeline with manual DaVinci Resolve gate
- [x] **Phase 19: Remaining Paths + Integration + Hardening** - Path B/D stubs, folder watcher bridge, and end-to-end validation (completed 2026-03-05)

## Phase Details

### Phase 14: Environment Setup
**Goal**: n8n environment is verified and configured so all subsequent workflow development succeeds on first attempt
**Depends on**: Nothing (first phase of v3.0)
**Requirements**: ENV-01, ENV-02, ENV-03
**Success Criteria** (what must be TRUE):
  1. n8n Execute Command node runs a Python script and returns output without error
  2. n8n execution timeout is configured to survive a 2-hour MipMap job without killing the workflow
  3. All six new environment variables are accessible from an n8n Code node expression
**Plans**: 2 plans

Plans:
- [ ] 14-01-PLAN.md — Decide Docker vs Native architecture, configure env vars and security overrides
- [ ] 14-02-PLAN.md — Create verification artifacts and verify all 3 success criteria in n8n

### Phase 15: Foundation Scripts + Schema
**Goal**: Python scripts and Supabase tables exist and are tested, so n8n workflows can call them reliably
**Depends on**: Phase 14
**Requirements**: MPC-01, MPC-02, MPC-04, MPC-05, MPC-07, SCH-01, SCH-02, SCH-03, TST-01, TST-02
**Success Criteria** (what must be TRUE):
  1. mipmap_launcher.py launches a subprocess, writes a PID file, and returns immediately with JSON stdout confirming launch
  2. mipmap_launcher.py detects an orphan MipMap process via PID file and refuses to launch a duplicate
  3. ortho_harvester.py copies a GeoTIFF to a mission mapping/ folder and verifies integrity (size + rasterio header)
  4. Both scripts follow pipeline contract (argparse CLI, JSON stdout, setup_logging, Supabase status update, exit codes 0/1/2)
  5. Supabase processing_jobs table exists with per-step status tracking, and processing_templates table has path-specific config columns
**Plans**: 3 plans

Plans:
- [ ] 15-01-PLAN.md — Supabase schema: processing_jobs table, mipmap_workspace column, processing_templates config
- [ ] 15-02-PLAN.md — mipmap_launcher.py: fire-and-forget subprocess launcher with PID file + orphan detection + tests
- [ ] 15-03-PLAN.md — ortho_harvester.py: GeoTIFF copy + rasterio integrity verification + tests

### Phase 16: Package Router Core + Path A
**Goal**: Missions arriving via webhook are automatically routed by package type, and real estate photo missions complete end-to-end without operator intervention
**Depends on**: Phase 15
**Requirements**: RTR-01, RTR-02, RTR-03, RTR-04, RTR-05, PHA-01, PHA-02, PHA-03
**Success Criteria** (what must be TRUE):
  1. POSTing an ingest_sorter payload to the Package Router webhook creates a processing_jobs row in Supabase with the correct active steps
  2. A real_estate mission routes to Path A, which color-grades photos and produces a delivery ZIP without manual steps
  3. Package Router fetches template defaults from processing_templates and merges with mission-specific overrides
  4. Each processing step in Path A updates its Supabase status to running/complete/failed as it progresses
  5. Both folder_watcher and ingest_sorter payloads are normalized to the same internal format before routing
**Plans**: 2 plans

Plans:
- [ ] 16-01-PLAN.md — Package Router main n8n workflow: webhook, normalizer, dedup, template fetch, job creation, Switch routing
- [ ] 16-02-PLAN.md — Path A sub-workflow + delivery_packaging.py PipelineStatusReporter enhancement

### Phase 17: Path C MipMap Automation + Path E Connection
**Goal**: Mapping missions automatically launch MipMap, harvest the orthomosaic, and trigger vegetation analysis -- saving 20-90 minutes of operator time per mission
**Depends on**: Phase 16
**Requirements**: MPC-03, MPC-06
**Success Criteria** (what must be TRUE):
  1. Path C sub-workflow polls MipMap output directory and detects GeoTIFF completion within the configured timeout
  2. After ortho is confirmed in mapping/, Path C fires a POST to the existing vegetation trigger webhook (when vegetation_analysis=true)
**Plans**: TBD

Plans:
- [ ] 17-01: TBD

### Phase 18: Path V Video Pipeline
**Goal**: Video missions execute V1-V4 automatically, pause for operator DaVinci Resolve edit, then complete V6 and delivery on resume
**Depends on**: Phase 16
**Requirements**: PHV-01, PHV-02, PHV-03, PHV-04, PHV-05
**Success Criteria** (what must be TRUE):
  1. Path V sub-workflow executes V1 (color grade), V1.5 (metadata), V2 (SRT), V3 (QA), V4 (proxy) in sequence without manual intervention
  2. After V4, the workflow pauses at a webhook-wait gate until the operator signals V5 (DaVinci Resolve manual edit) is complete
  3. On V5 resume webhook, V6 (format export) and delivery_packaging run automatically
  4. Each V-script step updates its Supabase processing_steps status (running/complete/failed)
  5. A V-script returning exit code 1 marks that step failed and halts Path V without blocking other paths running in parallel
**Plans**: TBD

Plans:
- [ ] 18-01: TBD
- [ ] 18-02: TBD

### Phase 19: Remaining Paths + Integration + Hardening
**Goal**: All package types have a routing destination, folder watcher events flow into the router, and the full pipeline is validated end-to-end
**Depends on**: Phase 17, Phase 18
**Requirements**: PBD-01, PBD-02, FWI-01, FWI-02, TST-03, TST-04
**Success Criteria** (what must be TRUE):
  1. Construction (Path B) and ADIAT (Path D) missions set status to manual and send operator notification instead of silently dropping
  2. Folder watcher webhook payload is normalized and routes through the same Package Router entry point as ingest_sorter
  3. All n8n workflow JSON files are syntactically valid and importable into a fresh n8n instance
  4. Integration test confirms Package Router webhook creates a processing_jobs row in Supabase with correct step structure
**Plans**: 2 plans

Plans:
- [ ] 19-01-PLAN.md — Build n8n artifacts: manual path sub-workflow, payload normalizer Code node, Python normalizer with tests
- [ ] 19-02-PLAN.md — Test suite: n8n workflow JSON validation and Package Router integration test

## Progress

**Execution Order:**
Phases execute in numeric order: 14 -> 14.x -> 15 -> 15.x -> 16 -> ... -> 19

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Code Hardening | v1.0 | 4/4 | Complete | 2026-02-24 |
| 2. Test Infrastructure | v1.0 | 2/2 | Complete | 2026-02-24 |
| 3. Ingest Layer Tests | v1.0 | 3/3 | Complete | 2026-02-24 |
| 4. Video Pipeline Tests | v1.0 | 3/3 | Complete | 2026-02-24 |
| 5. Delivery Layer Tests | v1.0 | 2/2 | Complete | 2026-02-24 |
| 6. Integration Tests | v1.0 | 3/3 | Complete | 2026-02-24 |
| 7. Environment and Foundation | v2.0 | 2/2 | Complete | 2026-02-25 |
| 8. Canopy Detection (E1) | v2.0 | 2/2 | Complete | 2026-02-25 |
| 9. Species Classification (E2) | v2.0 | 2/2 | Complete | 2026-02-25 |
| 10. Health Assessment (E3) | v2.0 | 1/1 | Complete | 2026-02-25 |
| 11. Report Generation (E4) | v2.0 | 2/2 | Complete | 2026-02-25 |
| 12. Integration and Delivery | v2.0 | 2/2 | Complete | 2026-02-25 |
| 13. Test Suite and Acceptance | v2.0 | 3/3 | Complete | 2026-02-25 |
| 14. Environment Setup | 2/2 | Complete    | 2026-03-05 | - |
| 15. Foundation Scripts + Schema | 3/3 | Complete    | 2026-03-05 | - |
| 16. Package Router Core + Path A | v3.0 | 2/2 | Complete | 2026-03-05 |
| 17. Path C MipMap + Path E | v3.0 | 0/1 | Not started | - |
| 18. Path V Video Pipeline | v3.0 | 0/2 | Not started | - |
| 19. Remaining Paths + Hardening | 2/2 | Complete    | 2026-03-05 | - |
