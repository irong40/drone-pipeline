#!/usr/bin/env python3
"""
test_environment.py — Path E GPU and dependency verification script

Run inside .venv-path-e to confirm the environment is production-ready:
  .venv-path-e/Scripts/python test_environment.py

Checks:
  1. Python version is 3.12.x
  2. PROJ_LIB / PROJ_DATA env vars cleared (prevents QGIS conflict)
  3. PyTorch CUDA support
  4. GPU compute capability >= 12.0 (sm_120 for RTX 5070)
  5. GPU device name contains "5070"
  6. DeepForest imports and can instantiate
  7. Geospatial deps: rasterio, geopandas, shapely, fiona, pyproj
  8. Reporting deps: reportlab, matplotlib, folium
  9. API/DB deps: openai, requests, supabase

Exits 0 on success, 1 on any failure.
Prints JSON result to stdout on success.
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Argument parsing (pipeline convention — no actual args needed)
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Verify Path E Python environment is production-ready"
    )
    parser.add_argument(
        "--log-dir",
        default=os.environ.get("LOG_DIR", "logs"),
        help="Directory for log output (default: logs/)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show verbose pass/fail for each check",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(log_dir: str, verbose: bool) -> logging.Logger:
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    log_file = log_path / "test_environment.log"

    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )
    return logging.getLogger("test_environment")


# ---------------------------------------------------------------------------
# Check helpers
# ---------------------------------------------------------------------------

def fail(logger: logging.Logger, msg: str) -> None:
    """Print failure reason and exit 1."""
    logger.error("FAIL: %s", msg)
    print(f"ENVIRONMENT CHECK FAILED: {msg}", file=sys.stderr)
    sys.exit(1)


def ok(logger: logging.Logger, msg: str) -> None:
    logger.info("PASS: %s", msg)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_python_version(logger: logging.Logger) -> str:
    """Assert Python 3.12.x."""
    vi = sys.version_info
    version_str = f"{vi.major}.{vi.minor}.{vi.micro}"
    if vi[:2] != (3, 12):
        fail(logger, f"Python 3.12 required, got {version_str}")
    ok(logger, f"Python {version_str}")
    return version_str


def clear_proj_env(logger: logging.Logger) -> None:
    """Remove PROJ_LIB and PROJ_DATA before any geospatial import.

    QGIS installs its own PROJ data and sets these env vars, which
    causes rasterio / pyproj to pick up wrong data. Must be cleared
    BEFORE importing rasterio or pyproj.
    """
    removed = []
    for var in ("PROJ_LIB", "PROJ_DATA"):
        if var in os.environ:
            del os.environ[var]
            removed.append(var)
    if removed:
        ok(logger, f"Cleared QGIS PROJ env vars: {', '.join(removed)}")
    else:
        ok(logger, "PROJ env vars not set (no QGIS conflict)")


def check_torch(logger: logging.Logger) -> dict:
    """Check PyTorch CUDA support and GPU compute capability."""
    try:
        import torch
    except ImportError as e:
        fail(logger, f"torch not importable: {e}")

    torch_version = torch.__version__
    if not torch.cuda.is_available():
        fail(logger, f"torch.cuda.is_available() returned False — CUDA build not detected. "
                     f"Reinstall: pip install --index-url https://download.pytorch.org/whl/cu128 torch torchvision")

    cuda_version = torch.version.cuda or "unknown"
    ok(logger, f"torch {torch_version}, CUDA {cuda_version}")

    # sm_120 requires compute capability >= 12.0
    major, minor = torch.cuda.get_device_capability(0)
    if major < 12:
        fail(logger, f"GPU compute capability {major}.{minor} < 12.0 — sm_120 (RTX 5070) required")
    ok(logger, f"GPU compute capability {major}.{minor} (sm_120 satisfied)")

    # Sanity: device name should contain "5070"
    device_name = torch.cuda.get_device_name(0)
    if "5070" not in device_name:
        fail(logger, f"Expected RTX 5070 device, got: '{device_name}'. "
                     f"Verify the correct GPU is selected.")
    ok(logger, f"GPU: {device_name}")

    return {
        "torch": torch_version,
        "cuda": cuda_version,
        "gpu": device_name,
        "compute_capability": f"{major}.{minor}",
    }


def check_deepforest(logger: logging.Logger) -> str:
    """Import DeepForest and verify core prediction methods are callable.

    DeepForest v2.x renamed the API: predict_image, predict_tile, predict_file
    replace the bare predict() of v1.x.
    """
    try:
        import deepforest
        from deepforest.main import deepforest as DeepForest
    except ImportError as e:
        fail(logger, f"deepforest not importable: {e}")

    version = deepforest.__version__
    # Instantiate without downloading weights (cold instantiation only)
    try:
        model = DeepForest()
    except Exception as e:
        fail(logger, f"deepforest.main.deepforest() instantiation failed: {e}")

    # v2.x API: predict_image / predict_tile / predict_file
    # v1.x API: predict (kept as fallback)
    predict_methods = ["predict_image", "predict_tile", "predict_file", "predict"]
    found = [m for m in predict_methods if callable(getattr(model, m, None))]
    if not found:
        fail(logger, f"deepforest model has no callable predict method (checked: {predict_methods})")

    ok(logger, f"deepforest {version} — callable methods: {found[:3]}")
    return version


def check_geospatial(logger: logging.Logger) -> None:
    """Import rasterio, geopandas, shapely, fiona, pyproj."""
    checks = [
        ("rasterio", lambda: __import__("rasterio")),
        ("geopandas", lambda: __import__("geopandas")),
        ("shapely", lambda: __import__("shapely")),
        ("fiona", lambda: __import__("fiona")),
        ("pyproj", lambda: __import__("pyproj")),
    ]
    for name, importer in checks:
        try:
            mod = importer()
            version = getattr(mod, "__version__", "unknown")
            ok(logger, f"{name} {version}")
        except ImportError as e:
            fail(logger, f"{name} not importable: {e}")


def check_reporting(logger: logging.Logger) -> None:
    """Import reportlab, matplotlib, folium."""
    checks = [
        ("reportlab", lambda: __import__("reportlab")),
        ("matplotlib", lambda: __import__("matplotlib")),
        ("folium", lambda: __import__("folium")),
    ]
    for name, importer in checks:
        try:
            mod = importer()
            version = getattr(mod, "__version__", "unknown")
            ok(logger, f"{name} {version}")
        except ImportError as e:
            fail(logger, f"{name} not importable: {e}")


def check_api_clients(logger: logging.Logger) -> None:
    """Import openai, requests, supabase."""
    checks = [
        ("openai", lambda: __import__("openai")),
        ("requests", lambda: __import__("requests")),
        ("supabase", lambda: __import__("supabase")),
    ]
    for name, importer in checks:
        try:
            mod = importer()
            version = getattr(mod, "__version__", "unknown")
            ok(logger, f"{name} {version}")
        except ImportError as e:
            fail(logger, f"{name} not importable: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()
    logger = setup_logging(args.log_dir, args.verbose)

    logger.info("=== Path E Environment Verification ===")

    # 1. Python version
    python_version = check_python_version(logger)

    # 2. Clear PROJ env vars BEFORE any geospatial import
    clear_proj_env(logger)

    # 3-5. PyTorch + CUDA + GPU
    torch_info = check_torch(logger)

    # 6. DeepForest
    deepforest_version = check_deepforest(logger)

    # 7. Geospatial deps
    check_geospatial(logger)

    # 8. Reporting deps
    check_reporting(logger)

    # 9. API / DB clients
    check_api_clients(logger)

    # All checks passed — print JSON result
    result = {
        "status": "CUDA sm_120 verified",
        "python": python_version,
        "torch": torch_info["torch"],
        "cuda": torch_info["cuda"],
        "gpu": torch_info["gpu"],
        "compute_capability": torch_info["compute_capability"],
        "deepforest": deepforest_version,
        "all_imports": True,
    }

    logger.info("=== ALL CHECKS PASSED ===")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
