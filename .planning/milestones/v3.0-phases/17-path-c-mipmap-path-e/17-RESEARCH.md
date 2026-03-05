# Phase 17: Path C MipMap Automation + Path E Connection - Research

**Researched:** 2026-03-05
**Domain:** n8n sub-workflow automation, MipMap polling, Path E webhook triggering
**Confidence:** HIGH

## Summary

Phase 17 replaces the Path C noOp stub in the Package Router with a real sub-workflow that launches MipMap via mipmap_launcher.py, polls for GeoTIFF completion in the MipMap workspace, harvests the ortho via ortho_harvester.py, and optionally fires the existing Path E vegetation trigger webhook. All foundation pieces are already built: mipmap_launcher.py (Phase 15), ortho_harvester.py (Phase 15), the Path E workflow with `/sentinel-vegetation-trigger` webhook (v2.0), and the Package Router with its Path C stub (Phase 16).

The existing Path E workflow already implements the exact polling pattern needed -- a Wait node loop with Execute Command file-existence check, attempt counter via workflow static data, and timeout detection. Phase 17 can mirror this proven pattern for Path C's MipMap output polling, with longer timeout (120 polls x 60s = 2 hours instead of Path E's 30 polls x 60s = 30 min).

**Primary recommendation:** Build a single `path_c_workflow.json` sub-workflow that follows the exact same architecture as `path_a_workflow.json` (Execute Sub Workflow Trigger entry, Execute Command nodes, exit code checking) combined with the Path E polling loop pattern. Replace the Package Router's `node-stub-path-c` noOp with an Execute Workflow node pointing to `sentinel-path-c`.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| MPC-03 | n8n Path C sub-workflow polls MipMap output directory for GeoTIFF completion with configurable interval and timeout | Proven polling pattern exists in Path E workflow (E0 nodes). MipMap workspace output path is `D:/{user_id}/{project_name}/{task_name}/result/orthomosaic.tif`. Wait node + Execute Command + IF + counter loop. |
| MPC-06 | After ortho confirmed in mapping/, Path C sub-workflow fires POST to /sentinel-vegetation-trigger to start existing Path E workflow (if vegetation_analysis=true) | Path E webhook already exists at `/sentinel-vegetation-trigger`, expects `{ mission_id }` payload. Use n8n HTTP Request node for POST. Conditional on `vegetation_analysis` flag from template config or drone_jobs. |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| n8n | 2.x | Workflow orchestration | Already deployed natively on Windows |
| mipmap_launcher.py | Phase 15 | Fire-and-forget MipMap subprocess launcher | Already built and tested (13 tests) |
| ortho_harvester.py | Phase 15 | GeoTIFF copy + integrity verification | Already built and tested (15 tests) |
| path_e_workflow.json | v2.0 | Vegetation analysis trigger target | Already deployed, webhook at /sentinel-vegetation-trigger |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| psutil | installed | MipMap orphan detection (used by mipmap_launcher.py) | Already a dependency |
| rasterio | optional | GeoTIFF validation in ortho_harvester.py | Falls back to magic bytes if unavailable |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Wait node polling loop | n8n Webhook Wait (callback from script) | Would require modifying mipmap_launcher.py to POST back on completion; fire-and-forget pattern is simpler and already proven |
| Execute Command file check | n8n Read File node | Read File would load the entire GeoTIFF into memory; Execute Command with `if exist` is lightweight |

## Architecture Patterns

