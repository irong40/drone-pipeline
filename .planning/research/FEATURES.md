# Feature Research

**Domain:** Drone vegetation analysis pipeline — Path E addon to existing drone post-processing system
**Researched:** 2026-02-24
**Confidence:** MEDIUM (academic benchmarks HIGH; pricing/arborist workflow MEDIUM; species classification from aerial view LOW-MEDIUM)

---

## Accuracy Expectations (Grounding)

Before mapping features, accuracy expectations must be established because they directly determine what can be promised to clients and what requires mandatory human review.

### Canopy Detection (E1 — DeepForest)

**What the research shows:**

- DeepForest pretrained model achieves **F1 0.73–0.95** on open-canopy North American forests (Weinstein et al., 2019) and **AP50 of 0.61** on the original training data
- Urban tree detection studies (Sofia, Bulgaria 2024 via ISPRS) show DeepForest results "comparable to original application" — i.e., roughly 0.73–0.80 F1 in similar open/semi-open settings
- **Closed-canopy validation** (2025, TLS ground truth): AP50 drops to **0.105–0.142** and F1 to **0.196–0.284** — severely degraded in dense overlapping canopy
- Fine-tuning with even modest local data (hundreds of labeled crowns) substantially recovers performance
- **Hampton Roads Virginia forests** are mixed deciduous (oak, pine, sweet gum, tulip poplar) in summer — dense canopy overlap is the norm for residential/commercial sites
- **GSD requirement**: 5–10 cm/pixel is the operational sweet spot; below 10 cm GSD is required for reliable individual crown delineation; coarser than 10 cm/pixel reduces detection accuracy significantly
- DJI Mini 4 Pro at 30m AGL produces ~0.8 cm GSD — well within range. Matrice 4E at 60m AGL produces ~1.5 cm GSD — also acceptable
- WebODM orthomosaics from Path C at typical mission altitudes will meet resolution requirements

**Realistic expectation:** 60–80% recall at default score_threshold=0.3 on residential/commercial sites with mature canopy. Precision will be lower in dense canopy. Expect **false negatives (missed trees) more than false positives (phantom trees)** because model under-detects in overlap zones. Fine-tuning after 5–10 missions is the path to reliable performance.

### Species Classification (E2 — OpenAI Vision + PlantNet)

**What the research shows:**

- RGB-only aerial species classification achieves **70–90% accuracy** in controlled research studies — but these use custom fine-tuned models with training data specific to the study site and species set
- High-accuracy studies (96–98%) use super-resolution preprocessing + deep CNNs trained on the exact species in the region — not zero-shot API calls
- **GPT-4o Vision** tested on plant identification achieved **~55.8% accuracy** on canopy images in an educational study — this is zero-shot performance
- PlantNet API is optimized for **flower, fruit, leaf, entire plant** views — bark is its worst-performing organ. **Canopy top-down view is not a supported organ type** and is expected to perform significantly worse than ground-level side views
- PlantNet rate limit: 500 requests/day on free research tier; paid tiers available but pricing is not public
- Multi-image submission (up to 5 per species) improves PlantNet results; top-down + any available side views of the same crown would help
- **Realistic accuracy from LLM + PlantNet combo on aerial canopy crops**: LOW confidence estimate of **30–55% top-1 species accuracy** for common regional species, higher for distinctive species (magnolia, palm, weeping willow), much lower for similar-looking oaks/maples

**Realistic expectation:** Species classification from aerial RGB is the most uncertain component of the entire pipeline. It should be presented to clients as **"probable species" with confidence scores**, not authoritative identification. The value proposition is rapid inventory starting point for arborist field verification — not replacing arborist judgment.

### RGB Health Assessment (E3 — VARI, ExG)

**What the research shows:**

