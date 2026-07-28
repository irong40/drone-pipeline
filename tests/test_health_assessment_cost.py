"""
Cost-protection tests for health_assessment.py (Step E3) — UNIT-E3-COST.

Ports the species_classification cost guard to the health (E3) pipeline:
worst-case pre-check that respects the VISION_BACKEND=ollama default and an
_ollama_reachable() probe, a runtime spend guard that counts billed OpenAI
requests against a per-mission ledger, and the cumulative-ledger rerun block.

All tests are hermetic: VISION_BACKEND and the spend ledger are patched, and no
network / real Ollama / OpenAI is ever touched. The suite drives the real
run_health_assessment / assess_via_vision_router / assess_via_vision code paths
with fakes injected at the module boundary.
"""
import sys
import json
import types
import logging
import pytest
from unittest.mock import MagicMock, patch

# health_assessment imports numpy/rasterio/shapely at module load. Skip the
# whole module (rather than erroring at collection) when they are unavailable.
try:
    import numpy as np
    np.array([1.0])  # verify it's a real module, not a stub
    import health_assessment as ha
    _HEALTH_IMPORTABLE = True
except Exception:  # pragma: no cover - environment guard
    _HEALTH_IMPORTABLE = False

pytestmark = pytest.mark.skipif(
    not _HEALTH_IMPORTABLE,
    reason="numpy/rasterio required for health_assessment cost tests",
)


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def _make_wkt(minx, miny, maxx, maxy):
    return (
        f"POLYGON (({minx} {miny}, {maxx} {miny}, "
        f"{maxx} {maxy}, {minx} {maxy}, {minx} {miny}))"
    )


def _make_health_detections(count):
    """Unassessed canopy detections (health_score=None) for the mission."""
    return [
        {
            "id": f"det-{i}",
            "detection_index": i,
            "geometry_wkt": _make_wkt(i * 10, 0, i * 10 + 10, 10),
            "health_score": None,
        }
        for i in range(count)
    ]


def _make_mock_dataset():
    """Context-manager mock rasterio dataset."""
    ds = MagicMock()
    ds.__enter__ = MagicMock(return_value=ds)
    ds.__exit__ = MagicMock(return_value=False)
    return ds


def _fake_indices():
    return {
        "mean_vari": 0.2,
        "mean_exg": 0.3,
        "green_fraction": 0.5,
        "stress_fraction": 0.2,
    }


def _openai_vision_result():
    """A paid-OpenAI vision result as annotated by assess_via_vision."""
    return {
        "vision_backend": "openai",
        "openai_requests": 1,
        "health_score": 0.7,
        "recommended_action": "monitor",
    }


def _ollama_vision_result():
    """A free Ollama vision result as annotated by assess_via_vision_router."""
    return {
        "vision_backend": "ollama",
        "health_score": 0.8,
        "recommended_action": "monitor",
    }


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


def _run_guard_scenario(
    detections,
    cost_threshold,
    prior_paid_calls=0,
    vision_result=None,
    vision_sample_pct=1.0,
):
    """Drive run_health_assessment with every sampled canopy hitting the router.

    Ollama is reported healthy (pre-check estimate $0), so gating is exercised
    purely by the runtime spend guard. The vision router return value decides
    whether calls are billed (openai) or free (ollama).
    """
    mock_log = logging.getLogger("test")
    if vision_result is None:
        vision_result = _openai_vision_result()

    with patch.object(ha, "VISION_BACKEND", "ollama"), \
         patch.object(ha, "OPENAI_API_KEY", "fake-key"), \
         patch.object(ha, "_ollama_reachable", return_value=True), \
         patch.object(ha, "_load_paid_calls", return_value=prior_paid_calls), \
         patch.object(ha, "_save_paid_calls") as mock_save, \
         patch.object(ha, "fetch_detections", return_value=detections), \
         patch.object(ha, "compute_health_indices", return_value=_fake_indices()), \
         patch.object(ha, "compute_index_score", side_effect=lambda idx: 0.5), \
         patch.object(ha, "crop_canopy_image", return_value=b"fakejpeg"), \
         patch.object(ha, "assess_via_vision_router", return_value=dict(vision_result)) as mock_router, \
         patch.object(ha, "update_health_batch", return_value=True) as mock_update, \
         patch.object(ha, "save_checkpoint"), \
         patch.object(ha, "rasterio") as mock_rasterio:
        mock_rasterio.open.return_value = _make_mock_dataset()

        result = ha.run_health_assessment(
            mission_id="mission-001",
            ortho_path="fake.tif",
            vision_sample_pct=vision_sample_pct,
            skip_vision=False,
            cost_threshold=cost_threshold,
            completed_keys=set(),
            mission_dir="/tmp",
            log=mock_log,
        )
    return result, mock_router, mock_update, mock_save