### Path C Sub-Workflow Structure
```
sentinel-path-c (sub-workflow)
  |
  +-- Execute Sub Workflow Trigger (entry point from Package Router)
  |
  +-- C1: Launch MipMap
  |     Execute Command: python mipmap_launcher.py --mission-id X --mission-path Y
  |     Parse stdout JSON (exit code check)
  |
  +-- C2: Poll Loop (mirrors Path E E0 pattern)
  |     +-- Build Ortho Path (Code node: construct D:/{workspace}/result/orthomosaic.tif)
  |     +-- Check Ortho Exists (Execute Command: if exist "path" echo FOUND else echo MISSING)
  |     +-- Ortho Found? (IF node)
  |     |     YES -> C3 Harvest
  |     |     NO  -> Max Attempts? (IF node)
  |     |           YES -> Set Failed (Timeout)
  |     |           NO  -> Wait 60s -> loop back to Build Ortho Path
  |
  +-- C3: Harvest Ortho
  |     Execute Command: python ortho_harvester.py --source-path X --mission-path Y --mission-id Z
  |     Parse stdout JSON (exit code check)
  |
  +-- C4: Trigger Path E (conditional)
        IF vegetation_analysis=true -> HTTP Request POST to /sentinel-vegetation-trigger
        ELSE -> done
```

### Pattern: Polling Loop with Wait Node (Proven in Path E)
**What:** Use n8n Wait node + Execute Command + IF node to create a polling loop
**When to use:** When waiting for an external process (MipMap) that produces a file on completion
**Example from Path E (already working):**
```
E0 -- Build Ortho Path (Code node: sets poll_attempt counter via $getWorkflowStaticData)
  -> E0 -- Check Ortho Exists (Execute Command: if exist "path" echo FOUND)
  -> E0 -- Ortho Found? (IF: stdout.trim() == "FOUND")
       TRUE  -> continue to processing
       FALSE -> E0 -- Max Attempts Reached? (IF: poll_attempt >= 30)
                  TRUE  -> Set Failed (Timeout)
                  FALSE -> E0 -- Wait 60s (Wait node, 60 seconds)
                             -> loops back to E0 -- Build Ortho Path
```

### Pattern: Sub-Workflow Entry (Proven in Path A)
**What:** `executeWorkflowTrigger` node receives payload from Package Router
**When to use:** All path sub-workflows
**Payload received from Package Router's Prepare Dispatch node:**
```json
{
  "mission_id": "uuid",
  "package_type": "mapping",
  "mission_number": 47,
  "folder_path": "E:\\Sentinel\\Incoming\\SAI_M0047_Mapping_20260218",
  "processing_job_id": "uuid",
  "source_platform": "ingest_sorter",
  "address": "123 Main St",
  "city": "Virginia Beach"
}
```

### Anti-Patterns to Avoid
- **Running MipMap via Execute Command directly:** MipMap produces 50-200MB stdout. n8n Execute Command has a maxBuffer that will kill the process. Use mipmap_launcher.py (fire-and-forget with stdout redirected to log file).
- **Checking MipMap PID instead of output file:** PID checking tells you the process is running, not that it produced valid output. Always check for the output GeoTIFF.
- **Hardcoding ortho filename:** MipMap output filename may vary (orthomosaic.tif, dom.tif, etc.). Use glob for `*.tif` in result/ directory, or check `info.json` status. The research notes this is an open question to validate with real MipMap run.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| MipMap subprocess management | Custom process manager | mipmap_launcher.py | Already handles PID files, orphan detection, log redirect |
| GeoTIFF copy + validation | Custom file copy logic | ortho_harvester.py | Already handles temp-file-then-rename, rasterio validation, magic byte fallback |
| Polling loop in n8n | Custom timer/scheduler | Wait node + IF + counter pattern | Proven in Path E E0 nodes, handles timeout gracefully |
| Path E triggering | Custom webhook server | HTTP Request to /sentinel-vegetation-trigger | Path E workflow already exists and handles the full E1-E4 pipeline |
| Processing step status | Custom Supabase updates | PipelineStatusReporter (in scripts) | Scripts self-report via --processing-job-id arg |

## Common Pitfalls

### Pitfall 1: MipMap Stdout Buffer Overflow
**What goes wrong:** n8n Execute Command node tries to capture MipMap stdout (50-200MB), hits maxBuffer, kills process
**Why it happens:** MipMap is extremely verbose; n8n buffers all stdout in memory
**How to avoid:** NEVER call reconstruct_full_engine.exe directly from Execute Command. Always use mipmap_launcher.py which redirects stdout to a log file and returns immediately with small JSON.
**Warning signs:** n8n execution log shows "stdout maxBuffer length exceeded"