- VARI (Visible Atmospherically Resistant Index) and ExG (Excess Green) are established RGB indices for vegetation stress detection
- Both correlate meaningfully with chlorophyll content and visible stress indicators — chlorosis, browning, defoliation
- **What they can detect**: Severe stress (browning, significant yellowing, major defoliation), relative health ranking between canopies in the same scene, gross anomalies like dead trees
- **What they cannot reliably detect**: Early-stage stress before visible symptoms appear, disease vs. drought vs. pest stress (same symptoms, different causes), subtle health differences between similar-looking healthy canopies
- **Calibration problem**: RGB index values cannot be compared between images taken at different times or with different lighting conditions unless radiometrically calibrated — a limitation for longitudinal monitoring
- Compared to NDVI (multispectral): NDVI captures NIR reflectance which responds to chlorophyll content before visible symptoms appear. VARI/ExG are **lagging indicators** — they show what's already visibly wrong
- DroneDeploy explicitly states VARI/TGI "are not applicable as general-purpose measures of field health" without calibration
- Biomass estimation: multispectral consistently outperforms RGB indices for quantitative biomass; RGB is qualitative

**Realistic expectation:** VARI/ExG health scoring is useful for flagging obvious stress (health_status: Critical/Concerning) and providing a ranked health distribution across detected canopies. It should NOT be sold as precise health measurement. The label "health score" risks overselling — "stress indicator" or "visual health index" is more accurate. GPT-4o Vision qualitative assessment on canopy crops adds interpretive value (describing what it sees) but is not a substitute for ground inspection.

---

## Feature Landscape

### Table Stakes (Clients Expect These)

Features that an arborist client or property manager expects from a vegetation analysis service. Missing these makes the product feel incomplete or unprofessional.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Individual tree count with locations | Core inventory output — what every arborist delivers manually | MEDIUM | DeepForest bounding boxes → centroid lat/lon → vegetation_detections table |
| Canopy area per tree | Standard measurement in all tree inventory software (Arborgold, ArborNote, ForestMetrix) | LOW | Calculate from polygon geometry post-detection |
| Species call (even if tentative) | Every tree inventory has a species column, even if "Unknown" | HIGH | 30–55% accuracy realistic; must clearly label confidence and mark as "probable" |
| Health status flag per tree | Minimum: Healthy / Concern / Critical triage | MEDIUM | VARI/ExG → threshold bucketing; must not claim diagnostic precision |
| Georeferenced output | GIS clients expect spatial data, not just a spreadsheet | LOW | GeoJSON always included — non-negotiable for professional GIS clients |
| PDF summary report | Standard deliverable for any professional service | MEDIUM | ReportLab; must include methodology note on accuracy expectations |
| Branded report with site metadata | Clients expect Sentinel branding, site address, flight date, imagery info | LOW | Header block in PDF; already have delivery_packaging.py pattern to follow |
| Total site canopy coverage % | Standard metric in urban tree canopy assessments | LOW | Sum of canopy polygons / site area |
| "Needs attention" count | Arborists and property managers want the triage summary up front | LOW | COUNT WHERE health_status IN ('Concerning','Critical') |
| Operator review gate before delivery | Arborists expect human sign-off on AI-generated assessments | MEDIUM | n8n Review Gate (E5) already in PRD; cannot skip for professional credibility |

### Differentiators (Competitive Advantage)

