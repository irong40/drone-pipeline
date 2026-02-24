# Project Research Summary

**Project:** Sentinel Aerial Inspections — Path E Vegetation Analysis Pipeline
**Domain:** Drone orthomosaic vegetation analysis — ML canopy detection, species classification, health assessment, professional report generation
**Researched:** 2026-02-24
**Confidence:** HIGH (stack, architecture, pitfalls) | MEDIUM (species classification accuracy, feature value assumptions)

## Executive Summary

Path E is a 4-script extension to the existing drone-pipeline v1.0 codebase, adding GPU-accelerated canopy detection (DeepForest), dual-API species classification (OpenAI Vision + PlantNet), RGB-index health assessment (VARI/ExG), and multi-format report generation (PDF, GeoJSON, interactive HTML). It integrates into the existing n8n orchestration layer as a conditional branch that fires after Path C (WebODM orthomosaic) completes. The architecture is fully determined by direct codebase audit — all 4 scripts follow the established contract (argparse, checkpoint resume, JSON stdout, Supabase update), meaning there are no novel patterns to design. The primary engineering challenge is environment setup: DeepForest 2.0.0 requires Python <3.13, which conflicts with the system Python 3.14, necessitating a dedicated `.venv-path-e` using `py -3.12`.

The recommended approach is to build E1 through E4 sequentially in dependency order, validate each step on a real orthomosaic before building the next, and wire the n8n workflow last. The Supabase migration goes first because all four scripts depend on it. The two most important quality gates are: (1) a startup GPU assertion in canopy_detection.py to confirm actual CUDA sm_120 execution rather than silent CPU fallback, and (2) a hard API cost cap in species_classification.py and health_assessment.py to prevent runaway Vision API spend. The operator review gate (E5) via n8n webhook wait is non-negotiable for professional credibility and must not be bypassed for launch.

Key risks are concentrated in Phase 1: the PyTorch/RTX 5070 compatibility story requires PyTorch 2.9.1 with cu128 wheels (not PyPI default), PROJ_LIB environment variable conflicts from QGIS/OSGeo4W are likely on this Windows machine and must be cleared at script startup, and DeepForest's tiling must use predict_tile() or manual cross-tile NMS to prevent duplicate detections that inflate API costs. Species classification accuracy is inherently limited (estimated 30-55% top-1 accuracy from aerial canopy crops) and must be disclosed transparently in all client deliverables — the professional risk of overselling this capability is higher than the risk of underselling it.

---

## Key Findings

### Recommended Stack

The new stack is a dedicated Python 3.12 venv (`.venv-path-e`) separate from the system Python 3.14 environment. The install order is critical: PyTorch must be installed first with the cu128 wheel index, then DeepForest, which pulls rasterio, geopandas, shapely, opencv-headless, and numpy as sub-dependencies. Installing DeepForest first results in a CPU-only PyTorch build from PyPI.

**Reconciled PyTorch version:** STACK.md reports PyTorch 2.9.1+cu128 as stable. PITFALLS.md reports that stable builds through 2.6.x lack sm_120 support and recommends nightly. The reconciled position: PyTorch 2.7+ introduced stable Blackwell sm_120 support via cu128 wheels (confirmed in PyTorch 2.7 release blog and PyTorch forums). PyTorch 2.9.1+cu128 is the correct stable target. The PITFALLS.md nightly recommendation reflects the pre-2.7 state when stable builds had no sm_120 kernels. Use 2.9.1 stable cu128, not nightly.