### Pitfall 2: n8n Execution Timeout
**What goes wrong:** EXECUTIONS_TIMEOUT kills the sub-workflow before MipMap finishes (2-6 hours)
**Why it happens:** Phase 14 set EXECUTIONS_TIMEOUT=7200 (2 hours). MipMap can exceed this for large datasets.
**How to avoid:** Path C uses polling loop with Wait node. The Wait node suspends execution and stores state to DB, so the execution timer pauses during waits. This means actual clock time can exceed EXECUTIONS_TIMEOUT as long as active processing time doesn't. Verify this behavior. If it does count wait time, increase EXECUTIONS_TIMEOUT_MAX or use per-workflow timeout override.
**Warning signs:** Sub-workflow terminates mid-poll with no error output

### Pitfall 3: MipMap Output Path Unknown
**What goes wrong:** Polling checks wrong path, never finds output, times out
**Why it happens:** MipMap workspace structure is `D:/{user_id}/{project_name}/{task_name}/result/orthomosaic.tif` but the exact task_name and output filename depend on MipMap configuration. MipMap is NOT installed on the new rig yet.
**How to avoid:** mipmap_launcher.py's JSON output includes the workspace path. The polling Code node should construct the expected output path from that response. Use a configurable glob pattern (`result/*.tif`) rather than hardcoded `result/orthomosaic.tif`. Include a TODO/note that the exact output path needs validation when MipMap is installed.
**Warning signs:** Poll loop runs to max attempts every time

### Pitfall 4: Path E Triggered Before Ortho Copy Completes
**What goes wrong:** Path C fires vegetation trigger before ortho_harvester.py finishes copying to mapping/
**Why it happens:** Race condition if trigger fires after MipMap completes but before harvest step runs
**How to avoid:** Path C is sequential: poll -> harvest -> verify -> trigger. The HTTP Request to Path E ONLY fires after ortho_harvester.py returns exit code 0 with success JSON.

### Pitfall 5: GPU Contention Between Path C and Path E
**What goes wrong:** MipMap (Path C) and DeepForest/PyTorch (Path E) fight for GPU memory
**Why it happens:** Both use GPU heavily
**How to avoid:** This is by design -- MipMap finishes BEFORE Path E is triggered (sequential). Path C polls until MipMap completes, harvests ortho, then triggers Path E. GPU is free by the time Path E starts. Document this sequential guarantee.

## Code Examples

### Package Router Patch: Replace Path C Stub
The Package Router's `node-stub-path-c` (noOp node at position [3120, 300]) must be replaced with:
```json
{
  "parameters": {
    "workflowId": "sentinel-path-c",
    "options": {}
  },
  "id": "node-exec-path-c",
  "name": "Execute Path C",
  "type": "n8n-nodes-base.executeWorkflow",
  "typeVersion": 1,
  "position": [3120, 300],
  "notes": "Execute Path C sub-workflow for mapping, site_survey, environmental_survey missions."
}
```
And update the connection in Package Router from `"Execute Path C (Stub)"` to `"Execute Path C"`.

### Path C Sub-Workflow: Entry Point
```json
{
  "parameters": {},
  "id": "node-trigger",
  "name": "Execute Sub Workflow Trigger",
  "type": "n8n-nodes-base.executeWorkflowTrigger",
  "typeVersion": 1,
  "position": [240, 300],
  "notes": "Entry point. Called by Package Router. Receives: { mission_id, package_type, mission_number, folder_path, processing_job_id, source_platform, address, city }"
}
```

### Path C: Launch MipMap via Execute Command
```json
{
  "parameters": {
    "command": "=python \"{{ $env.SENTINEL_SCRIPTS }}\\mipmap_launcher.py\" --mission-id {{ $json.mission_id }} --mission-path \"{{ $json.folder_path }}\" --processing-job-id {{ $json.processing_job_id }}"
  },
  "id": "node-c1-launch-mipmap",
  "name": "C1 — Launch MipMap",
  "type": "n8n-nodes-base.executeCommand",
  "typeVersion": 1,
  "position": [480, 300]
}
```

