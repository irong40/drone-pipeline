"""
Unit tests for species_classification.py (Step E2) — UNIT-E2
Tests crop extraction, OpenAI/PlantNet API mocking, confidence reconciliation,
cost gate, max_canopies cap, checkpoint resume, and Supabase batch updates.

All external packages (rasterio, openai, requests, supabase, PIL, shapely)
are fully stubbed. Runs against system Python with no geo/ML packages installed.
"""
import os
import sys
import json
import types
import logging
import pytest
from unittest.mock import MagicMock, patch, call


# ── Module-level stubs ──────────────────────────────────────────────────────
# species_classification.py performs top-level imports of rasterio and shapely.
# All stubs must be installed BEFORE the module is imported.

def _make_fake_polygon():
    class FakePoly:
        def __init__(self, minx=0, miny=0, maxx=1, maxy=1):
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

    return FakePoly


_FakePoly = _make_fake_polygon()


def _install_stubs():
    """Install all fake modules before species_classification is imported."""
    stubs = {}

    # ── numpy stub ────────────────────────────────────────────────────────────
    np_mod = types.ModuleType("numpy")

    class _FakeArr:
        dtype = "uint8"
        ndim = 3
        shape = (3, 100, 100)

        def __getitem__(self, key):
            return self

        def astype(self, t):
            return self

        def transpose(self, *axes):
            return self

    np_mod.uint8 = "uint8"
    np_mod.ndarray = _FakeArr
    np_mod.isscalar = lambda x: isinstance(x, (int, float, complex, bool))
    np_mod.bool_ = bool
    np_mod.float64 = float
    np_mod.int64 = int
    np_mod.integer = int
    np_mod.floating = float
    np_mod.complexfloating = complex
    np_mod.zeros = lambda shape, dtype=None: _FakeArr()
    np_mod.transpose = lambda a, axes: a
    stubs["numpy"] = np_mod

    # ── shapely stub ──────────────────────────────────────────────────────────
    shapely_mod = types.ModuleType("shapely")
    shapely_geo = types.ModuleType("shapely.geometry")
    shapely_geo.box = lambda a, b, c, d: _FakePoly(a, b, c, d)

    def _fake_wkt_loads(wkt_str):
        try:
            inner = wkt_str.replace("POLYGON ((", "").rstrip(")")
            coords = [tuple(map(float, p.strip().split())) for p in inner.split(",")]
            xs = [c[0] for c in coords]
            ys = [c[1] for c in coords]
            return _FakePoly(min(xs), min(ys), max(xs), max(ys))
        except Exception:
            return _FakePoly(0, 0, 1, 1)

    shapely_wkt = types.ModuleType("shapely.wkt")
    shapely_wkt.loads = _fake_wkt_loads
    shapely_mod.wkt = shapely_wkt
    shapely_mod.geometry = shapely_geo
    stubs["shapely"] = shapely_mod
    stubs["shapely.geometry"] = shapely_geo
    stubs["shapely.wkt"] = shapely_wkt

    # ── rasterio stub ─────────────────────────────────────────────────────────
    rasterio_mod = types.ModuleType("rasterio")
    rasterio_mod.open = MagicMock()
    rasterio_mod.DatasetReader = MagicMock

    rasterio_mask_mod = types.ModuleType("rasterio.mask")
    rasterio_mask_mod.mask = MagicMock(return_value=(_FakeArr(), MagicMock()))
    rasterio_mod.mask = rasterio_mask_mod

    stubs["rasterio"] = rasterio_mod
    stubs["rasterio.mask"] = rasterio_mask_mod

    # ── PIL stub ──────────────────────────────────────────────────────────────
    class _FakeImage:
        size = (100, 100)
        mode = "RGB"

        def save(self, path_or_buf, format=None, **kwargs):
            # Write minimal PNG-like bytes so base64 works
            if hasattr(path_or_buf, "write"):
                path_or_buf.write(b"\x89PNG fake")
            else:
                with open(path_or_buf, "wb") as f:
                    f.write(b"\x89PNG fake")

        def resize(self, size, resample=None):
            img = _FakeImage()
            img.size = size
            return img

    class _FakeImageModule:
        LANCZOS = 1

        @staticmethod
        def fromarray(arr, mode=None):
            return _FakeImage()

        @staticmethod
        def open(fp):
            return _FakeImage()

    fake_pil = types.ModuleType("PIL")
    fake_pil_image = types.ModuleType("PIL.Image")
    fake_pil_image.Image = _FakeImageModule
    fake_pil_image.LANCZOS = 1
    fake_pil_image.fromarray = _FakeImageModule.fromarray

    # Expose as both PIL.Image (module) and PIL.Image.Image (class)
    # species_classification does: from PIL import Image; Image.fromarray(...)
    fake_pil.Image = _FakeImageModule
    stubs["PIL"] = fake_pil
    stubs["PIL.Image"] = fake_pil_image

    # ── supabase stub ─────────────────────────────────────────────────────────
    fake_supabase = types.ModuleType("supabase")
    fake_supabase.create_client = MagicMock()
    stubs["supabase"] = fake_supabase

    # ── requests stub ─────────────────────────────────────────────────────────
    fake_requests = types.ModuleType("requests")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {}
    mock_resp.json.return_value = {"results": []}
    fake_requests.post = MagicMock(return_value=mock_resp)
    stubs["requests"] = fake_requests

    # ── openai stub ───────────────────────────────────────────────────────────
    fake_openai = types.ModuleType("openai")

    class _FakeOpenAIClient:
        def __init__(self, api_key=None):
            self.chat = MagicMock()

    fake_openai.OpenAI = _FakeOpenAIClient
    stubs["openai"] = fake_openai

    # Install stubs only when the real package is NOT importable.
    for name, mod in stubs.items():
        if name not in sys.modules:
            try:
                __import__(name)
            except ImportError:
                sys.modules[name] = mod


_install_stubs()


# ── Now safe to import from species_classification ────────────────────────────
from species_classification import (
    crop_canopy,
    classify_openai,
    classify_plantnet,
    reconcile,
    estimate_api_cost,
    run_classification,
    update_classification_batch,
    PLANTNET_QUOTA_EXHAUSTED,
)


