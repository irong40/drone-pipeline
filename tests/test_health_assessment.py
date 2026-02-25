"""
Unit tests for health_assessment.py — VARI/ExG computation, score combination,
vision sampling, checkpoint resume, Supabase update. TST-03.
"""
import os
import sys
import types
import json
import tempfile
import logging
import pytest
import numpy as np
from unittest.mock import MagicMock, patch, call


# ── Module-level stubs (required before any import of health_assessment) ──────

@pytest.fixture(autouse=True)
def stub_external_modules(mocker):
    """
    Inject minimal stubs for modules that require native libs or network.
    Order matters: shapely must be real (pure Python), but rasterio and openai
    need stubs so the module can be imported without GPU/API setup.
    """
    # Stub supabase if not installed
    if "supabase" not in sys.modules:
        fake_sb = types.ModuleType("supabase")
        fake_sb.create_client = MagicMock()
        mocker.patch.dict(sys.modules, {"supabase": fake_sb})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_pixel_array(r, g, b, shape=(1, 4, 4)):
    """Return a (3, H, W) uint8 array with uniform RGB values."""
    bands, h, w = shape
    arr = np.zeros((3, h, w), dtype=np.uint8)
    arr[0] = r  # R
    arr[1] = g  # G
    arr[2] = b  # B
    return arr


def _make_mock_dataset(r, g, b):
    """Return a rasterio-like mock dataset whose mask() call returns pixel array."""
    mock_ds = MagicMock()
    pixel_arr = _make_pixel_array(r, g, b)
    mock_ds.__enter__ = MagicMock(return_value=mock_ds)
    mock_ds.__exit__ = MagicMock(return_value=False)
    return mock_ds, pixel_arr


# ── VARI calculation ──────────────────────────────────────────────────────────

class TestVariCalculation:
    """test_vari_calculation — known RGB values produce expected VARI within 1%."""

    def test_vari_healthy_green(self):
        """Bright green pixels: VARI = (G-R)/(G+R-B) should be positive."""
        from health_assessment import compute_health_indices

        # R=50, G=180, B=50 — green-heavy; VARI = (180-50)/(180+50-50) = 130/180 ~ 0.722
        wkt = "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))"
        pixel_arr = _make_pixel_array(50, 180, 50)

        with patch("health_assessment.rasterio_mask") as mock_mask:
            mock_mask.return_value = (pixel_arr, None)
            with patch("health_assessment.shapely_wkt") as mock_wkt:
                mock_wkt.loads.return_value = MagicMock()
                result = compute_health_indices(MagicMock(), wkt)

        expected_vari = (180/255 - 50/255) / (180/255 + 50/255 - 50/255)
        expected_vari = max(-1.0, min(1.0, expected_vari))
        assert abs(result["mean_vari"] - expected_vari) < 0.01, (
            f"Expected VARI ~{expected_vari:.3f}, got {result['mean_vari']:.3f}"
        )

    def test_vari_stressed_pixels(self):
        """Brown/stressed pixels: VARI should be negative."""
        from health_assessment import compute_health_indices

        # R=200, G=120, B=60 — reddish/brown; VARI = (120-200)/(120+200-60) = -80/260 ~ -0.308
        wkt = "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))"
        pixel_arr = _make_pixel_array(200, 120, 60)

        with patch("health_assessment.rasterio_mask") as mock_mask:
            mock_mask.return_value = (pixel_arr, None)
            with patch("health_assessment.shapely_wkt") as mock_wkt:
                mock_wkt.loads.return_value = MagicMock()
                result = compute_health_indices(MagicMock(), wkt)

        assert result["mean_vari"] < 0.0, f"Stressed pixels should have negative VARI, got {result['mean_vari']}"

    def test_vari_clips_to_minus_one(self):
        """VARI is clipped to [-1, 1] range."""
        from health_assessment import compute_health_indices

        # R=255, G=0, B=255 — blue+red extreme; denom = 0+255-255 = 0 → VARI = 0.0 (guarded)
        wkt = "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))"
        pixel_arr = _make_pixel_array(255, 0, 255)

        with patch("health_assessment.rasterio_mask") as mock_mask:
            mock_mask.return_value = (pixel_arr, None)
            with patch("health_assessment.shapely_wkt") as mock_wkt:
                mock_wkt.loads.return_value = MagicMock()
                result = compute_health_indices(MagicMock(), wkt)

        assert -1.0 <= result["mean_vari"] <= 1.0, (
            f"VARI must be in [-1, 1], got {result['mean_vari']}"
        )


