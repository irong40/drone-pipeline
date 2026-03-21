# Roadmap: Sentinel Drone Pipeline

## Milestones

- [x] **v1.0 Hardening and Testing** — Phases 1-6 (shipped 2026-02-24)
- [x] **v2.0 Vegetation Analysis Pipeline** — Phases 7-13 (shipped 2026-02-25)
- [ ] **v3.0 WhatsApp Client Messaging** — Phase 3 (Input & Routing)

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

### Phase 3: Input & Routing

**Goal:** Client messages arrive via WhatsApp, the sender is identified, and every message is routed through the correct priority chain before any AI processing

**Requirements:** [INPT-01, INPT-02, INPT-03, INPT-04, INPT-05, INPT-06, INPT-07, INPT-08]

**Plans:** 3 plans

Plans:
- [ ] 03-01-PLAN.md — Webhook endpoint, HMAC verification, and client identification
- [ ] 03-02-PLAN.md — Priority routing chain (opt-out, manual mode, after-hours, media/text)
- [ ] 03-03-PLAN.md — Rate limiting per phone number

## Progress

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
| 3. Input & Routing | v3.0 | 0/3 | Planning | — |
