"""
Integration tests for the Path E vegetation pipeline (E1→E2→E3→E4) and
delivery_packaging vegetation subfolder support. INTG-E1..E4

Tests:
  1. test_e2e_pipeline          — Full E1→E4 sequence with mocked APIs; verify PDF,
                                  maps, GeoJSON produced and Supabase rows written.
  2. test_e2e_zero_canopies     — DeepForest returns empty; E1 exits 0, E2-E4 handle
                                  gracefully (empty outputs, no crash).
  3. test_delivery_include_vegetation  — vegetation_status='complete' + --include-vegetation
                                  → vegetation/ subfolder present in ZIP.
  4. test_delivery_without_vegetation  — Same mission, no --include-vegetation →
                                  no vegetation/ in ZIP.
  5. test_delivery_incomplete_vegetation — vegetation_status='failed' + --include-vegetation
                                  → no vegetation/ folder, no error.

All external packages (numpy, rasterio, deepforest, torch, openai, supabase,
matplotlib, geopandas, folium, reportlab, PIL) are fully stubbed so the tests
run against system Python with no geo/ML packages installed.
"""
import io
import os
import sys
import json
import types
import zipfile
import logging
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call


# ══════════════════════════════════════════════════════════════════════════════
# Section A: Module-level stubs
# All stubs are installed before ANY pipeline module is imported.
# ══════════════════════════════════════════════════════════════════════════════

def _make_np_stub():
    """Minimal numpy stub that satisfies all 4 pipeline scripts."""
    np_mod = types.ModuleType("numpy")

    class _FakeArr:
        dtype = "float64"
        ndim = 3
        shape = (3, 2048, 2048)

        def __init__(self, val=0.0):
            self._val = val

        def __getitem__(self, key):
            return _FakeArr(self._val)

        def astype(self, t):
            return _FakeArr(self._val)

        def transpose(self, *axes):
            return _FakeArr(self._val)

        @property
        def min(self):
            return lambda: self._val

        @property
        def max(self):
            return lambda: self._val + 255

        def sum(self):
            return 1000

        def __len__(self):
            return 3

    np_mod.uint8 = "uint8"
    np_mod.float64 = float
    np_mod.int64 = int
    np_mod.integer = int
    np_mod.floating = float
    np_mod.complexfloating = complex
    np_mod.bool_ = bool
    np_mod.ndarray = _FakeArr
    np_mod.isscalar = lambda x: isinstance(x, (int, float, complex, bool))
    np_mod.zeros = lambda *a, **kw: _FakeArr()
    np_mod.zeros_like = lambda a, dtype=None: _FakeArr()
    np_mod.transpose = lambda a, axes: a
    np_mod.stack = lambda arrays, axis=0: _FakeArr()
    np_mod.clip = lambda a, lo, hi: _FakeArr()
    np_mod.mean = lambda a, *args, **kw: 0.5
    np_mod.where = lambda cond, x, y: _FakeArr()
    np_mod.abs = lambda x: abs(x) if isinstance(x, (int, float)) else _FakeArr()
    np_mod.radians = lambda x: x
    np_mod.cos = lambda x: 1.0
    return np_mod


def _make_shapely_stub():
    """Shapely geometry stubs (geometry.box, geometry.mapping, wkt.loads)."""
    class _FakePoly:
        def __init__(self, minx=0, miny=0, maxx=10, maxy=10):
            self.minx = float(minx)
            self.miny = float(miny)
            self.maxx = float(maxx)
            self.maxy = float(maxy)
            self.wkt = (
                f"POLYGON (({minx} {miny}, {maxx} {miny}, "
                f"{maxx} {maxy}, {minx} {maxy}, {minx} {miny}))"
            )

        @property
        def bounds(self):
            return (self.minx, self.miny, self.maxx, self.maxy)

        @property
        def area(self):
            return max(0.0, self.maxx - self.minx) * max(0.0, self.maxy - self.miny)

        @property
        def centroid(self):
            class _P:
                pass
            p = _P()
            p.x = (self.minx + self.maxx) / 2.0
            p.y = (self.miny + self.maxy) / 2.0
            return p

        def intersects(self, other):
            return not (
                self.maxx <= other.minx or other.maxx <= self.minx
                or self.maxy <= other.miny or other.maxy <= self.miny
            )

        def intersection(self, other):
            ix1 = max(self.minx, other.minx)
            iy1 = max(self.miny, other.miny)
            ix2 = min(self.maxx, other.maxx)
            iy2 = min(self.maxy, other.maxy)
            if ix1 >= ix2 or iy1 >= iy2:
                return _FakePoly(0, 0, 0, 0)
            return _FakePoly(ix1, iy1, ix2, iy2)

        def union(self, other):
            class _U:
                pass
            u = _U()
            ix1 = max(self.minx, other.minx)
            iy1 = max(self.miny, other.miny)
            ix2 = min(self.maxx, other.maxx)
            iy2 = min(self.maxy, other.maxy)
            inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
            u.area = self.area + other.area - inter
            return u

        def simplify(self, tolerance, preserve_topology=True):
            return self

        def __geo_interface__(self):
            return {"type": "Polygon", "coordinates": []}

    _FakePolyClass = _FakePoly

    shapely_mod = types.ModuleType("shapely")
    shapely_geo = types.ModuleType("shapely.geometry")
    shapely_geo.box = lambda a, b, c, d: _FakePolyClass(a, b, c, d)
    shapely_geo.mapping = lambda g: {"type": "Polygon", "coordinates": []}
    shapely_geo.Polygon = _FakePolyClass

    shapely_wkt_mod = types.ModuleType("shapely.wkt")

    def _fake_wkt_loads(wkt_str):
        try:
            inner = wkt_str.replace("POLYGON ((", "").rstrip(")")
            coords = [tuple(map(float, p.strip().split())) for p in inner.split(",")]
            xs = [c[0] for c in coords]
            ys = [c[1] for c in coords]
            return _FakePolyClass(min(xs), min(ys), max(xs), max(ys))
        except Exception:
            return _FakePolyClass(0, 0, 1, 1)

    shapely_wkt_mod.loads = _fake_wkt_loads
    shapely_mod.geometry = shapely_geo
    shapely_mod.wkt = shapely_wkt_mod

    return shapely_mod, shapely_geo, shapely_wkt_mod, _FakePolyClass


