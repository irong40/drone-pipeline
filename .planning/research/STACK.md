# Stack Research — Path E Vegetation Analysis

**Domain:** Drone orthomosaic vegetation analysis pipeline (Python CLI)
**Researched:** 2026-02-24
**Confidence:** HIGH (all versions verified against PyPI, official docs, and PyTorch forums)

---

## Context: What This Is NOT Re-Researching

The existing stack is validated and stays unchanged:

| Already Have | Do Not Reinstall |
|--------------|-----------------|
| Python 3.14.3 (system) | — |
| pytest, pytest-mock, pytest-cov | — |
| supabase>=2.0.0 | — |
| google-api-python-client, google-auth | — |
| Pillow, pyexiftool, requests, watchdog | — |
| pywin32 | — |

Everything in this document is NEW — additions to `requirements.txt` for Path E only.

---

## Critical Constraint: Python Version Split

**The existing pipeline runs Python 3.14.3 (system default). DeepForest 2.0.0 requires Python >=3.10, <3.13.**

This means Path E scripts MUST run in a separate Python 3.12 virtual environment.

**Resolution:** Python 3.12.10 is already installed on this machine (confirmed via `py -3.12 --version`). Create a dedicated venv:

```cmd
py -3.12 -m venv C:\Users\redle\drone-pipeline\.venv-path-e
.venv-path-e\Scripts\activate
```

All Path E dependency installs below run inside this venv. The existing 14 scripts remain in the system Python 3.14 environment with their current requirements.txt untouched.

---

## Recommended Stack (New Additions Only)

### Core ML: GPU-Accelerated Canopy Detection

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| PyTorch | 2.9.1 (cu128) | Tensor ops, GPU execution for DeepForest | 2.9.x is the latest stable with official CUDA 12.8 wheels. RTX 5070 (sm_120/Blackwell) support is confirmed stable as of PyTorch 2.7+ — no source build required. |
| torchvision | 0.24.1 (cu128) | Object detection backbone, image transforms | Required by DeepForest; version must match torch exactly. |
| torchaudio | 2.9.1 (cu128) | Side dependency of torch ecosystem | Install alongside torch/torchvision to avoid version conflicts. |
| DeepForest | 2.0.0 | Tree crown / canopy detection from RGB orthomosaic | Pretrained RetinaNet model on NEON airborne imagery. Only production-ready open source package for this task. Pulls in pytorch-lightning, rasterio, geopandas, albumentations, opencv as sub-dependencies. |

### Geospatial Processing

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| rasterio | 1.4.4 | GeoTIFF reading, tile windowing, pixel extraction | 1.5.0 requires Python 3.12+ and numpy 2.x — compatible in this venv, but 1.4.4 is safer. Bundles GDAL 3.9.x for Windows. No separate GDAL install needed. |
| GeoPandas | 1.1.2 | Canopy polygon operations, GeoJSON/GeoPackage I/O | 1.x series is the modern release with Shapely 2.x required. pip install works cleanly on Windows since Shapely and pyogrio now ship binary wheels. |
| Shapely | >=2.0.6 | Geometry primitives (Point, Polygon, MultiPolygon) | Shapely 2.x is C-extension only (dropped pure Python), so it's significantly faster. GeoPandas 1.x mandates it. Installed automatically as a GeoPandas dependency. |
| pyproj | >=3.6.0 | CRS transformations (UTM ↔ WGS84) | Required by GeoPandas and rasterio. Bundles PROJ 9.x. Automatically installed. |

### Visualization and Reporting

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Folium | 0.20.0 | Interactive Leaflet.js map as HTML output | Latest stable. Pure Python, no C extensions. Generates standalone HTML with embedded Leaflet tiles — no server needed, ships in client ZIP. |
| ReportLab | 4.4.10 | Branded PDF report generation | Latest stable (released 2026-02-12). Open-source tier covers all needed features: text, images, charts, page layout. No license cost. |
| matplotlib | 3.10.8 | Health score charts, species distribution bar charts, annotated map PNGs | Almost certainly already installed as a DeepForest sub-dependency. Pin to >=3.9.0 to ensure compatibility with numpy 2.x. |

### External APIs

| Service | Version/Endpoint | Purpose | Auth |
|---------|-----------------|---------|------|
| OpenAI Vision API | gpt-4o, API v1 | Species classification from canopy crops, qualitative health assessment | API key via env var `OPENAI_API_KEY`. Use `openai>=1.0.0` Python client. |
| PlantNet API | v2, `https://my-api.plantnet.org/v2/identify/all` | Cross-validation of species classification | API key as query param `?api-key=`. Free tier: 500 identifications/day. |

---

## Installation

Run all of the following inside the Python 3.12 venv at `.venv-path-e\`:

```bash
# Step 1: PyTorch with CUDA 12.8 (RTX 5070 Blackwell support)
pip install torch==2.9.1 torchvision==0.24.1 torchaudio==2.9.1 \
    --index-url https://download.pytorch.org/whl/cu128