**Core technologies:**
- **Python 3.12.10 venv** — DeepForest 2.0.0 requires Python >=3.10,<3.13; system Python 3.14 is incompatible; `py -3.12` is already installed
- **PyTorch 2.9.1+cu128 + torchvision 0.24.1** — GPU tensor ops for DeepForest; must install first via `--index-url https://download.pytorch.org/whl/cu128`; RTX 5070 sm_120 supported in stable 2.7+ builds
- **DeepForest 2.0.0** — pretrained RetinaNet for tree crown detection from RGB orthomosaics; only production-ready open-source option; pulls rasterio, geopandas, opencv-headless as sub-deps
- **rasterio 1.4.4** — GeoTIFF tiled windowed reads; bundled GDAL 3.9.x wheels eliminate separate GDAL install; do not install system GDAL alongside
- **GeoPandas 1.1.2 + Shapely 2.x** — canopy polygon I/O, GeoPackage as working format, GeoJSON for delivery; pip install now works cleanly on Windows via pyogrio binary wheels
- **ReportLab 4.4.10** — pure Python PDF generation; no system dependencies (unlike WeasyPrint/pdfkit)
- **Folium 0.20.0** — self-contained Leaflet HTML map; no server required; appropriate for 50-500 trees per site
- **OpenAI SDK >=1.0.0 (gpt-4o)** — species calls + qualitative health narrative; ~$0.12/mission at 30% sampling rate on 200-canopy site
- **PlantNet API v2** — species cross-validation; 500 req/day free tier; start with skip_plantnet=true until behavior is understood
- **GDAL installed separately: DO NOT** — rasterio wheels bundle GDAL 3.9.x; a system GDAL install creates DLL conflicts on Windows that are hard to diagnose

See `.planning/research/STACK.md` for full version matrix and install order.

### Expected Features

Species classification accuracy sets the ceiling for what can be credibly delivered. The realistic accuracy envelope from aerial RGB canopy crops is: 60-80% recall for E1 canopy detection (dense Hampton Roads deciduous canopy will bias toward lower end), 30-55% top-1 species accuracy from LLM + PlantNet on aerial crops, and reliable detection of obvious stress events via VARI/ExG with no early-stage stress detection. All outputs must be labeled with confidence scores and the PDF must include a methodology disclosure. The value proposition is "rapid inventory starting point for arborist field verification," not a replacement for arborist judgment.

**Must have (table stakes — v2.0 launch):**
- E1 canopy detection — individual tree count with lat/lon centroids; without this, nothing else runs
- E2 species classification — "probable species" with confidence score; even 30-55% accuracy differentiates from TreeDetect which offers none
- E3 health assessment (VARI/ExG only) — Healthy/Concerning/Critical triage; do NOT label as "health score," use "visual health index"
- PDF report with species map and health map — non-negotiable; primary client deliverable
- GeoJSON output — standard GIS deliverable; free to produce from GeoPandas
- Supabase schema (vegetation_detections + vegetation_analysis_summary) — required for review gate and delivery integration
- n8n E5 Review Gate — webhook wait; operator sign-off before delivery; required for professional credibility
- delivery_packaging.py integration (--include-vegetation flag) — vegetation/ subfolder in delivery ZIP
- Methodology and accuracy disclosure in every PDF — legal and professional protection

**Should have (competitive advantage — v2.1, after first 5-10 missions):**
- Folium interactive HTML map — premium tier differentiator; competitors deliver PDF+GeoJSON but no self-contained interactive map
- Vision API qualitative health narrative (skip_vision=false) — adds interpretive text; defer until cost/value ratio is established
- PlantNet cross-validation enabled by default — two-source consensus raises client trust; defer until rate limit behavior understood
- Species and health distribution charts — high perceived value, low implementation cost (matplotlib)
- Ground truth tracking schema columns (ground_truth_species, ground_truth_health, etc.) — foundation for DeepForest fine-tuning flywheel

**Defer (v3.0+):**
- DeepForest fine-tuning on Hampton Roads species — requires 500-1,000 labeled crowns from 5-10 ground-truthed missions first
- Historical change detection — requires calibration panel, same-season imaging, standardized flight parameters
- Processing-only intake (client-supplied orthomosaic) — separate ingest path; not needed for Sentinel's own flight operation
- Multispectral path — only relevant if multispectral sensor acquired for Matrice 4E
- i-Tree economic valuation integration — contingent on species accuracy improvements via fine-tuning

**Anti-features (never build without documented rationale):**
- ISA TRA-compliant reports — requires licensed arborist physical inspection; liability and legal risk
- NDVI from RGB bands — mathematically invalid; label output explicitly as VARI/ExG only
- Automatic delivery without review — species misclassification without operator review creates client credibility risk