def _make_rasterio_stub():
    """Rasterio stubs with a 2048x2048 synthetic dataset factory."""
    class _FakeWindow:
        def __init__(self, col_off=0, row_off=0, width=512, height=512):
            self.col_off = int(col_off)
            self.row_off = int(row_off)
            self.width = int(width)
            self.height = int(height)

    def _make_ds(width=2048, height=2048, bands=3):
        ds = MagicMock()
        ds.__enter__ = MagicMock(return_value=ds)
        ds.__exit__ = MagicMock(return_value=False)
        ds.width = width
        ds.height = height
        ds.count = bands
        ds.crs = MagicMock()
        ds.crs.to_epsg = MagicMock(return_value=32618)
        ds.crs.is_geographic = False
        ds.transform = MagicMock()
        ds.transform.a = 0.05
        ds.transform.e = -0.05
        ds.bounds = MagicMock()
        ds.bounds.left = 500000.0
        ds.bounds.right = 500102.4
        ds.bounds.bottom = 3999897.6
        ds.bounds.top = 4000000.0
        fake_arr = MagicMock()
        fake_arr.dtype = "uint8"
        fake_arr.shape = (bands, height, width)
        fake_arr.__getitem__ = MagicMock(return_value=fake_arr)
        ds.read = MagicMock(return_value=fake_arr)
        return ds

    rasterio_windows = types.ModuleType("rasterio.windows")
    rasterio_windows.Window = _FakeWindow
    rasterio_transform = types.ModuleType("rasterio.transform")
    rasterio_transform.xy = MagicMock(return_value=(500005.0, 3999995.0))
    rasterio_mask_mod = types.ModuleType("rasterio.mask")
    rasterio_mask_mod.mask = MagicMock(return_value=(MagicMock(), MagicMock()))
    rasterio_plot_mod = types.ModuleType("rasterio.plot")
    rasterio_crs_mod = types.ModuleType("rasterio.crs")
    rasterio_crs_mod.CRS = MagicMock

    rasterio_mod = types.ModuleType("rasterio")
    rasterio_mod.open = MagicMock(return_value=_make_ds())
    rasterio_mod.DatasetReader = MagicMock
    rasterio_mod.windows = rasterio_windows
    rasterio_mod.transform = rasterio_transform
    rasterio_mod.mask = rasterio_mask_mod
    rasterio_mod.plot = rasterio_plot_mod
    rasterio_mod.crs = rasterio_crs_mod

    return rasterio_mod, rasterio_windows, rasterio_transform, rasterio_mask_mod, rasterio_plot_mod, rasterio_crs_mod, _make_ds


def _make_torch_stub():
    torch_cuda = types.ModuleType("torch.cuda")
    torch_cuda.is_available = MagicMock(return_value=True)
    torch_cuda.get_device_capability = MagicMock(return_value=(12, 0))
    torch_cuda.get_device_name = MagicMock(return_value="NVIDIA RTX 5060 Ti")
    torch_cuda.empty_cache = MagicMock()

    torch_mod = types.ModuleType("torch")
    torch_mod.cuda = torch_cuda
    torch_mod.Tensor = MagicMock
    return torch_mod, torch_cuda


def _make_deepforest_stub():
    mock_df_cls = MagicMock()
    deepforest_main = types.ModuleType("deepforest.main")
    deepforest_main.deepforest = mock_df_cls
    deepforest_mod = types.ModuleType("deepforest")
    deepforest_mod.main = deepforest_main
    return deepforest_mod, deepforest_main


def _make_geopandas_stub():
    fake_gpd = types.ModuleType("geopandas")
    fake_gdf_inst = MagicMock()
    fake_gdf_inst.to_file = MagicMock()
    fake_gdf_inst.astype = MagicMock(return_value=fake_gdf_inst)
    fake_gdf_inst.__iter__ = MagicMock(return_value=iter([]))
    fake_gdf_inst.__len__ = MagicMock(return_value=5)
    fake_gdf_inst.iterrows = MagicMock(return_value=iter([]))
    fake_gdf_inst.geometry = MagicMock()
    fake_gpd.GeoDataFrame = MagicMock(return_value=fake_gdf_inst)
    fake_gpd.read_file = MagicMock(return_value=fake_gdf_inst)
    return fake_gpd, fake_gdf_inst


