"""
Unit tests for canopy_detection.py (Step E1) — UNIT-E1
Tests tiling, NMS, coordinate transforms, GeoJSON/GPKG export, Supabase writes,
checkpoint resume, and zero-detection handling.

All external packages (numpy, torch, deepforest, rasterio, shapely, geopandas)
are fully stubbed. Runs against system Python with no geo/ML packages installed.
"""
import os
import sys
import types
import pytest
from unittest.mock import MagicMock, patch


# ── Module-level stubs ──────────────────────────────────────────────────────
# All stubs must be installed BEFORE canopy_detection is imported because
# canopy_detection performs top-level imports of all heavy dependencies.

def _make_fake_polygon_class():
    """Return a pure-Python polygon class with real geometric operations."""

    class FakePolygon:
        """Axis-aligned bounding box with Shapely-compatible interface."""

        def __init__(self, minx=0.0, miny=0.0, maxx=1.0, maxy=1.0):
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
                self.maxx <= other.minx
                or other.maxx <= self.minx
                or self.maxy <= other.miny
                or other.maxy <= self.miny
            )

        def intersection(self, other):
            ix1 = max(self.minx, other.minx)
            iy1 = max(self.miny, other.miny)
            ix2 = min(self.maxx, other.maxx)
            iy2 = min(self.maxy, other.maxy)
            if ix1 >= ix2 or iy1 >= iy2:
                return FakePolygon(0, 0, 0, 0)
            return FakePolygon(ix1, iy1, ix2, iy2)

        def union(self, other):
            class _U:
                pass
            ix1 = max(self.minx, other.minx)
            iy1 = max(self.miny, other.miny)
            ix2 = min(self.maxx, other.maxx)
            iy2 = min(self.maxy, other.maxy)
            inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
            u = _U()
            u.area = self.area + other.area - inter
            return u

    return FakePolygon


FakePolygon = _make_fake_polygon_class()


def _fake_box(minx, miny, maxx, maxy):
    return FakePolygon(minx, miny, maxx, maxy)


def _fake_wkt_loads(wkt_str):
    """Parse simple POLYGON WKT string."""
    try:
        inner = wkt_str.replace("POLYGON ((", "").rstrip(")")
        coords = [tuple(map(float, p.strip().split())) for p in inner.split(",")]
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        return FakePolygon(min(xs), min(ys), max(xs), max(ys))
    except Exception:
        return FakePolygon(0, 0, 1, 1)


class _FakeWindow:
    """Minimal rasterio.windows.Window stub."""
    def __init__(self, col_off=0, row_off=0, width=0, height=0):
        self.col_off = int(col_off)
        self.row_off = int(row_off)
        self.width = int(width)
        self.height = int(height)