# Step 2: DeepForest (installs rasterio, geopandas, shapely, opencv, etc. as sub-deps)
pip install deepforest==2.0.0

# Step 3: Visualization and reporting (may already be sub-deps; pin anyway)
pip install "folium==0.20.0" "reportlab==4.4.10" "matplotlib>=3.9.0"

# Step 4: OpenAI client
pip install "openai>=1.0.0"

# Step 5: Verify GPU is visible
python -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
```

Expected output from Step 5:
```
True
NVIDIA GeForce RTX 5070
```

### Why This Install Order Matters

DeepForest's pip install pulls torch, torchvision, rasterio, geopandas, shapely, and opencv as dependencies. If you install DeepForest first, pip will resolve torch from PyPI (no CUDA). Install PyTorch with `--index-url cu128` FIRST, then DeepForest. pip will see torch already satisfied and won't overwrite it with a CPU build.

---

## Alternatives Considered

| Recommended | Alternative | Why Alternative Was Rejected |
|-------------|-------------|-------------------------------|
| DeepForest 2.0.0 | Detectron2 | No pretrained tree crown model; requires training from scratch; Meta's maintenance cadence is slow. |
| DeepForest 2.0.0 | YOLOv8 + custom labels | Would need labeled training data we don't have. DeepForest's NEON pretrained weights work out-of-the-box on residential trees. |
| rasterio 1.4.4 | rasterio 1.5.0 | 1.5.0 requires numpy>=2 and is newer than we need. 1.4.4 is the stable LTS-equivalent and is installed automatically by deepforest anyway. |
| ReportLab | WeasyPrint / pdfkit | WeasyPrint requires Cairo system lib (painful on Windows). pdfkit wraps wkhtmltopdf (large binary dep). ReportLab is pure Python. |
| ReportLab | fpdf2 | fpdf2 is lighter but lacks the Platypus layout engine needed for multi-column reports with embedded charts. |
| Folium | Deck.gl / Kepler.gl | Overkill for 200-canopy maps. Folium generates self-contained HTML, no server required. |
| gpt-4o | gpt-4o-mini | Mini uses same high-detail vision pricing formula but has lower accuracy for plant identification. For 30% sample of canopies (vision_sample_pct=0.3), gpt-4o quality is worth the marginal cost. |
| PlantNet (cross-validate only) | iNaturalist API | iNaturalist's identification API is rate-limited and requires observation context. PlantNet is designed for programmatic image-only queries. |

---

## What NOT to Add

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| GDAL installed separately (OSGeo4W, etc.) | rasterio 1.4.x PyPI wheels bundle GDAL 3.9.x. Installing a separate system GDAL creates conflicting DLLs on Windows and breaks both installs. | Let rasterio's wheel manage GDAL. Never set `GDAL_DATA` or `PROJ_DATA` env vars in the venv. |
| tensorflow | DeepForest 2.0.0 dropped TensorFlow entirely (was in 1.x). PyPI still has the old `deepforest-pytorch` package — do not install that. | The standard `deepforest` package on PyPI is now PyTorch-only. |
| CUDA toolkit installer | RTX 5070 with CUDA 12.8 is already on the rig. PyTorch cu128 wheels bundle their own cudnn libs. Don't reinstall system CUDA. | Verify with `nvidia-smi` that driver 581.57 is present; that's sufficient. |
| numpy pinned to 1.x | rasterio 1.4.4 requires numpy>=1.24; DeepForest and matplotlib work with numpy 2.x. Pinning 1.x blocks upgrades. | Let pip resolve numpy; it will land on 2.x which everything supports. |
| opencv-python | DeepForest installs `opencv-python-headless`. Installing `opencv-python` alongside it causes DLL conflicts on Windows (two different cv2 builds fighting). | Use `opencv-python-headless` only, which deepforest pulls automatically. |
| Pillow version conflict | The existing requirements.txt has `Pillow>=10.0.0`. DeepForest requires Pillow as well. Both are compatible; no pin change needed. | Verify with `pip check` after install. |

---

## Stack Patterns by Variant

**If GPU not available (fallback to CPU):**
- DeepForest will automatically detect no CUDA and run on CPU
- E1 (canopy detection) will take 5-20x longer; tile_size reduction to 512 helps
- Use `DEEPFOREST_DEVICE=cpu` env var to force CPU explicitly
- Do NOT use CPU mode in production; RTX 5070 makes E1 tractable in seconds per tile

**If PlantNet 500/day limit is hit:**
- Set `--skip-plantnet` flag on E2; OpenAI Vision becomes sole classifier
- PlantNet is cross-validation only; PRD states `skip_plantnet: false` as default but it's a configurable parameter
- In high-volume periods (5+ missions/day), distribute calls across hours or upgrade to PlantNet Pro (€0.005/identification)

**If OpenAI API costs need reducing:**
- Reduce `vision_sample_pct` from 0.3 to 0.1 (sample 10% of canopies)
- Use low-detail mode for initial health triage, only high-detail on flagged canopies
- gpt-4o high-detail: ~765 tokens per 1024x1024 crop = ~$0.002/image at $2.50/1M input tokens
- At 200 canopies, 30% sample = 60 images = ~$0.12 per mission in Vision API calls

---

## Version Compatibility Matrix

| Package | Version | Compatible With | Notes |
|---------|---------|-----------------|-------|
| deepforest==2.0.0 | Python >=3.10, <3.13 | Use Python 3.12.10 (available via `py -3.12`) | Does NOT run on system Python 3.14 |
| torch==2.9.1+cu128 | torchvision==0.24.1 | RTX 5070 sm_120 confirmed working | Must install before deepforest to get CUDA build |
| rasterio==1.4.4 | GDAL 3.9.x (bundled) | numpy>=1.24, Python 3.10-3.14 | Bundled GDAL; do not install GDAL system-wide |
| geopandas==1.1.2 | shapely>=2.0, pyproj>=3.3 | Python>=3.10 | pip install works clean on Windows; no Fiona needed (uses pyogrio) |
| reportlab==4.4.10 | Python 3.9-3.14 | matplotlib, Pillow | pip install; no system deps |
| folium==0.20.0 | Python 3.x | branca, Jinja2, numpy, requests | All pure Python; already have requests in base env |
| matplotlib>=3.9.0 | numpy>=1.21 | Python>=3.9 | DeepForest sub-dep; will be installed automatically |
| openai>=1.0.0 | Python>=3.8 | Any | Modern v1 client with async support |

---

## requirements-path-e.txt (New File)

Create `C:\Users\redle\drone-pipeline\requirements-path-e.txt` (separate from the main `requirements.txt`):

```text
# Path E — Vegetation Analysis Pipeline
# Install in Python 3.12 venv ONLY (.venv-path-e)
# PyTorch must be installed FIRST via: pip install torch==2.9.1 torchvision==0.24.1 torchaudio==2.9.1 --index-url https://download.pytorch.org/whl/cu128
# Then: pip install -r requirements-path-e.txt