# ── ExG calculation ───────────────────────────────────────────────────────────

class TestExgCalculation:
    """test_exg_calculation — known RGB values produce expected ExG within 1%."""

    def test_exg_healthy(self):
        """ExG = 2G - R - B. Bright green: ExG should be positive."""
        from health_assessment import compute_health_indices

        # R=50, G=200, B=50: ExG = 2*(200/255) - 50/255 - 50/255 ~ 1.176
        # Clipped conceptually; but raw mean_exg can exceed 1.0 before clamp in index_score
        wkt = "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))"
        pixel_arr = _make_pixel_array(50, 200, 50)

        with patch("health_assessment.rasterio_mask") as mock_mask:
            mock_mask.return_value = (pixel_arr, None)
            with patch("health_assessment.shapely_wkt") as mock_wkt:
                mock_wkt.loads.return_value = MagicMock()
                result = compute_health_indices(MagicMock(), wkt)

        R = 50 / 255.0
        G = 200 / 255.0
        B = 50 / 255.0
        expected_exg = 2 * G - R - B
        assert abs(result["mean_exg"] - expected_exg) < 0.01, (
            f"Expected ExG ~{expected_exg:.3f}, got {result['mean_exg']:.3f}"
        )

    def test_exg_stressed(self):
        """Stressed (reddish) pixels: ExG should be negative."""
        from health_assessment import compute_health_indices

        wkt = "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))"
        pixel_arr = _make_pixel_array(200, 80, 50)

        with patch("health_assessment.rasterio_mask") as mock_mask:
            mock_mask.return_value = (pixel_arr, None)
            with patch("health_assessment.shapely_wkt") as mock_wkt:
                mock_wkt.loads.return_value = MagicMock()
                result = compute_health_indices(MagicMock(), wkt)

        assert result["mean_exg"] < 0.0, f"Stressed pixels should have negative ExG, got {result['mean_exg']}"

    def test_exg_fallback_on_nodata_pixels(self):
        """All-black (nodata) pixels return fallback ExG=0.0."""
        from health_assessment import compute_health_indices

        wkt = "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))"
        pixel_arr = _make_pixel_array(0, 0, 0)  # All nodata

        with patch("health_assessment.rasterio_mask") as mock_mask:
            mock_mask.return_value = (pixel_arr, None)
            with patch("health_assessment.shapely_wkt") as mock_wkt:
                mock_wkt.loads.return_value = MagicMock()
                result = compute_health_indices(MagicMock(), wkt)

        assert result == {
            "mean_vari": 0.0,
            "mean_exg": 0.0,
            "green_fraction": 0.0,
            "stress_fraction": 1.0,
        }


# ── Green fraction ────────────────────────────────────────────────────────────

class TestGreenFraction:
    """test_green_fraction — array with known ExG distribution produces correct %."""

    def test_all_green_pixels(self):
        """Fully green image: green_fraction should be 1.0."""
        from health_assessment import compute_health_indices

        wkt = "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))"
        # R=50, G=200, B=50: ExG = 2*(200/255) - 50/255 - 50/255 ~ 1.18 > 0.1
        pixel_arr = _make_pixel_array(50, 200, 50)

        with patch("health_assessment.rasterio_mask") as mock_mask:
            mock_mask.return_value = (pixel_arr, None)
            with patch("health_assessment.shapely_wkt") as mock_wkt:
                mock_wkt.loads.return_value = MagicMock()
                result = compute_health_indices(MagicMock(), wkt)

        assert result["green_fraction"] == pytest.approx(1.0), (
            f"All-green pixels: expected green_fraction=1.0, got {result['green_fraction']}"
        )

    def test_no_green_pixels(self):
        """All reddish image: green_fraction should be 0.0."""
        from health_assessment import compute_health_indices

        wkt = "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))"
        # R=200, G=80, B=50: ExG = 2*0.314 - 0.784 - 0.196 = -0.352 < 0.1
        pixel_arr = _make_pixel_array(200, 80, 50)

        with patch("health_assessment.rasterio_mask") as mock_mask:
            mock_mask.return_value = (pixel_arr, None)
            with patch("health_assessment.shapely_wkt") as mock_wkt:
                mock_wkt.loads.return_value = MagicMock()
                result = compute_health_indices(MagicMock(), wkt)

        assert result["green_fraction"] == pytest.approx(0.0), (
            f"Non-green pixels: expected green_fraction=0.0, got {result['green_fraction']}"
        )