Features that distinguish Sentinel from manual arborist visits and from pure-data drone services (TreeDetect, Deep Forestry).

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Folium interactive HTML map (premium tier) | Competitors (TreeDetect, Deep Forestry) deliver PDF + GeoJSON but no self-contained interactive map; arborists can click individual trees to see species, health, confidence | MEDIUM | Folium is appropriate for this scale (50–500 trees per site); for >5,000 trees consider leafmap/Kepler.gl; self-contained HTML file is the key — no server required for client |
| PlantNet cross-validation display | Shows both Vision API species call AND PlantNet agreement/disagreement — adds credibility by showing multi-source consensus | MEDIUM | Two-source agreement raises client trust even if individual accuracy is low; disagreements become explicit flags |
| Per-tree confidence score on all outputs | Most services deliver species calls without surfacing confidence — Sentinel shows confidence in map popups, report callouts, and GeoJSON properties | LOW | Already in schema design; this is a UX decision, not new engineering |
| Health distribution chart | Visual breakdown of site health (pie/bar chart) — management-friendly | LOW | matplotlib; fast to implement, high perceived value |
| Species distribution chart | Site-level species diversity at a glance | LOW | matplotlib; same as above |
| Explicit methodology disclosure | Transparency about RGB limitations vs NDVI builds trust with knowledgeable clients (arborists, municipalities, GIS staff) | LOW | Text block in PDF; distinguishes from overselling competitors |
| GeoPackage + GeoJSON dual output | Power GIS users (municipalities, landscape architects) need OGC-compliant formats; GeoPackage is the modern GIS standard | LOW | GeoPandas already in stack |
| Arborist partnership tier (flight + analysis) | Bundling Sentinel's flight capability with analysis creates a one-stop service arborists can resell to their clients; competitors only do software | HIGH | Business model, not engineering; requires cultivating arborist relationships |
| 24–48 hour turnaround | Manual arborist survey: 5–10 days. Aerial analysis gives comparable initial inventory same day | LOW | Already inherent in pipeline automation |
| Processing-only tier (client provides ortho) | Allows remote sensing firms, WebODM operators, or GIS consultants to use Sentinel's analysis on their own imagery | MEDIUM | OQ5/OQ6 from PRD; requires intake workflow for externally produced orthomosaics |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Certified arborist report / ISA-compliant TRA | Arborist partners will ask if Sentinel can produce ISA Tree Risk Assessment-compliant reports | ISA TRA certification requires licensed arborist physical inspection; producing a document that looks like one creates liability and is potentially illegal | Clearly brand output as "Aerial Inventory Report (AI-Assisted)" — separate from certified assessment; arborist partner does the TRA using Sentinel data as starting point |
| NDVI / multispectral health analysis from RGB data | Clients familiar with precision agriculture will ask for NDVI | Mini 4 Pro and Matrice 4E do not carry multispectral sensors; computing NDVI from RGB bands is mathematically invalid | VARI/ExG as "visual health index" with explicit disclaimer; recommend multispectral upgrade to clients who need true NDVI |
| Real-time classification during flight | Operators want immediate results | Canopy detection requires completed orthomosaic from WebODM (Path C) — real-time processing defeats the pipeline architecture and quality controls | Frame as "rapid post-processing" — 1–4 hours after landing vs 5–10 days for manual survey |
| Automatic delivery without review | Speed-focused clients want zero-delay delivery | Species misclassifications and false detections without review could damage credibility and create liability with paying arborist clients | Keep E5 review gate; reduce review burden by surfacing only low-confidence detections (confidence < threshold) for targeted operator review rather than full report review |
| Historical change detection / growth tracking | Obvious value to repeat-survey clients | Requires consistent flight parameters, same-season imaging, calibrated indices — impossible to guarantee across missions without standardized radiometric calibration setup | Defer to v3.0 with explicit prerequisites: consistent altitude, same season, calibration panel |
| Species treatment recommendations | Arborists will want pest/disease treatment suggestions | Sentinel's aerial analysis cannot diagnose disease (vs drought vs pest vs nutrient deficiency) from VARI/ExG; treatment recommendations require ground diagnosis | Include "Recommended Follow-up" section noting which trees warrant ground inspection; never suggest specific treatments |
| Ground-level trunk diameter / DBH | Standard arborist measurement | Completely invisible from overhead RGB orthomosaic | Canopy width as proxy; note DBH requires ground survey |
| Per-tree economic value (i-Tree valuation) | Municipal clients ask for this | Requires species confirmation + DBH + condition rating from certified source; aerial classification accuracy is too low to feed i-Tree formulas reliably | Reference i-Tree as methodology clients can apply after confirming species/condition |

---

## Feature Dependencies