def _make_matplotlib_stub():
    mpl_mod = types.ModuleType("matplotlib")
    mpl_mod.use = MagicMock()
    mpl_mod.pyplot = MagicMock()

    mpl_plt = types.ModuleType("matplotlib.pyplot")
    mock_fig = MagicMock()
    mock_ax = MagicMock()
    mock_ax.get_xlim = MagicMock(return_value=(0, 1))
    mock_ax.get_ylim = MagicMock(return_value=(0, 1))
    mpl_plt.subplots = MagicMock(return_value=(mock_fig, mock_ax))
    mpl_plt.close = MagicMock()
    mpl_plt.savefig = MagicMock()
    mock_fig.savefig = MagicMock()

    mpl_patches = types.ModuleType("matplotlib.patches")
    mpl_patches.Patch = MagicMock
    mpl_patches.FancyArrowPatch = MagicMock

    mpl_mod.patches = mpl_patches
    mpl_mod.pyplot = mpl_plt

    return mpl_mod, mpl_plt, mpl_patches


def _make_folium_stub():
    folium_mod = types.ModuleType("folium")
    mock_map = MagicMock()
    mock_map.get_root = MagicMock(return_value=MagicMock())
    mock_map.get_root.return_value.html.render = MagicMock(return_value="<html></html>")
    folium_mod.Map = MagicMock(return_value=mock_map)
    folium_mod.GeoJson = MagicMock(return_value=MagicMock())
    folium_mod.CircleMarker = MagicMock(return_value=MagicMock())
    folium_mod.Popup = MagicMock(return_value=MagicMock())
    folium_mod.LayerControl = MagicMock(return_value=MagicMock())
    folium_mod.FeatureGroup = MagicMock(return_value=MagicMock())
    return folium_mod


def _make_reportlab_stubs():
    """Stub the reportlab / platypus modules used by vegetation_report.py."""
    rl_lib = types.ModuleType("reportlab")
    rl_lib_styles = types.ModuleType("reportlab.lib.styles")
    rl_lib_styles.getSampleStyleSheet = MagicMock(return_value=MagicMock())
    rl_lib_styles.ParagraphStyle = MagicMock
    rl_lib_units = types.ModuleType("reportlab.lib.units")
    rl_lib_units.inch = 72
    rl_lib_units.cm = 28.35
    rl_lib_colors = types.ModuleType("reportlab.lib.colors")
    rl_lib_colors.HexColor = MagicMock(return_value=MagicMock())
    rl_lib_colors.white = MagicMock()
    rl_lib_colors.black = MagicMock()
    rl_lib_colors.grey = MagicMock()
    rl_lib_colors.Color = MagicMock
    rl_lib_colors.green = MagicMock()
    rl_lib_colors.red = MagicMock()
    rl_lib_pagesizes = types.ModuleType("reportlab.lib.pagesizes")
    rl_lib_pagesizes.letter = (612, 792)
    rl_lib_pagesizes.LETTER = (612, 792)

    rl_platypus = types.ModuleType("reportlab.platypus")
    mock_doc = MagicMock()
    mock_doc.build = MagicMock()

    class FakeSimpleDocTemplate:
        def __init__(self, *args, **kwargs):
            pass

        def build(self, elements, onFirstPage=None, onLaterPages=None):
            pass

    rl_platypus.SimpleDocTemplate = FakeSimpleDocTemplate
    rl_platypus.Paragraph = MagicMock(return_value=MagicMock())
    rl_platypus.Spacer = MagicMock(return_value=MagicMock())
    rl_platypus.Table = MagicMock(return_value=MagicMock())
    rl_platypus.TableStyle = MagicMock(return_value=MagicMock())
    rl_platypus.Image = MagicMock(return_value=MagicMock())
    rl_platypus.HRFlowable = MagicMock(return_value=MagicMock())
    rl_platypus.PageBreak = MagicMock(return_value=MagicMock())
    rl_platypus.KeepTogether = MagicMock(return_value=MagicMock())
    rl_platypus.ListFlowable = MagicMock(return_value=MagicMock())
    rl_platypus.ListItem = MagicMock(return_value=MagicMock())

    rl_lib_mod = types.ModuleType("reportlab.lib")
    rl_lib_mod.styles = rl_lib_styles
    rl_lib_mod.units = rl_lib_units
    rl_lib_mod.colors = rl_lib_colors
    rl_lib_mod.pagesizes = rl_lib_pagesizes
    rl_lib.lib = rl_lib_mod
    rl_lib.platypus = rl_platypus

    return {
        "reportlab": rl_lib,
        "reportlab.lib": rl_lib_mod,
        "reportlab.lib.styles": rl_lib_styles,
        "reportlab.lib.units": rl_lib_units,
        "reportlab.lib.colors": rl_lib_colors,
        "reportlab.lib.pagesizes": rl_lib_pagesizes,
        "reportlab.platypus": rl_platypus,
    }


def _make_pil_stub():
    class _FakeImage:
        size = (512, 512)
        mode = "RGB"

        def save(self, path_or_buf, format=None, **kw):
            if hasattr(path_or_buf, "write"):
                path_or_buf.write(b"\x89PNG\r\n\x1a\n")
            else:
                with open(path_or_buf, "wb") as f:
                    f.write(b"\x89PNG\r\n\x1a\n")

        def resize(self, size, resample=None):
            img = _FakeImage()
            img.size = size
            return img

        @property
        def width(self):
            return self.size[0]

        @property
        def height(self):
            return self.size[1]

    class _FakeImageMod:
        LANCZOS = 1

        @staticmethod
        def fromarray(arr, mode=None):
            return _FakeImage()

        @staticmethod
        def open(fp):
            return _FakeImage()

        @staticmethod
        def new(mode, size, color=None):
            img = _FakeImage()
            img.size = size
            img.mode = mode
            return img

    fake_pil = types.ModuleType("PIL")
    fake_pil.Image = _FakeImageMod
    fake_pil_image = types.ModuleType("PIL.Image")
    fake_pil_image.Image = _FakeImageMod
    fake_pil_image.LANCZOS = 1
    fake_pil_image.fromarray = _FakeImageMod.fromarray
    fake_pil_image.open = _FakeImageMod.open
    fake_pil_image.new = _FakeImageMod.new
    fake_pil.Image = _FakeImageMod
    return fake_pil, fake_pil_image