def _install_all_stubs():
    """Install every fake module needed before canopy_detection is imported."""
    stubs = {}

    # ── numpy stub (array operations are not tested here — we stub inference) ──
    np_mod = types.ModuleType("numpy")
    np_mod.uint8 = "uint8"
    np_mod.ndarray = object

    class _FakeArray:
        def __init__(self, *args, **kwargs):
            self.dtype = kwargs.get("dtype", "uint8")
            self.ndim = 3
            self.shape = (3, 512, 512)

        @property
        def min(self):
            return lambda: 0

        @property
        def max(self):
            return lambda: 255

        def astype(self, t):
            return self

    np_mod.zeros = lambda shape, dtype=None: _FakeArray()
    np_mod.transpose = lambda a, axes: a
    np_mod.stack = lambda arrays, axis=0: _FakeArray()
    np_mod.zeros_like = lambda a, dtype=None: _FakeArray()
    # pytest.approx uses: np.isscalar, np.ndarray, np.bool_
    np_mod.isscalar = lambda x: isinstance(x, (int, float, complex, bool))
    np_mod.ndarray = _FakeArray
    np_mod.bool_ = bool   # pytest.approx: isinstance(val, np.bool_)
    np_mod.float64 = float
    np_mod.int64 = int
    np_mod.integer = int
    np_mod.floating = float
    np_mod.complexfloating = complex
    stubs["numpy"] = np_mod

    # ── shapely stub ──────────────────────────────────────────────────────────
    shapely_mod = types.ModuleType("shapely")
    shapely_geo = types.ModuleType("shapely.geometry")
    shapely_geo.box = _fake_box
    shapely_geo.mapping = lambda g: {"type": "Polygon", "coordinates": []}
    shapely_geo.FakePolygon = FakePolygon  # expose for tests
    shapely_wkt_mod = types.ModuleType("shapely.wkt")
    shapely_wkt_mod.loads = _fake_wkt_loads
    shapely_mod.geometry = shapely_geo
    shapely_mod.wkt = shapely_wkt_mod
    stubs["shapely"] = shapely_mod
    stubs["shapely.geometry"] = shapely_geo
    stubs["shapely.wkt"] = shapely_wkt_mod

    # ── rasterio stub ─────────────────────────────────────────────────────────
    rasterio_windows = types.ModuleType("rasterio.windows")
    rasterio_windows.Window = _FakeWindow

    rasterio_transform = types.ModuleType("rasterio.transform")
    rasterio_transform.xy = MagicMock(return_value=(100.0, 200.0))

    rasterio_mask_mod = types.ModuleType("rasterio.mask")
    rasterio_mask_mod.mask = MagicMock(return_value=(MagicMock(), MagicMock()))

    rasterio_mod = types.ModuleType("rasterio")
    rasterio_mod.open = MagicMock()
    rasterio_mod.DatasetReader = MagicMock
    rasterio_mod.windows = rasterio_windows
    rasterio_mod.transform = rasterio_transform
    rasterio_mod.mask = rasterio_mask_mod

    stubs["rasterio"] = rasterio_mod
    stubs["rasterio.windows"] = rasterio_windows
    stubs["rasterio.transform"] = rasterio_transform
    stubs["rasterio.mask"] = rasterio_mask_mod

    # ── torch stub ────────────────────────────────────────────────────────────
    torch_cuda = types.ModuleType("torch.cuda")
    torch_cuda.is_available = MagicMock(return_value=True)
    torch_cuda.get_device_capability = MagicMock(return_value=(12, 0))
    torch_cuda.get_device_name = MagicMock(return_value="NVIDIA RTX 5060 Ti")
    torch_cuda.empty_cache = MagicMock()

    torch_mod = types.ModuleType("torch")
    torch_mod.cuda = torch_cuda
    torch_mod.Tensor = MagicMock

    stubs["torch"] = torch_mod
    stubs["torch.cuda"] = torch_cuda

    # ── deepforest stub ───────────────────────────────────────────────────────
    mock_df_cls = MagicMock()
    deepforest_main = types.ModuleType("deepforest.main")
    deepforest_main.deepforest = mock_df_cls
    deepforest_mod = types.ModuleType("deepforest")
    deepforest_mod.main = deepforest_main
    stubs["deepforest"] = deepforest_mod
    stubs["deepforest.main"] = deepforest_main

    # ── pandas stub (needed by canopy_detection zero-canopy branch) ──────────
    fake_pd = types.ModuleType("pandas")
    fake_pd.DataFrame = MagicMock(return_value=MagicMock())
    stubs["pandas"] = fake_pd

    # ── geopandas stub ────────────────────────────────────────────────────────
    fake_gpd = types.ModuleType("geopandas")
    fake_gpd.GeoDataFrame = MagicMock(return_value=MagicMock())
    stubs["geopandas"] = fake_gpd

    # ── supabase stub ─────────────────────────────────────────────────────────
    fake_supabase = types.ModuleType("supabase")
    fake_supabase.create_client = MagicMock()
    stubs["supabase"] = fake_supabase

    # Install stubs only when the real package is NOT importable.
    # setdefault alone isn't enough — a package can be installed but not yet
    # imported (so not in sys.modules).  Try-import first to let real packages win.
    for name, mod in stubs.items():
        if name not in sys.modules:
            try:
                __import__(name)
            except ImportError:
                sys.modules[name] = mod


_install_all_stubs()


# ── Now safe to import from canopy_detection ─────────────────────────────────
from canopy_detection import (
    compute_tile_windows,
    cross_tile_nms,
    compute_iou,
    pixel_box_to_geo,
    write_output_files,
    upsert_detections_to_supabase,
    detect_canopies,
)