```
[E1: Canopy Detection]
    └──requires──> [Completed Path C Orthomosaic] (GeoTIFF)
    └──produces──> [Canopy Polygons + Bounding Boxes]
                       └──required by──> [E2: Species Classification]
                       └──required by──> [E3: Health Assessment]

[E2: Species Classification]
    └──requires──> [E1 Canopy Polygons]
    └──requires──> [OpenAI Vision API credentials]
    └──optionally-requires──> [PlantNet API key]
    └──produces──> [species_tag, species_confidence, cross_validated per detection]

[E3: Health Assessment]
    └──requires──> [E1 Canopy Polygons]
    └──requires──> [Orthomosaic bands for VARI/ExG calculation]
    └──optionally-requires──> [OpenAI Vision API] (qualitative assessment)
    └──produces──> [health_score, health_status per detection]

[E4: Report Generation]
    └──requires──> [E1 outputs] (count, geometry, area)
    └──requires──> [E2 outputs] (species_tag, confidence)
    └──requires──> [E3 outputs] (health_score, health_status)
    └──produces──> [PDF, PNG maps, GeoJSON, HTML interactive map]
    └──produces──> [vegetation_analysis_summary record in Supabase]

[E5: Operator Review Gate]
    └──requires──> [E4 outputs] (report to review)
    └──triggers──> [delivery_packaging.py] on approval

[Folium Interactive Map]
    └──requires──> [E2 species data] (popup content)
    └──requires──> [E3 health data] (color coding)
    └──requires──> [GeoJSON canopy polygons] (geometry)
    └──conflicts──> [offline delivery] (requires internet for tile layers — use offline tiles or Stamen Toner if delivery environment is air-gapped)

[PlantNet Cross-validation]
    └──optional-enhances──> [E2 Species Classification]
    └──conflicts──> [PlantNet rate limit] — 500/day free tier limits sites to ~500 canopies/day at 1 req/canopy
    └──gated-by──> [skip_plantnet flag] in config
```

### Dependency Notes

- **E2 and E3 can run in parallel** after E1 completes — they share input (canopy polygons + orthomosaic) but do not depend on each other's output
- **E4 blocks on both E2 and E3** — report generation needs all three upstream outputs
- **PlantNet 500/day limit** (OQ4): With max_canopies=200, a single mission uses 200 requests (40% of daily quota), allowing 2–3 full missions per day. If PlantNet is called for all detections above score_threshold, not just up to max_canopies, the quota could exhaust faster. Recommendation: apply max_canopies cap before PlantNet calls
- **Orthomosaic GSD dependency**: E1 accuracy degrades significantly below 10 cm/pixel GSD (OQ2 from PRD). WebODM path C orthomosaics at typical DJI mission altitudes will satisfy this. The minimum flight altitude check should be documented in operator SOPs
- **Interactive HTML map** requires external tile service at render time (Folium default uses OpenStreetMap tiles loaded at view time) — the HTML file works offline only if tiles are pre-cached or a local tile server is running. For client deliverables, this is acceptable: most clients view the HTML on internet-connected devices

---

## MVP Definition

### Launch With (v2.0 — Path E Core)

Minimum viable pipeline that generates a defensible professional deliverable.

- [x] **E1 Canopy Detection** — core detection; without this, nothing else runs
- [x] **E2 Species Classification** — even at 30–55% accuracy, it differentiates from pure-count services like TreeDetect
- [x] **E3 Health Assessment (VARI/ExG only)** — skip Vision API qualitative for MVP if it adds cost/latency; VARI/ExG scores alone are sufficient for health_status bucketing
- [x] **PDF Report with species map and health map** — non-negotiable; this is what gets handed to the client
- [x] **GeoJSON output** — standard GIS deliverable; zero extra cost to produce from GeoPandas
- [x] **Supabase schema** (vegetation_detections + vegetation_analysis_summary) — needed for review gate and delivery packaging integration
- [x] **n8n E5 Review Gate** — required for professional credibility; operator must sign off before delivery
- [x] **delivery_packaging.py vegetation/ subfolder** — integration with existing v1.0 delivery workflow

### Add After Validation (v2.1 — After First 5–10 Missions)

