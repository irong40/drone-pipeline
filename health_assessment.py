"""
Sentinel Aerial Inspections — Health Assessment (Step E3)

Computes per-canopy vegetation health scores using RGB-derived indices (VARI, ExG)
and optional OpenAI Vision API qualitative assessment for the lowest-scoring canopies.

Usage:
    python health_assessment.py --mission-id {uuid} --ortho-path E:\\output\\{id}\\mapping\\orthomosaic.tif
    python health_assessment.py --mission-id {uuid} --ortho-path path.tif --skip-vision
    python health_assessment.py --mission-id {uuid} --ortho-path path.tif --vision-sample-pct 0.5
"""

# ─── ENV CLEANUP (must run before any rasterio/pyproj import) ────────────────
import os
for var in ("PROJ_LIB", "PROJ_DATA"):
    os.environ.pop(var, None)
os.environ["GDAL_CACHEMAX"] = "256"

# ─── STDLIB ──────────────────────────────────────────────────────────────────
import sys
import json
import base64
import argparse
import logging
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# ─── THIRD PARTY ─────────────────────────────────────────────────────────────
import numpy as np
import rasterio
from rasterio.mask import mask as rasterio_mask
from shapely import wkt as shapely_wkt

# ─── PIPELINE MODULES ────────────────────────────────────────────────────────
from checkpoint import load_checkpoint, save_checkpoint, clear_checkpoint
from pipeline_status import PipelineStatusReporter, add_pipeline_args
from pipeline_utils import setup_logging, get_supabase_client

# ─── CONFIG ──────────────────────────────────────────────────────────────────

SCRIPT_NAME = "health_assessment"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# OpenAI model for vision assessment
VISION_MODEL = "gpt-4o"
# Estimated cost per vision call (gpt-4o input image token est.)
COST_PER_VISION_CALL = 0.02  # ~$0.02 per crop at typical drone resolution

# Vision backend: "ollama" (local, free) or "openai" (cloud, ~$0.02/image)
# Ollama is default; falls back to OpenAI if Ollama is unavailable or fails.
VISION_BACKEND = os.environ.get("VISION_BACKEND", "ollama").lower()
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

SUPABASE_BATCH_SIZE = 50




# ─── VEGETATION INDEX COMPUTATION ────────────────────────────────────────────

def compute_health_indices(dataset: rasterio.DatasetReader, polygon_wkt: str) -> Dict[str, float]:
    """Compute VARI, ExG, green_fraction, stress_fraction for a canopy polygon.

    Crops the raster to the exact canopy polygon boundary (no padding) and computes
    vegetation indices on the clean canopy pixels only. Nodata pixels are excluded.

    Args:
        dataset: Open rasterio dataset (orthomosaic GeoTIFF).
        polygon_wkt: WKT string of the canopy polygon (in dataset CRS).

    Returns:
        Dict with keys: mean_vari, mean_exg, green_fraction, stress_fraction.
        Returns fallback values (0.0) on error rather than raising.
    """
    fallback = {
        "mean_vari": 0.0,
        "mean_exg": 0.0,
        "green_fraction": 0.0,
        "stress_fraction": 1.0,
    }
    try:
        polygon = shapely_wkt.loads(polygon_wkt)
        # rasterio.mask.mask() crops to polygon shape — no padding
        pixels, _ = rasterio_mask(
            dataset,
            [polygon],
            crop=True,
            nodata=0,
            all_touched=False,
            filled=True,
        )
        # pixels shape: (bands, height, width)
        if pixels.shape[0] < 3:
            return fallback

        # Use only RGB bands (first 3)
        r_band = pixels[0].astype(np.float64)
        g_band = pixels[1].astype(np.float64)
        b_band = pixels[2].astype(np.float64)

        # Build valid pixel mask: exclude nodata (0,0,0) and fully black pixels
        valid_mask = (r_band > 0) | (g_band > 0) | (b_band > 0)
        pixel_count = valid_mask.sum()
        if pixel_count == 0:
            return fallback

        # Normalize RGB to [0, 1]
        R = r_band[valid_mask] / 255.0
        G = g_band[valid_mask] / 255.0
        B = b_band[valid_mask] / 255.0

        # VARI = (G - R) / (G + R - B)  — handle div-by-zero with np.where
        denom = G + R - B
        vari = np.where(
            np.abs(denom) > 1e-6,
            (G - R) / denom,
            0.0,
        )
        # Clip VARI to [-1, 1] range (theoretical bounds)
        vari = np.clip(vari, -1.0, 1.0)

        # ExG = 2*G - R - B
        exg = 2.0 * G - R - B

        # green_fraction: % pixels where ExG > 0.1 (vegetated)
        green_fraction = float(np.mean(exg > 0.1))

        # stress_fraction: % pixels where VARI < -0.1 (stressed/non-vegetated)
        stress_fraction = float(np.mean(vari < -0.1))

        return {
            "mean_vari": float(np.mean(vari)),
            "mean_exg": float(np.mean(exg)),
            "green_fraction": green_fraction,
            "stress_fraction": stress_fraction,
        }

    except Exception:
        return fallback


