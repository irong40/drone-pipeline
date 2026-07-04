"""
Sentinel Aerial Inspections — Species Classification (Step E2)

Classifies tree species for each canopy detection using OpenAI Vision API
with PlantNet cross-validation. Crops canopy regions from orthomosaic,
sends to dual APIs, reconciles results with confidence adjustment.

Usage:
    python species_classification.py --mission-id {uuid} --ortho-path path.tif
    python species_classification.py --mission-id {uuid} --ortho-path path.tif --skip-plantnet --max-canopies 100
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
import tempfile
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

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

SCRIPT_NAME = "species_classification"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
PLANTNET_API_KEY = os.environ.get("PLANTNET_API_KEY", "")

# OpenAI model for vision classification
VISION_MODEL = "gpt-4o"
# Estimated cost per OpenAI Vision call (gpt-4o image input, low detail)
COST_PER_OPENAI_CALL = 0.02  # ~$0.02 per crop at typical drone resolution

SUPABASE_BATCH_SIZE = 50  # Rows per upsert request

# Vision backend: "ollama" (local, free) or "openai" (cloud, ~$0.02/image)
# Ollama is default; falls back to OpenAI if Ollama is unavailable or fails.
VISION_BACKEND = os.environ.get("VISION_BACKEND", "ollama").lower()
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

# Hampton Roads species list — 20 common species in the region
HAMPTON_ROADS_SPECIES = [
    "Loblolly Pine",
    "Live Oak",
    "Red Maple",
    "Sweetgum",
    "Eastern Redcedar",
    "Bald Cypress",
    "Southern Magnolia",
    "Tulip Poplar",
    "Willow Oak",
    "American Holly",
    "Virginia Pine",
    "White Oak",
    "Black Cherry",
    "River Birch",
    "Eastern White Pine",
    "American Sycamore",
    "Crape Myrtle",
    "Wax Myrtle",
    "Leyland Cypress",
    "Sabal Palmetto",
]

SPECIES_PROMPT = (
    "You are a certified arborist identifying tree species from aerial drone imagery "
    "over Hampton Roads, Virginia. "
    "The image shows a single tree canopy viewed from above. "
    "Identify the most likely species based on canopy shape, color, texture, and size.\n\n"
    "Common species in Hampton Roads include: "
    + ", ".join(HAMPTON_ROADS_SPECIES)
    + ".\n\n"
    "Respond with JSON only (no markdown, no explanation):\n"
    '{"species_common": "common name", '
    '"species_scientific": "Genus species", '
    '"vegetation_type": "tree" | "shrub" | "unknown", '
    '"confidence": 0.0-1.0, '
    '"reasoning": "brief explanation of key identifying features", '
    '"secondary_candidates": [{"species_common": "name", "confidence": 0.0-1.0}]}'
)




# ─── CANOPY CROP EXTRACTION ───────────────────────────────────────────────────

def crop_canopy(
    dataset: rasterio.DatasetReader,
    polygon_wkt: str,
    padding_pct: float = 0.15,
) -> Optional[Any]:
    """Crop a canopy polygon from the orthomosaic with padding.

    Args:
        dataset: Open rasterio dataset.
        polygon_wkt: WKT string of canopy polygon (in dataset CRS).
        padding_pct: Fractional padding around bounding box (0.15 = 15%).

    Returns:
        PIL.Image resized to max 512px on longest dimension, or None on failure.
    """
    try:
        from PIL import Image

        polygon = shapely_wkt.loads(polygon_wkt)

        # Get bounding box and expand by padding_pct on each side
        minx, miny, maxx, maxy = polygon.bounds
        width = maxx - minx
        height = maxy - miny
        pad_x = width * padding_pct
        pad_y = height * padding_pct

        from shapely.geometry import box as shapely_box
        padded_box = shapely_box(
            minx - pad_x,
            miny - pad_y,
            maxx + pad_x,
            maxy + pad_y,
        )

        # Use rasterio.mask.mask() with padded bounding box to extract pixels
        pixels, _ = rasterio_mask(
            dataset,
            [padded_box],
            crop=True,
            nodata=0,
            filled=True,
        )

        # pixels shape: (bands, height, width) — take first 3 bands (RGB)
        if pixels.shape[0] < 3:
            return None

        rgb = pixels[:3]
        # CHW -> HWC
        hwc = np.transpose(rgb, (1, 2, 0)).astype(np.uint8)

        if hwc.shape[0] == 0 or hwc.shape[1] == 0:
            return None

        img = Image.fromarray(hwc, mode="RGB")

        # Resize to max 512px on longest dimension preserving aspect ratio
        max_side = 512
        w, h = img.size
        if max(w, h) > max_side:
            scale = max_side / max(w, h)
            new_w = max(1, int(w * scale))
            new_h = max(1, int(h * scale))
            img = img.resize((new_w, new_h), Image.LANCZOS)

        return img

    except Exception:
        return None


# ─── SUPABASE ─────────────────────────────────────────────────────────────────

def _get_supabase_client(log: logging.Logger):
    """Return a Supabase client or None if credentials are missing."""
    client = get_supabase_client()
    if client is None:
        log.warning(
            "Supabase credentials not set (SUPABASE_URL / SUPABASE_SERVICE_KEY). "
            "Skipping vegetation_detections classification update."
        )
    return client


def fetch_detections(
    mission_id: str,
    force: bool,
    log: logging.Logger,
) -> List[Dict[str, Any]]:
    """Fetch canopy detections for classification from Supabase.

    Selects id, detection_index, geometry_wkt, canopy_area_sqm, species_tag.
    Orders by canopy_area_sqm DESC to prioritize largest canopies.

    Args:
        mission_id: Supabase drone_jobs.id UUID.
        force: If True, fetch all detections including already-classified ones.
        log: Logger instance.

    Returns:
        List of dicts. Empty list on failure.
    """
    client = _get_supabase_client(log)
    if client is None:
        return []

    try:
        query = (
            client.table("vegetation_detections")
            .select("id, detection_index, geometry_wkt, canopy_area_sqm, species_tag")
            .eq("mission_id", mission_id)
            .order("canopy_area_sqm", desc=True)
        )

        if not force:
            # Only fetch detections without species_tag (not yet classified)
            query = query.is_("species_tag", "null")

        result = query.execute()
        return result.data or []

    except Exception as exc:
        log.error(f"Supabase fetch failed: {exc}")
        return []


def update_classification_batch(
    rows: List[Dict[str, Any]],
    log: logging.Logger,
) -> bool:
    """Update species classification in vegetation_detections in batches.

    Each row must have: id, species_tag, species_confidence, vegetation_type,
    cross_validated, classification_details.

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
                        "species_tag": row["species_tag"],
                        "species_confidence": row["species_confidence"],
                        "vegetation_type": row["vegetation_type"],
                        "cross_validated": row["cross_validated"],
                        "classification_details": row["classification_details"],
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
        log.info(f"Supabase: all {total} classifications written to vegetation_detections")
    else:
        log.warning(
            f"Supabase: partial write — {updated}/{total} rows updated. "
            "Re-run to retry failed rows."
        )
    return success