See `.planning/research/FEATURES.md` for full competitor analysis, feature dependency graph, and QA review workflow.

### Architecture Approach

Path E integrates with zero changes to the core v1.0 architecture. The four new scripts (E1-E4) follow the established script contract exactly: argparse with mission_path + --mission-id + --dry-run + --force, JSON stdout, exit codes 0/1/2, Supabase update, checkpoint.py for resume. The existing checkpoint.py is reused without modification. delivery_packaging.py receives an additive-only modification (collect_vegetation() function + --include-vegetation flag). The existing n8n Package Router adds a single branch after Path C completion; no existing paths are modified. One Supabase migration file covers all schema changes (two new tables + four column additions to existing tables).

**Major components:**
1. **Supabase migration** — vegetation_detections (E1 seeds, E2/E3 update in-place), vegetation_analysis_summary (E4 writes), missions.vegetation_analysis/status columns, processing_templates.vegetation_enabled/config columns; one migration file for all v2.0 changes
2. **E1 canopy_detection.py** — tiles orthomosaic, runs DeepForest via predict_tile() (handles cross-tile NMS internally), writes GeoPackage + Supabase rows; GDAL_CACHEMAX and PROJ env var cleanup at startup
3. **E2 species_classification.py** — fetches unclassified detections (species_tag IS NULL), crops canopy patches via rasterio windowed read, calls OpenAI Vision + optionally PlantNet, checkpoint after every canopy (API calls are expensive); double-protection: checkpoint file + Supabase null filter
4. **E3 health_assessment.py** — computes VARI/ExG per canopy mask, optional Vision API sampling (vision_sample_pct), checkpoint for Vision calls; E2 and E3 can run in parallel after E1
5. **E4 vegetation_report.py** — single-pass aggregation; reads all Supabase detection rows, generates PDF (ReportLab), static PNGs (GeoPandas/matplotlib), and optional HTML map (Folium); no checkpoint needed (Supabase is durable state)
6. **E5 n8n Review Gate** — webhook wait node after E4; operator reviews PDF before delivery; resume endpoint triggers delivery_packaging.py --include-vegetation
7. **delivery_packaging.py (modified)** — collect_vegetation() returns empty list if vegetation/report/ missing (Path E failure never blocks primary delivery)
8. **vegetation/ mission subfolder** — canopy_detections.gpkg as working source of truth, canopy_detections.geojson as delivery copy, report/ subfolder for PDF+PNGs+HTML; mirrors existing photo/, video/, mapping/ conventions

The vegetation_config JSONB in processing_templates mirrors the video_qa_thresholds pattern already in the codebase. All four scripts accept --config JSON override. Build order is strictly: migration → E1 → E2 (parallel with E3) → E3 → E4 → delivery_packaging modification → n8n wiring. Tests write alongside each script.

See `.planning/research/ARCHITECTURE.md` for full SQL schemas, JSON stdout shapes, n8n node sequence, and delivery ZIP structure.

### Critical Pitfalls

1. **PyTorch CPU fallback on RTX 5070** — Installing PyTorch from default pip channel produces a CPU build; DeepForest runs silently on CPU at 10-20x slower speed with no error. Prevention: install `torch==2.9.1 --index-url https://download.pytorch.org/whl/cu128` first, before DeepForest; add startup assertion `assert torch.cuda.get_device_capability()[0] >= 12` in canopy_detection.py; verify wall time per 1GB ortho is <5 minutes.

2. **PROJ_LIB / PROJ_DATA environment variable conflict** — QGIS or OSGeo4W on this Windows machine likely sets PROJ_LIB as a system variable pointing to an incompatible PROJ version. rasterio 1.4.4 bundles its own PROJ 9.x but system env vars override it. Prevention: clear `PROJ_LIB`, `PROJ_DATA`, `GDAL_DATA` at top of every E script before importing rasterio; verify with CRS round-trip test on real ortho.

3. **DeepForest cross-tile duplicate detections** — Manual tile stitching via pd.concat produces duplicate overlapping polygons at tile boundaries (same tree detected 2-4 times), inflating canopy count and doubling API costs. Prevention: use `model.predict_tile()` (built-in overlap NMS) rather than manual tiling; if manual tiling required, apply torchvision.ops.nms across full ortho coordinate space after concat.