- [ ] **Folium Interactive HTML Map** — premium tier deliverable; add once PDF report is validated and clients want more
- [ ] **Vision API qualitative health assessment (E3 skip_vision=false)** — adds interpretive narrative to health scores; defer until cost/value ratio is established from first missions
- [ ] **PlantNet enabled by default (skip_plantnet=false)** — start with PlantNet disabled (skip_plantnet=true) for first missions to establish baseline accuracy without the rate limit risk; enable once API behavior is understood
- [ ] **Ground truth tracking schema** — accuracy tracking table per detection; feeds DeepForest fine-tuning workflow
- [ ] **Operator review UI** — simple web form or n8n approval node is MVP; dedicated review dashboard is v2.1

### Future Consideration (v3.0+)

- [ ] **DeepForest fine-tuning on Hampton Roads species** — requires 5–10 missions of ground-truthed data first; HIGH value but HIGH effort
- [ ] **Historical change detection** — repeat-survey comparison; requires calibration panel protocol, same-season imaging, and standardized flight parameters across missions
- [ ] **Processing-only intake workflow** (OQ5/OQ6) — client-supplied orthomosaic; requires separate ingest path and pricing model
- [ ] **Environmental survey package type** (OQ1) — separate from site_survey; requires business decision on package_type schema
- [ ] **Multispectral path** — true NDVI if a multispectral sensor is acquired for the Matrice 4E; entirely separate processing chain
- [ ] **i-Tree valuation integration** — contingent on species classification accuracy improvement via fine-tuning
- [ ] **Client-facing vegetation portal** — out of scope per PRD; deferred beyond v3.0

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| E1 Canopy Detection | HIGH | MEDIUM | P1 |
| E2 Species Classification | HIGH | HIGH | P1 |
| E3 Health Assessment (VARI/ExG) | HIGH | MEDIUM | P1 |
| PDF Report + maps | HIGH | MEDIUM | P1 |
| GeoJSON output | HIGH | LOW | P1 |
| Supabase schema (E1-E4) | HIGH | MEDIUM | P1 |
| n8n Review Gate (E5) | HIGH | LOW | P1 |
| delivery_packaging.py integration | HIGH | LOW | P1 |
| Accuracy/methodology disclosure in report | HIGH | LOW | P1 |
| Folium interactive map | MEDIUM | MEDIUM | P2 |
| Vision API qualitative health narrative | MEDIUM | LOW | P2 |
| PlantNet cross-validation | MEDIUM | LOW | P2 |
| Species/health distribution charts | MEDIUM | LOW | P2 |
| Ground truth tracking schema | HIGH | LOW | P2 |
| Operator review UI (beyond n8n gate) | LOW | HIGH | P3 |
| Processing-only intake (client ortho) | MEDIUM | HIGH | P3 |
| DeepForest fine-tuning pipeline | HIGH | HIGH | P3 |
| Historical change detection | HIGH | HIGH | P3 |

**Priority key:**
- P1: Must have for launch (v2.0)
- P2: Should have, add after first 5 missions
- P3: Future milestone (v3.0+)

---

## Competitor Feature Analysis

| Feature | TreeDetect | Deep Forestry | Sentinel Path E (planned) |
|---------|------------|--------------|--------------------------|
| Individual tree detection | YES — LiDAR + RGB | YES — LiDAR below-canopy | YES — RGB orthomosaic only |
| Tree count + location | YES | YES | YES |
| Height measurement | YES (from LiDAR DSM) | YES (full stem LiDAR) | NO — canopy area only; height from DSM optional future |
| Trunk diameter / DBH | YES (LiDAR) | YES | NO — aerial RGB limitation |
| Species classification | NO — not offered | YES — LiDAR-based | YES — Vision + PlantNet (low-medium accuracy) |
| Health assessment | NO | YES | YES — VARI/ExG + optional Vision |
| GeoJSON export | YES | API integration | YES |
| PDF report | YES | YES | YES |
| Interactive HTML map | YES — online report (requires account) | NO — API data only | YES (premium tier) — self-contained HTML |
| Sensor type | LiDAR + RGB | Autonomous LiDAR drone | RGB orthomosaic (consumer drones) |
| Pricing | Per-hectare, undisclosed | Enterprise, undisclosed | $200–$500 explicit tiered pricing |
| Turnaround | Hours (cloud processing) | 24 hours | 24–48 hours |
| Operator review gate | Unknown | Unknown | YES — explicit n8n gate |
| Methodology transparency | Unknown | Unknown | YES — explicit in report |
| Integration with flight workflow | Standalone — user provides data | Autonomous (their drone) | Native — extends existing Path C ortho |