# ─── PRE-CHECK GATE ──────────────────────────────────────────────────────────

def test_cost_precheck_abort_openai_backend():
    """Pre-check aborts when OpenAI is the backend and estimate exceeds threshold."""
    mock_log = logging.getLogger("test")
    detections = _make_health_detections(50)

    with patch.object(ha, "VISION_BACKEND", "openai"), \
         patch.object(ha, "OPENAI_API_KEY", "fake-key"), \
         patch.object(ha, "_load_paid_calls", return_value=0), \
         patch.object(ha, "fetch_detections", return_value=detections), \
         patch.object(ha, "compute_health_indices", return_value=_fake_indices()), \
         patch.object(ha, "compute_index_score", side_effect=lambda idx: 0.5), \
         patch.object(ha, "assess_via_vision_router") as mock_router, \
         patch.object(ha, "rasterio") as mock_rasterio:
        mock_rasterio.open.return_value = _make_mock_dataset()

        result = ha.run_health_assessment(
            mission_id="mission-001",
            ortho_path="fake.tif",
            vision_sample_pct=1.0,  # 50 candidates * $0.02 = $1.00 > $0.50
            skip_vision=False,
            cost_threshold=0.50,
            completed_keys=set(),
            mission_dir="/tmp",
            log=mock_log,
        )

    assert result.get("error") == "cost_threshold_exceeded"
    assert result["assessed_count"] == 0
    mock_router.assert_not_called()


def test_cost_gate_worst_case_when_ollama_unreachable():
    """Ollama backend + unreachable Ollama gates on worst-case OpenAI cost."""
    mock_log = logging.getLogger("test")
    detections = _make_health_detections(50)

    with patch.object(ha, "VISION_BACKEND", "ollama"), \
         patch.object(ha, "OPENAI_API_KEY", "fake-key"), \
         patch.object(ha, "_ollama_reachable", return_value=False), \
         patch.object(ha, "_load_paid_calls", return_value=0), \
         patch.object(ha, "fetch_detections", return_value=detections), \
         patch.object(ha, "compute_health_indices", return_value=_fake_indices()), \
         patch.object(ha, "compute_index_score", side_effect=lambda idx: 0.5), \
         patch.object(ha, "assess_via_vision_router") as mock_router, \
         patch.object(ha, "rasterio") as mock_rasterio:
        mock_rasterio.open.return_value = _make_mock_dataset()

        result = ha.run_health_assessment(
            mission_id="mission-001",
            ortho_path="fake.tif",
            vision_sample_pct=1.0,  # 50 fallback calls * $0.02 = $1.00 > $0.50
            skip_vision=False,
            cost_threshold=0.50,
            completed_keys=set(),
            mission_dir="/tmp",
            log=mock_log,
        )

    assert result.get("error") == "cost_threshold_exceeded"
    mock_router.assert_not_called()


def test_cost_gate_zero_when_ollama_healthy():
    """Ollama backend + healthy Ollama estimates $0 and does not abort."""
    detections = _make_health_detections(50)
    result, mock_router, _, _ = _run_guard_scenario(
        detections, cost_threshold=0.50, vision_result=_ollama_vision_result()
    )

    assert result.get("error") is None
    assert result["assessed_count"] == 50
    assert result["vision_samples"] == 50
    # Ollama served every canopy — no paid calls, no cost
    assert result["api_calls_openai"] == 0
    assert result["api_cost_estimate"] == 0.0
    assert mock_router.call_count == 50


def test_cost_precheck_equality_proceeds():
    """Pre-check estimate == threshold proceeds (250 * $0.02 == $5.00)."""
    mock_log = logging.getLogger("test")
    detections = _make_health_detections(250)

    with patch.object(ha, "VISION_BACKEND", "openai"), \
         patch.object(ha, "OPENAI_API_KEY", "fake-key"), \
         patch.object(ha, "_load_paid_calls", return_value=0), \
         patch.object(ha, "fetch_detections", return_value=detections), \
         patch.object(ha, "compute_health_indices", return_value=_fake_indices()), \
         patch.object(ha, "compute_index_score", side_effect=lambda idx: 0.5), \
         patch.object(ha, "crop_canopy_image", return_value=None), \
         patch.object(ha, "update_health_batch", return_value=True), \
         patch.object(ha, "save_checkpoint"), \
         patch.object(ha, "rasterio") as mock_rasterio:
        mock_rasterio.open.return_value = _make_mock_dataset()

        result = ha.run_health_assessment(
            mission_id="mission-001",
            ortho_path="fake.tif",
            vision_sample_pct=1.0,
            skip_vision=False,
            cost_threshold=5.0,
            completed_keys=set(),
            mission_dir="/tmp",
            log=mock_log,
        )

    assert result.get("error") is None  # gate did not fire at exact equality