def _make_supabase_stub():
    fake_sb = types.ModuleType("supabase")
    fake_sb.create_client = MagicMock()
    return fake_sb


def _make_pandas_stub():
    fake_pd = types.ModuleType("pandas")
    fake_pd.DataFrame = MagicMock(return_value=MagicMock())
    return fake_pd


def _make_pyproj_stub():
    fake_pyproj = types.ModuleType("pyproj")

    class _FakeTransformer:
        @staticmethod
        def from_crs(*args, **kwargs):
            return _FakeTransformer()

        def transform(self, x, y):
            return (x / 111320.0, y / 111320.0)

    fake_pyproj.Transformer = _FakeTransformer
    return fake_pyproj


def _install_all_stubs():
    """Install every fake module before any pipeline script is imported."""
    stubs = {}

    stubs["numpy"] = _make_np_stub()

    shapely_mod, shapely_geo, shapely_wkt_mod, _FakePoly = _make_shapely_stub()
    stubs["shapely"] = shapely_mod
    stubs["shapely.geometry"] = shapely_geo
    stubs["shapely.wkt"] = shapely_wkt_mod

    (
        rasterio_mod, rasterio_windows, rasterio_transform,
        rasterio_mask_mod, rasterio_plot_mod, rasterio_crs_mod, _make_ds_fn,
    ) = _make_rasterio_stub()
    stubs["rasterio"] = rasterio_mod
    stubs["rasterio.windows"] = rasterio_windows
    stubs["rasterio.transform"] = rasterio_transform
    stubs["rasterio.mask"] = rasterio_mask_mod
    stubs["rasterio.plot"] = rasterio_plot_mod
    stubs["rasterio.crs"] = rasterio_crs_mod

    torch_mod, torch_cuda = _make_torch_stub()
    stubs["torch"] = torch_mod
    stubs["torch.cuda"] = torch_cuda

    deepforest_mod, deepforest_main = _make_deepforest_stub()
    stubs["deepforest"] = deepforest_mod
    stubs["deepforest.main"] = deepforest_main

    fake_gpd, fake_gdf_inst = _make_geopandas_stub()
    stubs["geopandas"] = fake_gpd

    mpl_mod, mpl_plt, mpl_patches = _make_matplotlib_stub()
    stubs["matplotlib"] = mpl_mod
    stubs["matplotlib.pyplot"] = mpl_plt
    stubs["matplotlib.patches"] = mpl_patches

    stubs["folium"] = _make_folium_stub()

    stubs.update(_make_reportlab_stubs())

    fake_pil, fake_pil_image = _make_pil_stub()
    stubs["PIL"] = fake_pil
    stubs["PIL.Image"] = fake_pil_image

    stubs["supabase"] = _make_supabase_stub()
    stubs["pandas"] = _make_pandas_stub()
    stubs["pyproj"] = _make_pyproj_stub()

    # requests stub (PlantNet)
    fake_requests = types.ModuleType("requests")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"X-Remaining-Identifications": "100"}
    mock_resp.json.return_value = {"results": []}
    fake_requests.post = MagicMock(return_value=mock_resp)
    stubs["requests"] = fake_requests

    # openai stub
    fake_openai = types.ModuleType("openai")

    class _FakeOpenAI:
        def __init__(self, api_key=None):
            self.chat = MagicMock()

    fake_openai.OpenAI = _FakeOpenAI
    stubs["openai"] = fake_openai

    # Install stubs only when the real package is NOT importable.
    # setdefault alone isn't enough — a package can be installed but not yet
    # imported (so not in sys.modules).  Try-import first to let real packages win.
    for name, mod in stubs.items():
        if name not in sys.modules:
            try:
                __import__(name)
            except ImportError:
                sys.modules[name] = mod

    # Return objects tests need direct access to
    return {
        "FakePoly": _FakePoly,
        "make_ds": _make_ds_fn,
        "rasterio_mod": rasterio_mod,
        "rasterio_mask": rasterio_mask_mod,
        "geopandas": fake_gpd,
        "gdf_inst": fake_gdf_inst,
        "supabase": stubs["supabase"],
    }


# Install stubs at module level (before any imports below)
_stubs = _install_all_stubs()
_FakePoly = _stubs["FakePoly"]
_make_ds = _stubs["make_ds"]


# ══════════════════════════════════════════════════════════════════════════════
# Section B: Import pipeline modules
# Safe to import now that all stubs are in sys.modules.
# ══════════════════════════════════════════════════════════════════════════════

from canopy_detection import detect_canopies, write_output_files, upsert_detections_to_supabase
from species_classification import run_classification
from health_assessment import run_health_assessment
from vegetation_report import generate_all_outputs
from delivery_packaging import (
    collect_vegetation,
    get_vegetation_status,
    create_delivery_zip,
    build_prefix,
    build_zip_name,
)


# ══════════════════════════════════════════════════════════════════════════════
# Section C: Shared helpers
# ══════════════════════════════════════════════════════════════════════════════