def compute_index_score(indices: Dict[str, float]) -> float:
    """Compute a 0-1 health score from vegetation indices.

    Composite of VARI, ExG, green fraction, and inverted stress fraction.
    Formula weights (must sum to 1.0):
        vari_norm * 0.3 + exg_norm * 0.2 + green_fraction * 0.3 + (1 - stress_fraction) * 0.2

    Args:
        indices: Dict from compute_health_indices().

    Returns:
        Float in [0, 1] rounded to 3 decimal places.
    """
    # Normalize mean_vari from [-1, 1] to [0, 1]
    vari_norm = (indices["mean_vari"] + 1.0) / 2.0
    # Normalize mean_exg from [-1, 1] to [0, 1], clamped
    exg_norm = max(0.0, min(1.0, (indices["mean_exg"] + 1.0) / 2.0))

    score = (
        vari_norm * 0.3
        + exg_norm * 0.2
        + indices["green_fraction"] * 0.3
        + (1.0 - indices["stress_fraction"]) * 0.2
    )
    return round(max(0.0, min(1.0, score)), 3)


def compute_health_score(index_score: float, vision_score: Optional[float] = None) -> float:
    """Combine index score and optional vision score into final health score.

    When both are available: 40% index + 60% vision (HLT-03).
    When vision skipped or unavailable: index-only.

    Args:
        index_score: Float [0, 1] from compute_index_score().
        vision_score: Float [0, 1] from OpenAI Vision API, or None.

    Returns:
        Float in [0, 1] rounded to 3 decimal places.
    """
    if vision_score is not None:
        score = index_score * 0.4 + vision_score * 0.6
    else:
        score = index_score  # index-only when vision skipped
    return round(max(0.0, min(1.0, score)), 3)


def health_status(score: float) -> str:
    """Categorize health score into human-readable status (HLT-04).

    Args:
        score: Float health score [0, 1].

    Returns:
        One of: healthy, moderate_stress, stressed, severe_decline, dead.
    """
    if score >= 0.80:
        return "healthy"
    if score >= 0.60:
        return "moderate_stress"
    if score >= 0.40:
        return "stressed"
    if score >= 0.20:
        return "severe_decline"
    return "dead"


# ─── IMAGE CROP UTILITY ──────────────────────────────────────────────────────

def crop_canopy_image(
    dataset: rasterio.DatasetReader,
    polygon_wkt: str,
) -> Optional[bytes]:
    """Crop canopy polygon from orthomosaic and return JPEG bytes.

    Returns None on any error to allow graceful vision skip for this canopy.
    Encodes as JPEG at quality 85 to reduce OpenAI payload size.

    Args:
        dataset: Open rasterio dataset.
        polygon_wkt: WKT string of the canopy polygon.

    Returns:
        JPEG bytes or None.
    """
    try:
        from PIL import Image

        polygon = shapely_wkt.loads(polygon_wkt)
        pixels, _ = rasterio_mask(
            dataset,
            [polygon],
            crop=True,
            nodata=0,
            filled=True,
        )
        # pixels: (bands, h, w) — take first 3 bands (RGB)
        rgb = pixels[:3]
        # CHW -> HWC
        hwc = np.transpose(rgb, (1, 2, 0)).astype(np.uint8)
        img = Image.fromarray(hwc, mode="RGB")

        # Resize if too large (max 512px on longest side) to reduce API cost
        max_side = 512
        w, h = img.size
        if max(w, h) > max_side:
            scale = max_side / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except Exception:
        return None


# ─── OLLAMA VISION ───────────────────────────────────────────────────────────

def assess_via_ollama(image_bytes: bytes, log: logging.Logger) -> Optional[Dict[str, Any]]:
    """Send a canopy crop to local Ollama LLaVA for health assessment.

    Args:
        image_bytes: JPEG bytes of the canopy crop.
        log: Logger instance.

    Returns:
        Dict with health_score and other fields, or None on failure.
    """
    try:
        from ollama_vision import assess_health
        return assess_health(image_bytes)
    except Exception as exc:
        log.warning(f"Ollama health assessment failed: {exc}")
        return None