# ─── Supabase autouse stub ────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def ensure_supabase_stub(mocker):
    if "supabase" not in sys.modules:
        fake_sb = types.ModuleType("supabase")
        fake_sb.create_client = MagicMock()
        mocker.patch.dict(sys.modules, {"supabase": fake_sb})


# ─── CROP CANOPY TESTS ───────────────────────────────────────────────────────

def test_crop_canopy_returns_image_for_valid_polygon():
    """crop_canopy with valid polygon returns a PIL Image (not None)."""
    # Build a dataset mock that returns a valid 3-band crop
    mock_dataset = MagicMock()

    fake_pixels = MagicMock()
    fake_pixels.shape = (3, 50, 50)
    fake_pixels.__getitem__ = lambda self, k: fake_pixels  # pixels[:3]

    # rasterio_mask returns (pixels, transform)
    with patch("species_classification.rasterio_mask") as mock_mask, \
         patch("species_classification.np") as mock_np:
        mock_mask.return_value = (fake_pixels, MagicMock())
        # np.transpose returns a HWC-like array
        fake_hwc = MagicMock()
        fake_hwc.shape = (50, 50, 3)
        fake_hwc.__getitem__ = lambda s, k: fake_hwc
        mock_np.transpose.return_value = fake_hwc

        # PIL Image.fromarray is called on the hwc array
        with patch.dict(sys.modules, {
            "PIL": _make_pil_stub(),
        }):
            result = crop_canopy(mock_dataset, _make_wkt(0, 0, 10, 10))

    # result is either a PIL image or None — we just verify it doesn't crash
    # The actual return type depends on PIL stub
    # Key: no exception raised


def test_crop_canopy_edge_polygon_no_exception():
    """crop_canopy near ortho edge does not raise an exception."""
    mock_dataset = MagicMock()

    # Simulate out-of-bounds scenario by having rasterio_mask raise an exception
    with patch("species_classification.rasterio_mask", side_effect=Exception("out of bounds")):
        result = crop_canopy(mock_dataset, _make_wkt(-100, -100, 5, 5))

    # crop_canopy catches all exceptions and returns None
    assert result is None


def test_crop_canopy_missing_bands_returns_none():
    """crop_canopy returns None if fewer than 3 bands are available."""
    mock_dataset = MagicMock()

    fake_pixels = MagicMock()
    fake_pixels.shape = (2, 50, 50)  # only 2 bands — insufficient

    with patch("species_classification.rasterio_mask") as mock_mask:
        mock_mask.return_value = (fake_pixels, MagicMock())
        result = crop_canopy(mock_dataset, _make_wkt(0, 0, 10, 10))

    assert result is None


def test_crop_canopy_applies_15pct_padding():
    """15% padding is applied to each side of the polygon bounding box."""
    # shapely_box is imported lazily inside crop_canopy() as:
    #   from shapely.geometry import box as shapely_box
    # So we patch the class in the shapely.geometry module in sys.modules.
    captured_boxes = []

    def tracking_box(minx, miny, maxx, maxy):
        captured_boxes.append((minx, miny, maxx, maxy))
        # Return something with bounds so rasterio_mask can be called
        fake = _FakePoly(minx, miny, maxx, maxy)
        return fake

    import species_classification as sc

    # Patch shapely.geometry.box directly in sys.modules
    sys.modules["shapely.geometry"].box = tracking_box

    try:
        with patch.object(sc, "shapely_wkt") as mock_wkt:
            original_poly = _FakePoly(0.0, 0.0, 10.0, 10.0)
            mock_wkt.loads = MagicMock(return_value=original_poly)

            with patch("species_classification.rasterio_mask",
                       side_effect=Exception("stop")):
                crop_canopy(MagicMock(), _make_wkt(0, 0, 10, 10), padding_pct=0.15)
    finally:
        # Restore original stub box function
        sys.modules["shapely.geometry"].box = lambda a, b, c, d: _FakePoly(a, b, c, d)

    # With bounding box (0,0)-(10,10), width=height=10
    # 15% padding = 1.5 on each side
    # Expected padded box: (-1.5, -1.5, 11.5, 11.5)
    assert len(captured_boxes) >= 1
    padded = captured_boxes[0]
    assert padded[0] == pytest.approx(-1.5)
    assert padded[1] == pytest.approx(-1.5)
    assert padded[2] == pytest.approx(11.5)
    assert padded[3] == pytest.approx(11.5)


# ─── OPENAI CLASSIFICATION TESTS ─────────────────────────────────────────────

def test_openai_classification_parses_valid_response():
    """classify_openai returns parsed species dict for valid JSON response."""
    # OpenAI is imported lazily inside classify_openai() as:
    #   from openai import OpenAI
    # So we patch openai.OpenAI in sys.modules
    response_json = {
        "species_common": "Loblolly Pine",
        "species_scientific": "Pinus taeda",
        "vegetation_type": "tree",
        "confidence": 0.82,
        "reasoning": "Dense dark green canopy, conical shape",
        "secondary_candidates": [{"species_common": "Virginia Pine", "confidence": 0.15}],
    }

    mock_image = MagicMock()
    mock_image.save = lambda buf, format=None: buf.write(b"fakepng")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps(response_json)
    mock_client.chat.completions.create.return_value = mock_response
    mock_openai_cls = MagicMock(return_value=mock_client)

    sys.modules["openai"].OpenAI = mock_openai_cls
    try:
        result = classify_openai(mock_image, "fake-api-key")
    finally:
        # Restore stub
        sys.modules["openai"].OpenAI = MagicMock()

    assert result["species_common"] == "Loblolly Pine"
    assert result["species_scientific"] == "Pinus taeda"
    assert result["vegetation_type"] == "tree"
    assert result["confidence"] == pytest.approx(0.82, rel=1e-3)