**Key competitive insight:** TreeDetect and Deep Forestry both require LiDAR for height and DBH — sensors Sentinel does not have. Sentinel cannot compete on tree biometrics (height, DBH, volume). Sentinel's differentiation is: (1) lower cost via consumer RGB drones, (2) species classification attempt where TreeDetect offers none, (3) transparent pricing, (4) integration into an existing flight operation (not a standalone service), and (5) arborist partnership model where the drone operator + analysis is a bundled offering to tree care companies.

---

## Ground Truth Validation — Best Practices

This section addresses OQ-related accuracy questions and the "Comprehensive" tier that includes ground truth walk.

**Research-backed protocol:**

1. **Field survey timing**: Ground truth collection should coincide with (or within 1 week of) the drone flight — seasonal phenology changes rapidly in Hampton Roads mixed deciduous forests
2. **Data allocation**: 60–80% training, 10–20% validation, 10–20% test per standard remote sensing protocol
3. **Species labeling**: Ground crew records species (common + Latin), height estimate (clinometer), health condition (Good/Fair/Poor using ISA visual assessment criteria), and GPS point for each verified tree
4. **Annotation format**: COCO-format bounding boxes on orthomosaic or point labels at centroid — both supported by DeepForest fine-tuning
5. **Minimum for meaningful fine-tuning**: 500–1,000 labeled crowns across the target species set; achievable after 5–10 missions with systematic ground truth collection
6. **"Drone truthing" alternative**: For hard-to-access areas, low-altitude oblique drone photos from same mission can serve as ground reference for dominant/diagnostic plant species — established method in wetland vegetation mapping literature
7. **Accuracy tracking in Supabase**: Add `ground_truth_species`, `ground_truth_health`, `ground_truth_verified_by`, `ground_truth_date` columns to vegetation_detections — allows per-detection accuracy measurement as field data comes in

**The "Comprehensive" tier ($500) ground truth walk is a business differentiator:** It creates the training data needed to improve model accuracy over time, which is a flywheel — each Comprehensive mission makes future Standard missions more accurate. Market this explicitly once the pipeline is live.

---

## QA / Review Workflow — What Needs Human Oversight

Based on research into UAV vegetation analysis standards and the accuracy expectations above:

**Always flag for review:**
- Detections with species_confidence < 0.4 — below this threshold, Vision API calls are likely hallucinating or defaulting to generic categories
- Detections where PlantNet top-1 species disagrees with Vision API species (when both enabled) — surface disagreement explicitly in review UI
- health_status = "Critical" detections — should be visually confirmed before reporting to clients (dead tree vs shadow artifact)
- Sites where total_canopy_count < expected_count by large margin — indicates dense canopy overlap causing missed detections; operator should note in report

**Can auto-approve without review:**
- Detections where species_confidence >= 0.7 AND PlantNet agrees (when enabled)
- health_status = "Healthy" detections at high confidence — low-risk finding
- Geometric outputs (canopy area, centroid location) — deterministic from polygon geometry, not probabilistic

**Review UI minimum viable feature:**
- Side-by-side: canopy crop image | species call + confidence | health score | PlantNet result
- Flag / approve / edit species per detection
- Override health_status
- Add operator note to report
- Approve entire site for delivery

**Time estimate per review:** An experienced operator reviewing a 100-tree site should take 20–30 minutes for targeted review (low-confidence detections only, not every tree) — acceptable given the $200–$500 service fee.

---

## Open Questions Addressed by Research