# ─── OPENAI VISION ───────────────────────────────────────────────────────────

HEALTH_VISION_PROMPT = (
    "You are inspecting a tree canopy from aerial drone imagery. "
    "Assess visible health indicators: discoloration, dead branches, thinning, "
    "disease, pest damage. "
    "Respond with JSON only (no markdown, no explanation): "
    '{"health_score": 0.0-1.0, "observations": "brief text", '
    '"discoloration_pct": 0-100, "dead_branch_pct": 0-100, '
    '"thinning": true/false, "disease_indicators": "none or description", '
    '"recommended_action": "monitor" | "inspect" | "urgent"}'
)


def assess_via_vision(image_bytes: bytes, log: logging.Logger) -> Dict[str, Any]:
    """Send a canopy crop to OpenAI Vision API for health assessment.

    Always returns a dict annotated with ``vision_backend`` and
    ``openai_requests`` (billed request count) so the caller's spend guard can
    account for paid calls even when the response failed to parse — the request
    was still billed. ``health_score`` is None when no usable assessment was
    produced, signalling the caller to fall back to index-only scoring for that
    canopy.

    Args:
        image_bytes: JPEG bytes of the canopy crop.
        log: Logger instance.

    Returns:
        Dict with at least vision_backend, openai_requests, health_score.
    """
    # Billed-request counter: incremented BEFORE the call is dispatched so spend
    # accounting stays conservative when a request errors after being sent.
    requests_made = 0

    if not OPENAI_API_KEY:
        log.warning("OPENAI_API_KEY not set — skipping vision assessment")
        return {"vision_backend": "none", "openai_requests": 0, "health_score": None}

    try:
        from openai import OpenAI

        client = OpenAI(api_key=OPENAI_API_KEY)
        b64 = base64.b64encode(image_bytes).decode("utf-8")

        def _call_api() -> str:
            nonlocal requests_made
            requests_made += 1
            response = client.chat.completions.create(
                model=VISION_MODEL,
                max_tokens=256,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{b64}",
                                    "detail": "low",  # cost control
                                },
                            },
                            {
                                "type": "text",
                                "text": HEALTH_VISION_PROMPT,
                            },
                        ],
                    }
                ],
            )
            return response.choices[0].message.content.strip()

        raw = _call_api()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)

        # Validate health_score is numeric in [0, 1]
        score = float(result.get("health_score", 0.5))
        result["health_score"] = round(max(0.0, min(1.0, score)), 3)
        result["vision_backend"] = "openai"
        result["openai_requests"] = requests_made
        return result
    except Exception as exc:
        log.warning(f"Vision API call failed: {exc}")
        return {
            "vision_backend": "openai",
            "openai_requests": requests_made,
            "health_score": None,
        }


def assess_via_vision_router(image_bytes: bytes, log: logging.Logger) -> Optional[Dict[str, Any]]:
    """Route health assessment to Ollama or OpenAI based on VISION_BACKEND.

    When backend is "ollama" (default), tries Ollama first and falls back to
    OpenAI on failure. When backend is "openai", goes directly to OpenAI.

    Args:
        image_bytes: JPEG bytes of the canopy crop.
        log: Logger instance.

    Returns:
        Dict with health_score and other fields, or None on failure.
    """
    if VISION_BACKEND == "ollama":
        result = assess_via_ollama(image_bytes, log)
        if result is not None:
            # Free local inference — annotate so the spend guard skips it
            result["vision_backend"] = "ollama"
            return result
        log.warning("Ollama health assessment failed — falling back to OpenAI")

    # OpenAI path (primary when VISION_BACKEND=="openai", fallback when Ollama fails)
    return assess_via_vision(image_bytes, log)


def estimate_vision_cost(sample_count: int, ollama_available: bool = False) -> float:
    """Estimate worst-case paid API cost for N vision sample calls.

    When VISION_BACKEND is "ollama" AND Ollama is actually reachable, vision
    cost is $0 (local inference); the runtime spend guard in
    run_health_assessment covers any per-canopy OpenAI fallback. When Ollama is
    selected but unreachable, every sampled canopy will fall back to paid
    OpenAI, so the estimate is the full OpenAI worst case.

    Args:
        sample_count: Number of canopies queued for vision assessment.
        ollama_available: Result of a reachability probe; only meaningful
            when VISION_BACKEND == "ollama".

    Returns:
        Estimated cost in USD.
    """
    if VISION_BACKEND == "ollama" and ollama_available:
        return 0.0
    return round(sample_count * COST_PER_VISION_CALL, 4)