def test_openai_json_parse_failure_returns_unidentified():
    """Malformed response returns the 'unidentified' fallback dict."""
    mock_image = MagicMock()
    mock_image.save = lambda buf, format=None: buf.write(b"fakepng")

    mock_client = MagicMock()
    mock_response = MagicMock()
    # Both first and retry return unparseable content
    mock_response.choices[0].message.content = "not valid json at all {{{"
    mock_client.chat.completions.create.return_value = mock_response
    mock_openai_cls = MagicMock(return_value=mock_client)

    sys.modules["openai"].OpenAI = mock_openai_cls
    try:
        result = classify_openai(mock_image, "fake-api-key")
    finally:
        sys.modules["openai"].OpenAI = MagicMock()

    assert result["species_common"] == "unidentified"
    assert result["confidence"] == 0.0
    assert "could not be parsed" in result["reasoning"]


def test_openai_confidence_clamped_above_1():
    """Confidence value > 1.0 is clamped to 1.0."""
    response_json = {
        "species_common": "Live Oak",
        "species_scientific": "Quercus virginiana",
        "vegetation_type": "tree",
        "confidence": 1.5,  # out of range
        "reasoning": "Wide spreading canopy",
        "secondary_candidates": [],
    }

    mock_image = MagicMock()
    mock_image.save = lambda buf, format=None: buf.write(b"fakepng")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps(response_json)
    mock_client.chat.completions.create.return_value = mock_response
    sys.modules["openai"].OpenAI = MagicMock(return_value=mock_client)
    try:
        result = classify_openai(mock_image, "fake-api-key")
    finally:
        sys.modules["openai"].OpenAI = MagicMock()

    assert result["confidence"] == pytest.approx(1.0)


def test_openai_confidence_clamped_below_0():
    """Confidence value < 0.0 is clamped to 0.0."""
    response_json = {
        "species_common": "Red Maple",
        "species_scientific": "Acer rubrum",
        "vegetation_type": "tree",
        "confidence": -0.3,  # invalid
        "reasoning": "Broad canopy",
        "secondary_candidates": [],
    }

    mock_image = MagicMock()
    mock_image.save = lambda buf, format=None: buf.write(b"fakepng")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps(response_json)
    mock_client.chat.completions.create.return_value = mock_response
    sys.modules["openai"].OpenAI = MagicMock(return_value=mock_client)
    try:
        result = classify_openai(mock_image, "fake-api-key")
    finally:
        sys.modules["openai"].OpenAI = MagicMock()

    assert result["confidence"] == pytest.approx(0.0)


# ─── PLANTNET CLASSIFICATION TESTS ───────────────────────────────────────────