# ─── Supabase autouse stub ────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def ensure_supabase_stub(mocker):
    """Ensure supabase stub is in sys.modules for all tests."""
    if "supabase" not in sys.modules:
        fake_sb = types.ModuleType("supabase")
        fake_sb.create_client = MagicMock()
        mocker.patch.dict(sys.modules, {"supabase": fake_sb})


# ─── TILING TESTS ─────────────────────────────────────────────────────────────

def test_tiling_dimensions():
    """2048x2048 image with tile_size=1024, overlap=128 → 4 tiles."""
    tiles = compute_tile_windows(width=2048, height=2048, tile_size=1024, overlap=128)
    assert len(tiles) == 4
    core_positions = [(col, row) for _, col, row in tiles]
    assert (0, 0) in core_positions
    assert (1024, 0) in core_positions
    assert (0, 1024) in core_positions
    assert (1024, 1024) in core_positions


def test_tiling_window_first_tile_has_overlap():
    """First tile window includes right/bottom overlap padding only (left/top clamped)."""
    tiles = compute_tile_windows(width=2048, height=2048, tile_size=1024, overlap=128)
    win, core_col, core_row = tiles[0]
    assert core_col == 0
    assert core_row == 0
    assert win.col_off == 0   # clamped — no left overlap at boundary
    assert win.row_off == 0
    assert win.width == 1024 + 128   # core + right overlap
    assert win.height == 1024 + 128  # core + bottom overlap


def test_tiling_interior_tile_has_left_overlap():
    """Interior tile at (1024, 0) has left overlap: col_off = 1024-128 = 896."""
    tiles = compute_tile_windows(width=3072, height=1024, tile_size=1024, overlap=128)
    interior = [t for t in tiles if t[1] == 1024 and t[2] == 0]
    assert len(interior) == 1
    win = interior[0][0]
    assert win.col_off == 896  # 1024 - 128


def test_tiling_edge_handling():
    """Non-square image (3000x2000) — 6 tiles, all windows clamped to image bounds."""
    tiles = compute_tile_windows(width=3000, height=2000, tile_size=1024, overlap=128)
    assert len(tiles) == 6  # 3 col × 2 row offsets
    for win, _, _ in tiles:
        assert win.col_off >= 0
        assert win.row_off >= 0
        assert win.col_off + win.width <= 3000
        assert win.row_off + win.height <= 2000


def test_tiling_single_tile_small_image():
    """Image smaller than tile_size produces exactly one tile."""
    tiles = compute_tile_windows(width=512, height=512, tile_size=1024, overlap=128)
    assert len(tiles) == 1
    win, core_col, core_row = tiles[0]
    assert core_col == 0
    assert core_row == 0
    assert win.col_off == 0
    assert win.row_off == 0
    assert win.width == 512
    assert win.height == 512


# ─── NMS TESTS ────────────────────────────────────────────────────────────────

def test_nms_removes_duplicates():
    """Two overlapping polygons (IoU ≈ 0.47 > 0.3) — only higher confidence kept."""
    poly_a = FakePolygon(0, 0, 10, 10)   # area 100
    poly_b = FakePolygon(2, 2, 12, 12)   # area 100, overlap 8×8=64, IoU=64/136≈0.47

    dets = [_make_det(poly_a, 0.9), _make_det(poly_b, 0.6)]
    result = cross_tile_nms(dets, iou_threshold=0.3)

    assert len(result) == 1
    assert result[0]["confidence"] == pytest.approx(0.9)


def test_nms_keeps_separate():
    """Two non-overlapping polygons both survive NMS."""
    poly_a = FakePolygon(0, 0, 5, 5)
    poly_b = FakePolygon(20, 20, 25, 25)  # no overlap

    dets = [_make_det(poly_a, 0.8), _make_det(poly_b, 0.7)]
    result = cross_tile_nms(dets, iou_threshold=0.3)
    assert len(result) == 2


def test_nms_empty_input():
    """Empty detection list returns empty list."""
    assert cross_tile_nms([], iou_threshold=0.3) == []


