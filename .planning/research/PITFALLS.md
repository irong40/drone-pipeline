# Pitfalls Research

**Domain:** Geospatial vegetation analysis pipeline — Windows Python, GDAL/rasterio, PyTorch/DeepForest, Vision APIs
**Researched:** 2026-02-24
**Confidence:** HIGH (GDAL/rasterio, PyTorch/Blackwell, GeoPandas) | MEDIUM (DeepForest model behavior, PlantNet, Folium) | LOW (seasonal accuracy degradation specifics for Hampton Roads region)

---

## Critical Pitfalls

### Pitfall 1: PyTorch Stable Builds Do Not Support RTX 5070 (sm_120)

**What goes wrong:**
Installing PyTorch from the standard stable channel (`pip install torch --index-url https://download.pytorch.org/whl/cu128`) on Windows with an RTX 5070 either silently falls back to CPU inference or throws `CUDA capability sm_120 is not compatible with the current PyTorch installation`. DeepForest never errors out clearly — it just runs on CPU at 10-20x slower speeds, making it look like it works while processing a 1GB orthomosaic for 4+ hours instead of 15-20 minutes.

**Why it happens:**
Stable PyTorch builds up through 2.6.x compiled with CUDA 12.4 do not include sm_120 kernels. Blackwell (RTX 50-series) requires PyTorch nightly builds with cu128 or cu129, or PyTorch 2.7+ built with CUDA 12.8. The PyTorch website's GPU compatibility matrix does not prominently warn about this for Blackwell until you're already failing.

**How to avoid:**
1. Install PyTorch nightly with CUDA 12.8 explicitly before DeepForest: `pip install --pre torch torchvision --index-url https://download.pytorch.org/whl/nightly/cu128`
2. Add a startup assertion in canopy_detection.py: `assert torch.cuda.is_available() and torch.cuda.get_device_capability()[0] >= 8, "CUDA GPU required"` plus log `torch.cuda.get_device_name(0)` and `torch.cuda.get_device_capability()`.
3. Pin the nightly version in requirements-vegetation.txt with the exact build date hash to prevent automatic upgrade to an incompatible build.
4. Test GPU path explicitly: run a small synthetic inference call at script startup to verify CUDA is active before processing real data.

**Warning signs:**
- `torch.cuda.is_available()` returns True but `torch.cuda.get_device_capability()` returns `(8, 9)` or earlier instead of `(12, 0)`
- CPU utilization pegged at 100% during DeepForest inference while GPU sits idle in Task Manager
- Wall time per tile > 30 seconds (GPU should be 1-2 seconds per 1024x1024 tile)
- No CUDA OOM errors even when loading many tiles simultaneously

**Phase to address:** Phase 1 (E1 canopy_detection.py) — before writing any other path E code

---

### Pitfall 2: conda Channel Mixing Breaks CUDA or Geospatial Stack

**What goes wrong:**
Installing PyTorch from the `pytorch` channel and then installing rasterio/GeoPandas from `conda-forge` into the same environment produces a working-looking environment that fails at runtime with DLL load errors, GDAL version mismatches, or libgcc conflicts. The solver may not warn — it resolves but produces incompatible binaries because each channel compiles packages against different BLAS/OpenMP stacks.

**Why it happens:**
PyTorch must be installed from the official PyTorch index (pip) or pytorch channel (conda), not conda-forge — conda-forge's PyTorch build lacks GPU support in most cases. Geospatial packages (rasterio, GDAL, Fiona, GeoPandas) are best installed from conda-forge because conda-forge maintains pinned GDAL versions that ensure binary compatibility. Mixing these two ecosystems in one conda environment frequently fails.

**How to avoid:**
Use two separate strategies depending on team preference:

**Option A (pip-first, recommended for this project given existing pip-based pipeline):**
```
# Create a fresh venv
python -m venv .venv-vegetation
# Install PyTorch first (nightly cu128 for RTX 5070)
pip install --pre torch torchvision --index-url https://download.pytorch.org/whl/nightly/cu128
# Install GDAL wheel from Christoph Gohlke's Windows wheels or conda
pip install GDAL-3.x.x-cp311-cp311-win_amd64.whl  # from OSGeo4W or conda-forge wheel
# Install rasterio wheel (must match GDAL version)
pip install rasterio==1.3.x  # match to GDAL version
# Install remaining geospatial stack
pip install geopandas shapely pyproj fiona
# Install DeepForest last
pip install deepforest
```