def _ollama_reachable() -> bool:
    """Probe Ollama once; False on any failure so cost gating assumes OpenAI."""
    try:
        from ollama_vision import check_ollama
        return check_ollama()
    except Exception:
        return False


# ─── PER-MISSION SPEND LEDGER ────────────────────────────────────────────────
# cost_threshold is a per-MISSION budget. Paid OpenAI request counts persist
# across process runs so a re-trigger after a cost abort cannot spend another
# full threshold (K reruns x threshold). Cleared by --force with the checkpoint.

def _spend_ledger_path(mission_dir: str) -> str:
    return os.path.join(mission_dir, f"{SCRIPT_NAME}_spend.json")


def _load_paid_calls(mission_dir: str) -> int:
    """Return billed OpenAI request count from prior runs of this mission."""
    try:
        with open(_spend_ledger_path(mission_dir), "r", encoding="utf-8") as f:
            return int(json.load(f).get("openai_paid_calls", 0))
    except Exception:
        return 0


def _save_paid_calls(mission_dir: str, paid_calls: int, log: logging.Logger) -> None:
    try:
        with open(_spend_ledger_path(mission_dir), "w", encoding="utf-8") as f:
            json.dump(
                {"openai_paid_calls": paid_calls, "cost_per_call": COST_PER_VISION_CALL},
                f,
            )
    except OSError as exc:
        log.warning(f"Spend ledger save failed: {exc}")


def _clear_paid_calls(mission_dir: str) -> None:
    try:
        os.remove(_spend_ledger_path(mission_dir))
    except OSError:
        pass


# ─── SUPABASE ────────────────────────────────────────────────────────────────

def _get_supabase_client(log: logging.Logger):
    """Return a Supabase client or None if credentials are missing."""
    try:
        return get_supabase_client()
    except (ValueError, SystemExit):
        log.warning(
            "Supabase credentials not set (SUPABASE_URL / SUPABASE_SERVICE_KEY). "
            "Skipping vegetation_detections health update."
        )
        return None
    except Exception as exc:
        log.warning(f"Supabase client creation failed: {exc}. Skipping health update.")
        return None


def fetch_detections(
    mission_id: str,
    log: logging.Logger,
) -> List[Dict[str, Any]]:
    """Fetch all canopy detections for the mission from Supabase.

    Returns list of dicts with keys: id, detection_index, geometry_wkt, health_score.
    Returns empty list on failure — caller handles gracefully.

    Args:
        mission_id: Supabase drone_jobs.id UUID.
        log: Logger instance.
    """
    client = _get_supabase_client(log)
    if client is None:
        return []
    try:
        result = (
            client.table("vegetation_detections")
            .select("id, detection_index, geometry_wkt, health_score")
            .eq("mission_id", mission_id)
            .order("detection_index")
            .execute()
        )
        return result.data or []
    except Exception as exc:
        log.error(f"Supabase fetch failed: {exc}")
        return []


def update_health_batch(
    rows: List[Dict[str, Any]],
    log: logging.Logger,
) -> bool:
    """Update health scores in vegetation_detections in batches.

    Each row must have: id, health_score, health_status, health_details.
    Uses individual UPDATE per row (no batch upsert needed since rows exist from E1).

    Args:
        rows: List of update dicts.
        log: Logger instance.

    Returns:
        True if all updates succeeded, False if any failed.
    """
    if not rows:
        return True

    client = _get_supabase_client(log)
    if client is None:
        return False

    success = True
    total = len(rows)
    updated = 0

    for i in range(0, total, SUPABASE_BATCH_SIZE):
        batch = rows[i : i + SUPABASE_BATCH_SIZE]
        for row in batch:
            try:
                client.table("vegetation_detections").update(
                    {
                        "health_score": row["health_score"],
                        "health_status": row["health_status"],
                        "health_details": row["health_details"],
                    }
                ).eq("id", row["id"]).execute()
                updated += 1
            except Exception as exc:
                log.warning(
                    f"Supabase update failed for detection {row.get('detection_index', '?')}: {exc}"
                )
                success = False

        log.info(f"Supabase: updated {min(i + len(batch), total)}/{total} detections")

    if success:
        log.info(f"Supabase: all {total} health scores written to vegetation_detections")
    else:
        log.warning(
            f"Supabase: partial write — {updated}/{total} rows updated. "
            "Re-run to retry failed rows."
        )
    return success


# ─── MAIN HEALTH ASSESSMENT PIPELINE ─────────────────────────────────────────

