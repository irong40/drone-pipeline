# Phase 18: Path V Video Pipeline - Research

**Researched:** 2026-03-05
**Domain:** n8n workflow development, video processing pipeline orchestration, webhook-based pause/resume
**Confidence:** HIGH

## Summary

Phase 18 builds the Path V sub-workflow for n8n that automates the 6-script video pipeline (V1 through V6) with a manual DaVinci Resolve editing gate between V4 and V6. The Package Router already routes `video` package types to output index 2, which currently hits a NoOp stub node (`Execute Path V (Stub)`) that must be replaced with an Execute Sub Workflow node pointing to the new Path V workflow.

All six Python scripts already exist, are tested, and follow the pipeline contract (argparse CLI, exit codes 0/1/2, checkpoint resume). The `PipelineStatusReporter` class already has an `await_manual_edit()` method purpose-built for the V5 pause point. The key implementation challenge is the webhook-wait gate for V5: since Path V is invoked as a sub-workflow (via Execute Sub Workflow from the Package Router), and sub-workflows cannot host their own Webhook trigger nodes, the V5 gate must use the n8n **Wait node** with "On webhook call" resume type rather than a standalone Webhook node.

The established patterns from Path A (sub-workflow with Execute Command nodes, IF exit code check, Stop on Failure branching) and Path E (sequential script execution with status updates, review gate webhook) provide all the architectural precedent needed. Path V combines both patterns: Path A's sub-workflow structure with Path E's multi-step sequential execution and pause gate.

**Primary recommendation:** Build Path V as a sub-workflow JSON file (`path_v_workflow.json`) following the exact Path A pattern, with 5 sequential Execute Command nodes (V1-V4, then V6 after the gate), a Wait node for V5, and IF/Stop branching after each step for exit code 1 halting. Update the Package Router to replace the NoOp stub with an Execute Sub Workflow node.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PHV-01 | Path V executes V1, V1.5, V2, V3, V4 in sequence via Execute Command nodes | All 5 scripts exist with documented CLI interfaces; Path A pattern proves sequential Execute Command chaining works; PipelineStatusReporter already integrated into video_color_grade.py, needs --processing-job-id added to V1.5/V2/V3/V4 |
| PHV-02 | After V4, Path V pauses at webhook-wait gate for V5 manual edit | n8n Wait node (typeVersion 1.1) with "On webhook call" resume type; PipelineStatusReporter.await_manual_edit() already exists; processing_jobs step v5_resolve_gate already in STEP_MAP |
| PHV-03 | On V5 resume webhook, V6 and delivery_packaging run automatically | Wait node resumes execution on POST; V6 (video_format_export.py) reads from video/master/; delivery_packaging.py with --video-addendum flag packages exports |
| PHV-04 | Each V-script step updates Supabase processing_steps status | PipelineStatusReporter handles start/complete/fail; video_color_grade.py already uses it; other V scripts need --processing-job-id arg added via add_pipeline_args() |
| PHV-05 | Exit code 1 marks step failed and halts Path V without blocking other paths | Path A IF node pattern (check exitCode != 0 -> Stop on Failure); sub-workflow isolation means failure does not propagate to Package Router or other paths |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| n8n | 2.10.3 | Workflow orchestration | Already installed natively on Windows (Phase 14 verified) |
| Python | 3.14 (system) | Script execution via Execute Command | All V scripts use system Python |
| FFmpeg | system PATH | Video processing (color grade, proxy, export) | Required by V1, V4, V6 scripts |

### Node Types Used
| n8n Node | TypeVersion | Purpose |
|----------|-------------|---------|
| n8n-nodes-base.executeWorkflowTrigger | 1 | Sub-workflow entry point (same as Path A) |
| n8n-nodes-base.executeCommand | 1 | Run V1/V1.5/V2/V3/V4/V6/delivery scripts |
| n8n-nodes-base.code | 2 | Parse Execute Command stdout, merge data between steps |
| n8n-nodes-base.if | 2 | Check exit codes for stop-on-failure branching |
| n8n-nodes-base.wait | 1.1 | V5 gate: pause until operator POSTs resume webhook |
| n8n-nodes-base.executeWorkflow | 1 | Package Router dispatches to Path V (replaces NoOp stub) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Wait node (webhook resume) | Separate Webhook node in standalone workflow | Sub-workflows cannot host Webhook trigger nodes; Wait node is the correct approach for pausing within a sub-workflow |
| Individual IF nodes per step | Single error handler node | Per-step IF matches Path A pattern and is clearer; halts at exact failure point |

