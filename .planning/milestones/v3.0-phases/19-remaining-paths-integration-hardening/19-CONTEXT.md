# Phase 19: Remaining Paths + Integration + Hardening - Context

**Gathered:** 2026-03-05
**Status:** Ready for planning

<domain>
## Phase Boundary

All package types have a routing destination, folder watcher events flow into the router, and the full pipeline is validated end-to-end. Specifically: Path B (construction) and Path D (ADIAT) get manual-handling stubs, folder_watcher.py payloads are normalized to match ingest_sorter format, all n8n workflow JSONs are validated, and an integration test proves webhook-to-Supabase flow works.

</domain>

<decisions>
## Implementation Decisions

### Operator Notifications (Path B/D)
- Use n8n Send Email node via SMTP for operator notification when B/D missions arrive
- Recipient address from OPERATOR_EMAIL environment variable (single address, configurable without workflow edit)
- Single shared "manual path" sub-workflow for both Path B and Path D — package type passed as parameter, not two separate workflows
- Sub-workflow sets processing_jobs status to "manual" in Supabase AND sends notification email

### Folder Watcher Normalization
- Package Router Code node normalizes folder_watcher.py payload to match ingest_sorter.py format before routing
- Both folder_watcher webhook and ingest_sorter webhook route to the same Package Router entry point (FWI-02)

### Claude's Discretion
- Email body content and formatting (mission number, package type, folder path, inventory summary — Claude picks appropriate detail level)
- How to derive package_type from folder_watcher payload (recommended: parse from SAI_MNNNN_TYPE_DATE folder name pattern — no external dependency)
- How to resolve mission_id from folder_watcher payload (recommended: Supabase lookup by mission_number since ingest_sorter creates mission record first)
- Workflow JSON validation approach (TST-03) — syntax check, schema validation, or n8n API import test
- Integration test strategy (TST-04) — mock vs live n8n, mock vs real Supabase, test fixture design
- Error handling when folder name doesn't match expected pattern (fallback to manual status?)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `folder_watcher.py`: Sends `{mission_folder, mission_number, photo_count, video_count, has_ppk, total_size_bytes, first_file_time, last_file_time}` to `/webhook/folder-watcher`
- `ingest_sorter.py`: Sends `{mission_id, mission_number, package_type, sorted_folder, files_moved, total_bytes}` to `/webhook/ingest`
- `pipeline_utils.py`: Shared constants (LOG_DIR, PHOTO_EXTS, VIDEO_EXTS, PPK_EXTS), `setup_logging()`, `extract_sequence_number()`
- `platform_detect.py`: `detect_platform_from_folder()` — may inform package type inference
- Existing test patterns: pytest with mock external services via sys.modules stub injection

### Established Patterns
- Pipeline contract: argparse CLI, JSON stdout, setup_logging, Supabase status update, exit codes 0/1/2
- n8n workflow JSON files live in project root (e.g., `package_router_patch.json`, `path_e_workflow.json`)
- Webhook URLs use env vars with localhost defaults
- Supabase service role auth via SUPABASE_URL + SUPABASE_SERVICE_KEY env vars

### Integration Points
- Package Router Switch node routes to Path A/B/C/D/V sub-workflows based on package_type
- processing_jobs table tracks per-mission step status (created by RTR-04 in Phase 16)
- Folder watcher fires to `/webhook/folder-watcher`, ingest_sorter fires to `/webhook/ingest`
- Path E vegetation trigger webhook already exists at `/sentinel-vegetation-trigger`

</code_context>

<specifics>
## Specific Ideas

No specific requirements — user deferred all remaining decisions to Claude's judgment with instruction to "do it the most best way" using recommended approaches.

</specifics>

<deferred>
## Deferred Ideas

- Full Path B (construction) automation beyond stub — v3.1 (PBD-03)
- Full Path D (ADIAT) automation beyond stub — v3.1 (PBD-04)
- Slack/Discord notifications as alternative to email — future enhancement
- n8n dashboard for real-time mission status monitoring — v3.1 (AUT-03)

</deferred>

---

*Phase: 19-remaining-paths-integration-hardening*
*Context gathered: 2026-03-05*