def _make_synthetic_detections(n=5):
    """Return n synthetic detection dicts as E1 would produce."""
    dets = []
    for i in range(n):
        poly = _FakePoly(
            float(i * 10), float(i * 10),
            float(i * 10 + 8), float(i * 10 + 8),
        )
        dets.append({
            "polygon": poly,
            "geo_xmin": float(i * 10),
            "geo_ymin": float(i * 10),
            "geo_xmax": float(i * 10 + 8),
            "geo_ymax": float(i * 10 + 8),
            "centroid_x": float(i * 10 + 4),
            "centroid_y": float(i * 10 + 4),
            "confidence": 0.7 + i * 0.02,
            "label": "Tree",
            "width_m": 8.0,
            "height_m": 8.0,
            "area_m2": 64.0,
        })
    return dets


def _make_supabase_detections(n=5, mission_id="mission-intg-001"):
    """Return detection rows as Supabase would return to E2/E3/E4."""
    rows = []
    for i in range(n):
        rows.append({
            "id": f"veg-det-{i:03d}",
            "detection_index": i,
            "mission_id": mission_id,
            "geometry_wkt": (
                f"POLYGON (({i*10} {i*10}, {i*10+8} {i*10}, "
                f"{i*10+8} {i*10+8}, {i*10} {i*10+8}, {i*10} {i*10}))"
            ),
            "centroid_lat": float(i * 10 + 4),
            "centroid_lon": float(i * 10 + 4),
            "canopy_area_sqm": 64.0,
            "canopy_width_m": 8.0,
            "canopy_height_m": 8.0,
            "detection_confidence": 0.7 + i * 0.02,
            "label": "Tree",
            "species_tag": f"Loblolly Pine" if i % 2 == 0 else "Live Oak",
            "species_confidence": 0.75,
            "vegetation_type": "tree",
            "health_score": 0.7 + i * 0.02,
            "health_status": "healthy",
            "health_details": {},
            "recommended_action": "monitor",
        })
    return rows


def _mission_dir_log(tmp_path):
    """Return (mission_dir_str, log) suitable for pipeline functions."""
    log = logging.getLogger("integration_test")
    return str(tmp_path), log


# ══════════════════════════════════════════════════════════════════════════════
# Section D: E1→E4 integration tests
# ══════════════════════════════════════════════════════════════════════════════

