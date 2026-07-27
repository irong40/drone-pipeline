"""Shim — real implementation lives at dormant/archive_sync.py (moved 2026-07-27).

The \\Sentinel\\ArchiveSync scheduled task points at this path and cannot be
repointed without elevation. This keeps the weekly Drive -> cold-storage sync
alive (it had been failing silently with exit 2 since the dormant/ move) while
the code itself stays retired in dormant/.
"""
import os
import sys
import runpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
runpy.run_module("dormant.archive_sync", run_name="__main__")