## Architecture Patterns

### Recommended Workflow Structure
```
n8n/
  path_v_workflow.json          # NEW: Path V sub-workflow
  package_router.json           # PATCH: Replace NoOp stub with Execute Sub Workflow
  package_router_patch.json     # EXISTING: May need video step config additions
```

### Pattern 1: Sequential Execute Command Chain with Exit Code Guards
**What:** Each V-script runs as an Execute Command node, followed by a Code node to parse stdout/exit code, followed by an IF node to check for failure.
**When to use:** Every script step in the pipeline (V1, V1.5, V2, V3, V4, V6).
**Example (from Path A, applied to V1):**
```
Execute V1 Color Grade
  -> Parse V1 Result (Code node: extract exitCode, merge with trigger params)
  -> IF V1 Failed (IF node: exitCode != 0)
    -> TRUE: Stop on Failure (Code node: return failure status)
    -> FALSE: Execute V1.5 Metadata (next step)
```

### Pattern 2: Wait Node for V5 DaVinci Resolve Gate
**What:** After V4 completes, the workflow pauses using an n8n Wait node configured for "On webhook call" resume. The operator edits video in DaVinci Resolve (offline), then POSTs to the Wait node's resume URL to continue.
**When to use:** V5 manual edit gate only.
**Configuration:**
```json
{
  "parameters": {
    "resume": "webhook",
    "options": {
      "webhookSuffix": "v5-resolve-complete"
    }
  },
  "type": "n8n-nodes-base.wait",
  "typeVersion": 1.1
}
```
**Resume URL format:** `{N8N_BASE_URL}/webhook-waiting/{executionId}/v5-resolve-complete`
**Critical detail:** Before the Wait node, a Code node should update the processing_jobs step `v5_resolve_gate` to `awaiting_manual_edit` via PipelineStatusReporter pattern, and output the resume URL so the operator knows where to POST when done.

### Pattern 3: PipelineStatusReporter Integration per Step
**What:** Each script uses `--processing-job-id` to self-report status to Supabase processing_jobs.steps JSONB.
**When to use:** Every Execute Command node passes `--processing-job-id {{ $json.processing_job_id }}`.
**Current state of V scripts:**
- `video_color_grade.py` -- already has `add_pipeline_args(parser)` and PipelineStatusReporter
- `video_metadata.py` -- does NOT have PipelineStatusReporter; needs addition
- `srt_telemetry_parser.py` -- does NOT have PipelineStatusReporter; needs addition
- `video_qa.py` -- does NOT have PipelineStatusReporter; needs addition
- `video_proxy_gen.py` -- does NOT have PipelineStatusReporter; needs addition
- `video_format_export.py` -- does NOT have PipelineStatusReporter; needs addition

### Pattern 4: Sub-workflow Payload Contract
**What:** The Execute Sub Workflow Trigger receives a standard payload from the Package Router's Prepare Dispatch node.
**Expected input parameters (same as Path A):**
```json
{
  "mission_id": "UUID from processing_jobs table",
  "package_type": "video",
  "mission_number": "integer",
  "folder_path": "Full path to mission folder on disk",
  "processing_job_id": "UUID of the processing_jobs row for status reporting",
  "source_platform": "Drone platform (mini4pro, m4e, m3e)",
  "address": "Property street address",
  "city": "City name"
}
```