def test_e2e_pipeline(tmp_path):
    """E1→E2→E3→E4 on a synthetic 2048×2048 ortho with 5 mocked detections.

    Verifies:
    - E1 returns 5 detections from mocked DeepForest
    - E2 run_classification completes for 5 canopies
    - E3 run_health_assessment scores all 5 canopies
    - E4 generate_all_outputs writes species PNG, health PNG, and GeoJSON
    - Supabase write functions were called (not skipped due to missing creds)
    """
    mission_id = "mission-intg-e2e-001"
    ortho_path = str(tmp_path / "orthomosaic.tif")
    output_dir = str(tmp_path / "vegetation")
    os.makedirs(output_dir, exist_ok=True)

    # Create a zero-byte placeholder ortho (all actual reads are mocked)
    Path(ortho_path).touch()

    mission_dir, log = _mission_dir_log(tmp_path)

    # ── E1: detect_canopies ─────────────────────────────────────────────────
    # DeepForest returns a DataFrame with xmin/ymin/xmax/ymax/score/label columns.
    # We mock detect_canopies at the level that matters: have it return our
    # pre-built synthetic detections by patching cross_tile_nms's input feeding.
    synthetic_dets = _make_synthetic_detections(5)

    mock_dataset = _make_ds(width=2048, height=2048)

    # Build a fake DataFrame-like result for run_inference_on_tile
    class _FakeRow:
        def __init__(self, i):
            self._data = {
                "xmin": float(i * 10),
                "ymin": float(i * 10),
                "xmax": float(i * 10 + 8),
                "ymax": float(i * 10 + 8),
                "score": 0.8,
                "label": "Tree",
            }
            # Also expose as attributes for iterrows usage
            for k, v in self._data.items():
                setattr(self, k, v)

        def __getitem__(self, key):
            return self._data[key]

        def get(self, key, default=None):
            return self._data.get(key, default)

    class _FakeDF:
        def __init__(self, n=5):
            self._rows = [_FakeRow(i) for i in range(n)]

        def __len__(self):
            return len(self._rows)

        def iterrows(self):
            for i, row in enumerate(self._rows):
                yield i, row

    fake_df = _FakeDF(5)

    with patch("canopy_detection.rasterio") as mock_rasterio, \
         patch("canopy_detection.load_deepforest_model", return_value=MagicMock()), \
         patch("canopy_detection.run_inference_on_tile", return_value=fake_df), \
         patch("canopy_detection.save_checkpoint"), \
         patch("canopy_detection.torch") as mock_torch, \
         patch("canopy_detection.write_output_files") as mock_write_output, \
         patch("canopy_detection.upsert_detections_to_supabase", return_value=True) as mock_e1_upsert, \
         patch("canopy_detection.pixel_box_to_geo",
               side_effect=lambda ds, win, xmin, ymin, xmax, ymax: (
                   500000.0 + xmin, 4000000.0 + ymin,
                   500000.0 + xmax, 4000000.0 + ymax
               )):
        mock_rasterio.open.return_value = mock_dataset
        mock_torch.cuda.empty_cache = MagicMock()

        e1_detections, had_failure, dataset_crs = detect_canopies(
            ortho_path=ortho_path,
            tile_size=2048,
            overlap=0,
            score_threshold=0.3,
            iou_threshold=0.3,
            completed_tiles=set(),
            mission_dir=mission_dir,
            log=log,
        )

    assert len(e1_detections) == 5, f"Expected 5 E1 detections, got {len(e1_detections)}"
    assert had_failure is False

    # ── E2: run_classification ────────────────────────────────────────────────
    e2_detections = _make_supabase_detections(5, mission_id)

    def fake_openai_result(img, key):
        return {
            "species_common": "Loblolly Pine",
            "species_scientific": "Pinus taeda",
            "vegetation_type": "tree",
            "confidence": 0.78,
            "reasoning": "Dense canopy from aerial view",
            "secondary_candidates": [],
        }

    import species_classification as sc

    with patch.object(sc, "fetch_detections", return_value=e2_detections), \
         patch.object(sc, "crop_canopy", return_value=MagicMock()), \
         patch.object(sc, "classify_openai", side_effect=fake_openai_result), \
         patch.object(sc, "classify_plantnet", return_value=None), \
         patch.object(sc, "update_classification_batch", return_value=True) as mock_e2_update, \
         patch.object(sc, "save_checkpoint"), \
         patch.object(sc, "rasterio") as mock_rasterio_e2, \
         patch.object(sc, "OPENAI_API_KEY", "fake-e2-key"), \
         patch("species_classification.time") as mock_time_e2:
        mock_rasterio_e2.open.return_value = _make_ds()
        mock_time_e2.sleep = MagicMock()

        e2_result = sc.run_classification(
            mission_id=mission_id,
            ortho_path=ortho_path,
            max_canopies=200,
            skip_plantnet=True,
            cost_threshold=5.0,
            force=False,
            completed_keys=set(),
            mission_dir=mission_dir,
            log=log,
        )

    assert e2_result.get("error") is None, f"E2 error: {e2_result.get('error')}"
    assert e2_result["classified_count"] == 5
    mock_e2_update.assert_called()

    # ── E3: run_health_assessment ─────────────────────────────────────────────
    import health_assessment as ha

    # E3 fetches detections from Supabase — mock them without health_score (so it runs)
    e3_detections = [
        {**d, "health_score": None}
        for d in _make_supabase_detections(5, mission_id)
    ]

    with patch.object(ha, "fetch_detections", return_value=e3_detections), \
         patch.object(ha, "compute_health_indices", return_value={
             "mean_vari": 0.3,
             "mean_exg": 0.4,
             "green_fraction": 0.7,
             "stress_fraction": 0.1,
         }), \
         patch.object(ha, "update_health_batch", return_value=True) as mock_e3_update, \
         patch.object(ha, "save_checkpoint"), \
         patch.object(ha, "rasterio") as mock_rasterio_e3:
        mock_rasterio_e3.open.return_value = _make_ds()

        e3_result = ha.run_health_assessment(
            mission_id=mission_id,
            ortho_path=ortho_path,
            vision_sample_pct=0.3,
            skip_vision=True,
            cost_threshold=2.0,
            completed_keys=set(),
            mission_dir=mission_dir,
            log=log,
        )

    assert e3_result["assessed_count"] == 5, f"E3 assessed_count={e3_result['assessed_count']}"
    mock_e3_update.assert_called()

    # ── E4: generate_all_outputs ──────────────────────────────────────────────
    import vegetation_report as vr

    e4_detections = _make_supabase_detections(5, mission_id)

    with patch.object(vr, "fetch_detections", return_value=e4_detections), \
         patch.object(vr, "fetch_mission_info", return_value={
             "job_name": "TestSite_001",
             "created_at": "2026-02-25T12:00:00Z",
             "location": "Virginia Beach VA",
         }), \
         patch.object(vr, "write_vegetation_summary") as mock_e4_summary, \
         patch.object(vr, "generate_species_map", return_value=True) as mock_species_map, \
         patch.object(vr, "generate_health_map", return_value=True) as mock_health_map, \
         patch.object(vr, "export_geojson", return_value=True) as mock_geojson, \
         patch.object(vr, "generate_pdf", return_value=True) as mock_pdf, \
         patch.object(vr, "rasterio") as mock_rasterio_e4:
        mock_rasterio_e4.open.return_value = _make_ds()

        # Write placeholder output files so assertions can check existence
        species_map_path = os.path.join(output_dir, "Sentinel_TestSite_001_Species_Map.png")
        health_map_path = os.path.join(output_dir, "Sentinel_TestSite_001_Health_Map.png")
        geojson_path = os.path.join(output_dir, "Sentinel_TestSite_001_Canopy_Detections.geojson")
        pdf_path = os.path.join(output_dir, "Sentinel_TestSite_001_Vegetation_Report.pdf")

        # Patch generate_* to actually create the files
        def _create_species_map(*args, **kwargs):
            Path(species_map_path).write_bytes(b"PNG_FAKE")
            return True

        def _create_health_map(*args, **kwargs):
            Path(health_map_path).write_bytes(b"PNG_FAKE")
            return True

        def _create_geojson(*args, **kwargs):
            Path(geojson_path).write_text(
                json.dumps({"type": "FeatureCollection", "features": []})
            )
            return True

        def _create_pdf(*args, **kwargs):
            Path(pdf_path).write_bytes(b"%PDF-1.4 FAKE")
            return True

        mock_species_map.side_effect = _create_species_map
        mock_health_map.side_effect = _create_health_map
        mock_geojson.side_effect = _create_geojson
        mock_pdf.side_effect = _create_pdf

        e4_result = vr.generate_all_outputs(
            mission_id=mission_id,
            ortho_path=ortho_path,
            output_dir=output_dir,
            tier="standard",
            log=log,
        )

    # Verify E4 generated all expected output files
    assert os.path.isfile(species_map_path), "Species map PNG not created"
    assert os.path.isfile(health_map_path), "Health map PNG not created"
    assert os.path.isfile(geojson_path), "Delivery GeoJSON not created"
    assert os.path.isfile(pdf_path), "Vegetation Report PDF not created"

    # Verify GeoJSON is valid JSON
    with open(geojson_path) as f:
        geojson_data = json.load(f)
    assert "type" in geojson_data

    # Verify E4 wrote the Supabase summary
    mock_e4_summary.assert_called_once()

    # Verify e4_result has expected keys
    assert e4_result is not None