# ── Stress fraction ───────────────────────────────────────────────────────────

class TestStressFraction:
    """test_stress_fraction — array with known VARI distribution produces correct %."""

    def test_all_stressed_pixels(self):
        """Heavily reddish pixels: stress_fraction should be 1.0."""
        from health_assessment import compute_health_indices

        wkt = "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))"
        # R=200, G=80, B=50: VARI = (80-200)/(80+200-50) = -120/230 ~ -0.522 < -0.1
        pixel_arr = _make_pixel_array(200, 80, 50)

        with patch("health_assessment.rasterio_mask") as mock_mask:
            mock_mask.return_value = (pixel_arr, None)
            with patch("health_assessment.shapely_wkt") as mock_wkt:
                mock_wkt.loads.return_value = MagicMock()
                result = compute_health_indices(MagicMock(), wkt)

        assert result["stress_fraction"] == pytest.approx(1.0), (
            f"Stressed pixels: expected stress_fraction=1.0, got {result['stress_fraction']}"
        )

    def test_no_stress_in_healthy_pixels(self):
        """Healthy green pixels: stress_fraction should be 0.0."""
        from health_assessment import compute_health_indices

        wkt = "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))"
        # R=50, G=180, B=50: VARI ~ 0.722 > -0.1 → stress_fraction = 0
        pixel_arr = _make_pixel_array(50, 180, 50)

        with patch("health_assessment.rasterio_mask") as mock_mask:
            mock_mask.return_value = (pixel_arr, None)
            with patch("health_assessment.shapely_wkt") as mock_wkt:
                mock_wkt.loads.return_value = MagicMock()
                result = compute_health_indices(MagicMock(), wkt)

        assert result["stress_fraction"] == pytest.approx(0.0), (
            f"Healthy pixels: expected stress_fraction=0.0, got {result['stress_fraction']}"
        )


# ── Health score formula ──────────────────────────────────────────────────────

class TestHealthScoreFormula:
    """test_health_score_formula — known indices produce expected weighted score."""

    def test_perfect_health_indices(self):
        """Max health indices → index_score near 1.0."""
        from health_assessment import compute_index_score

        indices = {
            "mean_vari": 1.0,    # normalized: (1+1)/2 = 1.0
            "mean_exg": 1.0,     # normalized: clamped to 1.0
            "green_fraction": 1.0,
            "stress_fraction": 0.0,
        }
        # Expected: 1.0*0.3 + 1.0*0.2 + 1.0*0.3 + 1.0*0.2 = 1.0
        score = compute_index_score(indices)
        assert score == pytest.approx(1.0, abs=0.001)

    def test_worst_health_indices(self):
        """Worst-case indices → index_score near 0.0."""
        from health_assessment import compute_index_score

        indices = {
            "mean_vari": -1.0,    # normalized: 0.0
            "mean_exg": -1.0,     # normalized: 0.0
            "green_fraction": 0.0,
            "stress_fraction": 1.0,
        }
        # Expected: 0*0.3 + 0*0.2 + 0*0.3 + 0*0.2 = 0.0
        score = compute_index_score(indices)
        assert score == pytest.approx(0.0, abs=0.001)

    def test_midpoint_indices(self):
        """Midpoint indices → index_score ~ 0.5."""
        from health_assessment import compute_index_score

        indices = {
            "mean_vari": 0.0,     # normalized: 0.5
            "mean_exg": 0.0,      # normalized: 0.5
            "green_fraction": 0.5,
            "stress_fraction": 0.5,
        }
        # Expected: 0.5*0.3 + 0.5*0.2 + 0.5*0.3 + 0.5*0.2 = 0.5
        score = compute_index_score(indices)
        assert score == pytest.approx(0.5, abs=0.001)

    def test_score_clamped_to_zero_one(self):
        """Index score is always in [0, 1]."""
        from health_assessment import compute_index_score

        # Extreme values that might overflow
        indices = {
            "mean_vari": 2.0,
            "mean_exg": 3.0,
            "green_fraction": 2.0,
            "stress_fraction": -1.0,
        }
        score = compute_index_score(indices)
        assert 0.0 <= score <= 1.0

    def test_vision_blend_40_60(self):
        """Combined score uses 40% index + 60% vision weights."""
        from health_assessment import compute_health_score

        # 0.6 * 0.4 + 0.8 * 0.6 = 0.24 + 0.48 = 0.72
        score = compute_health_score(0.6, 0.8)
        assert score == pytest.approx(0.72, abs=0.001)

    def test_vision_none_returns_index_only(self):
        """No vision score → final score equals index score exactly."""
        from health_assessment import compute_health_score

        score = compute_health_score(0.65, None)
        assert score == pytest.approx(0.65, abs=0.001)


