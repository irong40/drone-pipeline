"""
Sentinel Aerial Inspections — Ollama Vision Utility

Shared module for local LLaVA-based vision inference via Ollama.
Provides species classification and health assessment functions that
mirror the OpenAI Vision API calls but run locally at zero cost.

Requires Ollama running at OLLAMA_URL (default: http://localhost:11434)
with the llava:13b model pulled.

Usage:
    from ollama_vision import classify_species, assess_health, check_ollama

    if check_ollama():
        result = classify_species(image_bytes, HAMPTON_ROADS_SPECIES)
        health = assess_health(image_bytes)
"""

import base64
import json
import logging
import os
from typing import Any, Dict, List, Optional

import requests

# ─── CONFIG ──────────────────────────────────────────────────────────────────

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = "llava:13b"
OLLAMA_TIMEOUT = 30  # seconds


log = logging.getLogger(__name__)


# ─── HEALTH CHECK ────────────────────────────────────────────────────────────

def check_ollama() -> bool:
    """Check if Ollama is available and has the llava model loaded.

    Returns:
        True if Ollama is reachable and llava:13b is available, False otherwise.
    """
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if resp.status_code != 200:
            return False
        models = resp.json().get("models", [])
        model_names = [m.get("name", "") for m in models]
        # Match "llava:13b" or "llava:13b-v1.6" etc.
        return any(name.startswith("llava:13b") for name in model_names)
    except Exception:
        return False


# ─── SPECIES CLASSIFICATION ──────────────────────────────────────────────────

def classify_species(
    image_bytes: bytes,
    species_list: List[str],
) -> Optional[Dict[str, Any]]:
    """Classify tree species from canopy image bytes using Ollama LLaVA.

    Args:
        image_bytes: JPEG or PNG bytes of the canopy crop.
        species_list: List of common species names for the region.

    Returns:
        Dict with species_common, species_scientific, vegetation_type,
        confidence, reasoning, secondary_candidates.
        Returns None on timeout or any failure.
    """
    prompt = (
        "You are a certified arborist identifying tree species from aerial drone imagery "
        "over Hampton Roads, Virginia. "
        "The image shows a single tree canopy viewed from above. "
        "Identify the most likely species based on canopy shape, color, texture, and size.\n\n"
        "Common species in Hampton Roads include: "
        + ", ".join(species_list)
        + ".\n\n"
        "Respond with JSON only (no markdown, no explanation):\n"
        '{"species_common": "common name", '
        '"species_scientific": "Genus species", '
        '"vegetation_type": "tree" | "shrub" | "unknown", '
        '"confidence": 0.0-1.0, '
        '"reasoning": "brief explanation of key identifying features", '
        '"secondary_candidates": [{"species_common": "name", "confidence": 0.0-1.0}]}'
    )

    try:
        img_b64 = base64.b64encode(image_bytes).decode()

        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "images": [img_b64],
                "stream": False,
                "options": {"num_predict": 512, "temperature": 0.1},
            },
            timeout=OLLAMA_TIMEOUT,
        )

        if response.status_code != 200:
            log.warning(f"Ollama returned HTTP {response.status_code}")
            return None

        raw = response.json().get("response", "").strip()

        result = _parse_json(raw)
        if result is None:
            return None

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

    except requests.exceptions.Timeout:
        log.warning(f"Ollama classify_species timed out after {OLLAMA_TIMEOUT}s")
        return None
    except Exception as exc:
        log.warning(f"Ollama classify_species failed: {exc}")
        return None


# ─── HEALTH ASSESSMENT ───────────────────────────────────────────────────────

def assess_health(image_bytes: bytes) -> Optional[Dict[str, Any]]:
    """Assess tree canopy health from image bytes using Ollama LLaVA.

    Args:
        image_bytes: JPEG or PNG bytes of the canopy crop.

    Returns:
        Dict with health_score, observations, discoloration_pct, dead_branch_pct,
        thinning, disease_indicators, recommended_action.
        Returns None on timeout or any failure.
    """
    prompt = (
        "You are inspecting a tree canopy from aerial drone imagery. "
        "Assess visible health indicators: discoloration, dead branches, thinning, "
        "disease, pest damage. "
        "Respond with JSON only (no markdown, no explanation): "
        '{"health_score": 0.0-1.0, "observations": "brief text", '
        '"discoloration_pct": 0-100, "dead_branch_pct": 0-100, '
        '"thinning": true/false, "disease_indicators": "none or description", '
        '"recommended_action": "monitor" | "inspect" | "urgent"}'
    )

    try:
        img_b64 = base64.b64encode(image_bytes).decode()

        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "images": [img_b64],
                "stream": False,
                "options": {"num_predict": 256, "temperature": 0.1},
            },
            timeout=OLLAMA_TIMEOUT,
        )

        if response.status_code != 200:
            log.warning(f"Ollama returned HTTP {response.status_code}")
            return None

        raw = response.json().get("response", "").strip()

        result = _parse_json(raw)
        if result is None:
            return None

        # Validate health_score is numeric in [0, 1]
        score = float(result.get("health_score", 0.5))
        result["health_score"] = round(max(0.0, min(1.0, score)), 3)

        return result

    except requests.exceptions.Timeout:
        log.warning(f"Ollama assess_health timed out after {OLLAMA_TIMEOUT}s")
        return None
    except Exception as exc:
        log.warning(f"Ollama assess_health failed: {exc}")
        return None


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def _parse_json(text: str) -> Optional[Dict[str, Any]]:
    """Parse JSON from LLM response, stripping markdown fences if present.

    Args:
        text: Raw LLM output string.

    Returns:
        Parsed dict or None on failure.
    """
    try:
        # Strip markdown code fences if present
        if text.startswith("```"):
            parts = text.split("```")
            if len(parts) >= 2:
                text = parts[1]
                if text.startswith("json"):
                    text = text[4:].strip()
        return json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning(f"Ollama JSON parse failed: {exc} — raw: {text[:200]}")
        return None
