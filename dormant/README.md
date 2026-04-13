# Dormant Subsystems

Infrastructure that was built but never put into active use. Lives here
instead of the repo root so the active file surface stays visible at a
glance. Reactivate by moving files back to the parent directory and
completing the setup step listed below.

## Folder Watcher Windows Service
- `folder_watcher_service.py`

**Why dormant:** Never registered as a Windows service (`sc query sentinel_folder_watcher` returns error 1060). The active workflow runs `folder_watcher.py` as a subprocess of `start-all.bat` instead, which only lives as long as that console stays open.

**Reactivate:** Move back, then run as Administrator:
`python folder_watcher_service.py install` followed by `sc start sentinel_folder_watcher`.

## Archive Sync
- `archive_sync.py`
- `install-scheduled-tasks.bat`

**Why dormant:** The `install-scheduled-tasks.bat` was never executed as Administrator, so no scheduled task exists. `archive_sync.py` has only ever been invoked manually (see `logs/archive_sync.log`).

**Reactivate:** Move both back, right-click `install-scheduled-tasks.bat` -> "Run as administrator".

## Path A (Lightroom photo edit)
- `photo_edit.py`
- `sentinel-auto-export.lrplugin/`

**Why dormant:** Blocked on (1) SAI XMP preset installation in `AppData/Roaming/Adobe/CameraRaw/Settings/` and (2) Lightroom Classic plugin setup via Plugin Manager. See `drone-pipeline.md` memory for the full activation checklist.

**Reactivate:** Move both back. Install the plugin via `File > Plug-in Manager` in Lightroom Classic, then run `python photo_edit.py --mission-id test-001 ... --dry-run` to verify.

## Path E (Vegetation analysis)
- `canopy_detection.py`
- `species_classification.py`
- `health_assessment.py`
- `vegetation_report.py`
- `ollama_vision.py`
- `requirements-path-e.txt`
- `n8n/path_e_workflow.json`

**Why dormant:** Requires a local Ollama server running and the `.venv-path-e` virtual environment. Last exercised Mar 16 per `logs/canopy_detection.log`. No active vegetation-analysis contracts.

**Reactivate:** Move files back, create `.venv-path-e` with `python -m venv .venv-path-e`, install from `requirements-path-e.txt`, start Ollama, import `path_e_workflow.json` into n8n.

## Path V (Video processing)
- `video_color_grade.py`
- `video_metadata.py`
- `srt_telemetry_parser.py`
- `video_qa.py`
- `video_proxy_gen.py`
- `video_format_export.py`

**Why dormant:** No active video deliverables. DaVinci Resolve CLI integration never tested against real footage. `package_router_workflow.json` (still in `n8n/`) has the `run_video` branch that would dispatch these once reactivated.

**Reactivate:** Move all six back. Confirm DaVinci Resolve CLI/Python API works on the rig, then flip `video_included` to `true` on the relevant rows of `processing_templates`.