4. **OpenAI Vision API cost overrun** — Without a hard cap, a 500-tree site at 30% sampling sends 150 Vision API calls; misconfigured max_canopies results in $15-25 spend per mission. Prevention: enforce max_canopies cap (default 200) before any API loop; compute and log estimated cost before first call; abort if estimated cost exceeds configurable threshold (default $10).

5. **rasterio windowed read memory leak** — On rasterio 1.3.10+, windowed reads on tiled GeoTIFFs do not release GDAL block cache between tiles; processing 1GB ortho can consume 8-16GB RAM. Prevention: set `os.environ["GDAL_CACHEMAX"] = "256"` before rasterio import; use `del tile_data` explicitly in tile loop; consider COG format conversion for large orthomosaics.

6. **GeoPandas CRS area calculation error** — Area/perimeter computations in EPSG:4326 (degrees) produce wildly wrong values. Prevention: always project to local UTM before area/distance operations; use EPSG:4326 only for output GeoJSON; verify canopy_area_sqm with a known-area test parcel within 5% of expected value.

See `.planning/research/PITFALLS.md` for full pitfall list, integration gotchas, performance traps, and "Looks Done But Isn't" verification checklist.

---

## Implications for Roadmap

### Phase 1: Environment and Foundation

**Rationale:** Everything depends on a working Python 3.12 venv with verified GPU inference. The Supabase migration must exist before any script can write to the database. DeepForest model weights must be downloaded before E1 can run. This phase produces no user-visible output but unblocks all subsequent phases. The two most dangerous pitfalls (CPU fallback, PROJ conflict) must be eliminated here before a single line of pipeline code is written.

**Delivers:** Verified `.venv-path-e` with GPU inference confirmed, migration_001_vegetation.sql applied, test_environment.py passing all assertions, requirements-path-e.txt pinned.

**Addresses:** Environment setup for all P1 features.

**Avoids:**
- PyTorch CPU fallback (Pitfall 1) — verify CUDA capability >= (12,0) in test_environment.py
- conda channel mixing (Pitfall 2) — pip-first strategy documented
- PROJ_LIB conflict (Pitfall 3) — env var clear template established for all E scripts
- Schema dependency errors — migration applied and verified before any script writes

**Research flag:** Standard — environment setup for pip-based Windows Python is well-documented. No additional research needed.

---

### Phase 2: Canopy Detection (E1)

**Rationale:** E1 is the only script with no external API dependency, making it the safest first script to build and test end-to-end. Every downstream script (E2, E3, E4) depends on the vegetation_detections rows E1 creates. Memory management, GPU OOM handling, and cross-tile NMS must be solved here because they cannot be retrofitted later without data re-processing.

**Delivers:** canopy_detection.py, test_canopy_detection.py, verified GeoPackage output with centroid lat/lons, Supabase vegetation_detections rows, JSON stdout shape confirmed, checkpoint resume verified.

**Addresses:** Individual tree count + locations (P1), canopy area per tree (P1), site canopy coverage % (P1), GeoJSON output (P1), Supabase schema foundation.

**Avoids:**
- Cross-tile NMS duplicates (Pitfall 5) — use predict_tile() or manual NMS; validate canopy count against visual inspection
- Memory leak on windowed reads (Pitfall 4) — GDAL_CACHEMAX, del tile_data, confirm <2GB peak RSS on 500MB test ortho
- GPU OOM (Architecture error handling) — catch RuntimeError, retry with tile_size // 2, exit code 1 on partial

**Research flag:** Standard — DeepForest predict_tile() API and rasterio windowed reads are well-documented. The one non-obvious item is the predict_tile() overlap/NMS behavior, documented in DeepForest readthedocs.

---

### Phase 3: Species Classification (E2)

**Rationale:** E2 is the most expensive script to run incorrectly (API costs) and has the most complex failure modes (two external APIs, rate limits, daily quota, per-canopy checkpoint criticality). Building it second, after E1 produces real test data in Supabase, allows testing against actual detected canopies rather than synthetic data. PlantNet should start disabled (skip_plantnet=true) for first test runs to isolate OpenAI behavior.