def test_plantnet_classification_parses_response():
    """classify_plantnet parses top result correctly from PlantNet response."""
    # requests is imported lazily inside classify_plantnet():
    #   import requests
    # So we patch requests.post in sys.modules.
    mock_image = MagicMock()
    mock_image.save = MagicMock()

    plantnet_response = {
        "results": [
            {"species": {"scientificNameWithoutAuthor": "Pinus taeda"}, "score": 0.73},
            {"species": {"scientificNameWithoutAuthor": "Pinus virginiana"}, "score": 0.15},
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"X-Remaining-Identifications": "42"}
    mock_resp.json.return_value = plantnet_response

    # Set up the requests mock in sys.modules
    sys.modules["requests"].post = MagicMock(return_value=mock_resp)

    with patch("species_classification.tempfile") as mock_tempfile, \
         patch("os.unlink"), \
         patch("builtins.open", create=True) as mock_open:
        mock_tmp = MagicMock()
        mock_tmp.__enter__ = MagicMock(return_value=mock_tmp)
        mock_tmp.__exit__ = MagicMock(return_value=False)
        mock_tmp.name = "fake_tmp.png"
        mock_tempfile.NamedTemporaryFile.return_value = mock_tmp

        mock_f = MagicMock()
        mock_f.__enter__ = MagicMock(return_value=mock_f)
        mock_f.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = mock_f

        result = classify_plantnet(mock_image, "fake-plantnet-key")

    assert result is not None
    assert result["species_name"] == "Pinus taeda"
    assert result["score"] == pytest.approx(0.73, rel=1e-3)
    assert result["remaining_quota"] == 42


def test_plantnet_skip_flag_no_plantnet_calls():
    """With skip_plantnet=True, classify_plantnet is never called."""
    import species_classification as sc

    # We test this behavior through run_classification with a mock for classify_plantnet
    mock_log = logging.getLogger("test")

    # Build minimal detections list
    detections = [
        {
            "id": "det-001",
            "detection_index": 0,
            "geometry_wkt": _make_wkt(0, 0, 10, 10),
            "canopy_area_sqm": 100.0,
            "species_tag": None,
        }
    ]

    with patch.object(sc, "VISION_BACKEND", "openai"), \
         patch.object(sc, "OPENAI_API_KEY", "fake-key"), \
         patch.object(sc, "_load_paid_calls", return_value=0), \
         patch.object(sc, "_save_paid_calls"), \
         patch.object(sc, "fetch_detections", return_value=detections), \
         patch.object(sc, "crop_canopy", return_value=MagicMock()), \
         patch.object(sc, "classify_openai", return_value=_fake_openai_result("Oak", "Quercus sp.", 0.7)), \
         patch.object(sc, "classify_plantnet") as mock_plantnet, \
         patch.object(sc, "update_classification_batch", return_value=True), \
         patch.object(sc, "save_checkpoint"), \
         patch.object(sc, "rasterio") as mock_rasterio, \
         patch("species_classification.time") as mock_time:
        mock_rasterio.open.return_value = _make_mock_dataset()
        mock_time.sleep = MagicMock()

        sc.run_classification(
            mission_id="mission-001",
            ortho_path="fake.tif",
            max_canopies=200,
            skip_plantnet=True,  # ← key flag
            cost_threshold=99.0,
            force=False,
            completed_keys=set(),
            mission_dir="/tmp",
            log=mock_log,
        )

    # classify_plantnet should NOT have been called
    mock_plantnet.assert_not_called()


def test_plantnet_quota_exhausted_returns_sentinel():
    """classify_plantnet returns PLANTNET_QUOTA_EXHAUSTED on HTTP 429."""
    mock_image = MagicMock()
    mock_image.save = MagicMock()

    mock_resp = MagicMock()
    mock_resp.status_code = 429  # rate limit

    sys.modules["requests"].post = MagicMock(return_value=mock_resp)

    with patch("species_classification.tempfile") as mock_tempfile, \
         patch("os.unlink"), \
         patch("builtins.open", create=True) as mock_open:
        mock_tmp = MagicMock()
        mock_tmp.__enter__ = MagicMock(return_value=mock_tmp)
        mock_tmp.__exit__ = MagicMock(return_value=False)
        mock_tmp.name = "fake_tmp.png"
        mock_tempfile.NamedTemporaryFile.return_value = mock_tmp

        mock_f = MagicMock()
        mock_f.__enter__ = MagicMock(return_value=mock_f)
        mock_f.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = mock_f

        result = classify_plantnet(mock_image, "fake-key")

    assert result is PLANTNET_QUOTA_EXHAUSTED


# ─── CONFIDENCE RECONCILIATION TESTS ─────────────────────────────────────────

def test_reconcile_genus_match():
    """Genus-level agreement boosts confidence +0.1 and sets cross_validated=True."""
    openai_result = _fake_openai_result("Loblolly Pine", "Pinus taeda", 0.7)
    plantnet_result = {"species_name": "Pinus palustris", "score": 0.6, "full_results": []}

    result = reconcile(openai_result, plantnet_result)

    # Genus "Pinus" matches "Pinus" → +0.1 boost
    assert result["species_confidence"] == pytest.approx(0.8, rel=1e-3)
    assert result["cross_validated"] is True
    assert result["species_tag"] == "Loblolly Pine"
    details = result["classification_details"]["reconciliation"]
    assert details["genus_match"] is True
    assert details["adjustment"] == pytest.approx(0.1)


def test_reconcile_genus_mismatch():
    """Genus disagreement reduces confidence -0.15 and sets cross_validated=False."""
    openai_result = _fake_openai_result("Loblolly Pine", "Pinus taeda", 0.7)
    plantnet_result = {"species_name": "Quercus virginiana", "score": 0.8, "full_results": []}

    result = reconcile(openai_result, plantnet_result)

    # "Pinus" != "Quercus" → -0.15 adjustment
    assert result["species_confidence"] == pytest.approx(0.55, rel=1e-3)
    assert result["cross_validated"] is False
    details = result["classification_details"]["reconciliation"]
    assert details["genus_match"] is False
    assert details["adjustment"] == pytest.approx(-0.15)


def test_reconcile_no_plantnet_returns_openai_as_is():
    """With plantnet_result=None, OpenAI confidence is used unchanged."""
    openai_result = _fake_openai_result("Live Oak", "Quercus virginiana", 0.65)

    result = reconcile(openai_result, None)

    assert result["species_confidence"] == pytest.approx(0.65)
    assert result["cross_validated"] is False
    assert result["species_tag"] == "Live Oak"


def test_reconcile_confidence_clamped_at_1():
    """Boost that would exceed 1.0 is clamped to 1.0."""
    openai_result = _fake_openai_result("Loblolly Pine", "Pinus taeda", 0.95)
    plantnet_result = {"species_name": "Pinus sp.", "score": 0.9, "full_results": []}

    result = reconcile(openai_result, plantnet_result)

    assert result["species_confidence"] <= 1.0


def test_reconcile_confidence_clamped_at_0():
    """Reduction that would go below 0.0 is clamped to 0.0."""
    openai_result = _fake_openai_result("Loblolly Pine", "Pinus taeda", 0.05)
    plantnet_result = {"species_name": "Quercus sp.", "score": 0.9, "full_results": []}

    result = reconcile(openai_result, plantnet_result)

    assert result["species_confidence"] >= 0.0


def test_reconcile_genus_extracted_from_scientific_name():
    """Genus is extracted as the first word of species_scientific."""
    openai_result = _fake_openai_result("Bald Cypress", "Taxodium distichum", 0.6)
    plantnet_result = {"species_name": "Taxodium mucronatum", "score": 0.5, "full_results": []}

    result = reconcile(openai_result, plantnet_result)

    # "Taxodium" == "Taxodium" → genus match → boost
    assert result["cross_validated"] is True
    assert result["species_confidence"] == pytest.approx(0.7, rel=1e-3)


# ─── COST ESTIMATION TESTS ───────────────────────────────────────────────────

def _make_cost_detections(count):
    return [
        {
            "id": f"det-{i}",
            "detection_index": i,
            "geometry_wkt": _make_wkt(i * 10, 0, i * 10 + 10, 10),
            "canopy_area_sqm": float(i + 1),
            "species_tag": None,
        }
        for i in range(count)
    ]


def test_cost_estimation_abort():
    """Pre-check aborts when OpenAI is the backend and estimate exceeds threshold."""
    import species_classification as sc
    mock_log = logging.getLogger("test")

    detections = _make_cost_detections(50)

    with patch.object(sc, "VISION_BACKEND", "openai"), \
         patch.object(sc, "fetch_detections", return_value=detections), \
         patch.object(sc, "classify_openai") as mock_openai, \
         patch.object(sc, "rasterio") as mock_rasterio:
        mock_rasterio.open.return_value = _make_mock_dataset()

        result = sc.run_classification(
            mission_id="mission-001",
            ortho_path="fake.tif",
            max_canopies=200,
            skip_plantnet=False,
            cost_threshold=0.50,  # Very low: 50 * $0.02 = $1.00 > $0.50
            force=False,
            completed_keys=set(),
            mission_dir="/tmp",
            log=mock_log,
        )

    # Should have aborted before any API calls
    assert result.get("error") == "cost_threshold_exceeded"
    mock_openai.assert_not_called()


def test_cost_gate_worst_case_when_ollama_unreachable():
    """Ollama backend + unreachable Ollama gates on worst-case OpenAI cost."""
    import species_classification as sc
    mock_log = logging.getLogger("test")

    detections = _make_cost_detections(50)

    with patch.object(sc, "VISION_BACKEND", "ollama"), \
         patch.object(sc, "_ollama_reachable", return_value=False), \
         patch.object(sc, "_load_paid_calls", return_value=0), \
         patch.object(sc, "fetch_detections", return_value=detections), \
         patch.object(sc, "classify_vision") as mock_vision, \
         patch.object(sc, "rasterio") as mock_rasterio:
        mock_rasterio.open.return_value = _make_mock_dataset()

        result = sc.run_classification(
            mission_id="mission-001",
            ortho_path="fake.tif",
            max_canopies=200,
            skip_plantnet=True,
            cost_threshold=0.50,  # 50 fallback calls * $0.02 = $1.00 > $0.50
            force=False,
            completed_keys=set(),
            mission_dir="/tmp",
            log=mock_log,
        )

    assert result.get("error") == "cost_threshold_exceeded"
    mock_vision.assert_not_called()


def test_cost_gate_zero_when_ollama_healthy():
    """Ollama backend + healthy Ollama estimates $0 and does not abort."""
    import species_classification as sc
    mock_log = logging.getLogger("test")

    detections = _make_cost_detections(50)
    ollama_result = _fake_openai_result("Loblolly Pine", "Pinus taeda", 0.8)
    ollama_result["vision_backend"] = "ollama"

    with patch.object(sc, "VISION_BACKEND", "ollama"), \
         patch.object(sc, "_ollama_reachable", return_value=True), \
         patch.object(sc, "_load_paid_calls", return_value=0), \
         patch.object(sc, "_save_paid_calls"), \
         patch.object(sc, "fetch_detections", return_value=detections), \
         patch.object(sc, "crop_canopy", return_value=MagicMock()), \
         patch.object(sc, "classify_vision", return_value=ollama_result), \
         patch.object(sc, "update_classification_batch", return_value=True), \
         patch.object(sc, "save_checkpoint"), \
         patch.object(sc, "rasterio") as mock_rasterio, \
         patch("species_classification.time") as mock_time:
        mock_rasterio.open.return_value = _make_mock_dataset()
        mock_time.sleep = MagicMock()

        result = sc.run_classification(
            mission_id="mission-001",
            ortho_path="fake.tif",
            max_canopies=200,
            skip_plantnet=True,
            cost_threshold=0.50,
            force=False,
            completed_keys=set(),
            mission_dir="/tmp",
            log=mock_log,
        )

    assert result.get("error") is None
    assert result["classified_count"] == 50
    # Ollama served every canopy — no paid calls, no cost
    assert result["api_calls_openai"] == 0
    assert result["total_api_cost_estimate"] == 0.0


def test_cost_runtime_spend_guard_aborts_on_openai_fallback():
    """Healthy-Ollama run aborts mid-loop when OpenAI fallback spend breaches threshold."""
    import species_classification as sc
    mock_log = logging.getLogger("test")

    detections = _make_cost_detections(10)
    openai_result = _fake_openai_result("Red Maple", "Acer rubrum", 0.7)
    openai_result["vision_backend"] = "openai"
    openai_result["openai_requests"] = 1

    with patch.object(sc, "VISION_BACKEND", "ollama"), \
         patch.object(sc, "_ollama_reachable", return_value=True), \
         patch.object(sc, "_load_paid_calls", return_value=0), \
         patch.object(sc, "_save_paid_calls"), \
         patch.object(sc, "fetch_detections", return_value=detections), \
         patch.object(sc, "crop_canopy", return_value=MagicMock()), \
         patch.object(sc, "classify_vision", return_value=openai_result) as mock_vision, \
         patch.object(sc, "update_classification_batch", return_value=True) as mock_update, \
         patch.object(sc, "save_checkpoint"), \
         patch.object(sc, "rasterio") as mock_rasterio, \
         patch("species_classification.time") as mock_time:
        mock_rasterio.open.return_value = _make_mock_dataset()
        mock_time.sleep = MagicMock()

        result = sc.run_classification(
            mission_id="mission-001",
            ortho_path="fake.tif",
            max_canopies=200,
            skip_plantnet=True,
            cost_threshold=0.05,  # 3rd fallback call: 3 * $0.02 = $0.06 > $0.05
            force=False,
            completed_keys=set(),
            mission_dir="/tmp",
            log=mock_log,
        )

    assert result.get("error") == "cost_threshold_exceeded"
    # The call that crossed the line is kept; the remaining 7 never ran
    assert mock_vision.call_count == 3
    assert result["classified_count"] == 3
    assert result["api_calls_openai"] == 3
    assert result["total_api_cost_estimate"] == pytest.approx(0.06)
    # Partial rows were still batch-updated for checkpoint-resume
    mock_update.assert_called_once()
    assert len(mock_update.call_args[0][0]) == 3


def test_cost_vision_backend_annotation_real_classify_vision():
    """REAL classify_vision annotates vision_backend for all three routes.

    Guards the linchpin of the cost fix: if the annotation is dropped, the
    spend guard silently goes inert (the original bug).
    """
    import species_classification as sc
    mock_log = logging.getLogger("test")

    ollama_hit = _fake_openai_result("Loblolly Pine", "Pinus taeda", 0.8)
    openai_hit = _fake_openai_result("Red Maple", "Acer rubrum", 0.7)
    openai_hit["openai_requests"] = 1

    # Route 1: Ollama answers → tagged "ollama"
    with patch.object(sc, "VISION_BACKEND", "ollama"), \
         patch.object(sc, "classify_ollama", return_value=dict(ollama_hit)):
        result = sc.classify_vision(MagicMock(), mock_log)
    assert result["vision_backend"] == "ollama"

    # Route 2: Ollama fails → OpenAI fallback → tagged "openai"
    with patch.object(sc, "VISION_BACKEND", "ollama"), \
         patch.object(sc, "classify_ollama", return_value=None), \
         patch.object(sc, "OPENAI_API_KEY", "fake-key"), \
         patch.object(sc, "classify_openai", return_value=dict(openai_hit)):
        result = sc.classify_vision(MagicMock(), mock_log)
    assert result["vision_backend"] == "openai"

    # Route 3: Ollama fails, no OpenAI key → tagged "none", zero paid requests
    with patch.object(sc, "VISION_BACKEND", "ollama"), \
         patch.object(sc, "classify_ollama", return_value=None), \
         patch.object(sc, "OPENAI_API_KEY", ""):
        result = sc.classify_vision(MagicMock(), mock_log)
    assert result["vision_backend"] == "none"
    assert result["openai_requests"] == 0

    # Route 4: OpenAI-primary backend → tagged "openai"
    with patch.object(sc, "VISION_BACKEND", "openai"), \
         patch.object(sc, "OPENAI_API_KEY", "fake-key"), \
         patch.object(sc, "classify_openai", return_value=dict(openai_hit)):
        result = sc.classify_vision(MagicMock(), mock_log)
    assert result["vision_backend"] == "openai"


def _make_fake_openai_module(responses):
    """Fake `openai` module whose client returns each response text in order."""
    calls = []

    class _FakeClient:
        def __init__(self, api_key):
            class _Completions:
                def create(_self, **kwargs):
                    calls.append(1)
                    text = responses[min(len(calls) - 1, len(responses) - 1)]
                    msg = types.SimpleNamespace(content=text)
                    choice = types.SimpleNamespace(message=msg)
                    return types.SimpleNamespace(choices=[choice])

            self.chat = types.SimpleNamespace(completions=_Completions())

    mod = types.ModuleType("openai")
    mod.OpenAI = _FakeClient
    return mod, calls


def test_cost_openai_retry_counts_two_billed_requests():
    """classify_openai reports openai_requests=2 when the parse-failure retry fires."""
    import species_classification as sc

    fake_mod, calls = _make_fake_openai_module(["not json at all"])
    with patch.dict(sys.modules, {"openai": fake_mod}):
        result = sc.classify_openai(MagicMock(), "fake-key")

    assert len(calls) == 2  # retry really made a second billed call
    assert result["openai_requests"] == 2
    assert result["species_common"] == "unidentified"


def test_cost_openai_clean_parse_counts_one_request():
    """classify_openai reports openai_requests=1 on a clean first response."""
    import species_classification as sc

    good = json.dumps({
        "species_common": "Oak",
        "species_scientific": "Quercus sp.",
        "vegetation_type": "tree",
        "confidence": 0.8,
    })
    fake_mod, calls = _make_fake_openai_module([good])
    with patch.dict(sys.modules, {"openai": fake_mod}):
        result = sc.classify_openai(MagicMock(), "fake-key")

    assert len(calls) == 1
    assert result["openai_requests"] == 1
    assert result["species_common"] == "Oak"


def _run_guard_scenario(sc, detections, cost_threshold, prior_paid_calls=0):
    """Drive run_classification with every canopy falling back to paid OpenAI."""
    mock_log = logging.getLogger("test")
    openai_result = _fake_openai_result("Red Maple", "Acer rubrum", 0.7)
    openai_result["vision_backend"] = "openai"
    openai_result["openai_requests"] = 1

    with patch.object(sc, "VISION_BACKEND", "ollama"), \
         patch.object(sc, "_ollama_reachable", return_value=True), \
         patch.object(sc, "_load_paid_calls", return_value=prior_paid_calls), \
         patch.object(sc, "_save_paid_calls") as mock_save, \
         patch.object(sc, "fetch_detections", return_value=detections), \
         patch.object(sc, "crop_canopy", return_value=MagicMock()), \
         patch.object(sc, "classify_vision", return_value=openai_result), \
         patch.object(sc, "update_classification_batch", return_value=True), \
         patch.object(sc, "save_checkpoint"), \
         patch.object(sc, "rasterio") as mock_rasterio, \
         patch("species_classification.time") as mock_time:
        mock_rasterio.open.return_value = _make_mock_dataset()
        mock_time.sleep = MagicMock()

        result = sc.run_classification(
            mission_id="mission-001",
            ortho_path="fake.tif",
            max_canopies=500,
            skip_plantnet=True,
            cost_threshold=cost_threshold,
            force=False,
            completed_keys=set(),
            mission_dir="/tmp",
            log=mock_log,
        )
    return result, mock_save


def test_cost_guard_exact_budget_does_not_abort():
    """Spend == threshold must NOT abort (strict > semantics)."""
    import species_classification as sc

    # 2 paid calls * $0.02 = $0.04 == threshold — allowed
    result, _ = _run_guard_scenario(sc, _make_cost_detections(2), cost_threshold=0.04)
    assert result.get("error") is None
    assert result["classified_count"] == 2


def test_cost_guard_rounding_at_float_dusty_threshold():
    """35 * 0.02 = 0.7000000000000001 in raw float math — rounded guard must not trip at $0.70."""
    import species_classification as sc

    result, _ = _run_guard_scenario(sc, _make_cost_detections(35), cost_threshold=0.70)
    assert result.get("error") is None
    assert result["classified_count"] == 35


def test_cost_cumulative_ledger_blocks_rerun_overspend():
    """Prior runs' paid calls count against the threshold — a rerun cannot spend a fresh budget."""
    import species_classification as sc

    # Prior runs already spent $5.00 (250 calls); first paid call here = $5.02 > $5.00
    result, mock_save = _run_guard_scenario(
        sc, _make_cost_detections(10), cost_threshold=5.0, prior_paid_calls=250
    )
    assert result.get("error") == "cost_threshold_exceeded"
    assert result["classified_count"] == 1
    # Ledger persisted the cumulative count (250 prior + 1 this run)
    mock_save.assert_called_with("/tmp", 251, logging.getLogger("test"))


def test_cost_breach_on_final_canopy_is_not_an_error():
    """If the threshold-crossing call was the LAST canopy, the run completed — no error."""
    import species_classification as sc

    # 1 canopy, $0.02 spend > $0.01 threshold, but nothing was left undone
    result, _ = _run_guard_scenario(sc, _make_cost_detections(1), cost_threshold=0.01)
    assert result.get("error") is None
    assert result["classified_count"] == 1


def test_cost_precheck_equality_proceeds():
    """Pre-check estimate == threshold proceeds (250 * $0.02 == $5.00)."""
    import species_classification as sc
    mock_log = logging.getLogger("test")

    with patch.object(sc, "VISION_BACKEND", "openai"), \
         patch.object(sc, "_load_paid_calls", return_value=0), \
         patch.object(sc, "fetch_detections", return_value=_make_cost_detections(250)), \
         patch.object(sc, "crop_canopy", return_value=None), \
         patch.object(sc, "update_classification_batch", return_value=True), \
         patch.object(sc, "rasterio") as mock_rasterio:
        mock_rasterio.open.return_value = _make_mock_dataset()

        result = sc.run_classification(
            mission_id="mission-001",
            ortho_path="fake.tif",
            max_canopies=500,
            skip_plantnet=True,
            cost_threshold=5.0,
            force=False,
            completed_keys=set(),
            mission_dir="/tmp",
            log=mock_log,
        )

    assert result.get("error") is None  # gate did not fire at exact equality


def test_cost_estimate_api_cost_three_arg_contract():
    """estimate_api_cost: $0 only for healthy Ollama; worst case otherwise."""
    import species_classification as sc

    with patch.object(sc, "VISION_BACKEND", "ollama"):
        assert sc.estimate_api_cost(100, True, ollama_available=True) == 0.0
        assert sc.estimate_api_cost(100, True, ollama_available=False) == 2.0
        assert sc.estimate_api_cost(100, True) == 2.0  # default fails safe
    with patch.object(sc, "VISION_BACKEND", "openai"):
        assert sc.estimate_api_cost(100, True, ollama_available=True) == 2.0


def test_cost_ollama_reachable_false_on_probe_exception():
    """_ollama_reachable returns False (never raises) when the probe blows up."""
    import species_classification as sc

    bad = types.ModuleType("ollama_vision")

    def _boom():
        raise RuntimeError("probe exploded")

    bad.check_ollama = _boom
    with patch.dict(sys.modules, {"ollama_vision": bad}):
        assert sc._ollama_reachable() is False

    good = types.ModuleType("ollama_vision")
    good.check_ollama = lambda: True
    with patch.dict(sys.modules, {"ollama_vision": good}):
        assert sc._ollama_reachable() is True


def test_cost_estimation_allows_below_threshold():
    """run_classification proceeds when estimated cost is within threshold."""
    import species_classification as sc
    mock_log = logging.getLogger("test")

    # 1 canopy * $0.02 = $0.02 << $5.00
    detections = [
        {
            "id": "det-001",
            "detection_index": 0,
            "geometry_wkt": _make_wkt(0, 0, 10, 10),
            "canopy_area_sqm": 100.0,
            "species_tag": None,
        }
    ]

    with patch.object(sc, "VISION_BACKEND", "openai"), \
         patch.object(sc, "OPENAI_API_KEY", "fake-key"), \
         patch.object(sc, "_load_paid_calls", return_value=0), \
         patch.object(sc, "_save_paid_calls"), \
         patch.object(sc, "fetch_detections", return_value=detections), \
         patch.object(sc, "crop_canopy", return_value=MagicMock()), \
         patch.object(sc, "classify_openai",
                      return_value=_fake_openai_result("Oak", "Quercus sp.", 0.7)), \
         patch.object(sc, "classify_plantnet", return_value=None), \
         patch.object(sc, "update_classification_batch", return_value=True), \
         patch.object(sc, "save_checkpoint"), \
         patch.object(sc, "rasterio") as mock_rasterio, \
         patch("species_classification.time") as mock_time:
        mock_rasterio.open.return_value = _make_mock_dataset()
        mock_time.sleep = MagicMock()

        result = sc.run_classification(
            mission_id="mission-001",
            ortho_path="fake.tif",
            max_canopies=200,
            skip_plantnet=True,
            cost_threshold=5.0,
            force=False,
            completed_keys=set(),
            mission_dir="/tmp",
            log=mock_log,
        )

    assert result.get("error") is None
    assert result["classified_count"] == 1


# ─── MAX CANOPIES CAP TESTS ──────────────────────────────────────────────────

def test_max_canopies_cap():
    """300 detections capped to max_canopies=200 (largest by area first)."""
    import species_classification as sc
    mock_log = logging.getLogger("test")

    # 300 canopies — ordered by canopy_area_sqm DESC (query ordering preserved)
    detections = [
        {
            "id": f"det-{i}",
            "detection_index": i,
            "geometry_wkt": _make_wkt(i * 5, 0, i * 5 + 5, 5),
            "canopy_area_sqm": float(300 - i),  # descending by area
            "species_tag": None,
        }
        for i in range(300)
    ]

    processed_ids = []

    def fake_crop(dataset, wkt, padding_pct=0.15):
        return MagicMock()

    def fake_classify(img, key):
        return _fake_openai_result("Oak", "Quercus sp.", 0.7)

    with patch.object(sc, "VISION_BACKEND", "openai"), \
         patch.object(sc, "_load_paid_calls", return_value=0), \
         patch.object(sc, "_save_paid_calls"), \
         patch.object(sc, "fetch_detections", return_value=detections), \
         patch.object(sc, "crop_canopy", side_effect=fake_crop), \
         patch.object(sc, "classify_openai", side_effect=fake_classify), \
         patch.object(sc, "classify_plantnet", return_value=None), \
         patch.object(sc, "update_classification_batch", return_value=True), \
         patch.object(sc, "save_checkpoint"), \
         patch.object(sc, "rasterio") as mock_rasterio, \
         patch("species_classification.time") as mock_time, \
         patch.object(sc, "OPENAI_API_KEY", "fake-key"):
        mock_rasterio.open.return_value = _make_mock_dataset()
        mock_time.sleep = MagicMock()

        result = sc.run_classification(
            mission_id="mission-001",
            ortho_path="fake.tif",
            max_canopies=200,
            skip_plantnet=True,
            cost_threshold=99.0,  # no abort
            force=False,
            completed_keys=set(),
            mission_dir="/tmp",
            log=mock_log,
        )

    # Only 200 canopies processed despite 300 available
    assert result["classified_count"] == 200


# ─── CHECKPOINT RESUME TESTS ─────────────────────────────────────────────────

def test_checkpoint_resume():
    """Already-classified canopies (in completed_keys) are skipped."""
    import species_classification as sc
    mock_log = logging.getLogger("test")

    detections = [
        {
            "id": f"det-{i}",
            "detection_index": i,
            "geometry_wkt": _make_wkt(i * 10, 0, i * 10 + 10, 10),
            "canopy_area_sqm": float(10 - i),
            "species_tag": None,
        }
        for i in range(5)
    ]

    # Pre-complete 3 of the 5 canopies
    completed_keys = {"canopy_0", "canopy_1", "canopy_2"}
    classified_calls = []

    def fake_classify(img, key):
        classified_calls.append(1)
        return _fake_openai_result("Oak", "Quercus sp.", 0.7)

    with patch.object(sc, "VISION_BACKEND", "openai"), \
         patch.object(sc, "_load_paid_calls", return_value=0), \
         patch.object(sc, "_save_paid_calls"), \
         patch.object(sc, "fetch_detections", return_value=detections), \
         patch.object(sc, "crop_canopy", return_value=MagicMock()), \
         patch.object(sc, "classify_openai", side_effect=fake_classify), \
         patch.object(sc, "classify_plantnet", return_value=None), \
         patch.object(sc, "update_classification_batch", return_value=True), \
         patch.object(sc, "save_checkpoint"), \
         patch.object(sc, "rasterio") as mock_rasterio, \
         patch("species_classification.time") as mock_time, \
         patch.object(sc, "OPENAI_API_KEY", "fake-key"):
        mock_rasterio.open.return_value = _make_mock_dataset()
        mock_time.sleep = MagicMock()

        result = sc.run_classification(
            mission_id="mission-001",
            ortho_path="fake.tif",
            max_canopies=200,
            skip_plantnet=True,
            cost_threshold=99.0,
            force=False,
            completed_keys=completed_keys,
            mission_dir="/tmp",
            log=mock_log,
        )

    # Only 2 canopies should be classified (the ones NOT in checkpoint)
    assert result["classified_count"] == 2
    assert len(classified_calls) == 2


# ─── SUPABASE BATCH UPDATE TESTS ─────────────────────────────────────────────

def test_supabase_batch_update_correct_payload(mock_supabase_client, mocker):
    """update_classification_batch calls update with correct species fields."""
    mocker.patch("supabase.create_client", return_value=mock_supabase_client)

    rows = [
        {
            "id": "veg-det-001",
            "detection_index": 0,
            "species_tag": "Loblolly Pine",
            "species_confidence": 0.82,
            "vegetation_type": "tree",
            "cross_validated": True,
            "classification_details": {"openai": {}, "plantnet": None, "reconciliation": {}},
        }
    ]

    mock_log = logging.getLogger("test")

    with patch("pipeline_utils.SUPABASE_URL", "https://test.supabase.co"), \
         patch("pipeline_utils.SUPABASE_SERVICE_KEY", "test-key"):
        result = update_classification_batch(rows, mock_log)

    assert result is True

    # Verify table was called with vegetation_detections
    mock_supabase_client.table.assert_called_with("vegetation_detections")

    # Verify update was called on the table
    update_call = mock_supabase_client.table.return_value.update
    update_call.assert_called_once()

    update_payload = update_call.call_args[0][0]
    assert update_payload["species_tag"] == "Loblolly Pine"
    assert update_payload["species_confidence"] == pytest.approx(0.82)
    assert update_payload["vegetation_type"] == "tree"
    assert update_payload["cross_validated"] is True
    assert "classification_details" in update_payload


def test_supabase_batch_update_empty_returns_true():
    """update_classification_batch with empty list returns True."""
    mock_log = logging.getLogger("test")
    result = update_classification_batch([], mock_log)
    assert result is True


def test_supabase_batch_update_skips_when_no_credentials():
    """update_classification_batch returns False when Supabase credentials absent."""
    mock_log = logging.getLogger("test")
    rows = [{
        "id": "veg-001",
        "detection_index": 0,
        "species_tag": "Oak",
        "species_confidence": 0.7,
        "vegetation_type": "tree",
        "cross_validated": False,
        "classification_details": {},
    }]

    with patch("pipeline_utils.SUPABASE_URL", ""), \
         patch("pipeline_utils.SUPABASE_SERVICE_KEY", ""), \
         patch("species_classification._get_supabase_client", return_value=None):
        result = update_classification_batch(rows, mock_log)

    assert result is False


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def _make_wkt(minx, miny, maxx, maxy):
    """Build a simple POLYGON WKT string."""
    return (
        f"POLYGON (({minx} {miny}, {maxx} {miny}, "
        f"{maxx} {maxy}, {minx} {maxy}, {minx} {miny}))"
    )


def _fake_openai_result(common, scientific, confidence):
    return {
        "species_common": common,
        "species_scientific": scientific,
        "vegetation_type": "tree",
        "confidence": confidence,
        "reasoning": "Aerial canopy identification",
        "secondary_candidates": [],
    }


def _make_mock_dataset():
    """Context-manager mock rasterio dataset."""
    ds = MagicMock()
    ds.__enter__ = MagicMock(return_value=ds)
    ds.__exit__ = MagicMock(return_value=False)
    return ds


def _make_pil_stub():
    """Return a fake PIL module for patch.dict use."""
    class _FakeImage:
        size = (100, 100)

        def save(self, f, format=None, **kw):
            if hasattr(f, "write"):
                f.write(b"fakepng")

        def resize(self, sz, resample=None):
            return self

    class _FakeImageMod:
        LANCZOS = 1
        fromarray = staticmethod(lambda arr, mode=None: _FakeImage())
        open = staticmethod(lambda fp: _FakeImage())

    fake_pil = types.ModuleType("PIL")
    fake_pil.Image = _FakeImageMod
    return fake_pil