def run_health_assessment(
    mission_id: str,
    ortho_path: str,
    vision_sample_pct: float,
    skip_vision: bool,
    cost_threshold: float,
    completed_keys: Set[str],
    mission_dir: str,
    log: logging.Logger,
) -> Dict[str, Any]:
    """Run full health assessment pipeline for a mission.

    Pipeline:
    1. Fetch all canopy detections from Supabase.
    2. Skip detections already in checkpoint (resume) OR already have health_score.
    3. Compute VARI/ExG indices for all canopies (fast, no API calls).
    4. Sort by index_score ascending — bottom vision_sample_pct get Vision API calls.
    5. Estimate and check Vision API cost against --cost-threshold.
    6. Run Vision API for sampled canopies (skippable via --skip-vision).
    7. Compute final health scores and status.
    8. Batch update Supabase.
    9. Return summary dict for JSON stdout.

    Args:
        mission_id: Supabase drone_jobs.id UUID.
        ortho_path: Path to the source GeoTIFF orthomosaic.
        vision_sample_pct: Fraction of lowest-scoring canopies to vision-assess.
        skip_vision: If True, use index-only scoring for all canopies.
        cost_threshold: Abort vision calls if estimated cost exceeds this (USD).
        completed_keys: Set of canopy keys already processed (checkpoint).
        mission_dir: Directory for checkpoint file storage.
        log: Logger instance.

    Returns:
        Dict with assessment summary for JSON stdout output.
    """
    # ── Fetch detections ─────────────────────────────────────────────────────
    detections = fetch_detections(mission_id, log)
    if not detections:
        log.warning("No detections found — nothing to assess. Did E1 run?")
        return {
            "assessed_count": 0,
            "healthy": 0,
            "moderate_stress": 0,
            "stressed": 0,
            "severe_decline": 0,
            "dead": 0,
            "vision_samples": 0,
            "api_calls_openai": 0,
            "api_cost_estimate": 0.0,
        }

    log.info(f"Fetched {len(detections)} canopy detections for mission {mission_id}")

    # ── Phase 1: Index computation (all canopies) ────────────────────────────
    log.info("Phase 1: Computing VARI/ExG indices for all canopies...")
    canopy_results: List[Dict[str, Any]] = []

    with rasterio.open(ortho_path) as dataset:
        for det in detections:
            det_key = f"canopy_{det['detection_index']}"

            # Checkpoint resume: skip already-assessed canopies
            if det_key in completed_keys:
                log.debug(f"  Canopy {det['detection_index']} [SKIPPED — checkpoint]")
                continue

            # Also skip if already has a health_score in Supabase (previous partial run)
            if det.get("health_score") is not None and not False:
                # We still need to count it in summary; it will be skipped from update
                log.debug(
                    f"  Canopy {det['detection_index']} already has health_score={det['health_score']}, "
                    "skipping index recomputation"
                )
                completed_keys.add(det_key)
                save_checkpoint(mission_dir, SCRIPT_NAME, completed_keys)
                continue

            geometry_wkt = det.get("geometry_wkt", "")
            if not geometry_wkt:
                log.warning(f"  Canopy {det['detection_index']} missing geometry_wkt — skipping")
                continue

            indices = compute_health_indices(dataset, geometry_wkt)
            index_score = compute_index_score(indices)

            canopy_results.append({
                "id": det["id"],
                "detection_index": det["detection_index"],
                "geometry_wkt": geometry_wkt,
                "indices": indices,
                "index_score": index_score,
                "vision_score": None,
                "vision_result": None,
            })

            log.info(
                f"  Canopy {det['detection_index']}: "
                f"VARI={indices['mean_vari']:.3f}, ExG={indices['mean_exg']:.3f}, "
                f"index_score={index_score:.3f}"
            )

    if not canopy_results:
        log.info("All canopies already assessed — nothing new to compute.")
        # Build summary from existing Supabase data
        status_counts = {"healthy": 0, "moderate_stress": 0, "stressed": 0, "severe_decline": 0, "dead": 0}
        for det in detections:
            s = det.get("health_score")
            if s is not None:
                status_counts[health_status(s)] = status_counts.get(health_status(s), 0) + 1
        return {
            "assessed_count": len(detections),
            **status_counts,
            "vision_samples": 0,
            "api_calls_openai": 0,
            "api_cost_estimate": 0.0,
        }

    log.info(f"Phase 1 complete: {len(canopy_results)} canopies indexed")

    # ── Phase 2: Vision sampling (bottom vision_sample_pct) ──────────────────
    vision_samples = 0
    api_cost_estimate = 0.0
    # Billed OpenAI requests this run (Ollama is free). Drives the actual-cost
    # report and, with the ledger, the runtime spend guard.
    openai_call_count = 0
    # Set when accumulated OpenAI spend (this run + prior runs) breaches
    # cost_threshold; the second flag records whether vision samples were left
    # undone so the summary can flag a partial run for n8n.
    cost_aborted = False
    cost_abort_left_unprocessed = False

    vision_available = VISION_BACKEND == "ollama" or bool(OPENAI_API_KEY)
    if not skip_vision and vision_available:
        # Sort ascending by index_score — lowest-scoring = most stressed = need vision most
        canopy_results.sort(key=lambda c: c["index_score"])

        sample_n = max(1, int(len(canopy_results) * vision_sample_pct))
        vision_candidates = canopy_results[:sample_n]

        # cost_threshold is a per-mission budget: prior runs' paid calls count
        # against it so a re-trigger after a cost abort cannot burn a fresh
        # threshold each time.
        prior_paid_calls = _load_paid_calls(mission_dir)
        prior_spend = round(prior_paid_calls * COST_PER_VISION_CALL, 4)

        # Worst-case pre-check: when Ollama is the backend but unreachable, every
        # sampled canopy falls back to paid OpenAI — gate on that worst case. A
        # $0 estimate (healthy Ollama) is never pre-blocked; the runtime guard
        # stops the first paid fallback instead.
        ollama_ok = VISION_BACKEND == "ollama" and _ollama_reachable()
        if VISION_BACKEND == "ollama" and not ollama_ok:
            log.warning(
                "Ollama backend selected but unreachable — every vision sample "
                "would fall back to paid OpenAI; gating on worst-case OpenAI cost"
            )
        estimated_cost = estimate_vision_cost(len(vision_candidates), ollama_ok)

        if prior_paid_calls:
            log.info(
                f"Prior OpenAI spend this mission: ${prior_spend:.2f} "
                f"({prior_paid_calls} paid calls) — counted against cost threshold"
            )
        log.info(
            f"Phase 2: Vision sampling — {len(vision_candidates)} canopies selected "
            f"({vision_sample_pct*100:.0f}% of {len(canopy_results)}), "
            f"estimated cost ${estimated_cost:.2f}"
        )

        if estimated_cost > 0 and round(prior_spend + estimated_cost, 4) > cost_threshold:
            log.error(
                f"Estimated vision cost ${estimated_cost:.2f} (plus ${prior_spend:.2f} "
                f"prior) exceeds threshold ${cost_threshold:.2f}. Aborting before any "
                f"paid vision call. Use --skip-vision for free index-only scoring or "
                f"--cost-threshold to raise the limit."
            )
            return {
                "assessed_count": 0,
                "healthy": 0,
                "moderate_stress": 0,
                "stressed": 0,
                "severe_decline": 0,
                "dead": 0,
                "vision_samples": 0,
                "api_calls_openai": 0,
                "api_cost_estimate": estimated_cost,
                "error": "cost_threshold_exceeded",
            }

        with rasterio.open(ortho_path) as dataset:
            for canopy in vision_candidates:
                if cost_aborted:
                    cost_abort_left_unprocessed = True
                    break

                det_idx = canopy["detection_index"]
                log.info(f"  Vision: canopy {det_idx} (index_score={canopy['index_score']:.3f})")

                image_bytes = crop_canopy_image(dataset, canopy["geometry_wkt"])
                if image_bytes is None:
                    log.warning(f"  Could not crop canopy {det_idx} — skipping vision")
                    continue

                vision_result = assess_via_vision_router(image_bytes, log)

                # Runtime spend guard: fallback OpenAI calls are paid even when
                # the pre-check estimated $0 for a healthy Ollama backend. Count
                # billed requests, persist to the ledger, and stop after the
                # canopy that crossed the line (its result is kept). Rounded to
                # match the pre-check so exact-budget runs don't trip on float
                # dust (35 * 0.02 > 0.70 in raw float math).
                if vision_result.get("vision_backend") == "openai":
                    openai_call_count += vision_result.get("openai_requests", 1)
                    _save_paid_calls(mission_dir, prior_paid_calls + openai_call_count, log)
                    openai_spend = round(
                        (prior_paid_calls + openai_call_count) * COST_PER_VISION_CALL, 4
                    )
                    if openai_spend > cost_threshold:
                        log.error(
                            f"Cumulative OpenAI spend ${openai_spend:.2f} exceeds threshold "
                            f"${cost_threshold:.2f} ({prior_paid_calls} paid calls from prior "
                            f"runs + {openai_call_count} this run) — aborting remaining "
                            f"vision samples (scored rows are kept)"
                        )
                        cost_aborted = True

                if vision_result.get("health_score") is not None:
                    canopy["vision_score"] = vision_result.get("health_score")
                    canopy["vision_result"] = vision_result
                    vision_samples += 1
                    log.info(
                        f"  Canopy {det_idx}: vision_score={canopy['vision_score']:.3f}, "
                        f"action={vision_result.get('recommended_action', 'unknown')}"
                    )

        # Actual spend: only billed OpenAI calls cost money (Ollama is free)
        api_cost_estimate = round(openai_call_count * COST_PER_VISION_CALL, 4)
        log.info(f"Phase 2 complete: {vision_samples} vision assessments, actual cost ${api_cost_estimate:.2f}")
    else:
        if skip_vision:
            log.info("Phase 2: Vision sampling skipped (--skip-vision)")
        else:
            log.info("Phase 2: Vision sampling skipped (no vision backend available — "
                     "set VISION_BACKEND=ollama or OPENAI_API_KEY)")

    # ── Phase 3: Compute final health scores and build Supabase update rows ──
    log.info("Phase 3: Computing final health scores...")
    update_rows: List[Dict[str, Any]] = []
    status_counts = {"healthy": 0, "moderate_stress": 0, "stressed": 0, "severe_decline": 0, "dead": 0}

    for canopy in canopy_results:
        final_score = compute_health_score(canopy["index_score"], canopy["vision_score"])
        final_status = health_status(final_score)
        status_counts[final_status] = status_counts.get(final_status, 0) + 1

        health_details = {
            "vari": round(canopy["indices"]["mean_vari"], 4),
            "exg": round(canopy["indices"]["mean_exg"], 4),
            "green_fraction": round(canopy["indices"]["green_fraction"], 4),
            "stress_fraction": round(canopy["indices"]["stress_fraction"], 4),
            "index_score": canopy["index_score"],
            "vision": canopy["vision_result"],  # None if not sampled
        }

        update_rows.append({
            "id": canopy["id"],
            "detection_index": canopy["detection_index"],
            "health_score": final_score,
            "health_status": final_status,
            "health_details": health_details,
        })

        # Save per-canopy checkpoint
        det_key = f"canopy_{canopy['detection_index']}"
        completed_keys.add(det_key)
        try:
            save_checkpoint(mission_dir, SCRIPT_NAME, completed_keys)
        except OSError as exc:
            log.warning(f"Checkpoint save failed for canopy {canopy['detection_index']}: {exc}")

    log.info(f"Phase 3 complete: {len(update_rows)} canopies scored")

    # ── Phase 4: Supabase batch update ───────────────────────────────────────
    update_health_batch(update_rows, log)

    # Build total assessed count including previously completed canopies
    total_assessed = len(update_rows) + len(completed_keys) - len(canopy_results)

    summary = {
        "assessed_count": len(update_rows),
        **status_counts,
        "vision_samples": vision_samples,
        "api_calls_openai": openai_call_count,
        "api_cost_estimate": api_cost_estimate,
    }
    if cost_aborted and cost_abort_left_unprocessed:
        # Mid-run abort with vision samples left undone: every indexed canopy was
        # still scored (vision where obtained before the breach, index-only
        # otherwise), batch-updated and checkpointed above. main() prints this
        # summary before exiting 1 so n8n receives spend/progress telemetry. If
        # the breaching call was the LAST vision candidate, nothing was left
        # undone — no error; the ledger enforces the exhausted budget next run.
        summary["error"] = "cost_threshold_exceeded"
    return summary


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sentinel Aerial Inspections — Health Assessment (Step E3)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Computes per-canopy vegetation health scores using VARI/ExG RGB indices
and optional OpenAI Vision qualitative assessment for stressed canopies.

