---
phase: 06-integration-tests
plan: 01
status: complete
duration: 2 min
tests_added: 4
tests_total: 282
---

## Summary

Created integration test package and wrote 4 ingest flow integration tests (INTG-01).

### Tests
1. `test_full_ingest_sorts_files_into_mission_subfolders` — full flow: scan→sort→create→copy→verify all 6 subfolders and files on disk
2. `test_ingest_unassigned_files_not_copied` — outlier sequence numbers remain unassigned
3. `test_ingest_multi_extension_routing` — JPG→photos/jpeg, DNG→photos/raw, MP4→video/full, SRT→video/telemetry, MRK→ppk
4. `test_inventory_count_after_ingest` — photo_count=2, video_count=1, has_ppk_data=True

### Key Design
- Real filesystem I/O against `tmp_path` — no mocking
- Synthetic SD card with 5 in-range files + 1 outlier + 1 non-DJI file
- `importorskip("requests")` guard for CI environments

### Verification
```
python -m pytest tests/integration/test_ingest_flow.py -v
4 passed in 0.12s
```

### Files Created
- `tests/integration/__init__.py` — package marker
- `tests/integration/test_ingest_flow.py` — 4 integration tests