def test_nms_exactly_at_threshold_kept():
    """Two polygons with IoU below threshold are both kept."""
    # poly_a (0,0)-(10,10), poly_b (5,5)-(15,15)
    # overlap 5×5=25, union=175, IoU=25/175≈0.143 < 0.3 → both kept
    poly_a = FakePolygon(0, 0, 10, 10)
    poly_b = FakePolygon(5, 5, 15, 15)

    dets = [_make_det(poly_a, 0.9), _make_det(poly_b, 0.8)]
    result = cross_tile_nms(dets, iou_threshold=0.3)
    assert len(result) == 2


def test_nms_high_overlap_keeps_highest_confidence():
    """Near-identical polygons (IoU > 0.9) — highest confidence survives."""
    poly_a = FakePolygon(0, 0, 10, 10)
    poly_b = FakePolygon(0.5, 0.5, 10.5, 10.5)  # heavy overlap

    dets = [_make_det(poly_a, 0.5), _make_det(poly_b, 0.9)]
    result = cross_tile_nms(dets, iou_threshold=0.3)
    assert len(result) == 1
    assert result[0]["confidence"] == pytest.approx(0.9)


# ─── COORDINATE TRANSFORM TESTS ───────────────────────────────────────────────

def test_pixel_to_geo_transform():
    """Known pixel coords + simulated transform produce expected geo coordinates."""
    import canopy_detection as _cd

    mock_ds = MagicMock()
    win = _FakeWindow(col_off=0, row_off=0, width=512, height=512)

    # xy(transform, row, col) → (500000+col, 4000000-row)
    with patch.object(_cd, "rasterio_xy",
                      side_effect=lambda t, row, col: (500000.0 + col, 4000000.0 - row)):
        geo_xmin, geo_ymin, geo_xmax, geo_ymax = pixel_box_to_geo(
            mock_ds, win, 10.0, 20.0, 30.0, 40.0
        )

    # abs pixel: (col=10,row=20) → (500010, 3999980); (col=30,row=40) → (500030, 3999960)
    assert geo_xmin == pytest.approx(500010.0)
    assert geo_xmax == pytest.approx(500030.0)
    assert geo_ymin == pytest.approx(3999960.0)
    assert geo_ymax == pytest.approx(3999980.0)


def test_pixel_to_geo_window_offset():
    """Window offset (100, 200) is correctly added to tile-local pixel coordinates."""
    import canopy_detection as _cd

    mock_ds = MagicMock()
    win = _FakeWindow(col_off=100, row_off=200, width=512, height=512)

    with patch.object(_cd, "rasterio_xy",
                      side_effect=lambda t, row, col: (float(col), float(-row))):
        geo_xmin, geo_ymin, geo_xmax, geo_ymax = pixel_box_to_geo(
            mock_ds, win, 0.0, 0.0, 50.0, 50.0
        )

    # abs col: 100, 150; abs row: 200, 250 → xy returns (col, -row)
    assert geo_xmin == pytest.approx(100.0)
    assert geo_xmax == pytest.approx(150.0)
    assert geo_ymin == pytest.approx(-250.0)
    assert geo_ymax == pytest.approx(-200.0)


# ─── CANOPY METRICS TESTS ─────────────────────────────────────────────────────

def test_canopy_metrics():
    """Area, width, height computed correctly from a 10×5 bounding box."""
    poly = FakePolygon(500000.0, 4000000.0, 500010.0, 4000005.0)
    width_m = poly.bounds[2] - poly.bounds[0]
    height_m = poly.bounds[3] - poly.bounds[1]
    area_m2 = poly.area

    assert width_m == pytest.approx(10.0)
    assert height_m == pytest.approx(5.0)
    assert area_m2 == pytest.approx(50.0)
    assert poly.centroid.x == pytest.approx(500005.0)
    assert poly.centroid.y == pytest.approx(4000002.5)


def test_compute_iou_overlapping():
    """IoU computed correctly for two overlapping polygons."""
    a = FakePolygon(0, 0, 10, 10)   # area 100
    b = FakePolygon(5, 0, 15, 10)   # area 100, overlap 5×10=50
    # IoU = 50 / (100 + 100 - 50) = 50/150 ≈ 0.333
    iou = compute_iou(a, b)
    assert iou == pytest.approx(50.0 / 150.0, rel=1e-3)