Exit codes:
  0 — Success: all canopies assessed, Supabase updated
  1 — Fatal error: ortho not found, Supabase fetch failed, or cost threshold
      exceeded (pre-check abort or runtime OpenAI spend guard)
  2 — Partial success: some canopies failed, remaining assessed

Examples:
  python health_assessment.py --mission-id abc-123 --ortho-path ortho.tif
  python health_assessment.py --mission-id abc-123 --ortho-path ortho.tif --skip-vision
  python health_assessment.py --mission-id abc-123 --ortho-path ortho.tif --vision-sample-pct 0.5
  python health_assessment.py --mission-id abc-123 --ortho-path ortho.tif --force
        """,
    )
    parser.add_argument(
        "--mission-id",
        required=True,
        help="Supabase mission UUID (drone_jobs.id)",
    )
    parser.add_argument(
        "--ortho-path",
        required=True,
        help="Path to source GeoTIFF orthomosaic",
    )
    parser.add_argument(
        "--vision-sample-pct",
        type=float,
        default=0.3,
        help="Fraction of lowest-scoring canopies to send for Vision API assessment (default: 0.3)",
    )
    parser.add_argument(
        "--skip-vision",
        action="store_true",
        help="Use index-only scoring — no OpenAI Vision API calls",
    )
    parser.add_argument(
        "--cost-threshold",
        type=float,
        default=2.0,
        help="Abort vision calls if estimated cost exceeds this amount in USD (default: 2.0)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Clear checkpoint and reprocess all canopies from scratch",
    )
    add_pipeline_args(parser)
    args = parser.parse_args()

    log = setup_logging(SCRIPT_NAME)

    # ── Startup log ─────────────────────────────────────────────────────────
    log.info(f"Health Assessment (E3) starting — mission {args.mission_id}")
    log.info(f"Ortho:            {args.ortho_path}")
    log.info(f"Vision backend:   {VISION_BACKEND} (OLLAMA_URL={OLLAMA_URL})")
    log.info(f"Vision sample:    {args.vision_sample_pct * 100:.0f}%")
    log.info(f"Skip vision:      {args.skip_vision}")
    log.info(f"Cost threshold:   ${args.cost_threshold:.2f}")

    # Pre-flight check: verify Ollama availability if selected as backend
    if VISION_BACKEND == "ollama" and not args.skip_vision:
        try:
            from ollama_vision import check_ollama
            if check_ollama():
                log.info("Ollama pre-flight: llava:13b available")
            else:
                log.warning(
                    "Ollama pre-flight: llava:13b NOT available — "
                    "will fall back to OpenAI for each image"
                )
        except Exception as exc:
            log.warning(f"Ollama pre-flight check failed: {exc}")

    # ── Input validation ─────────────────────────────────────────────────────
    if not os.path.isfile(args.ortho_path):
        log.error(f"Ortho file not found: {args.ortho_path}")
        sys.exit(1)

    if not 0.0 < args.vision_sample_pct <= 1.0:
        log.error(
            f"--vision-sample-pct must be between 0.0 (exclusive) and 1.0 (inclusive), "
            f"got {args.vision_sample_pct}"
        )
        sys.exit(1)

    # ── Checkpoint setup ─────────────────────────────────────────────────────
    mission_dir = os.path.dirname(os.path.abspath(args.ortho_path))
    if args.force:
        clear_checkpoint(mission_dir, SCRIPT_NAME)
        _clear_paid_calls(mission_dir)
        log.info("--force: checkpoint and spend ledger cleared, reprocessing all canopies")

    completed_keys = load_checkpoint(mission_dir, SCRIPT_NAME)
    if completed_keys:
        log.info(f"Resuming from checkpoint: {len(completed_keys)} canopies already complete")

    # ── Pipeline status reporter ──────────────────────────────────────────────
    reporter = PipelineStatusReporter(
        processing_job_id=getattr(args, "processing_job_id", None),
        step_name="veg_health_assessment",
    )
    reporter.start()

    # ── Run assessment ────────────────────────────────────────────────────────
    start_time = time.time()
    try:
        summary = run_health_assessment(
            mission_id=args.mission_id,
            ortho_path=args.ortho_path,
            vision_sample_pct=args.vision_sample_pct,
            skip_vision=args.skip_vision,
            cost_threshold=args.cost_threshold,
            completed_keys=completed_keys,
            mission_dir=mission_dir,
            log=log,
        )
    except Exception as exc:
        log.exception(f"Health assessment failed: {exc}")
        reporter.fail(str(exc))
        sys.exit(1)

    elapsed = time.time() - start_time
    log.info(f"Assessment complete in {elapsed:.1f}s — {summary['assessed_count']} canopies")

    # ── JSON stdout (parseable by n8n) ────────────────────────────────────────
    # Printed BEFORE any cost-abort exit so the caller still receives spend and
    # progress telemetry (assessed_count, api_calls_openai, cost) on partial runs.
    print(json.dumps(summary))

    # Check for cost threshold exceeded (pre-check abort or runtime spend guard)
    if summary.get("error") == "cost_threshold_exceeded":
        reporter.fail("cost_threshold_exceeded")
        sys.exit(1)

    # ── Reporter + exit code ──────────────────────────────────────────────────
    assessed = summary["assessed_count"]
    reporter.complete(output=f"{assessed} canopies assessed")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logging.getLogger(__name__).exception(f"Fatal: {exc}")
        sys.exit(1)