### Path C: Polling Loop Code Node (Counter + Path Construction)
```javascript
// Construct expected ortho output path from MipMap workspace
// mipmap_launcher.py returns JSON with workspace info
const trigger = $('Execute Sub Workflow Trigger').first().json;
const missionId = trigger.mission_id;
const workspace = $env.MIPMAP_WORKSPACE || 'D:\\MipMapWorkspace';

// MipMap output structure: {workspace}/{project}/result/orthomosaic.tif
// The exact path depends on how mipmap_launcher.py configured the task
const orthoPath = workspace + '\\' + missionId + '\\result\\orthomosaic.tif';

// Track poll attempt via workflow static data
const staticData = $getWorkflowStaticData('global');
staticData.pollAttempt = (staticData.pollAttempt || 0) + 1;

return [{
  json: {
    mission_id: missionId,
    ortho_source_path: orthoPath,
    mission_path: trigger.folder_path,
    processing_job_id: trigger.processing_job_id,
    poll_attempt: staticData.pollAttempt,
    max_attempts: 120  // 120 x 60s = 2 hours
  }
}];
```

### Path C: Trigger Path E (Conditional HTTP Request)
```json
{
  "parameters": {
    "method": "POST",
    "url": "={{ $env.N8N_BASE_URL }}/webhook/sentinel-vegetation-trigger",
    "sendBody": true,
    "contentType": "json",
    "body": "={{ JSON.stringify({ mission_id: $json.mission_id }) }}",
    "options": {}
  },
  "id": "node-c4-trigger-path-e",
  "name": "C4 — Trigger Path E",
  "type": "n8n-nodes-base.httpRequest",
  "typeVersion": 4.2,
  "position": [1800, 300],
  "notes": "POST to /sentinel-vegetation-trigger to start Path E vegetation analysis. Only reached when vegetation_analysis=true."
}
```

### How to Check vegetation_analysis Flag
Two options for determining if Path E should be triggered:

**Option A: Check processing_templates config (already fetched by Package Router)**
The template_config from Prepare Dispatch may include `vegetation_enabled: true`. Pass this through the sub-workflow trigger payload.

**Option B: Check drone_jobs.vegetation_analysis column directly**
```json
{
  "parameters": {
    "url": "={{ $env.SUPABASE_URL }}/rest/v1/drone_jobs?id=eq.{{ $json.mission_id }}&select=vegetation_analysis",
    "sendHeaders": true,
    "headerParameters": {
      "parameters": [
        { "name": "apikey", "value": "={{ $env.SUPABASE_SERVICE_KEY }}" },
        { "name": "Authorization", "value": "=Bearer {{ $env.SUPABASE_SERVICE_KEY }}" }
      ]
    }
  }
}
```

**Recommendation:** Use Option B (direct Supabase check) because it's the same pattern Path E itself uses to verify the flag, and it ensures consistency. The `vegetation_analysis` column on drone_jobs is the source of truth, not template defaults.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Direct MipMap call via subprocess.wait() | Fire-and-forget via mipmap_launcher.py | Phase 15 (2026-03-05) | Prevents n8n stdout overflow |
| Manual ortho copy | ortho_harvester.py with integrity checks | Phase 15 (2026-03-05) | Automated with validation |
| Manual Path E triggering | Webhook trigger /sentinel-vegetation-trigger | v2.0 (2026-02-25) | Automated, already deployed |
| Path C stub (noOp) | Real sub-workflow (this phase) | Phase 17 | End-to-end mapping automation |

## Open Questions

1. **MipMap Output Path Pattern**
   - What we know: MipMap workspace structure is `D:/{user_id}/{project_name}/{task_name}/result/orthomosaic.tif` per prior research
   - What's unclear: MipMap is NOT installed on the new rig. The exact output filename may vary. Prior research notes it could be `orthomosaic.tif`, `dom.tif`, or other names.
   - Recommendation: Use `result/*.tif` glob in polling check (via `dir /b` command). Add a TODO to validate exact filename when MipMap is installed. Default to `orthomosaic.tif` for now.