# ─── RUNTIME SPEND GUARD ─────────────────────────────────────────────────────

def test_cost_runtime_spend_guard_aborts_on_openai_fallback():
    """Healthy-Ollama run aborts mid-loop when OpenAI fallback spend breaches threshold."""
    detections = _make_health_detections(10)
    # 3rd fallback call: 3 * $0.02 = $0.06 > $0.05
    result, mock_router, mock_update, _ = _run_guard_scenario(
        detections, cost_threshold=0.05
    )

    assert result.get("error") == "cost_threshold_exceeded"
    # The call that crossed the line is kept; the remaining 7 never hit the router
    assert mock_router.call_count == 3
    assert result["vision_samples"] == 3
    assert result["api_calls_openai"] == 3
    assert result["api_cost_estimate"] == pytest.approx(0.06)
    # Every indexed canopy is still scored (index-only for the un-visioned 7)
    assert result["assessed_count"] == 10
    mock_update.assert_called_once()
    assert len(mock_update.call_args[0][0]) == 10


def test_cost_guard_exact_budget_does_not_abort():
    """Spend == threshold must NOT abort (strict > semantics)."""
    # 2 paid calls * $0.02 = $0.04 == threshold — allowed
    result, mock_router, _, _ = _run_guard_scenario(
        _make_health_detections(2), cost_threshold=0.04
    )
    assert result.get("error") is None
    assert result["vision_samples"] == 2
    assert result["api_calls_openai"] == 2
    assert mock_router.call_count == 2


def test_cost_guard_rounding_at_float_dusty_threshold():
    """35 * 0.02 = 0.7000000000000001 in raw float math — rounded guard must not trip at $0.70."""
    result, _, _, _ = _run_guard_scenario(
        _make_health_detections(35), cost_threshold=0.70
    )
    assert result.get("error") is None
    assert result["vision_samples"] == 35
    assert result["api_calls_openai"] == 35


def test_cost_cumulative_ledger_blocks_rerun_overspend():
    """Prior runs' paid calls count against the threshold — a rerun cannot spend a fresh budget."""
    # Prior runs already spent $5.00 (250 calls); first paid call here = $5.02 > $5.00
    result, mock_router, _, mock_save = _run_guard_scenario(
        _make_health_detections(10), cost_threshold=5.0, prior_paid_calls=250
    )
    assert result.get("error") == "cost_threshold_exceeded"
    assert mock_router.call_count == 1
    assert result["vision_samples"] == 1
    assert result["api_calls_openai"] == 1
    # Ledger persisted the cumulative count (250 prior + 1 this run)
    mock_save.assert_called_with("/tmp", 251, logging.getLogger("test"))


def test_cost_breach_on_final_canopy_is_not_an_error():
    """If the threshold-crossing call was the LAST candidate, the run completed — no error."""
    # 1 candidate, $0.02 spend > $0.01 threshold, but nothing was left undone
    result, mock_router, _, _ = _run_guard_scenario(
        _make_health_detections(1), cost_threshold=0.01
    )
    assert result.get("error") is None
    assert result["vision_samples"] == 1
    assert result["api_calls_openai"] == 1
    assert mock_router.call_count == 1


# ─── VISION-BACKEND ANNOTATION (mutation linchpin) ───────────────────────────

def test_cost_vision_backend_annotation_real_router():
    """REAL assess_via_vision_router annotates vision_backend for all routes.

    Guards the linchpin of the cost fix: if the annotation is dropped, the
    runtime spend guard silently goes inert (the original bug).
    """
    mock_log = logging.getLogger("test")

    # Route 1: Ollama answers (dict lacking the tag) → router tags it "ollama"
    with patch.object(ha, "VISION_BACKEND", "ollama"), \
         patch.object(ha, "assess_via_ollama", return_value={"health_score": 0.8}):
        result = ha.assess_via_vision_router(b"img", mock_log)
    assert result["vision_backend"] == "ollama"

    # Route 2: Ollama fails → OpenAI fallback → "openai"
    with patch.object(ha, "VISION_BACKEND", "ollama"), \
         patch.object(ha, "assess_via_ollama", return_value=None), \
         patch.object(ha, "OPENAI_API_KEY", "fake-key"), \
         patch.object(ha, "assess_via_vision", return_value=_openai_vision_result()):
        result = ha.assess_via_vision_router(b"img", mock_log)
    assert result["vision_backend"] == "openai"

    # Route 3: Ollama fails, no OpenAI key → "none", zero billed requests
    with patch.object(ha, "VISION_BACKEND", "ollama"), \
         patch.object(ha, "assess_via_ollama", return_value=None), \
         patch.object(ha, "OPENAI_API_KEY", ""):
        result = ha.assess_via_vision_router(b"img", mock_log)
    assert result["vision_backend"] == "none"
    assert result["openai_requests"] == 0
    assert result["health_score"] is None

    # Route 4: OpenAI-primary backend → "openai"
    with patch.object(ha, "VISION_BACKEND", "openai"), \
         patch.object(ha, "OPENAI_API_KEY", "fake-key"), \
         patch.object(ha, "assess_via_vision", return_value=_openai_vision_result()):
        result = ha.assess_via_vision_router(b"img", mock_log)
    assert result["vision_backend"] == "openai"