# ─── OLLAMA VISION CLASSIFICATION ────────────────────────────────────────────

def classify_ollama(image: Any) -> Optional[Dict[str, Any]]:
    """Classify tree species using local Ollama LLaVA model.

    Encodes PIL Image as PNG bytes and delegates to ollama_vision.classify_species().
    Returns None on failure so the caller can fall back to OpenAI.

    Args:
        image: PIL.Image of the canopy crop.

    Returns:
        Dict with species_common, species_scientific, vegetation_type,
        confidence, reasoning, secondary_candidates.
        Returns None on any failure.
    """
    try:
        from ollama_vision import classify_species

        buf = BytesIO()
        image.save(buf, format="PNG")
        image_bytes = buf.getvalue()

        return classify_species(image_bytes, HAMPTON_ROADS_SPECIES)
    except Exception:
        return None


# ─── OPENAI VISION CLASSIFICATION ────────────────────────────────────────────

def classify_openai(image: Any, api_key: str) -> Dict[str, Any]:
    """Classify tree species using OpenAI Vision API (gpt-4o).

    Args:
        image: PIL.Image of the canopy crop.
        api_key: OpenAI API key.

    Returns:
        Dict with: species_common, species_scientific, vegetation_type,
        confidence, reasoning, secondary_candidates.
        Returns "unidentified" fallback dict on parse failure.
    """
    fallback = {
        "species_common": "unidentified",
        "species_scientific": "Unknown species",
        "vegetation_type": "unknown",
        "confidence": 0.0,
        "reasoning": "API response could not be parsed",
        "secondary_candidates": [],
    }

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)

        # Encode PIL Image as base64 PNG
        buf = BytesIO()
        image.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        def _call_api() -> str:
            response = client.chat.completions.create(
                model=VISION_MODEL,
                max_tokens=512,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a certified arborist with expertise in tree identification "
                            "from aerial drone imagery over Hampton Roads, Virginia. "
                            "Always respond with valid JSON only."
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{b64}",
                                    "detail": "low",  # cost control
                                },
                            },
                            {
                                "type": "text",
                                "text": SPECIES_PROMPT,
                            },
                        ],
                    },
                ],
            )
            return response.choices[0].message.content.strip()

        # First attempt
        raw = _call_api()

        def _parse_json(text: str) -> Dict[str, Any]:
            """Parse JSON from response, stripping markdown fences if present."""
            if text.startswith("```"):
                parts = text.split("```")
                if len(parts) >= 2:
                    text = parts[1]
                    if text.startswith("json"):
                        text = text[4:].strip()
            return json.loads(text)

        try:
            result = _parse_json(raw)
        except (json.JSONDecodeError, ValueError):
            # Retry once on JSON parse failure
            raw = _call_api()
            try:
                result = _parse_json(raw)
            except (json.JSONDecodeError, ValueError):
                return fallback

        # Validate and clamp confidence
        confidence = float(result.get("confidence", 0.0))
        result["confidence"] = round(max(0.0, min(1.0, confidence)), 3)

        # Ensure required keys exist with defaults
        result.setdefault("species_common", "unidentified")
        result.setdefault("species_scientific", "Unknown species")
        result.setdefault("vegetation_type", "unknown")
        result.setdefault("reasoning", "")
        result.setdefault("secondary_candidates", [])

        return result

    except Exception:
        return fallback