**Option B (conda-only, cleanest isolation):**
```
conda create -n sentinel-veg python=3.11
conda activate sentinel-veg
# PyTorch from pip (conda-forge PyTorch lacks GPU)
pip install --pre torch torchvision --index-url https://download.pytorch.org/whl/nightly/cu128
# Everything else from conda-forge
conda install -c conda-forge rasterio geopandas fiona shapely pyproj
pip install deepforest
```

Never mix conda-forge and pytorch conda channels in the same environment.

**Warning signs:**
- Import error: `ImportError: DLL load failed while importing _gdal`
- PROJ database version mismatch errors on first `rasterio.open()` call
- `torch.cuda.is_available()` returns False in an environment where you installed CUDA PyTorch
- `conda list` shows `pytorch` package from `conda-forge` source instead of `pytorch` channel

**Phase to address:** Phase 1 — environment setup before any code is written

---

### Pitfall 3: PROJ_LIB / PROJ_DATA Environment Variable Conflicts

**What goes wrong:**
Windows system-level GDAL or QGIS installations set `PROJ_LIB` (older) or `PROJ_DATA` (PROJ 9.1+) as system environment variables. When rasterio opens a dataset, it picks up these system variables and finds a PROJ database version that is incompatible with the PROJ bundled inside rasterio's wheel. The error is cryptic: `PROJ: internal_proj_create_from_database ERROR 1: PROJ: internal_proj_identify [...] proj.db lacks DATABASE.LAYOUT.VERSION.MAJOR / DATABASE.LAYOUT.VERSION.MINOR metadata.` CRS operations then silently fail or raise exceptions.

