---
phase: 06-integration-tests
plan: 02
status: complete
duration: 2 min
tests_added: 4
tests_total: 282
---

## Summary

Wrote 4 video pipeline integration tests (INTG-02): color grading through proxy generation with mocked FFmpeg and real checkpoint I/O.

### Tests
1. `test_color_grade_creates_graded_files` — grade loop creates output files + writes checkpoint (2 files)
2. `test_color_grade_checkpoint_skips_completed` — pre-populated checkpoint causes only 1 of 2 files to process
3. `test_proxy_generation_runs_after_grading` — proxy gen finds graded files, creates proxy outputs
4. `test_video_pipeline_no_videos_exits_cleanly` — empty video/full/ means no subprocess calls

### Key Design
- `mock_ffmpeg_success` side_effect writes fake output to the last cmd argument
- Real checkpoint files via `save_checkpoint`/`load_checkpoint`
- Supabase sys.modules stub (autouse) for video_color_grade import

### Verification
```
python -m pytest tests/integration/test_video_pipeline.py -v
4 passed in 0.08s
```

### Files Created
- `tests/integration/test_video_pipeline.py` — 4 integration tests