# ─── VISION BACKEND ROUTER ───────────────────────────────────────────────────

def classify_vision(image: Any, log: logging.Logger) -> Dict[str, Any]:
    """Route vision classification to Ollama or OpenAI based on VISION_BACKEND.

    When backend is "ollama" (default), tries Ollama first and falls back to
    OpenAI on failure. When backend is "openai", goes directly to OpenAI.

    Args:
        image: PIL.Image of the canopy crop.
        log: Logger instance.

    Returns:
        Dict with species_common, species_scientific, vegetation_type,
        confidence, reasoning, secondary_candidates.
        Returns "unidentified" fallback on total failure.
    """
    openai_fallback = {
        "species_common": "unidentified",
        "species_scientific": "Unknown species",
        "vegetation_type": "unknown",
        "confidence": 0.0,
        "reasoning": "All vision backends failed or unavailable",
        "secondary_candidates": [],
    }

    if VISION_BACKEND == "ollama":
        result = classify_ollama(image)
        if result is not None:
            log.info(f"  Ollama: {result['species_common']} ({result['confidence']:.2f} confidence)")
            return result
        # Ollama failed — fall back to OpenAI
        log.warning("Ollama classification failed — falling back to OpenAI")

    # OpenAI path (primary when VISION_BACKEND=="openai", fallback when Ollama fails)
    if not OPENAI_API_KEY:
        log.warning("OPENAI_API_KEY not set — cannot fall back to OpenAI")
        return openai_fallback

    return classify_openai(image, OPENAI_API_KEY)