**Delivers:** species_classification.py, test_species_classification.py (with mocked APIs), per-canopy API calls with exponential backoff, PlantNet daily quota guard, cost estimator pre-run, checkpoint verified with simulated mid-run kill.

**Addresses:** Species call with confidence (P1), PlantNet cross-validation (P2, disabled by default at launch).

**Avoids:**
- API cost overrun (Pitfall 6) — hard max_canopies cap enforced before loop, pre-run cost estimate logged, abort threshold
- PlantNet quota exhaustion — remainingIdentificationRequests read from every response, warning at <10 remaining
- Re-calling API on already-classified canopies (Anti-Pattern 4) — double protection: checkpoint + species_tag IS NULL filter

**Research flag:** Standard — OpenAI Vision API and PlantNet API are well-documented. The species accuracy limitation (30-55%) is well-established by research and should be surfaced explicitly in test output.

---

### Phase 4: Health Assessment (E3)

**Rationale:** E3 can be built in parallel with E2 (same input: E1 detection rows + orthomosaic) but is listed after E2 for sequential simplicity. VARI/ExG computation is deterministic and does not require external APIs for MVP (skip_vision=true for launch). This is the lowest-risk script to build and the easiest to test because numpy/rasterio pixel math produces verifiable numbers. The Vision API optional path can be added in v2.1.

**Delivers:** health_assessment.py, test_health_assessment.py, VARI/ExG computation verified against known pixel values, health_status bucketing thresholds documented, checkpoint resume verified.

**Addresses:** Health status flag per tree (P1), "needs attention" count (P1).

**Avoids:**
- GeoPandas CRS area errors (Performance trap) — project to UTM before any spatial operations; verify canopy_area_sqm with known parcel
- Overselling health assessment — label as "visual health index" not "health score" in all code and outputs

**Research flag:** Standard — VARI/ExG formulas are textbook; rasterio mask operations are well-documented.

---

### Phase 5: Report Generation (E4)

**Rationale:** E4 is a single-pass aggregation that requires all three upstream scripts to have produced valid test data. It has no external API dependency, no checkpoint, and no GPU requirement. The main complexity is ReportLab PDF layout and Folium HTML size management. Build last among the scripts; test with real Supabase data from a completed E1+E2+E3 run.

**Delivers:** vegetation_report.py, test_vegetation_report.py, PDF template verified, species and health PNGs generated, GeoJSON delivery copy, optional Folium HTML confirmed <8MB for 200-polygon site, vegetation_analysis_summary row in Supabase.

**Addresses:** PDF report (P1), branded report with site metadata (P1), species/health distribution charts (P2 — include in MVP since matplotlib cost is low), interactive HTML map (P2 — include as conditional on package tier), GeoJSON output (P1).

**Avoids:**
- Folium HTML size explosion (Performance trap) — single GeoJson layer, smooth_factor=1, verify <8MB in Chrome before shipping
- Missing methodology disclosure — text block mandated in PDF per FEATURES.md anti-feature section

**Research flag:** Standard — ReportLab Platypus and Folium GeoJson API are well-documented. Folium polygon performance limit is documented in GitHub issues.

---

### Phase 6: Integration and Delivery

**Rationale:** The n8n workflow and delivery_packaging.py modification are integration work that can only be validated after all four E scripts are producing correct outputs. The delivery_packaging.py change is additive-only (collect_vegetation() returns empty list on missing vegetation/report/) and must not break existing delivery paths. The n8n workflow is wired last because Execute Command nodes require the scripts to be finalized.

**Delivers:** delivery_packaging.py --include-vegetation flag, collect_vegetation() function, n8n Path E workflow (E0-E5 nodes, review gate webhook), processing_templates seeded with vegetation_config JSONB, end-to-end smoke test on one real mission folder.

**Addresses:** Operator review gate (P1), delivery_packaging.py integration (P1), 24-48 hour turnaround (inherent in automation).