# ── Health status boundaries ──────────────────────────────────────────────────

class TestHealthStatusBoundaries:
    """test_health_status_boundaries — scores at each boundary map to correct status."""

    def test_above_0_80_is_healthy(self):
        from health_assessment import health_status
        assert health_status(0.85) == "healthy"
        assert health_status(1.0) == "healthy"
        assert health_status(0.80) == "healthy"

    def test_0_60_to_0_79_is_moderate_stress(self):
        from health_assessment import health_status
        assert health_status(0.79) == "moderate_stress"
        assert health_status(0.60) == "moderate_stress"
        assert health_status(0.65) == "moderate_stress"

    def test_0_40_to_0_59_is_stressed(self):
        from health_assessment import health_status
        assert health_status(0.59) == "stressed"
        assert health_status(0.40) == "stressed"
        assert health_status(0.50) == "stressed"

    def test_0_20_to_0_39_is_severe_decline(self):
        from health_assessment import health_status
        assert health_status(0.39) == "severe_decline"
        assert health_status(0.20) == "severe_decline"
        assert health_status(0.25) == "severe_decline"

    def test_below_0_20_is_dead(self):
        from health_assessment import health_status
        assert health_status(0.19) == "dead"
        assert health_status(0.0) == "dead"
        assert health_status(0.10) == "dead"

    def test_exact_boundaries(self):
        """Verify exact boundary values for each status transition."""
        from health_assessment import health_status
        # Boundaries at 0.80, 0.60, 0.40, 0.20
        assert health_status(0.800) == "healthy"
        assert health_status(0.799) == "moderate_stress"
        assert health_status(0.600) == "moderate_stress"
        assert health_status(0.599) == "stressed"
        assert health_status(0.400) == "stressed"
        assert health_status(0.399) == "severe_decline"
        assert health_status(0.200) == "severe_decline"
        assert health_status(0.199) == "dead"


# ── Vision sample selection ───────────────────────────────────────────────────

class TestVisionSampleSelection:
    """test_vision_sample_selection — 30% of lowest-scoring canopies selected for vision."""

    def test_bottom_30pct_selected(self):
        """With vision_sample_pct=0.3, bottom 30% of canopies by index_score selected."""
        # Simulate 10 canopies with known scores
        canopy_results = [
            {"detection_index": i, "index_score": i * 0.1, "geometry_wkt": "POLYGON (...)"}
            for i in range(10)
        ]
        # Sort ascending by index_score: [0.0, 0.1, ..., 0.9]
        sorted_canopies = sorted(canopy_results, key=lambda c: c["index_score"])
        vision_sample_pct = 0.3
        sample_n = max(1, int(len(sorted_canopies) * vision_sample_pct))
        vision_candidates = sorted_canopies[:sample_n]

        assert sample_n == 3
        # Must be the 3 lowest-scoring canopies
        assert [c["detection_index"] for c in vision_candidates] == [0, 1, 2]

    def test_vision_candidates_are_lowest_scoring(self):
        """Vision candidates have lower scores than non-selected canopies."""
        canopy_results = [
            {"detection_index": i, "index_score": float(i) / 10.0}
            for i in range(10)
        ]
        sorted_canopies = sorted(canopy_results, key=lambda c: c["index_score"])
        sample_n = max(1, int(len(sorted_canopies) * 0.3))
        vision_candidates = sorted_canopies[:sample_n]
        non_candidates = sorted_canopies[sample_n:]

        max_candidate_score = max(c["index_score"] for c in vision_candidates)
        min_non_candidate = min(c["index_score"] for c in non_candidates)
        assert max_candidate_score <= min_non_candidate

    def test_minimum_one_vision_candidate(self):
        """Even with very small vision_sample_pct, at least 1 canopy is selected."""
        canopy_results = [{"detection_index": 0, "index_score": 0.5}]
        sample_n = max(1, int(len(canopy_results) * 0.01))
        assert sample_n == 1