# ─── PLANTNET CLASSIFICATION ──────────────────────────────────────────────────

# Sentinel value returned by classify_plantnet() when daily quota is exhausted.
# The classification loop checks for this sentinel and disables PlantNet for all
# subsequent canopies in the run to avoid wasting retries.
PLANTNET_QUOTA_EXHAUSTED: Dict[str, Any] = {"_quota_exhausted": True}


def classify_plantnet(image: Any, api_key: str) -> Optional[Dict[str, Any]]:
    """Cross-validate species using PlantNet API.

    Args:
        image: PIL.Image of the canopy crop.
        api_key: PlantNet API key (from PLANTNET_API_KEY env var).

    Returns:
        Dict with: species_name (top result scientific name), score, full_results.
        Returns PLANTNET_QUOTA_EXHAUSTED sentinel dict when daily quota is used up.
        Returns None if API call fails for any other reason.
    """
    import requests

    try:
        # Save PIL Image to temp PNG file for multipart upload
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
            image.save(tmp_path, format="PNG")

        try:
            with open(tmp_path, "rb") as f:
                response = requests.post(
                    "https://my-api.plantnet.org/v2/identify/all",
                    params={"project": "useful"},
                    headers={"Api-Key": api_key},
                    files={"images": ("canopy.png", f, "image/png")},
                    data={"organs": ["leaf"]},
                    timeout=30,
                )
        finally:
            # Clean up temp file
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        # 429 = rate limit / quota exhausted
        if response.status_code == 429:
            logging.getLogger(__name__).warning(
                "PlantNet quota exhausted (HTTP 429), switching to OpenAI-only for remaining canopies"
            )
            return PLANTNET_QUOTA_EXHAUSTED

        if response.status_code != 200:
            return None

        # Check remaining identifications quota from response headers
        remaining = response.headers.get("X-Remaining-Identifications")
        if remaining is not None:
            try:
                remaining_int = int(remaining)
                if remaining_int == 0:
                    logging.getLogger(__name__).warning(
                        "PlantNet quota exhausted (0 remaining), switching to OpenAI-only for remaining canopies"
                    )
                    # Still return this result since the call succeeded; loop will
                    # set plantnet_quota_exhausted=True after seeing remaining==0.
                    # We signal via the _quota_at_zero marker in full_results sentinel.
                elif remaining_int < 10:
                    logging.getLogger(__name__).warning(
                        f"PlantNet: only {remaining_int} identifications remaining today"
                    )
            except ValueError:
                pass

        data = response.json()
        results = data.get("results", [])

        if not results:
            return None

        # Extract top result
        top = results[0]
        species_name = top.get("species", {}).get("scientificNameWithoutAuthor", "")
        score = float(top.get("score", 0.0))
        remaining_after = None
        try:
            rem_hdr = response.headers.get("X-Remaining-Identifications")
            if rem_hdr is not None:
                remaining_after = int(rem_hdr)
        except (ValueError, TypeError):
            pass

        # Build condensed full_results list (top 5 to avoid bloat)
        full_results = []
        for r in results[:5]:
            full_results.append({
                "species": r.get("species", {}).get("scientificNameWithoutAuthor", ""),
                "score": round(float(r.get("score", 0.0)), 4),
            })

        return {
            "species_name": species_name,
            "score": round(score, 4),
            "full_results": full_results,
            "remaining_quota": remaining_after,
        }

    except Exception:
        return None


# ─── CONFIDENCE RECONCILIATION ────────────────────────────────────────────────