# ─── BILLED-REQUEST COUNTING ─────────────────────────────────────────────────

def test_cost_openai_clean_parse_counts_one_request():
    """assess_via_vision reports openai_requests=1 on a clean first response."""
    mock_log = logging.getLogger("test")
    good = json.dumps({
        "health_score": 0.8,
        "observations": "healthy canopy",
        "recommended_action": "monitor",
    })
    fake_mod, calls = _make_fake_openai_module([good])

    with patch.object(ha, "OPENAI_API_KEY", "fake-key"), \
         patch.dict(sys.modules, {"openai": fake_mod}):
        result = ha.assess_via_vision(b"img", mock_log)

    assert len(calls) == 1
    assert result["openai_requests"] == 1
    assert result["vision_backend"] == "openai"
    assert result["health_score"] == pytest.approx(0.8)


def test_cost_openai_billed_request_counted_on_parse_failure():
    """A billed-but-unparseable OpenAI response is still counted (health does not retry)."""
    mock_log = logging.getLogger("test")
    fake_mod, calls = _make_fake_openai_module(["not json at all {{{"])

    with patch.object(ha, "OPENAI_API_KEY", "fake-key"), \
         patch.dict(sys.modules, {"openai": fake_mod}):
        result = ha.assess_via_vision(b"img", mock_log)

    assert len(calls) == 1  # single billed call — no parse-retry in E3
    assert result["openai_requests"] == 1
    assert result["vision_backend"] == "openai"
    assert result["health_score"] is None  # unusable → caller falls back to index-only


def test_cost_openai_no_key_makes_no_billed_request():
    """assess_via_vision with no key makes zero billed requests and tags 'none'."""
    mock_log = logging.getLogger("test")
    with patch.object(ha, "OPENAI_API_KEY", ""):
        result = ha.assess_via_vision(b"img", mock_log)
    assert result["openai_requests"] == 0
    assert result["vision_backend"] == "none"
    assert result["health_score"] is None


# ─── ESTIMATE + PROBE CONTRACTS ──────────────────────────────────────────────

def test_cost_estimate_vision_cost_two_arg_contract():
    """estimate_vision_cost: $0 only for healthy Ollama; worst case otherwise."""
    with patch.object(ha, "VISION_BACKEND", "ollama"):
        assert ha.estimate_vision_cost(100, ollama_available=True) == 0.0
        assert ha.estimate_vision_cost(100, ollama_available=False) == 2.0
        assert ha.estimate_vision_cost(100) == 2.0  # default fails safe
    with patch.object(ha, "VISION_BACKEND", "openai"):
        assert ha.estimate_vision_cost(100, ollama_available=True) == 2.0


def test_cost_ollama_reachable_false_on_probe_exception():
    """_ollama_reachable returns False (never raises) when the probe blows up."""
    bad = types.ModuleType("ollama_vision")

    def _boom():
        raise RuntimeError("probe exploded")

    bad.check_ollama = _boom
    with patch.dict(sys.modules, {"ollama_vision": bad}):
        assert ha._ollama_reachable() is False

    good = types.ModuleType("ollama_vision")
    good.check_ollama = lambda: True
    with patch.dict(sys.modules, {"ollama_vision": good}):
        assert ha._ollama_reachable() is True


def test_cost_force_clears_spend_ledger(tmp_path):
    """_clear_paid_calls removes the persisted per-mission ledger (used by --force)."""
    mission_dir = str(tmp_path)
    mock_log = logging.getLogger("test")
    ha._save_paid_calls(mission_dir, 7, mock_log)
    assert ha._load_paid_calls(mission_dir) == 7
    ha._clear_paid_calls(mission_dir)
    assert ha._load_paid_calls(mission_dir) == 0