| Question ID | Question | Research Answer |
|-------------|----------|-----------------|
| OQ2 | Minimum orthomosaic GSD for reliable canopy detection? | 10 cm/pixel maximum GSD; 5 cm/pixel optimal. DJI missions at typical AGL satisfy this. |
| OQ3 | Interactive map measurement tools (area, distance)? | Folium supports Leaflet Draw plugin for measurement tools — add as P2 enhancement |
| OQ4 | PlantNet 500 req/day limit sufficient? | With max_canopies=200 per mission, 2–3 full missions/day. Start with skip_plantnet=true to baseline without rate limit pressure |
| OQ5 | Standalone vegetation analysis without ortho package? | Technically feasible (any GeoTIFF input); requires separate ingest workflow — P3 |

---

## Sources

- [DeepForest Documentation — Prebuilt Models](https://deepforest.readthedocs.io/en/v1.3.3/prebuilt.html) — HIGH confidence
- [Fine-Tuning DeepForest for UAV Imagery (ISPRS 2025)](https://isprs-archives.copernicus.org/articles/XLVIII-4-W15-2025/39/2025/) — HIGH confidence
- [Manual Labelling Inflates Closed Canopy Performance (arXiv 2025)](https://arxiv.org/html/2503.14273) — HIGH confidence; documents F1 degradation in dense canopy
- [Urban Tree Detection DeepForest (ISPRS 2024)](https://isprs-annals.copernicus.org/articles/X-4-W4-2024/35/2024/) — HIGH confidence; urban performance benchmark
- [Tree Crown Detection Effects of Spatial Resolution (Remote Sensing 2023)](https://www.mdpi.com/2072-4292/15/3/778) — HIGH confidence; GSD impact quantified
- [Advances in Automated Tree Species ID: Systematic Review (MDPI 2024)](https://www.mdpi.com/2227-7080/13/5/187) — HIGH confidence; 70–90% accuracy range established
- [Tree Species Classification from UAV Canopy Images with Deep Learning (Remote Sensing 2024)](https://www.mdpi.com/2072-4292/16/20/3836) — HIGH confidence
- [Comparing RGB Vegetation Indices With NDVI (Semantic Scholar)](https://www.semanticscholar.org/paper/Comparing-RGB-Based-Vegetation-Indices-With-NDVI-McKinnon/5ec3ec2a92e61e49dbc6b33f9f0d170b313128f5) — HIGH confidence
- [Forage Biomass UAV Multispectral vs RGB (PMC 2024)](https://pmc.ncbi.nlm.nih.gov/articles/PMC11397825/) — HIGH confidence; NDVI superiority over RGB indices
- [PlantNet API Documentation](https://my.plantnet.org/doc/getting-started/introduction) — HIGH confidence; organ type limitations explicitly documented
- [GPT-4 vs Plant.id Plant Identification Battle (Kindwise)](https://www.kindwise.com/post/the-plant-identification-battle-gpt-4-vs-plant-id) — MEDIUM confidence; 55.8% accuracy baseline from educational study
- [Drone and Ground-Truth Data Collection Protocol (ScienceDirect 2024)](https://www.sciencedirect.com/science/article/pii/S2215016124003868) — HIGH confidence; training/validation split ratios
- [Best Practices for Ground Truthing a Drone Survey (Pilot Institute)](https://pilotinstitute.com/ground-drone-mapping/) — MEDIUM confidence
- [TreeDetect Platform](https://www.treedetect.com/en/) — competitor analysis; pay-per-hectare model, no species classification
- [Deep Forestry](https://www.deepforestry.com/) — competitor analysis; enterprise LiDAR, no public pricing
- [Task Planning Support for Arborists (arXiv 2023)](https://arxiv.org/html/2307.01651) — HIGH confidence; arborist workflow requirements
- [UAV Tree Risk Assessment Systematic Review (ISA/AUF 2025)](https://auf.isa-arbor.com/content/early/2025/05/05/jauf.2025.015) — HIGH confidence; human oversight requirements
- [Best Libraries for Geospatial Visualization in Python (Towards Data Science)](https://towardsdatascience.com/best-libraries-for-geospatial-data-visualisation-in-python-d23834173b35/) — MEDIUM confidence; Folium vs alternatives

---

*Feature research for: Sentinel drone vegetation analysis pipeline — Path E*
*Researched: 2026-02-24*