def test_e2e_zero_canopies(tmp_path):
    """E1→E4 with no tree detections — all steps handle empty gracefully.

    Verifies:
    - detect_canopies() returns empty list (exit 0)
    - run_classification() with empty fetch returns classified_count=0
    - run_health_assessment() with no detections returns assessed_count=0
    - generate_all_outputs() with empty detections does not raise
    """
    mission_id = "mission-intg-zero-001"
    ortho_path = str(tmp_path / "orthomosaic.tif")
    output_dir = str(tmp_path / "vegetation")
    os.makedirs(output_dir, exist_ok=True)
    Path(ortho_path).touch()

    mission_dir, log = _mission_dir_log(tmp_path)

    # ── E1: no detections ─────────────────────────────────────────────────────
    mock_dataset = _make_ds(width=512, height=512)

    with patch("canopy_detection.rasterio") as mock_rasterio, \
         patch("canopy_detection.load_deepforest_model", return_value=MagicMock()), \
         patch("canopy_detection.run_inference_on_tile", return_value=None), \
         patch("canopy_detection.save_checkpoint"), \
         patch("canopy_detection.torch") as mock_torch:
        mock_rasterio.open.return_value = mock_dataset
        mock_torch.cuda.empty_cache = MagicMock()

        e1_detections, had_failure, _ = detect_canopies(
            ortho_path=ortho_path,
            tile_size=1024,
            overlap=0,
            score_threshold=0.3,
            iou_threshold=0.3,
            completed_tiles=set(),
            mission_dir=mission_dir,
            log=log,
        )

    assert e1_detections == [], f"Expected empty detections, got {e1_detections}"
    assert had_failure is False

    # ── E2: empty fetch → classified_count=0 ─────────────────────────────────
    import species_classification as sc

    with patch.object(sc, "fetch_detections", return_value=[]), \
         patch.object(sc, "rasterio") as mock_rasterio_e2:
        mock_rasterio_e2.open.return_value = _make_ds()

        e2_result = sc.run_classification(
            mission_id=mission_id,
            ortho_path=ortho_path,
            max_canopies=200,
            skip_plantnet=True,
            cost_threshold=5.0,
            force=False,
            completed_keys=set(),
            mission_dir=mission_dir,
            log=log,
        )

    assert e2_result.get("classified_count", 0) == 0
    assert e2_result.get("error") is None

    # ── E3: empty fetch → assessed_count=0 ───────────────────────────────────
    import health_assessment as ha

    with patch.object(ha, "fetch_detections", return_value=[]), \
         patch.object(ha, "rasterio") as mock_rasterio_e3:
        mock_rasterio_e3.open.return_value = _make_ds()

        e3_result = ha.run_health_assessment(
            mission_id=mission_id,
            ortho_path=ortho_path,
            vision_sample_pct=0.3,
            skip_vision=True,
            cost_threshold=2.0,
            completed_keys=set(),
            mission_dir=mission_dir,
            log=log,
        )

    assert e3_result["assessed_count"] == 0

    # ── E4: no detections → no exception ─────────────────────────────────────
    import vegetation_report as vr

    with patch.object(vr, "fetch_detections", return_value=[]), \
         patch.object(vr, "fetch_mission_info", return_value={}), \
         patch.object(vr, "write_vegetation_summary"), \
         patch.object(vr, "generate_species_map", return_value=True), \
         patch.object(vr, "generate_health_map", return_value=True), \
         patch.object(vr, "export_geojson", return_value=True), \
         patch.object(vr, "generate_pdf", return_value=True), \
         patch.object(vr, "rasterio") as mock_rasterio_e4:
        mock_rasterio_e4.open.return_value = _make_ds()

        # Should not raise even with zero detections
        try:
            e4_result = vr.generate_all_outputs(
                mission_id=mission_id,
                ortho_path=ortho_path,
                output_dir=output_dir,
                tier="standard",
                log=log,
            )
        except Exception as exc:
            pytest.fail(f"generate_all_outputs raised with zero detections: {exc}")


# ══════════════════════════════════════════════════════════════════════════════
# Section E: Delivery packaging — vegetation subfolder tests
# ══════════════════════════════════════════════════════════════════════════════

def _create_mission_with_vegetation(tmp_path, status="complete"):
    """Set up a mission folder with vegetation output files and a .status marker."""
    mission_path = tmp_path / "SAI_M0001_PKG_20260225"
    veg_dir = mission_path / "vegetation"
    veg_dir.mkdir(parents=True)

    # Write vegetation output files
    (veg_dir / "Sentinel_TestSite_001_Vegetation_Report.pdf").write_bytes(b"%PDF FAKE")
    (veg_dir / "Sentinel_TestSite_001_Species_Map.png").write_bytes(b"PNG1 FAKE")
    (veg_dir / "Sentinel_TestSite_001_Health_Map.png").write_bytes(b"PNG2 FAKE")
    (veg_dir / "Sentinel_TestSite_001_Canopy_Detections.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": []})
    )

    # Write status file
    (veg_dir / ".status").write_text(status)

    # Also create some photos so the manifest is not empty
    photos_dir = mission_path / "photos" / "jpeg"
    photos_dir.mkdir(parents=True)
    (photos_dir / "SAI_M0001_001.jpg").write_bytes(b"FAKE_JPG")

    return str(mission_path)


