#!/usr/bin/env bash
# ===========================================================================
#  Sentinel Aerial - headless RGB vegetation analysis wrapper (POSIX)
#
#  Works two ways:
#   1) From Git Bash on Windows  -> calls the QGIS python .bat directly.
#   2) From WSL2 (e.g. the NodeODM box) -> shells out to Windows QGIS via
#      cmd.exe, translating the /mnt/c path back to a Windows path.
#
#  Usage:
#    ./run_veg_analysis.sh <ortho.tif> <out_dir> [mission_id]
# ===========================================================================
set -euo pipefail

QGIS_PY_WIN='C:\Program Files\QGIS 3.44.12\bin\python-qgis-ltr.bat'
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ORTHO="${1:?usage: run_veg_analysis.sh <ortho.tif> <out_dir> [mission_id]}"
OUTDIR="${2:?usage: run_veg_analysis.sh <ortho.tif> <out_dir> [mission_id]}"
MID="${3:-ad-hoc}"

# Detect WSL vs native Git Bash
if grep -qiE "(microsoft|wsl)" /proc/version 2>/dev/null; then
  # WSL: convert paths and call Windows QGIS python through cmd.exe
  win_ortho="$(wslpath -w "$ORTHO")"
  win_out="$(wslpath -w "$OUTDIR")"
  win_script="$(wslpath -w "$SCRIPT_DIR/rgb_vegetation_analysis.py")"
  exec cmd.exe /c "\"$QGIS_PY_WIN\" \"$win_script\" --ortho \"$win_ortho\" --out \"$win_out\" --mission-id \"$MID\""
else
  # Git Bash on Windows: call the .bat directly
  exec "$SCRIPT_DIR/run_veg_analysis.bat" "$ORTHO" "$OUTDIR" "$MID"
fi