**Why it happens:**
rasterio wheels since v1.2.0 bundle their own PROJ 7+ / GDAL 3+, but if `PROJ_LIB` or `PROJ_DATA` is set in Windows environment and points to an older installation (e.g., QGIS's PROJ 6.x), rasterio uses the wrong database. This is a Windows-specific issue because QGIS and OSGeo4W installers commonly set these system-wide.

**How to avoid:**
At the start of canopy_detection.py, before importing rasterio, add:
```python
import os
# Clear conflicting PROJ environment variables to let rasterio use its bundled PROJ
for var in ("PROJ_LIB", "PROJ_DATA", "GDAL_DATA"):
    if var in os.environ:
        del os.environ[var]
import rasterio
```
Document this in the vegetation environment setup guide. Verify after rasterio import that `rasterio.crs.CRS.from_epsg(4326)` succeeds without warnings.

**Warning signs:**
- Any error message containing `proj.db lacks DATABASE.LAYOUT.VERSION`
- `UserWarning: The PROJ library is broken` from pyproj
- CRS operations that worked in conda environment fail in venv
- `echo %PROJ_LIB%` or `echo %PROJ_DATA%` returns a path in `C:\Program Files\QGIS*` or `C:\OSGeo4W`

**Phase to address:** Phase 1 (E1) — environment setup and script initialization

---

### Pitfall 4: rasterio Windowed Read Memory Leak on Tiled GeoTIFFs

**What goes wrong:**
When iterating over tiles of a large (1GB+) GeoTIFF using `rasterio.open()` inside a loop with `dataset.read(window=window)`, memory usage grows continuously and never returns to baseline. Processing a 1GB orthomosaic with 1024x1024 tiles consumes 8-16GB RAM and may OOM before completing. This is a confirmed regression in rasterio 1.3.10+ (tracked in rasterio issue #3241 and #3250).

**Why it happens:**
GDAL block cache is not aggressively freed between windowed reads, and rasterio 1.3.10+ changed internal caching behavior. Re-opening the file inside the loop (re-instantiating the dataset context manager) prevents the leak because each `rasterio.open()` context flushes the cache on close.

**How to avoid:**
Open the dataset once outside the tile loop but use `GDAL_CACHEMAX` to limit GDAL's internal block cache:
```python
import os
os.environ["GDAL_CACHEMAX"] = "256"  # MB — set before importing rasterio

with rasterio.open(ortho_path) as src:
    for window in tile_windows:
        tile_data = src.read(window=window)
        process_tile(tile_data)
        del tile_data  # explicit deletion helps GC
```
If leak persists, process tiles in subprocess batches (e.g., 50 tiles per subprocess call) so memory is fully reclaimed between batches. Convert orthomosaics to Cloud-Optimized GeoTIFF (COG) format before processing — COG's tiled internal structure aligns with windowed reads and reduces cache pressure.

**Warning signs:**
- Task Manager shows Python process growing >2GB during tile iteration with no corresponding release
- Processing completes first 100 tiles normally then slows dramatically (thrashing to page file)
- Processing a test 50MB ortho succeeds but a 500MB ortho OOMs at the same tile count

**Phase to address:** Phase 1 (E1 canopy_detection.py) — tile iteration design

---

### Pitfall 5: DeepForest Duplicate Detections at Tile Boundaries Without Cross-Tile NMS

**What goes wrong:**
When tiling a large orthomosaic and running DeepForest on each tile independently, trees that overlap a tile boundary are detected twice — once in each adjacent tile. The same crown appears as two overlapping polygons in the final GeoPackage. With a 40-50% tile overlap strategy, a single tree may be detected 4 times. Species classification and health assessment then run on all duplicates, quadrupling API costs.

**Why it happens:**
DeepForest's built-in `predict_image()` handles intra-tile NMS internally, but when you split and stitch manually, the stitching step must apply a second NMS pass across the full ortho coordinate space. If you just `pd.concat()` all tile results, duplicates remain.

**How to avoid:**
Use DeepForest's built-in tiling via `model.predict_tile()` instead of manual tiling — it handles overlap and cross-tile NMS automatically with configurable `iou_threshold`. If manual tiling is required for memory control:
```python
from deepforest.utilities import annotations_dataframe_to_geodataframe
import geopandas as gpd

all_boxes = gpd.GeoDataFrame(pd.concat(tile_results))
# Apply spatial NMS in the full orthomosaic CRS
from torchvision.ops import nms
import torch
boxes = torch.tensor(all_boxes[['xmin','ymin','xmax','ymax']].values, dtype=torch.float32)
scores = torch.tensor(all_boxes['score'].values, dtype=torch.float32)
keep = nms(boxes, scores, iou_threshold=0.3)
final_boxes = all_boxes.iloc[keep.numpy()]
```
Set tile overlap to exactly 0.25 (25%) to balance detection coverage against duplicate rate — less than 0.1 misses edge trees, more than 0.5 explodes duplicates.

**Warning signs:**
- Canopy count in the GeoPackage is 1.5-4x higher than visual inspection of the ortho suggests
- Pairs of nearly-identical polygons with slightly different bounding boxes at regular intervals matching tile size
- API costs for species classification 2-4x higher than expected based on canopy count

**Phase to address:** Phase 1 (E1 canopy_detection.py) — tile stitching logic

---

### Pitfall 6: OpenAI Vision API Cost Overrun on Large Orthomosaics

**What goes wrong:**
Processing a site with 300 detected trees at the default 30% sampling rate (90 canopy crops) with gpt-4o vision at $2.50/M input tokens results in $3-8 per analysis rather than the estimated $1-5. If `vision_sample_pct` is misconfigured or max_canopies guard is skipped, a site with 500 trees processes all 500 through the Vision API and costs $15-25 in a single run.

**Why it happens:**
Each canopy crop sent to gpt-4o-vision encodes as 765-1105 tokens depending on image size and detail level. A 200x200 pixel crop in "high" detail mode costs approximately 1500 tokens. Without a hard cap on API calls per script invocation, a single large site blows through the mission budget.

**How to avoid:**
Implement three layers of cost control:
1. **Hard cap**: Enforce `max_canopies` (default 200) as a per-run ceiling with no override without explicit `--no-cap` flag and a confirmation prompt.
2. **Cost estimator**: Before making any API calls, compute estimated cost: `n_canopies * avg_tokens_per_crop * $0.0000025` and log it. Abort if estimated cost > configurable threshold (default $10).
3. **Budget tracker**: Use a simple JSON file per mission tracking cumulative API spend. Refuse to process if mission budget is already exceeded.
4. Use `detail="low"` for gpt-4o vision on canopy crops under 512px — reduces per-image token cost by ~4x with minimal accuracy loss for species classification.
5. For health_assessment.py, sample only canopies that scored below a health threshold from RGB indices — avoid Vision API for clearly healthy canopies.

**Warning signs:**
- OpenAI usage dashboard shows unexpected spikes
- Processing time for species_classification.py exceeds 5 minutes for a single site
- Log output shows more than 200 Vision API calls in a single run
- Rate limit 429 errors (sign you're making too many concurrent calls)

**Phase to address:** Phase 1 (E2 species_classification.py and E3 health_assessment.py) — must be built in from the start, not added later

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Reading entire orthomosaic into RAM with `src.read()` | Simple code | OOM on any file >2GB | Never — always use windowed reads |
| Using `requests.post()` for PlantNet without timeout | Simpler code | Script hangs indefinitely on network hiccup | Never — always set `timeout=(5, 30)` |
| Hard-coding EPSG:4326 as output CRS | Avoids CRS logic | Breaks area/distance calculations (degrees not meters) | Never for area/perimeter fields; OK for output GeoJSON only |
| Processing all canopies through Vision API (no sampling) | Simpler loop | Cost overrun, slow | Never — always enforce max_canopies cap |
| Using `model.predict_image()` on full ortho without tiling | One function call | OOM on any ortho >~200MB | Never for production orthomosaics |
| Skipping COG conversion step | Faster to start | 3-5x slower windowed reads, memory leak risk | Skip only on files <100MB for debugging |
| `pd.concat` tile results without NMS | Simple merge | Duplicate detections, inflated API costs | Never — always apply cross-tile NMS |
| Storing canopy crops as temp files with fixed names | Simple | Race condition if two missions run simultaneously | OK for single-operator use; fix before multi-operator |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| OpenAI Vision API | Sending full ortho tile (1024px) to Vision | Crop individual canopy bbox with 20px padding, resize to max 512px |
| OpenAI Vision API | Using base64-encoded image in every request | For repeated processing, use OpenAI Files API to upload once and reference by file_id |
| OpenAI Vision API | No retry on 429/503 | Exponential backoff: 1s, 2s, 4s, 8s, max 3 retries; log and skip after retries exhausted |
| PlantNet API | Sending aerial canopy crops directly | PlantNet expects ground-level plant photos; aerial crop species ID accuracy is poor — treat as supplemental signal only, not primary classifier |
| PlantNet API | No `remainingIdentificationRequests` check | Read this field from every response; pause 24h if < 10 remaining |
| PlantNet API | Missing `lang` parameter | Default returns scientific names only; pass `lang=en` for common names |
| rasterio | Opening file with `mode='r+'` for coordinate transforms | Use `mode='r'` plus separate write; in-place modification corrupts GeoTIFF internal structure |
| DeepForest | Calling `model.use_release()` every run | Downloads/verifies model weights on every invocation; cache the model object, load once at script start |
| GeoPandas | `.to_file()` default format | Default is ESRI Shapefile with 10-char field name truncation; use `driver='GPKG'` for GeoPackage or `driver='GeoJSON'` |
| Supabase | Storing WKT geometry as TEXT | Use PostGIS geometry type via `ST_GeomFromText()`; enables spatial queries without app-side filtering |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Re-instantiating DeepForest model per tile | 30-60s load time per tile instead of per run | Load model once at script start, pass to tile processing function | 10+ tiles (visible within first run) |
| No tile overlap — adjacent trees split at boundary | Systematic undercounting at tile edges | Use `predict_tile()` with overlap=0.25 or manual 25% overlap | Always — any tile-based approach without overlap |
| Sending unresized crops to gpt-4o | 3000+ tokens per image, costs 4x more | Resize crops to max 512px on longest side before encoding | Always — every Vision API call |
| Generating Folium map with all canopy polygons as individual GeoJson layers | HTML > 20MB, browser freezes on open | Use single `folium.GeoJson` layer with all polygons, set `smooth_factor=1` | >50 polygons if added individually |
| `geopandas.sjoin()` in geographic CRS (EPSG:4326) | Area calculations in degrees, not meters | Project to local UTM before any area/distance operations | Always — EPSG:4326 is never appropriate for measurements |
| Loading all detections into memory for final GeoJSON output | OOM for sites with >10k detections | Stream rows with `iterrows()` or use GeoPackage layer API | >5000 detections (~10 acre dense canopy site) |
| GDAL block cache at default size (32MB) during tiling | Repeated disk seeks, 5-10x slower read | Set `GDAL_CACHEMAX=512` (MB) before rasterio import | Any file >512MB |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| API keys in script or requirements file | Key exfiltration if script is shared or committed | Load from environment variables or `.env` file; add `.env` to `.gitignore` |
| No path validation on orthomosaic input path | Path traversal if mission_id or path comes from webhook payload | Use `pathlib.Path.resolve()` and assert it is within allowed base directories |
| Logging full PlantNet/OpenAI API responses | Response may contain PII or reveal internal scoring | Log only result fields (species, confidence), not raw response body |
| No spend cap on OpenAI API | Runaway cost if called in a loop bug | Set a max monthly spend limit in OpenAI dashboard AND enforce per-run cost estimator in code |
| Temp canopy crop files with predictable names | Overwrite race condition if two processes run simultaneously | Use `tempfile.mkdtemp()` for per-run temp directories, clean up in finally block |

---

## "Looks Done But Isn't" Checklist

- [ ] **GPU inference verified**: Confirm `torch.cuda.get_device_name(0)` returns "NVIDIA GeForce RTX 5070" and inference wall time < 5 min per 1GB ortho — not just `is_available() == True`
- [ ] **Cross-tile NMS applied**: Spot-check output GeoPackage in QGIS for duplicate overlapping polygons at tile boundaries — bbox count should not exceed 1.3x visual tree count
- [ ] **PROJ_LIB cleared**: CRS operations tested with a real drone orthomosaic (not a synthetic test file) on the production Windows machine; check for proj.db warnings in logs
- [ ] **API cost capped**: Test with `max_canopies=5` override, then check OpenAI usage dashboard confirms < $0.05 spend for that test run
- [ ] **PlantNet quota guarded**: `remainingIdentificationRequests` logged on every call; test that script pauses gracefully when quota < 10
- [ ] **Folium HTML size checked**: Open output HTML in browser and confirm <8MB file size and smooth interaction with 200+ polygons
- [ ] **Output CRS consistent**: All output files (GeoPackage, GeoJSON, PDF maps) verified to use same CRS; no mixed EPSG:4326 / UTM outputs
- [ ] **Memory bounded**: Run on largest available test ortho while watching Task Manager; confirm Python process does not exceed 4GB RAM during tile iteration
- [ ] **Seasonal accuracy disclosed**: Confirm PDF report footer includes data collection date and a note that accuracy degrades for leafless deciduous trees (winter) and low-light conditions
- [ ] **Checkpoint resume works**: Kill script mid-run on step E2; confirm re-run skips already-classified canopies rather than re-calling Vision API

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Wrong PyTorch (CPU fallback) discovered after E1 written | MEDIUM | Reinstall PyTorch nightly cu128; verify no code changes needed (CUDA path transparent if assertions added) |
| PROJ_LIB conflict causing CRS failures in production | LOW | Add env var clear at script top; no data loss |
| Duplicate detections shipped to client in report | HIGH | Re-run E1 with cross-tile NMS fix; re-run E2+E3 (additional API cost); regenerate report |
| OpenAI cost overrun ($50+ on one mission) | MEDIUM | Set OpenAI spend limit immediately; add per-run cost cap before next run; no data recovery needed |
| rasterio memory leak causing OOM crash mid-tile | LOW | Add GDAL_CACHEMAX env var; restart processing from last checkpoint (uses existing GAP-11 resume mechanism) |
| conda channel mix breaks environment | HIGH | Nuke environment, recreate from scratch following pip-first strategy; typically 2-4 hours |
| PlantNet quota exhausted mid-mission | LOW | Script should detect and skip; re-run with `--skip-plantnet` flag next day when quota resets |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| PyTorch sm_120 not supported in stable | Phase 1 setup — install script | `assert torch.cuda.get_device_capability() >= (12, 0)` in test_environment.py |
| conda channel mixing | Phase 1 setup — environment creation doc | `conda list` shows no rasterio from pytorch channel; no DLL errors on import |
| PROJ_LIB conflict | Phase 1 (E1 canopy_detection.py) | CRS round-trip test: open real ortho, read CRS, reproject, verify no PROJ warnings |
| Memory leak on windowed reads | Phase 1 (E1) | Process 500MB test ortho with `tracemalloc` — confirm <2GB peak RSS |
| Cross-tile NMS duplicates | Phase 1 (E1) | Canopy count from tiled processing within 10% of count from `predict_tile()` on same ortho |
| Vision API cost overrun | Phase 1 (E2, E3) | Run with 10-tree test ortho; verify OpenAI dashboard shows <$0.10 spend |
| PlantNet quota exhaustion | Phase 1 (E2) | Mock `remainingIdentificationRequests: 5`; verify script logs warning and skips further calls |
| GeoPandas CRS measurement errors | Phase 1 (E1) | Area calculation test: 1-acre known parcel within 5% of 4047m² in projected CRS |
| Folium performance with 200+ polygons | Phase 2 (E4 vegetation_report.py) | Load HTML in Chrome with 200-polygon test; confirm render <3s, file size <8MB |
| Winter/low-light accuracy degradation | Phase 3 (ground truth baseline) | Accuracy tracking table flagging orthos collected Dec-Feb or shadow fraction >20% |

---

## Seasonal and Lighting Accuracy Degradation

This section is specific to this domain and merits explicit treatment.

**Winter bare tree degradation (MEDIUM confidence):**
DeepForest's pretrained model was trained primarily on leaf-on imagery. For deciduous species (common in Hampton Roads: oaks, maples, sweetgums), canopy detection F1 score drops from ~0.85 (summer) to an estimated 0.55-0.70 (winter) based on published RGB-based canopy detection literature. Bare crowns are spectrally similar to surrounding ground, and crown shape cues are weaker without foliage.

Prevention: Note collection date in PDF report. Flag missions where deciduous trees are likely to be bare (November through March in Hampton Roads). Recommend leaf-on collection for vegetation analysis jobs when scheduling. Do not claim >85% accuracy for winter collections.

**Shadow and low-sun-angle degradation:**
Early morning and late afternoon flights (sun angle < 30°) produce significant cast shadows that reduce detection confidence. Canopy mortality research found shadow was the primary source of false negatives. Standardize vegetation missions to solar noon ±2 hours.

**GSD (Ground Sample Distance) sensitivity:**
DeepForest accuracy degrades significantly below 5cm/pixel GSD. Matrice 4E at 120m AGL produces ~3cm/pixel (excellent). Mini 4 Pro at 80m AGL produces ~2.5cm/pixel (excellent). Verify minimum GSD of 5cm/pixel is documented as a requirement in the service terms — arborist-supplied imagery from consumer drones at high altitude may not meet this.

---

## Sources

- [rasterio Installation docs — PROJ conflict warnings](https://rasterio.readthedocs.io/en/stable/installation.html)
- [rasterio FAQ — PROJ_LIB / PROJ_DATA conflict fix](https://rasterio.readthedocs.io/en/stable/faq.html)
- [rasterio GitHub Issue #3241 — Windowed read memory leak in tiled GeoTIFF](https://github.com/rasterio/rasterio/issues/3241)
- [rasterio Windowed Reading docs](https://rasterio.readthedocs.io/en/stable/topics/windowed-rw.html)
- [PyTorch GitHub Issue #164342 — Official sm_120 Blackwell support tracking](https://github.com/pytorch/pytorch/issues/164342)
- [PyTorch GitHub Issue #159207 — Add sm_120 support](https://github.com/pytorch/pytorch/issues/159207)
- [PyTorch Forums — RTX 5070 Ti sm_120 not compatible with current PyTorch](https://discuss.pytorch.org/t/nvidia-geforce-rtx-5070-ti-with-cuda-capability-sm-120-is-not-compatible-with-the-current-pytorch-installation/222090)
- [GitHub — pytorch-build-blackwell-sm120 guide](https://github.com/bajegani/pytorch-build-blackwell-sm120)
- [DeepForest Installation docs](https://deepforest.readthedocs.io/en/latest/getting_started/install.html)
- [GeoPandas Projections docs — CRS pitfalls](https://geopandas.org/en/stable/docs/user_guide/projections.html)
- [Folium — Reducing map file sizes (Andrew Wheeler, 2024)](https://andrewpwheeler.com/2024/08/04/reducing-folium-map-sizes/)
- [Folium — GitHub Issue #975: HTML file size](https://github.com/python-visualization/folium/issues/975)
- [Folium — GitHub Issue #1131: Performance with many markers](https://github.com/python-visualization/folium/issues/1131)
- [OpenAI — How to handle rate limits](https://developers.openai.com/cookbook/examples/how_to_handle_rate_limits/)
- [OpenAI — Rate limits docs](https://platform.openai.com/docs/guides/rate-limits)
- [PlantNet API — Free tier 500/day limit and authentication](https://my.plantnet.org/)
- [PlantNet API docs](https://docs.plantnet.org/en/reference/api-plantnet/)
- [conda-forge — rasterio Windows install recommendation](https://rasterio.readthedocs.io/en/stable/installation.html)
- [Forest canopy mortality detection — shadow / illumination degradation](https://academic.oup.com/forestry/article/97/3/376/7307321)
- [DeepForest — ML-X Nexus description and F1 score ranges](https://uw-madison-datascience.github.io/ML-X-Nexus/Toolbox/Models/DeepForest.html)
- [OpenSourceOptions — rasterio Windows pip vs conda](https://opensourceoptions.com/install-rasterio-for-windows-with-pip-or-conda/)

---
*Pitfalls research for: Vegetation analysis pipeline (Path E), Windows 11, RTX 5070, Python 3.11+*
*Researched: 2026-02-24*