### Anti-Patterns to Avoid
- **Running V scripts with shell=True:** Never use shell=True in subprocess calls (established project convention from Phase 15)
- **Blocking on FFmpeg stdout in n8n:** V1/V4/V6 involve FFmpeg which can produce large stderr; Execute Command node handles this correctly since stderr goes to node output, not n8n memory
- **Using a standalone Webhook node for V5 gate:** Sub-workflows cannot register their own webhook paths; use Wait node instead
- **Skipping exit code checks:** Every Execute Command MUST be followed by an exit code check IF node; a failed V script should halt the chain immediately

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Step status reporting | Custom Supabase HTTP calls in n8n Code nodes | PipelineStatusReporter in each Python script | Already built, handles all edge cases (missing Supabase, failed connections, status aggregation) |
| Workflow pause/resume | Custom polling loop or external job queue | n8n Wait node with webhook resume | Built-in n8n feature, persists execution state to database, survives n8n restarts |
| Video format configuration | Hardcoded format list in n8n | Supabase processing_templates.video_formats | Already exists, V6 script reads from Supabase or falls back to DEFAULT_FORMATS |
| Processing steps definition | Custom step builder per workflow | STEP_MAP in Package Router Build Steps node | Already defines video steps: v1_color, v1_5_metadata, v2_srt, v3_qa, v4_proxy, v5_resolve_gate, v6_export, delivery_packaging |

**Key insight:** The processing_jobs steps for video are already defined in the Package Router's STEP_MAP. The V scripts just need --processing-job-id to report against those pre-created step entries.

## Common Pitfalls

### Pitfall 1: Wait Node Resume URL Not Communicated to Operator
**What goes wrong:** Workflow pauses at V5 but operator has no way to know the resume URL since it contains the executionId.
**Why it happens:** The resume URL is dynamic (includes executionId) and is not automatically surfaced.
**How to avoid:** Before the Wait node, use a Code node to set the v5_resolve_gate step status to `awaiting_manual_edit` and store the resume URL hint in the step output. The operator can find it in Supabase or n8n execution UI.
**Warning signs:** Workflow stays paused forever; operator does not know how to resume.

### Pitfall 2: V Script Missing --processing-job-id Argument
**What goes wrong:** Script runs fine but does not update Supabase status; processing_jobs row shows step stuck on "pending".
**Why it happens:** 5 of 6 V scripts do not yet have `add_pipeline_args(parser)` or PipelineStatusReporter integration.
**How to avoid:** Add PipelineStatusReporter to all V scripts before building the n8n workflow.
**Warning signs:** Steps show "pending" in processing_jobs after script has completed.

### Pitfall 3: Video QA Requires --mission-id (Not Just mission_path)
**What goes wrong:** video_qa.py exits with error because it requires `--mission-id` as a required argument (it fetches data from Supabase).
**Why it happens:** V3 QA operates on Supabase video_assets data populated by V1.5 and V2, not on local files.
**How to avoid:** Execute Command for V3 must include `--mission-id {{ $json.mission_id }}`.
**Warning signs:** V3 exits with code 2 (configuration error).

### Pitfall 4: V6 Requires Master Video in video/master/
**What goes wrong:** video_format_export.py exits with "No master video found in video/master/" error.
**Why it happens:** V5 (DaVinci Resolve manual edit) is supposed to produce the master edit file in video/master/. If operator forgets to save there, V6 fails.
**How to avoid:** Document the expected V5 output location in the Wait node notes; optionally add a Code node after Wait that checks video/master/ exists before running V6.
**Warning signs:** V6 exits with code 2 immediately after V5 resume.

### Pitfall 5: Sub-workflow Failure Does Not Block Other Paths
**What goes wrong:** Actually this is DESIRED behavior, not a pitfall. But be aware: if Path V fails, the Package Router continues normally. Other paths (A, C) running for the same mission are unaffected.
**Why it happens:** n8n Execute Sub Workflow runs the sub-workflow; errors within the sub-workflow are caught by the sub-workflow's own flow.
**How to avoid:** This is correct architecture. Path V failure is isolated by design.

## Code Examples

### Execute Command Pattern for V1 Color Grade
```
Command expression (Execute Command node):
python "{{ $env.SENTINEL_SCRIPTS }}\video_color_grade.py" "{{ $json.folder_path }}" --platform {{ $json.source_platform || 'mini4pro' }} --processing-job-id {{ $json.processing_job_id }}
```