2. **Wait Node and Execution Timeout Interaction**
   - What we know: EXECUTIONS_TIMEOUT=7200 (2 hours). Path C polling could run 2+ hours.
   - What's unclear: Does n8n count Wait node pause time toward the execution timeout? If yes, 2 hours of polling would hit the limit.
   - Recommendation: The Wait node stores execution state to DB and resumes -- this should NOT count against timeout. Path E's 30-minute poll already works within the 2-hour limit. But validate during testing. If needed, the sub-workflow can be configured with a higher per-workflow timeout.

3. **MipMap Workspace Path Construction**
   - What we know: mipmap_launcher.py uses `--workspace` arg (default `D:\MipMapWorkspace`) and `--mission-path`
   - What's unclear: How does mipmap_launcher.py translate mission-path into the workspace subdirectory structure?
   - Recommendation: The polling Code node should read the mipmap_launcher.py stdout JSON which includes the workspace path. If the JSON doesn't include the exact output path, construct it from `MIPMAP_WORKSPACE/{mission_id}/result/`.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | n8n workflow JSON validation + pytest for Python scripts |
| Config file | n8n/package_router.json (patch target), tests/ directory |
| Quick run command | `python -m pytest tests/test_mipmap_launcher.py tests/test_ortho_harvester.py -x` |
| Full suite command | `python -m pytest tests/ -x` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MPC-03 | Path C polls MipMap output directory for GeoTIFF | manual-only | n8n workflow test (import + visual inspect) | N/A - n8n JSON artifact |
| MPC-06 | Path C fires POST to /sentinel-vegetation-trigger | manual-only | n8n workflow test (import + visual inspect) | N/A - n8n JSON artifact |

Justification for manual-only: Both requirements are n8n workflow JSON artifacts. The workflow JSON can be validated for syntax (TST-03 already covers this in Phase 19), but functional testing requires n8n runtime with MipMap installed. The Python scripts called by the workflow (mipmap_launcher.py, ortho_harvester.py) already have comprehensive test suites from Phase 15.

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_mipmap_launcher.py tests/test_ortho_harvester.py -x`
- **Per wave merge:** `python -m pytest tests/ -x`
- **Phase gate:** Workflow JSON passes n8n import validation (TST-03 pattern)

### Wave 0 Gaps
None -- existing test infrastructure covers all phase requirements. Python scripts already have full test suites. n8n JSON validation is covered by Phase 19's TST-03.

## Sources

### Primary (HIGH confidence)
- `n8n/path_e_workflow.json` - Existing polling loop pattern (E0 nodes), webhook trigger contract
- `n8n/package_router.json` - Path C stub node, routing table, dispatch payload shape
- `n8n/path_a_workflow.json` - Sub-workflow entry pattern (executeWorkflowTrigger)
- `mipmap_launcher.py` - CLI interface, JSON output format, exit codes
- `ortho_harvester.py` - CLI interface, JSON output format, exit codes
- `.planning/research/STACK.md` - MipMap workspace structure, webhook contracts
- `n8n/NATIVE-CONFIG.md` - Environment variables, timeout configuration

### Secondary (MEDIUM confidence)
- [n8n Wait node docs](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.wait/) - Wait node parameters and resume conditions
- [n8n Waiting flow logic](https://docs.n8n.io/flow-logic/waiting/) - Polling pattern recommendations

### Tertiary (LOW confidence)
- MipMap output filename pattern - Based on prior research, NOT validated on new rig (MipMap not installed)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All components already built and tested
- Architecture: HIGH - Mirrors proven Path E polling and Path A sub-workflow patterns
- Pitfalls: HIGH - Well-documented from prior research phases and existing code analysis
- MipMap output path: LOW - MipMap not installed; filename pattern unvalidated

**Research date:** 2026-03-05
**Valid until:** 2026-04-05 (stable -- core patterns already proven in production)