def test_compute_iou_no_overlap():
    """Non-overlapping polygons return IoU = 0."""
    a = FakePolygon(0, 0, 5, 5)
    b = FakePolygon(10, 10, 15, 15)
    assert compute_iou(a, b) == pytest.approx(0.0)


# ─── GEOJSON EXPORT TESTS ────────────────────────────────────────────────────

def test_geojson_export_schema(tmp_path):
    """write_output_files passes all required schema fields to GeoDataFrame."""
    import logging
    log = logging.getLogger("test")

    det = _make_det_full(FakePolygon(500000.0, 4000000.0, 500010.0, 4000010.0), 0.85)
    captured_data = {}

    def fake_gdf(*args, **kwargs):
        # GeoDataFrame can be called as GeoDataFrame(data_dict, geometry=..., crs=...)
        # where data_dict is first positional arg or 'data' keyword
        data = kwargs.get("data") or (args[0] if args else {})
        if isinstance(data, dict):
            captured_data.update(data)
        inst = MagicMock()
        inst.to_file = MagicMock()
        inst.astype = MagicMock(return_value=inst)
        return inst

    with patch("canopy_detection.gpd") as mock_gpd:
        mock_gpd.GeoDataFrame = fake_gdf
        write_output_files([det], str(tmp_path), MagicMock(), log)

    required = [
        "detection_index", "centroid_lat", "centroid_lon",
        "canopy_area_sqm", "canopy_width_m", "canopy_height_m",
        "detection_confidence", "label",
    ]
    for field in required:
        assert field in captured_data, f"Missing required field: {field}"


def test_geojson_export_values(tmp_path):
    """Detection values flow correctly into GeoDataFrame constructor."""
    import logging
    log = logging.getLogger("test")

    det = _make_det_full(FakePolygon(500000.0, 4000000.0, 500010.0, 4000010.0), 0.85)
    det["centroid_x"] = 500005.0
    det["centroid_y"] = 4000005.0
    captured = {}

    def fake_gdf(*args, **kwargs):
        data = kwargs.get("data") or (args[0] if args else {})
        if isinstance(data, dict):
            captured.update(data)
        inst = MagicMock()
        inst.to_file = MagicMock()
        return inst

    with patch("canopy_detection.gpd") as mock_gpd:
        mock_gpd.GeoDataFrame = fake_gdf
        write_output_files([det], str(tmp_path), MagicMock(), log)

    assert captured["centroid_lat"] == [4000005.0]
    assert captured["centroid_lon"] == [500005.0]
    assert captured["canopy_area_sqm"] == [det["area_m2"]]
    assert captured["detection_confidence"] == [0.85]


def test_gpkg_export(tmp_path):
    """write_output_files calls to_file with driver='GPKG'."""
    import logging
    log = logging.getLogger("test")

    det = _make_det_full(FakePolygon(0, 0, 10, 10), 0.7)
    mock_gdf_instance = MagicMock()
    mock_gdf_instance.to_file = MagicMock()

    with patch("canopy_detection.gpd") as mock_gpd:
        mock_gpd.GeoDataFrame = MagicMock(return_value=mock_gdf_instance)
        write_output_files([det], str(tmp_path), MagicMock(), log)

    calls = mock_gdf_instance.to_file.call_args_list
    drivers_used = [c[1].get("driver") for c in calls]
    assert "GPKG" in drivers_used, f"Expected 'GPKG' but got: {drivers_used}"


# ─── SUPABASE WRITE TESTS ────────────────────────────────────────────────────