def reconcile(
    openai_result: Dict[str, Any],
    plantnet_result: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Reconcile OpenAI and PlantNet results with confidence adjustment.

    Genus-level agreement boosts confidence +0.1. Disagreement reduces -0.15.
    If PlantNet is skipped (None), returns OpenAI result as-is.

    Args:
        openai_result: Dict from classify_openai().
        plantnet_result: Dict from classify_plantnet(), or None if skipped.

    Returns:
        Dict with: species_tag, species_confidence, vegetation_type,
        cross_validated, classification_details.
    """
    openai_confidence = openai_result.get("confidence", 0.0)
    openai_scientific = openai_result.get("species_scientific", "")

    cross_validated = False
    genus_match = False
    adjustment = 0.0

    if plantnet_result is not None:
        # Extract genus: first word of scientific name
        openai_genus = openai_scientific.split()[0] if openai_scientific else ""
        plantnet_genus = (
            plantnet_result.get("species_name", "").split()[0]
            if plantnet_result.get("species_name")
            else ""
        )

        if openai_genus and plantnet_genus and openai_genus.lower() == plantnet_genus.lower():
            # Genus match — boost confidence
            adjustment = 0.1
            genus_match = True
            cross_validated = True
            final_confidence = min(openai_confidence + adjustment, 1.0)
        else:
            # Genus mismatch — reduce confidence
            adjustment = -0.15
            genus_match = False
            cross_validated = False
            final_confidence = max(openai_confidence + adjustment, 0.0)
    else:
        # PlantNet skipped — use OpenAI result as-is
        final_confidence = openai_confidence

    classification_details = {
        "openai": openai_result,
        "plantnet": plantnet_result,
        "reconciliation": {
            "genus_match": genus_match,
            "adjustment": adjustment,
        },
    }

    return {
        "species_tag": openai_result.get("species_common", "unidentified"),
        "species_confidence": round(max(0.0, min(1.0, final_confidence)), 3),
        "vegetation_type": openai_result.get("vegetation_type", "unknown"),
        "cross_validated": cross_validated,
        "classification_details": classification_details,
    }


# ─── COST ESTIMATION ─────────────────────────────────────────────────────────

def estimate_api_cost(canopy_count: int, skip_plantnet: bool) -> float:
    """Estimate total API cost for classifying N canopies.

    When VISION_BACKEND is "ollama", vision cost is $0 (local inference).
    PlantNet is free tier — not counted in cost estimate.

    Args:
        canopy_count: Number of canopies to classify.
        skip_plantnet: If True, only OpenAI calls counted.

    Returns:
        Estimated cost in USD.
    """
    if VISION_BACKEND == "ollama":
        # Ollama is local/free — cost is $0 unless fallback triggers OpenAI
        return 0.0
    cost = canopy_count * COST_PER_OPENAI_CALL
    # PlantNet is free tier — not counted in cost estimate
    return round(cost, 4)


# ─── MAIN CLASSIFICATION PIPELINE ────────────────────────────────────────────

def run_classification(
    mission_id: str,
    ortho_path: str,
    max_canopies: int,
    skip_plantnet: bool,
    cost_threshold: float,
    force: bool,
    completed_keys: Set[str],
    mission_dir: str,
    log: logging.Logger,
) -> Dict[str, Any]:
    """Run full species classification pipeline for a mission.

    Pipeline:
    1. Fetch unclassified canopy detections from Supabase (or all if --force).
    2. Cap at max_canopies (largest by canopy_area_sqm).
    3. Estimate API cost and check against cost_threshold.
    4. For each canopy: crop from ortho, classify via OpenAI Vision + PlantNet.
    5. Reconcile results with confidence adjustment.
    6. Batch update Supabase.
    7. Return summary dict for JSON stdout.

    Args:
        mission_id: Supabase drone_jobs.id UUID.
        ortho_path: Path to the source GeoTIFF orthomosaic.
        max_canopies: Maximum number of canopies to classify.
        skip_plantnet: If True, skip PlantNet API calls.
        cost_threshold: Abort if estimated OpenAI cost exceeds this (USD).
        force: If True, reclassify even if species_tag exists.
        completed_keys: Set of canopy checkpoint keys already processed.
        mission_dir: Directory for checkpoint file storage.
        log: Logger instance.

    Returns:
        Dict with classification summary for JSON stdout.
    """
    # ── Fetch detections ─────────────────────────────────────────────────────
    all_detections = fetch_detections(mission_id, force, log)

    if not all_detections:
        log.warning("No unclassified detections found — did E1 run? Use --force to reclassify all.")
        return {
            "classified_count": 0,
            "skipped_count": 0,
            "cross_validated_count": 0,
            "avg_confidence": 0.0,
            "api_calls_openai": 0,
            "api_calls_plantnet": 0,
            "total_api_cost_estimate": 0.0,
            "api_cost_estimate": 0.0,
            "plantnet_used": not skip_plantnet,
        }

    total = len(all_detections)

    # Cap at max_canopies (already ordered by area DESC from query)
    if total > max_canopies:
        detections = all_detections[:max_canopies]
        log.info(
            f"Processing {len(detections)} of {total} canopies "
            f"(max_canopies={max_canopies})"
        )
    else:
        detections = all_detections
        log.info(f"Processing {len(detections)} of {total} canopies (max_canopies={max_canopies})")

    # ── Cost pre-check ───────────────────────────────────────────────────────
    # Count how many still need processing (not in checkpoint)
    pending = [
        d for d in detections
        if f"canopy_{d['detection_index']}" not in completed_keys
    ]

    estimated_cost = estimate_api_cost(len(pending), skip_plantnet)
    log.info(
        f"Estimated API cost: ${estimated_cost:.2f} for {len(pending)} canopies "
        f"({len(detections) - len(pending)} in checkpoint, skipped)"
    )

    if estimated_cost > cost_threshold:
        log.error(
            f"Estimated cost ${estimated_cost:.2f} exceeds threshold ${cost_threshold:.2f}. "
            f"Aborting. Use --cost-threshold to raise limit or --max-canopies to reduce count."
        )
        return {
            "classified_count": 0,
            "skipped_count": len(detections),
            "cross_validated_count": 0,
            "avg_confidence": 0.0,
            "api_calls_openai": 0,
            "api_calls_plantnet": 0,
            "total_api_cost_estimate": estimated_cost,
            "api_cost_estimate": estimated_cost,
            "plantnet_used": not skip_plantnet,
            "error": "cost_threshold_exceeded",
        }

    # ── Classification loop ──────────────────────────────────────────────────
    update_rows: List[Dict[str, Any]] = []
    skipped_count = 0
    classified_count = 0
    openai_call_count = 0
    plantnet_call_count = 0
    # Track PlantNet quota exhaustion across iterations
    plantnet_quota_exhausted = False

    with rasterio.open(ortho_path) as dataset:
        for detection in detections:
            det_idx = detection["detection_index"]
            det_key = f"canopy_{det_idx}"

            # Checkpoint resume: skip already-classified canopies
            if det_key in completed_keys:
                log.debug(f"  Canopy {det_idx} [SKIPPED — checkpoint]")
                skipped_count += 1
                continue

            geometry_wkt = detection.get("geometry_wkt", "")
            if not geometry_wkt:
                log.warning(f"  Canopy {det_idx} missing geometry_wkt — skipping")
                skipped_count += 1
                continue

            log.info(
                f"  Classifying canopy {det_idx} "
                f"(area={detection.get('canopy_area_sqm', 0):.1f} sqm)"
            )

            # Crop canopy from orthomosaic with 15% padding
            crop = crop_canopy(dataset, geometry_wkt, padding_pct=0.15)
            if crop is None:
                log.warning(f"  Canopy {det_idx}: crop failed — skipping")
                skipped_count += 1
                continue

            # Vision classification (Ollama primary → OpenAI fallback)
            openai_result = classify_vision(crop, log)
            openai_call_count += 1

            # PlantNet cross-validation (optional)
            # Skip if: explicitly disabled, no key, or quota exhausted this run
            if skip_plantnet or plantnet_quota_exhausted:
                plantnet_result = None
            elif not PLANTNET_API_KEY:
                log.warning("PLANTNET_API_KEY not set — skipping PlantNet")
                plantnet_result = None
            else:
                raw_plantnet = classify_plantnet(crop, PLANTNET_API_KEY)

                # Check for quota-exhausted sentinel
                if raw_plantnet is PLANTNET_QUOTA_EXHAUSTED:
                    plantnet_quota_exhausted = True
                    log.warning(
                        "PlantNet quota exhausted — switching to OpenAI-only for remaining canopies"
                    )
                    plantnet_result = None
                elif raw_plantnet is not None:
                    plantnet_call_count += 1
                    plantnet_result = raw_plantnet
                    log.info(
                        f"  PlantNet: {plantnet_result['species_name']} "
                        f"({plantnet_result['score']:.2f} score)"
                    )
                    # Check if remaining quota just hit 0 — disable PlantNet for next canopies
                    if plantnet_result.get("remaining_quota") == 0:
                        plantnet_quota_exhausted = True
                        log.warning(
                            "PlantNet quota now at 0 — switching to OpenAI-only for remaining canopies"
                        )
                else:
                    log.warning(f"  PlantNet: identification failed for canopy {det_idx}")
                    plantnet_result = None

            # Confidence reconciliation
            final = reconcile(openai_result, plantnet_result)
            log.info(
                f"  Result: {final['species_tag']} "
                f"(confidence={final['species_confidence']:.3f}, "
                f"cross_validated={final['cross_validated']})"
            )

            update_rows.append({
                "id": detection["id"],
                "detection_index": det_idx,
                "species_tag": final["species_tag"],
                "species_confidence": final["species_confidence"],
                "vegetation_type": final["vegetation_type"],
                "cross_validated": final["cross_validated"],
                "classification_details": final["classification_details"],
            })
            classified_count += 1

            # Save per-canopy checkpoint after successful classification
            completed_keys.add(det_key)
            try:
                save_checkpoint(mission_dir, SCRIPT_NAME, completed_keys)
            except OSError as exc:
                log.warning(f"Checkpoint save failed for canopy {det_idx}: {exc}")

            # Rate limiting: 0.5s delay between API calls to respect quotas
            time.sleep(0.5)

    log.info(
        f"Classification loop complete: {classified_count} classified, "
        f"{skipped_count} skipped"
    )

    # ── Supabase batch update ────────────────────────────────────────────────
    update_classification_batch(update_rows, log)

    actual_cost = estimate_api_cost(classified_count, skip_plantnet)

    # Compute summary stats over classified canopies
    cross_validated_count = sum(
        1 for row in update_rows if row.get("cross_validated", False)
    )
    confidences = [row["species_confidence"] for row in update_rows if update_rows]
    avg_confidence = round(sum(confidences) / len(confidences), 3) if confidences else 0.0

    return {
        "classified_count": classified_count,
        "skipped_count": skipped_count,
        "cross_validated_count": cross_validated_count,
        "avg_confidence": avg_confidence,
        "api_calls_openai": openai_call_count,
        "api_calls_plantnet": plantnet_call_count,
        "total_api_cost_estimate": actual_cost,
        # Keep legacy key for backwards compatibility
        "api_cost_estimate": actual_cost,
        "plantnet_used": not skip_plantnet and bool(PLANTNET_API_KEY),
    }


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sentinel Aerial Inspections — Species Classification (Step E2)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Classifies tree species for each canopy detection using OpenAI Vision API
with optional PlantNet cross-validation.

Exit codes:
  0 — Success: all canopies classified, Supabase updated
  1 — Fatal error: ortho not found, cost threshold exceeded
  2 — Partial success: some canopies failed, remaining classified

Examples:
  python species_classification.py --mission-id abc-123 --ortho-path ortho.tif
  python species_classification.py --mission-id abc-123 --ortho-path ortho.tif --skip-plantnet
  python species_classification.py --mission-id abc-123 --ortho-path ortho.tif --max-canopies 50
  python species_classification.py --mission-id abc-123 --ortho-path ortho.tif --force
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
        "--max-canopies",
        type=int,
        default=200,
        help="Maximum number of canopies to classify (default: 200, largest by area first)",
    )
    parser.add_argument(
        "--skip-plantnet",
        action="store_true",
        help="Skip PlantNet cross-validation — OpenAI classification only",
    )
    parser.add_argument(
        "--cost-threshold",
        type=float,
        default=5.0,
        help="Abort if estimated OpenAI API cost exceeds this amount in USD (default: 5.0)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reclassify all canopies, ignoring existing species_tag",
    )
    add_pipeline_args(parser)
    args = parser.parse_args()

    log = setup_logging(SCRIPT_NAME)

    # ── Startup log ──────────────────────────────────────────────────────────
    log.info(f"Species Classification (E2) starting — mission {args.mission_id}")
    log.info(f"Ortho:          {args.ortho_path}")
    log.info(f"Vision backend: {VISION_BACKEND} (OLLAMA_URL={OLLAMA_URL})")
    log.info(f"Max canopies:   {args.max_canopies}")
    log.info(f"Skip PlantNet:  {args.skip_plantnet}")
    log.info(f"Cost threshold: ${args.cost_threshold:.2f}")
    log.info(f"Force:          {args.force}")

    # Pre-flight check: verify Ollama availability if selected as backend
    if VISION_BACKEND == "ollama":
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

    if args.max_canopies < 1:
        log.error(f"--max-canopies must be >= 1, got {args.max_canopies}")
        sys.exit(1)

    # ── Checkpoint setup ─────────────────────────────────────────────────────
    mission_dir = os.path.dirname(os.path.abspath(args.ortho_path))
    if args.force:
        clear_checkpoint(mission_dir, SCRIPT_NAME)
        log.info("--force: checkpoint cleared, reclassifying all canopies")

    completed_keys = load_checkpoint(mission_dir, SCRIPT_NAME)
    if completed_keys:
        log.info(f"Resuming from checkpoint: {len(completed_keys)} canopies already classified")

    # ── Pipeline status reporter ──────────────────────────────────────────────
    reporter = PipelineStatusReporter(
        processing_job_id=getattr(args, "processing_job_id", None),
        step_name="veg_species_classification",
    )
    reporter.start()

    # ── Run classification ────────────────────────────────────────────────────
    start_time = time.time()
    try:
        summary = run_classification(
            mission_id=args.mission_id,
            ortho_path=args.ortho_path,
            max_canopies=args.max_canopies,
            skip_plantnet=args.skip_plantnet,
            cost_threshold=args.cost_threshold,
            force=args.force,
            completed_keys=completed_keys,
            mission_dir=mission_dir,
            log=log,
        )
    except Exception as exc:
        log.exception(f"Classification failed: {exc}")
        reporter.fail(str(exc))
        sys.exit(1)

    elapsed = time.time() - start_time
    log.info(f"Classification complete in {elapsed:.1f}s — {summary['classified_count']} canopies classified")

    # Check for cost threshold exceeded error
    if summary.get("error") == "cost_threshold_exceeded":
        reporter.fail("cost_threshold_exceeded")
        sys.exit(1)

    # ── JSON stdout (parseable by n8n) ────────────────────────────────────────
    summary["processing_time_seconds"] = round(elapsed, 1)
    print(json.dumps(summary))

    # ── Reporter + exit code ──────────────────────────────────────────────────
    classified = summary["classified_count"]
    skipped = summary["skipped_count"]

    if skipped > 0 and classified == 0:
        # Everything skipped (all checkpointed or all failed)
        reporter.complete(output=f"{classified} classified, {skipped} skipped")
        sys.exit(2)
    else:
        reporter.complete(output=f"{classified} canopies classified")
        sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logging.getLogger(__name__).exception(f"Fatal: {exc}")
        sys.exit(1)