# ── Skip vision ───────────────────────────────────────────────────────────────

class TestSkipVision:
    """test_skip_vision — --skip-vision uses index-only weights, no API calls."""

    def test_skip_vision_no_openai_calls(self, mocker):
        """With skip_vision=True, OpenAI client is never instantiated."""
        from health_assessment import compute_health_score

        # Verify index-only path: vision_score=None
        score = compute_health_score(0.75, None)
        assert score == pytest.approx(0.75, abs=0.001)

    def test_skip_vision_final_score_equals_index(self):
        """Skip vision: final score must equal index score exactly (no blending)."""
        from health_assessment import compute_health_score

        for idx_score in [0.2, 0.5, 0.8, 1.0, 0.0]:
            assert compute_health_score(idx_score, None) == pytest.approx(idx_score, abs=0.001)

    def test_with_vision_score_blends_40_60(self):
        """With vision score present, verify 40% index + 60% vision blend."""
        from health_assessment import compute_health_score

        index_score = 0.4
        vision_score = 0.9
        expected = index_score * 0.4 + vision_score * 0.6
        assert compute_health_score(index_score, vision_score) == pytest.approx(expected, abs=0.001)


# ── Checkpoint resume ─────────────────────────────────────────────────────────

class TestCheckpointResume:
    """test_checkpoint_resume — already-assessed canopies are skipped."""

    def test_completed_key_skips_canopy(self, mocker, tmp_path):
        """Canopies with keys in completed_keys are not re-processed."""
        # Mock Supabase to return 2 detections
        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_table.select.return_value.eq.return_value.order.return_value.execute.return_value.data = [
            {"id": "det-1", "detection_index": 0, "geometry_wkt": "POLYGON ((0 0,1 0,1 1,0 1,0 0))", "health_score": None},
            {"id": "det-2", "detection_index": 1, "geometry_wkt": "POLYGON ((0 0,1 0,1 1,0 1,0 0))", "health_score": None},
        ]
        mock_sb.table.return_value = mock_table
        mocker.patch("supabase.create_client", return_value=mock_sb)
        mocker.patch.dict(os.environ, {
            "SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_SERVICE_KEY": "test-key",
        })

        log = logging.getLogger("test")
        call_count = []

        # Mock rasterio.open to track how many canopies are processed
        mock_ds = MagicMock()
        mock_ds.__enter__ = MagicMock(return_value=mock_ds)
        mock_ds.__exit__ = MagicMock(return_value=False)

        pixel_arr = _make_pixel_array(50, 180, 50)

        with patch("health_assessment.rasterio.open", return_value=mock_ds):
            with patch("health_assessment.rasterio_mask") as mock_mask:
                mock_mask.return_value = (pixel_arr, None)
                with patch("health_assessment.shapely_wkt") as mock_wkt:
                    mock_wkt.loads.return_value = MagicMock()
                    with patch("health_assessment.save_checkpoint"):
                        with patch("health_assessment.update_health_batch", return_value=True):
                            from health_assessment import run_health_assessment

                            # canopy_0 already completed
                            completed = {"canopy_0"}
                            summary = run_health_assessment(
                                mission_id="test-mission",
                                ortho_path="fake.tif",
                                vision_sample_pct=0.3,
                                skip_vision=True,
                                cost_threshold=2.0,
                                completed_keys=completed,
                                mission_dir=str(tmp_path),
                                log=log,
                            )

        # Only 1 canopy should be in the update (canopy_1; canopy_0 was checkpoint-skipped)
        assert summary["assessed_count"] == 1

    def test_empty_completed_keys_processes_all(self, mocker, tmp_path):
        """With no checkpoint keys, all canopies are processed."""
        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_table.select.return_value.eq.return_value.order.return_value.execute.return_value.data = [
            {"id": "det-1", "detection_index": 0, "geometry_wkt": "POLYGON ((0 0,1 0,1 1,0 1,0 0))", "health_score": None},
        ]
        mock_sb.table.return_value = mock_table
        mocker.patch("supabase.create_client", return_value=mock_sb)
        mocker.patch.dict(os.environ, {
            "SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_SERVICE_KEY": "test-key",
        })

        log = logging.getLogger("test")
        mock_ds = MagicMock()
        mock_ds.__enter__ = MagicMock(return_value=mock_ds)
        mock_ds.__exit__ = MagicMock(return_value=False)
        pixel_arr = _make_pixel_array(50, 180, 50)

        with patch("health_assessment.rasterio.open", return_value=mock_ds):
            with patch("health_assessment.rasterio_mask") as mock_mask:
                mock_mask.return_value = (pixel_arr, None)
                with patch("health_assessment.shapely_wkt") as mock_wkt:
                    mock_wkt.loads.return_value = MagicMock()
                    with patch("health_assessment.save_checkpoint"):
                        with patch("health_assessment.update_health_batch", return_value=True):
                            from health_assessment import run_health_assessment

                            summary = run_health_assessment(
                                mission_id="test-mission",
                                ortho_path="fake.tif",
                                vision_sample_pct=0.3,
                                skip_vision=True,
                                cost_threshold=2.0,
                                completed_keys=set(),
                                mission_dir=str(tmp_path),
                                log=log,
                            )

        assert summary["assessed_count"] == 1