**Avoids:**
- Blocking delivery on Path E failure (Anti-Pattern 3) — collect_vegetation() returns [] when vegetation/report/ absent; n8n only passes --include-vegetation when vegetation_status == 'complete'
- n8n timeout on long-running E1/E4 — set Execute Command timeout to 60 minutes

**Research flag:** Standard — n8n webhook wait pattern and delivery_packaging.py additive modification follow established codebase conventions.

---

### Phase 7: Test Suite Completion and Acceptance

**Rationale:** Tests write alongside each script during Phases 2-6, but a final consolidation phase ensures coverage meets project standards (pytest-cov), validates end-to-end accuracy on real orthomosaic data, and confirms the "Looks Done But Isn't" checklist from PITFALLS.md. This phase also produces the operator SOP (flight altitude minimums, seasonal disclosure requirements, review gate procedures).

**Delivers:** Full test suite passing at target coverage, end-to-end run on real mission producing PDF report reviewed by operator, "Looks Done But Isn't" checklist verified, operator SOP documented.

**Addresses:** Ground truth tracking schema (P2 — add columns in final migration if not done earlier), seasonal accuracy disclosure in PDF confirmed.

**Avoids:** Shipping false confidence from unit tests alone — validation on real orthomosaic data is required before first commercial mission.

**Research flag:** Standard. One validation item requires attention: DeepForest fine-tuning workflow (v3.0) will require ground truth data collected starting from first commercial missions — set up accuracy tracking columns and SOP in this phase to enable the v3.0 flywheel.

---

### Phase Ordering Rationale