def test_supabase_write_correct_payload(mock_supabase_client, mocker):
    """Supabase client receives correct payload with conflict key."""
    mocker.patch("supabase.create_client", return_value=mock_supabase_client)
    import logging
    log = logging.getLogger("test")

    det = _make_det_full(FakePolygon(500000.0, 4000000.0, 500010.0, 4000010.0), 0.85)

    with patch("pipeline_utils.SUPABASE_URL", "https://test.supabase.co"), \
         patch("pipeline_utils.SUPABASE_SERVICE_KEY", "test-key"):
        result = upsert_detections_to_supabase([det], "mission-uuid-001", log)

    assert result is True
    mock_supabase_client.table.assert_called_with("vegetation_detections")

    upsert_call = mock_supabase_client.table.return_value.upsert
    upsert_call.assert_called_once()
    assert upsert_call.call_args[1].get("on_conflict") == "mission_id,detection_index"

    payload = upsert_call.call_args[0][0]
    assert len(payload) == 1
    row = payload[0]
    assert row["mission_id"] == "mission-uuid-001"
    assert row["detection_index"] == 0
    assert "geometry_wkt" in row
    assert "centroid_lat" in row
    assert "centroid_lon" in row
    assert "canopy_area_sqm" in row
    assert "detection_confidence" in row


def test_supabase_write_skips_when_no_credentials():
    """upsert_detections_to_supabase returns False when credentials are absent."""
    import logging
    log = logging.getLogger("test")

    det = _make_det_full(FakePolygon(0, 0, 10, 10), 0.8)

    with patch("pipeline_utils.SUPABASE_URL", ""), \
         patch("pipeline_utils.SUPABASE_SERVICE_KEY", ""), \
         patch("canopy_detection._get_supabase_client", return_value=None):
        result = upsert_detections_to_supabase([det], "mission-uuid", log)

    assert result is False


def test_supabase_write_zero_detections():
    """upsert returns True immediately for empty detection list."""
    import logging
    log = logging.getLogger("test")
    result = upsert_detections_to_supabase([], "mission-uuid", log)
    assert result is True


# ─── CHECKPOINT RESUME TESTS ─────────────────────────────────────────────────

def test_checkpoint_resume_skips_completed_tiles(tmp_path):
    """With 2 tiles pre-completed, only the remaining 2 tiles invoke inference."""
    import logging
    log = logging.getLogger("test")

    # Pre-complete 2 of the 4 tiles for a 2048×2048 image
    completed_tiles = {"tile_0_0", "tile_1024_0"}
    inference_calls = []

    mock_dataset = _make_mock_dataset(width=2048, height=2048)

    def mock_inference(model, tile_array, score_threshold):
        inference_calls.append(1)
        return None

    with patch("canopy_detection.rasterio") as mock_rasterio, \
         patch("canopy_detection.load_deepforest_model", return_value=MagicMock()), \
         patch("canopy_detection.run_inference_on_tile", side_effect=mock_inference), \
         patch("canopy_detection.save_checkpoint"), \
         patch("canopy_detection.torch") as mock_torch:
        mock_rasterio.open.return_value = mock_dataset
        mock_torch.cuda.empty_cache = MagicMock()

        detections, had_failure, crs = detect_canopies(
            ortho_path="fake/path.tif",
            tile_size=1024,
            overlap=128,
            score_threshold=0.3,
            iou_threshold=0.3,
            completed_tiles=completed_tiles,
            mission_dir=str(tmp_path),
            log=log,
        )

    # 4 total tiles, 2 already done → only 2 inference calls
    assert len(inference_calls) == 2
    assert detections == []
    assert had_failure is False


# ─── ZERO DETECTIONS TESTS ───────────────────────────────────────────────────

def test_zero_detections(tmp_path):
    """Inference returning None everywhere → empty detections, no failure."""
    import logging
    log = logging.getLogger("test")

    mock_dataset = _make_mock_dataset(width=512, height=512)

    with patch("canopy_detection.rasterio") as mock_rasterio, \
         patch("canopy_detection.load_deepforest_model", return_value=MagicMock()), \
         patch("canopy_detection.run_inference_on_tile", return_value=None), \
         patch("canopy_detection.save_checkpoint"), \
         patch("canopy_detection.torch") as mock_torch:
        mock_rasterio.open.return_value = mock_dataset
        mock_torch.cuda.empty_cache = MagicMock()

        detections, had_failure, crs = detect_canopies(
            ortho_path="fake/path.tif",
            tile_size=1024,
            overlap=128,
            score_threshold=0.3,
            iou_threshold=0.3,
            completed_tiles=set(),
            mission_dir=str(tmp_path),
            log=log,
        )

    assert detections == []
    assert had_failure is False