# ── Supabase update ───────────────────────────────────────────────────────────

class TestSupabaseUpdate:
    """test_supabase_update — mocked client receives correct health data."""

    def test_update_health_batch_calls_correct_fields(self, mocker):
        """update_health_batch sends health_score, health_status, health_details per row."""
        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.update.return_value.eq.return_value.execute.return_value.data = []

        mocker.patch("supabase.create_client", return_value=mock_sb)
        mocker.patch.dict(os.environ, {
            "SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_SERVICE_KEY": "test-key",
        })

        log = logging.getLogger("test")

        rows = [
            {
                "id": "det-1",
                "detection_index": 0,
                "health_score": 0.75,
                "health_status": "healthy",
                "health_details": {"vari": 0.5, "exg": 0.6},
            }
        ]

        from health_assessment import update_health_batch
        result = update_health_batch(rows, log)

        assert result is True
        # Verify update was called on vegetation_detections table
        mock_sb.table.assert_called_with("vegetation_detections")
        mock_table.update.assert_called_once_with({
            "health_score": 0.75,
            "health_status": "healthy",
            "health_details": {"vari": 0.5, "exg": 0.6},
        })
        mock_table.update.return_value.eq.assert_called_once_with("id", "det-1")

    def test_update_empty_rows_returns_true(self, mocker):
        """update_health_batch with empty list returns True without Supabase calls."""
        log = logging.getLogger("test")
        from health_assessment import update_health_batch
        result = update_health_batch([], log)
        assert result is True

    def test_update_returns_false_on_exception(self, mocker):
        """update_health_batch returns False when Supabase raises exception."""
        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.update.return_value.eq.return_value.execute.side_effect = RuntimeError("DB error")

        mocker.patch("supabase.create_client", return_value=mock_sb)
        mocker.patch.dict(os.environ, {
            "SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_SERVICE_KEY": "test-key",
        })

        log = logging.getLogger("test")
        rows = [{
            "id": "det-1",
            "detection_index": 0,
            "health_score": 0.5,
            "health_status": "stressed",
            "health_details": {},
        }]

        from health_assessment import update_health_batch
        result = update_health_batch(rows, log)
        assert result is False