- Environment and migration must precede all scripts (hard dependencies)
- E1 precedes E2 and E3 (E2 and E3 read E1's Supabase rows as input)
- E2 and E3 are parallelizable but ordered here for sequential simplicity; if timeline is aggressive, build them in parallel
- E4 requires completed E2 and E3 test data in Supabase
- Integration (Phase 6) requires finalized script outputs to wire correctly
- Test consolidation (Phase 7) is final to catch cross-script integration issues

### Research Flags

**Phases needing deeper research during planning:**
- None identified — all technology choices are well-documented with specific version numbers and working examples. The codebase audit (ARCHITECTURE.md) provides exact patterns to follow.

**Phases with standard patterns (skip research-phase):**
- All 7 phases — research is complete. The only unknowns are execution details (exact VARI/ExG threshold values for Hampton Roads species, optimal tile_size for RTX 5070 12GB VRAM) that should be determined empirically during Phase 2-3 development rather than by further research.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All versions verified against PyPI, official docs, PyTorch forums. One reconciliation required (see below). |
| Features | MEDIUM | Table stakes features HIGH confidence. Species classification accuracy is LOW confidence for exact numbers (30-55% is a bounded estimate, not a measured value for this specific region/drone combination). |
| Architecture | HIGH | Based on direct codebase audit of all 14 existing scripts. Patterns are explicit, not inferred. |
| Pitfalls | HIGH (infrastructure) / MEDIUM (model behavior) | GDAL/rasterio/PyTorch pitfalls are HIGH confidence with cited GitHub issues. DeepForest accuracy degradation in dense Hampton Roads canopy is MEDIUM confidence (extrapolated from published benchmarks, not local ground truth). |

**Overall confidence: HIGH** for build plan. MEDIUM for accuracy expectations delivered to clients.

### PyTorch Version Reconciliation

STACK.md recommends PyTorch 2.9.1+cu128 (stable). PITFALLS.md states "stable builds only went to 2.6.x" and recommends nightly. These are not contradictory — they reflect different points in time. PITFALLS.md's advice was accurate as of PyTorch 2.6.x; stable Blackwell sm_120 support landed in 2.7 (April 2025 release blog). As of 2026-02-24, PyTorch 2.9.1 stable cu128 is the correct target. The PITFALLS.md startup assertion (`torch.cuda.get_device_capability()[0] >= 12`) remains valuable regardless — it catches any future regression where the wrong wheel is installed.

**Recommendation:** Use `torch==2.9.1 --index-url https://download.pytorch.org/whl/cu128` (stable). Add the capability assertion. Do not use nightly.

### Gaps to Address

- **VARI/ExG health threshold values** — The mapping from VARI/ExG scores to Healthy/Concerning/Critical must be tuned empirically on Hampton Roads imagery. The literature provides general guidance but no Hampton Roads-specific calibration. Start with published thresholds (VARI > 0.2 = healthy, 0.1-0.2 = stressed, < 0.1 = poor) and refine after first 3-5 missions. This is acceptable — accuracy tracking schema will capture discrepancies.

- **Optimal tile_size for RTX 5070 with VRAM 12GB** — STACK.md specifies tile_size=1024 as default. The actual optimal value for the RTX 5070 depends on VRAM allocation at inference time. Start with 1024, watch GPU-Z VRAM usage during first E1 run, reduce to 512 if VRAM utilization exceeds 10GB. Document observed value in vegetation_config defaults after first real mission.

- **DeepForest accuracy on Hampton Roads deciduous canopy** — The 60-80% recall estimate is extrapolated from published urban tree detection benchmarks (Sofia, Bulgaria; NEON training data). Hampton Roads' dense mixed deciduous canopy in summer may perform at the lower end of this range. Recommend setting operator expectations at 60% recall for initial missions and measuring against visual inspection counts.

- **PlantNet aerial canopy accuracy** — FEATURES.md estimates 30-55% top-1 species accuracy for the combined OpenAI Vision + PlantNet approach. This is a conservative estimate based on known limitations of both APIs with aerial canopy crops. Start with skip_plantnet=true for first missions to establish a OpenAI-only baseline, then enable PlantNet to measure whether cross-validation improves or introduces noise.

---

## Sources

### Primary (HIGH confidence)
- `.planning/research/STACK.md` — all technologies verified against PyPI, official docs, PyTorch forums (2026-02-24)
- `.planning/research/ARCHITECTURE.md` — direct codebase audit of all 14 existing scripts (2026-02-24)
- `.planning/research/PITFALLS.md` — confirmed issues from rasterio GitHub #3241, PyTorch GitHub #164342, #159207 (2026-02-24)
- [PyTorch 2.7 Release Blog](https://pytorch.org/blog/pytorch-2-7/) — CUDA 12.8 sm_120 stable support confirmed
- [DeepForest pyproject.toml](https://github.com/weecology/DeepForest/blob/main/pyproject.toml) — Python version constraint >=3.10,<3.13 verified
- [rasterio PyPI](https://pypi.org/project/rasterio/) — v1.4.4, bundled GDAL 3.9.x on Windows
- [GeoPandas PyPI](https://pypi.org/project/geopandas/) — v1.1.2, shapely>=2.0 required
- [ReportLab PyPI](https://pypi.org/project/reportlab/) — v4.4.10 (2026-02-12)
- [GPT-4o Pricing](https://pricepertoken.com/pricing-page/model/openai-gpt-4o) — $2.50/1M input (verified 2026-02-24)

### Secondary (MEDIUM confidence)
- `.planning/research/FEATURES.md` — feature value judgments and competitor analysis (2026-02-24)
- [Fine-Tuning DeepForest for UAV Imagery (ISPRS 2025)](https://isprs-archives.copernicus.org/articles/XLVIII-4-W15-2025/39/2025/) — urban tree detection performance benchmarks
- [GPT-4 vs Plant.id Plant Identification (Kindwise)](https://www.kindwise.com/post/the-plant-identification-battle-gpt-4-vs-plant-id) — 55.8% zero-shot accuracy baseline
- [Folium GitHub Issue #975](https://github.com/python-visualization/folium/issues/975) — HTML file size limits
- [rasterio GitHub Issue #3241](https://github.com/rasterio/rasterio/issues/3241) — windowed read memory leak

### Tertiary (LOW confidence)
- Hampton Roads species accuracy estimates (30-55%) — extrapolated from general aerial RGB benchmarks; no Hampton Roads-specific studies found; validate after first 3-5 commercial missions
- Winter deciduous canopy accuracy degradation (0.55-0.70 F1) — estimated from published literature on bare-crown RGB detection; not validated for Hampton Roads climate or specific drone altitudes

---
*Research completed: 2026-02-24*
*Ready for roadmap: yes*