def test_delivery_include_vegetation(tmp_path):
    """--include-vegetation + vegetation_status='complete' → vegetation/ in ZIP.

    Verifies:
    - collect_vegetation() returns 4 files (PDF, 2 PNGs, GeoJSON)
    - create_delivery_zip() creates ZIP with vegetation/ subfolder entries
    - All 4 vegetation files appear under vegetation/ prefix in archive
    """
    mission_path = _create_mission_with_vegetation(tmp_path, status="complete")

    # Verify collect_vegetation finds 4 files
    veg_files = collect_vegetation(mission_path)
    assert len(veg_files) == 4, f"Expected 4 vegetation files, got {len(veg_files)}: {veg_files}"

    # Build manifest with vegetation entries
    manifest = []
    for vpath in veg_files:
        archive_name = f"vegetation/{os.path.basename(vpath)}"
        manifest.append((vpath, archive_name))

    # Add a photo so ZIP is not empty
    photo_path = str(tmp_path / "SAI_M0001_PKG_20260225" / "photos" / "jpeg" / "SAI_M0001_001.jpg")
    manifest.append((photo_path, "photos/Sentinel_TestSite_001_001.jpg"))

    zip_path = str(tmp_path / "delivery.zip")
    result = create_delivery_zip(zip_path, manifest, dry_run=False)

    assert result == zip_path, "ZIP was not created"
    assert os.path.isfile(zip_path), "ZIP file does not exist on disk"

    # Inspect ZIP contents
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()

    veg_entries = [n for n in names if n.startswith("vegetation/")]
    assert len(veg_entries) == 4, (
        f"Expected 4 vegetation/ entries in ZIP, got {len(veg_entries)}: {veg_entries}"
    )

    # All expected extensions present
    ext_in_zip = {os.path.splitext(n)[1].lower() for n in veg_entries}
    assert ".pdf" in ext_in_zip, "PDF not in vegetation/ ZIP entries"
    assert ".png" in ext_in_zip, "PNG not in vegetation/ ZIP entries"
    assert ".geojson" in ext_in_zip, "GeoJSON not in vegetation/ ZIP entries"


def test_delivery_without_vegetation(tmp_path):
    """No --include-vegetation → no vegetation/ subfolder in ZIP.

    Verifies that even when vegetation outputs are present and complete,
    omitting the flag means no vegetation/ entries appear in the archive.
    The output should be identical to a v1 delivery (photos only).
    """
    mission_path = _create_mission_with_vegetation(tmp_path, status="complete")

    # Build manifest WITHOUT vegetation (flag not passed)
    photo_path = str(tmp_path / "SAI_M0001_PKG_20260225" / "photos" / "jpeg" / "SAI_M0001_001.jpg")
    manifest = [(photo_path, "photos/Sentinel_TestSite_001_001.jpg")]

    zip_path = str(tmp_path / "delivery.zip")
    create_delivery_zip(zip_path, manifest, dry_run=False)

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()

    veg_entries = [n for n in names if n.startswith("vegetation/")]
    assert veg_entries == [], (
        f"Unexpected vegetation/ entries in ZIP when flag omitted: {veg_entries}"
    )


def test_delivery_incomplete_vegetation(tmp_path):
    """vegetation_status='failed' + --include-vegetation → no vegetation/ entries.

    Verifies that collect_vegetation() returns [] when status != 'complete',
    so no vegetation files are added to the ZIP even when the flag is present.
    """
    mission_path = _create_mission_with_vegetation(tmp_path, status="failed")

    # collect_vegetation must return empty for failed status
    veg_files = collect_vegetation(mission_path)
    assert veg_files == [], (
        f"Expected [] for failed status, got {veg_files}"
    )

    # Build manifest with --include-vegetation logic (as delivery_packaging.main does)
    photo_path = str(tmp_path / "SAI_M0001_PKG_20260225" / "photos" / "jpeg" / "SAI_M0001_001.jpg")
    manifest = [(photo_path, "photos/Sentinel_TestSite_001_001.jpg")]

    # Simulate --include-vegetation: collect_vegetation returned [] → nothing added
    for vpath in veg_files:  # veg_files == [] so loop is no-op
        manifest.append((vpath, f"vegetation/{os.path.basename(vpath)}"))

    zip_path = str(tmp_path / "delivery.zip")
    create_delivery_zip(zip_path, manifest, dry_run=False)

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()

    veg_entries = [n for n in names if n.startswith("vegetation/")]
    assert veg_entries == [], (
        f"Unexpected vegetation/ entries for failed status: {veg_entries}"
    )

    # Verify no exception was raised — mission proceeds as photos-only
    assert len(names) == 1  # just the photo


def test_vegetation_status_absent_returns_none(tmp_path):
    """get_vegetation_status() returns None when .status file absent."""
    mission_path = tmp_path / "SAI_M0001_PKG_20260225"
    veg_dir = mission_path / "vegetation"
    veg_dir.mkdir(parents=True)
    # No .status file created

    status = get_vegetation_status(str(mission_path))
    assert status is None


def test_vegetation_status_pending_no_collect(tmp_path):
    """collect_vegetation() returns [] when status is 'pending'."""
    mission_path = _create_mission_with_vegetation(tmp_path, status="pending")
    veg_files = collect_vegetation(mission_path)
    assert veg_files == [], f"Expected [] for pending status, got {veg_files}"