### Execute Command Pattern for V1.5 Metadata
```
Command expression:
python "{{ $env.SENTINEL_SCRIPTS }}\video_metadata.py" "{{ $json.folder_path }}" --platform {{ $json.source_platform || 'mini4pro' }} --mission-id {{ $json.mission_id }} --upload --processing-job-id {{ $json.processing_job_id }}
```

### Execute Command Pattern for V2 SRT Telemetry
```
Command expression:
python "{{ $env.SENTINEL_SCRIPTS }}\srt_telemetry_parser.py" "{{ $json.folder_path }}" --platform {{ $json.source_platform || 'mini4pro' }} --mission-id {{ $json.mission_id }} --upload --processing-job-id {{ $json.processing_job_id }}
```

### Execute Command Pattern for V3 QA
```
Command expression:
python "{{ $env.SENTINEL_SCRIPTS }}\video_qa.py" --mission-id {{ $json.mission_id }} --mission-path "{{ $json.folder_path }}" --processing-job-id {{ $json.processing_job_id }}
```

### Execute Command Pattern for V4 Proxy Gen
```
Command expression:
python "{{ $env.SENTINEL_SCRIPTS }}\video_proxy_gen.py" "{{ $json.folder_path }}" --processing-job-id {{ $json.processing_job_id }}
```

### Execute Command Pattern for V6 Format Export (after V5 gate)
```
Command expression:
python "{{ $env.SENTINEL_SCRIPTS }}\video_format_export.py" "{{ $json.folder_path }}" --mission-id {{ $json.mission_id }} --processing-job-id {{ $json.processing_job_id }}
```

### Execute Command Pattern for Delivery Packaging (final step)
```
Command expression:
python "{{ $env.SENTINEL_SCRIPTS }}\delivery_packaging.py" "{{ $json.folder_path }}" --address "{{ $json.address || 'Unknown' }}" --city "{{ $json.city || 'Unknown' }}" --video-addendum --processing-job-id {{ $json.processing_job_id }}
```

### Parse Result Code Node Pattern (reused per step)
```javascript
// Source: path_a_workflow.json Parse Color Grade Result pattern
const input = $('Execute Sub Workflow Trigger').first().json;
const execResult = items[0].json;
const exitCode = execResult.exitCode || 0;
const stdout = execResult.stdout || '';

let parsed = {};
try { parsed = JSON.parse(stdout); } catch(e) { parsed = { raw: stdout }; }

return [{json: {
  ...input,
  v1_exit_code: exitCode,
  v1_result: parsed
}}];
```

### V5 Gate Code Node (before Wait node)
```javascript
// Mark v5_resolve_gate as awaiting_manual_edit in processing_jobs
const input = items[0].json;

return [{json: {
  ...input,
  v5_status: 'awaiting_manual_edit',
  v5_message: 'V4 proxy generation complete. Open DaVinci Resolve, edit using proxies in video/proxy/, export master to video/master/. Then POST to the resume webhook to continue.'
}}];
```