deepforest==2.0.0
folium==0.20.0
reportlab==4.4.10
matplotlib>=3.9.0
openai>=1.0.0

# Note: rasterio, geopandas, shapely, pyproj, opencv-python-headless, numpy
# are installed automatically as DeepForest sub-dependencies.
# Do not pin them separately to avoid version conflicts.
```

---

## Sources

- [PyTorch 2.7 Release Blog](https://pytorch.org/blog/pytorch-2-7/) — CUDA 12.8 wheels confirmed, Blackwell support introduced (April 2025)
- [PyTorch Forums: sm_120 support timeline](https://discuss.pytorch.org/t/when-will-sm120-support-be-available/223621) — Stable 2.9.0 + cu128 confirmed working on RTX 50 series (HIGH confidence)
- [PyTorch sm_120 GitHub Issue #164342](https://github.com/pytorch/pytorch/issues/164342) — Official tracking issue for Blackwell support
- [deepforest PyPI](https://pypi.org/project/deepforest/) — v2.0.0 released November 4, 2025; Python >=3.10,<3.13; Windows wheels available
- [DeepForest Installation Docs](https://deepforest.readthedocs.io/en/stable/getting_started/install.html) — pip install deepforest; strongly recommends virtualenv
- [DeepForest pyproject.toml](https://github.com/weecology/DeepForest/blob/main/pyproject.toml) — torch>2.2.0, torchvision>0.17.0, pytorch-lightning>2.6.0,<3.0.0 (HIGH confidence)
- [rasterio PyPI](https://pypi.org/project/rasterio/) — v1.4.4 stable, Python>=3.10, Windows wheels bundled with GDAL 3.9.x
- [rasterio 1.5.0 release announcement](https://rasterio.readthedocs.io/en/latest/installation.html) — Python>=3.12, numpy>=2 requirement (confirms need to stay on 1.4.4)
- [GeoPandas PyPI](https://pypi.org/project/geopandas/) — v1.1.2 released December 22, 2025; shapely>=2.0 required
- [Folium PyPI](https://pypi.org/project/folium/) — v0.20.0 latest stable
- [ReportLab PyPI](https://pypi.org/project/reportlab/) — v4.4.10 released February 12, 2026
- [PlantNet API Pricing](https://my.plantnet.org/pricing) — Free tier: 500 identifications/day; Pro: €0.005/identification (HIGH confidence, fetched directly)
- [PlantNet API Endpoint](https://my.plantnet.org/doc/getting-started/introduction) — `https://my-api.plantnet.org/v2/identify/{project}`; API key as query param
- [GPT-4o Pricing](https://pricepertoken.com/pricing-page/model/openai-gpt-4o) — $2.50/1M input, $10.00/1M output tokens (verified February 24, 2026)
- [matplotlib stable docs](https://matplotlib.org/stable/install/index.html) — v3.10.8 latest stable

---

*Stack research for: Path E Vegetation Analysis — drone-pipeline v2.0*
*Researched: 2026-02-24*
*Scope: NEW additions only — existing stack (Python, pytest, Supabase, Drive, Pillow, etc.) not re-researched*