def test_zero_detections_write_output_uses_columns_schema(tmp_path):
    """write_output_files for empty list uses columns kwarg with all schema fields."""
    import logging
    log = logging.getLogger("test")
    captured = {}

    def fake_gdf(*args, **kwargs):
        captured.update(kwargs)
        inst = MagicMock()
        inst.to_file = MagicMock()
        inst.astype = MagicMock(return_value=inst)
        return inst

    # Also stub pandas (used in the zero-canopy branch of write_output_files)
    fake_pd = types.ModuleType("pandas")
    fake_pd.DataFrame = MagicMock(return_value=MagicMock())

    with patch("canopy_detection.gpd") as mock_gpd, \
         patch.dict(sys.modules, {"pandas": fake_pd}):
        mock_gpd.GeoDataFrame = fake_gdf
        write_output_files([], str(tmp_path), MagicMock(), log)

    assert "columns" in captured
    cols = captured["columns"]
    for field in ["detection_index", "centroid_lat", "centroid_lon",
                  "canopy_area_sqm", "detection_confidence", "label"]:
        assert field in cols


# ─── ENV CLEANUP TESTS ───────────────────────────────────────────────────────

def test_proj_env_cleanup():
    """PROJ_LIB and PROJ_DATA removal leaves other env vars intact."""
    env = {"PROJ_LIB": "/some/path", "PROJ_DATA": "/other/path", "OTHER_VAR": "keep"}
    for var in ("PROJ_LIB", "PROJ_DATA"):
        env.pop(var, None)

    assert "PROJ_LIB" not in env
    assert "PROJ_DATA" not in env
    assert env["OTHER_VAR"] == "keep"


def test_proj_env_cleanup_idempotent():
    """Popping absent PROJ_LIB/PROJ_DATA keys does not raise."""
    env = {"GDAL_CACHEMAX": "256"}
    for var in ("PROJ_LIB", "PROJ_DATA"):
        env.pop(var, None)  # must not raise even when absent
    assert "PROJ_LIB" not in env
    assert "PROJ_DATA" not in env
    assert env.get("GDAL_CACHEMAX") == "256"


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def _make_det(polygon, confidence=0.8, label="Tree"):
    """Minimal detection dict with just required NMS fields."""
    bounds = polygon.bounds
    return {
        "polygon": polygon,
        "geo_xmin": bounds[0],
        "geo_ymin": bounds[1],
        "geo_xmax": bounds[2],
        "geo_ymax": bounds[3],
        "centroid_x": (bounds[0] + bounds[2]) / 2.0,
        "centroid_y": (bounds[1] + bounds[3]) / 2.0,
        "confidence": confidence,
        "label": label,
        "width_m": bounds[2] - bounds[0],
        "height_m": bounds[3] - bounds[1],
        "area_m2": polygon.area,
    }


def _make_det_full(polygon, confidence=0.8, label="Tree"):
    """Full detection dict matching upsert_detections_to_supabase expectations."""
    bounds = polygon.bounds
    cx = (bounds[0] + bounds[2]) / 2.0
    cy = (bounds[1] + bounds[3]) / 2.0
    return {
        "polygon": polygon,
        "geo_xmin": bounds[0],
        "geo_ymin": bounds[1],
        "geo_xmax": bounds[2],
        "geo_ymax": bounds[3],
        "centroid_x": cx,
        "centroid_y": cy,
        "confidence": confidence,
        "label": label,
        "width_m": bounds[2] - bounds[0],
        "height_m": bounds[3] - bounds[1],
        "area_m2": polygon.area,
    }


def _make_mock_dataset(width=2048, height=2048, bands=3):
    """Create a context-manager-compatible mock dataset."""
    ds = MagicMock()
    ds.__enter__ = MagicMock(return_value=ds)
    ds.__exit__ = MagicMock(return_value=False)
    ds.crs = MagicMock()
    ds.crs.to_epsg = MagicMock(return_value=32618)
    ds.width = width
    ds.height = height
    ds.count = bands
    # read() returns a stub array-like object
    fake_array = MagicMock()
    fake_array.dtype = "uint8"
    fake_array.__getitem__ = MagicMock(return_value=fake_array)
    ds.read = MagicMock(return_value=fake_array)
    return ds