### Wait Node Configuration for V5
```json
{
  "parameters": {
    "resume": "webhook",
    "options": {
      "webhookSuffix": "v5-resolve-complete"
    }
  },
  "id": "node-v5-wait",
  "name": "V5 — Wait for DaVinci Resolve Edit",
  "type": "n8n-nodes-base.wait",
  "typeVersion": 1.1,
  "notes": "MANUAL GATE: Workflow pauses here. Operator edits video in DaVinci Resolve using proxies from video/proxy/. When complete, operator exports master to video/master/ and POSTs to resume webhook. Resume URL: {N8N_BASE_URL}/webhook-waiting/{executionId}/v5-resolve-complete"
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual execution of V1-V6 scripts one by one | n8n orchestrated sequential execution | Phase 18 (this phase) | Saves 10-15 minutes operator time per video mission |
| No pause mechanism for V5 | n8n Wait node with webhook resume | Phase 18 (this phase) | Reliable pause/resume survives n8n restarts |
| No processing status tracking for V scripts | PipelineStatusReporter per step | Phase 18 (this phase) | Real-time visibility into video processing progress |

## Script CLI Interface Summary

| Script | Step | Required Args | Optional Args | Exit Codes |
|--------|------|--------------|---------------|------------|
| video_color_grade.py | V1 | mission_path | --platform, --lut, --processing-job-id | 0=ok, 1=partial, 2=all failed |
| video_metadata.py | V1.5 | mission_path | --platform, --mission-id, --upload, --processing-job-id (needs adding) | 0=ok, 1=probe failures |
| srt_telemetry_parser.py | V2 | mission_path | --platform, --mission-id, --upload, --processing-job-id (needs adding) | 0=ok, 1=partial, 2=all failed |
| video_qa.py | V3 | --mission-id | --mission-path, --thresholds, --processing-job-id (needs adding) | 0=ok, 1=partial, 2=all failed |
| video_proxy_gen.py | V4 | mission_path | --resolution, --processing-job-id (needs adding) | 0=ok, 1=partial, 2=all failed |
| video_format_export.py | V6 | mission_path | --mission-id, --formats, --processing-job-id (needs adding) | 0=ok, 1=partial, 2=all failed |
| delivery_packaging.py | final | mission_path, --address, --city | --video-addendum, --processing-job-id | 0=ok, 1=failure |

## Package Router Patch Required

The Package Router (`package_router.json`) must be updated:
1. Replace `node-stub-path-v` (NoOp) with Execute Sub Workflow node pointing to `sentinel-path-v`
2. The Switch node output index 2 (video) already routes correctly; only the target node changes

## Processing Steps Already Defined

The STEP_MAP in `package_router.json` Build Steps node already defines video steps:
```javascript
video: [
  {name: 'v1_color', status: 'pending'},
  {name: 'v1_5_metadata', status: 'pending'},
  {name: 'v2_srt', status: 'pending'},
  {name: 'v3_qa', status: 'pending'},
  {name: 'v4_proxy', status: 'pending'},
  {name: 'v5_resolve_gate', status: 'pending'},
  {name: 'v6_export', status: 'pending'},
  {name: 'delivery_packaging', status: 'pending'}
]
```

Each V script's PipelineStatusReporter `step_name` must match these exactly.

## Open Questions

1. **PipelineStatusReporter step_name mapping**
   - What we know: The STEP_MAP uses names like `v1_color`, `v1_5_metadata`, etc.
   - What's unclear: Each script currently uses its Python filename as step_name (e.g., `video_color_grade`). These must be changed to match the STEP_MAP names.
   - Recommendation: Update step_name in each script's PipelineStatusReporter constructor OR keep script names and update STEP_MAP. Updating the scripts is cleaner since STEP_MAP is already in production in the Package Router.

2. **V5 resume webhook authentication**
   - What we know: n8n Wait node supports authentication options for the webhook resume endpoint.
   - What's unclear: Whether authentication should be added for the V5 resume webhook.
   - Recommendation: Skip authentication for now (single-rig local network); add in v3.1 if needed.

## Sources

### Primary (HIGH confidence)
- `n8n/path_a_workflow.json` - Sub-workflow pattern (Execute Command + IF exit code + Stop on Failure)
- `n8n/path_e_workflow.json` - Sequential script execution with status updates and review gate
- `n8n/package_router.json` - STEP_MAP for video, Switch routing, NoOp stub to replace
- `pipeline_status.py` - PipelineStatusReporter with await_manual_edit() method
- V script source files (video_color_grade.py, video_metadata.py, srt_telemetry_parser.py, video_qa.py, video_proxy_gen.py, video_format_export.py)

### Secondary (MEDIUM confidence)
- [n8n Wait node docs](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.wait/) - Wait node configuration and webhook resume type
- [n8n Waiting flow logic](https://docs.n8n.io/flow-logic/waiting/) - Execution persistence and resume mechanics

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all tools already installed, verified in Phase 14
- Architecture: HIGH - Path A and Path E provide complete patterns; sub-workflow + Execute Command pattern proven
- Pitfalls: HIGH - based on actual script source code analysis (CLI args, exit codes, file paths)
- V5 Wait node config: MEDIUM - based on n8n docs; exact webhook-wait behavior in sub-workflows should be validated

**Research date:** 2026-03-05
**Valid until:** 2026-04-05 (stable infrastructure, no fast-moving dependencies)
