# Phase 16: Package Router Core + Path A - Research

**Researched:** 2026-03-05
**Domain:** n8n workflow development, webhook-driven pipeline orchestration, Supabase integration
**Confidence:** HIGH

## Summary

Phase 16 builds the central n8n Package Router workflow and proves the pattern with Path A (real estate photo processing). The router receives webhooks from ingest_sorter.py and folder_watcher.py, normalizes payloads, creates processing_jobs rows in Supabase with appropriate steps, fetches template config, and dispatches to path-specific sub-workflows. Path A is the simplest end-to-end path: color grade photos then package for delivery.

The project already has significant foundation work completed: the payload normalizer (JS + Python), the manual path sub-workflow, the Path E workflow (as a pattern reference), the processing_jobs schema, and integration tests with step mapping. The primary work is assembling these into working n8n workflow JSON files and wiring the Execute Command nodes to call video_color_grade.py and delivery_packaging.py with correct arguments.

**Primary recommendation:** Build the Package Router as a main workflow JSON file and Path A as a separate sub-workflow JSON file, following the exact patterns established by manual_path_workflow.json and path_e_workflow.json. Use HTTP Request nodes for all Supabase operations (not community nodes, per Out of Scope decision).

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| RTR-01 | n8n webhook receives POST from ingest_sorter.py with mission_id, package_type, inventory | Webhook node pattern from path_e_workflow.json; ingest_sorter fire_webhook() sends to N8N_WEBHOOK_URL with exact payload shape documented |
| RTR-02 | Switch node routes to Path A/B/C/D/V sub-workflows based on package_type | Switch node with Execute Sub Workflow pattern from manual_path_workflow.json; step mapping from integration test covers all 6 automated + 2 manual types |
| RTR-03 | Fetches processing_templates config and merges overrides | HTTP Request GET to Supabase REST API; template_defaults in package_router_patch.json define per-package-type config |
| RTR-04 | Creates processing_jobs row with active steps before dispatching | processing_jobs table schema documented; build_processing_steps() logic from integration test; steps JSONB array structure defined |
| RTR-05 | Normalizes folder_watcher and ingest_sorter payloads to common format | package_router_normalizer.js already complete; payload_normalizer.py Python reference with tests exists |
| PHA-01 | Path A executes photo color grading script | video_color_grade.py CLI interface documented: `python video_color_grade.py MISSION_PATH --platform PLATFORM --processing-job-id JOB_ID` |
| PHA-02 | Path A executes delivery_packaging.py for client delivery ZIP | delivery_packaging.py CLI: `python delivery_packaging.py MISSION_PATH --address ADDR --city CITY --photos-only` |
| PHA-03 | Path A updates Supabase processing_steps status at each stage | PipelineStatusReporter already integrated into video_color_grade.py; delivery_packaging.py needs --processing-job-id added |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| n8n | 2.10.3 | Workflow orchestration | Already installed natively on Windows (Phase 14) |
| Supabase REST API | PostgREST | Database operations from n8n | HTTP Request nodes per Out of Scope (no community nodes) |
| Python | 3.14 (system) | Script execution | Pipeline scripts use system Python |

### Node Types Used
| n8n Node | TypeVersion | Purpose |
|----------|-------------|---------|
| n8n-nodes-base.webhook | 1.1 | Entry point for POST payloads |
| n8n-nodes-base.code | 2 | Payload normalization, step building, result parsing |
| n8n-nodes-base.switch | 3 | Route by package_type |
| n8n-nodes-base.httpRequest | 4.2 | Supabase CRUD operations |
| n8n-nodes-base.executeCommand | 1 | Run Python scripts |
| n8n-nodes-base.executeWorkflow | 1 | Dispatch to sub-workflows |
| n8n-nodes-base.executeWorkflowTrigger | 1 | Sub-workflow entry point |
| n8n-nodes-base.if | 2 | Conditional branching |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| HTTP Request for Supabase | n8n Supabase community node | Out of scope per project decision; HTTP Request is more transparent and reliable |
| Switch node | Multiple IF nodes | Switch is cleaner for 5+ routes; single node handles all package types |

## Architecture Patterns

### Recommended Workflow Structure
```
n8n/
├── package_router.json          # Main workflow: webhook -> normalize -> template -> job -> switch -> dispatch
├── path_a_workflow.json         # Sub-workflow: color grade -> delivery packaging
├── manual_path_workflow.json    # Already exists: Path B/D handler
├── path_e_workflow.json         # Already exists: vegetation analysis
├── package_router_normalizer.js # Already exists: Code node source
├── package_router_patch.json    # Already exists: template defaults reference
└── 14-env-verification.json     # Already exists: env var check
```

### Pattern 1: Package Router Main Workflow
**What:** Central n8n workflow that receives all mission webhooks and routes to sub-workflows
**When to use:** This is THE entry point for all automated processing

**Node chain:**
```
Webhook (POST /package-router)
  -> Normalize Payload (Code node, uses package_router_normalizer.js)
  -> IF needs_mission_lookup (for folder_watcher payloads)
     -> Lookup Mission ID (HTTP Request GET Supabase)
  -> Check Duplicate Job (HTTP Request GET processing_jobs)
  -> IF duplicate exists -> Stop
  -> Fetch Template (HTTP Request GET processing_templates)
  -> Build Steps (Code node, build_processing_steps logic)
  -> Create Processing Job (HTTP Request POST processing_jobs)
  -> Switch by package_type
     -> re_standard / real_estate -> Execute Path A Sub-Workflow
     -> mapping / site_survey / environmental_survey -> Execute Path C Sub-Workflow (Phase 17)
     -> video -> Execute Path V Sub-Workflow (Phase 18)
     -> construction_hybrid / adiat -> Execute Manual Path Sub-Workflow
     -> default -> Execute Manual Path Sub-Workflow
```

### Pattern 2: Path A Sub-Workflow
**What:** Execute color grading then delivery packaging for real estate photo missions
**When to use:** Triggered by Package Router for re_standard and real_estate package types

**Node chain:**
```
Execute Sub Workflow Trigger
  -> Set Step Status: color_grade=running (HTTP Request PATCH)
  -> Execute Color Grade (Execute Command: python video_color_grade.py)
  -> Parse Color Grade Result (Code node)
  -> IF exit code != 0 -> Set Step Failed -> Stop
  -> Set Step Status: color_grade=complete
  -> Set Step Status: delivery_packaging=running
  -> Execute Delivery Packaging (Execute Command: python delivery_packaging.py)
  -> Parse Delivery Result (Code node)
  -> IF exit code != 0 -> Set Step Failed -> Stop
  -> Set Step Status: delivery_packaging=complete
```

### Pattern 3: Supabase HTTP Request (from existing workflows)
**What:** Standard pattern for all Supabase operations from n8n
**Source:** path_e_workflow.json and manual_path_workflow.json

```json
{
  "parameters": {
    "method": "POST",
    "url": "={{ $env.SUPABASE_URL }}/rest/v1/processing_jobs",
    "sendHeaders": true,
    "headerParameters": {
      "parameters": [
        { "name": "apikey", "value": "={{ $env.SUPABASE_SERVICE_KEY }}" },
        { "name": "Authorization", "value": "=Bearer {{ $env.SUPABASE_SERVICE_KEY }}" },
        { "name": "Content-Type", "value": "application/json" },
        { "name": "Prefer", "value": "return=representation" }
      ]
    },
    "sendBody": true,
    "contentType": "json",
    "body": "={ ... }"
  },
  "type": "n8n-nodes-base.httpRequest",
  "typeVersion": 4.2
}
```

### Pattern 4: Execute Command for Python Scripts (from Path E)
**What:** Run Python scripts and capture stdout JSON
**Source:** path_e_workflow.json E1-E4 nodes

```json
{
  "parameters": {
    "command": "=python \"{{ $env.SENTINEL_SCRIPTS }}\\video_color_grade.py\" \"{{ $json.folder_path }}\" --platform {{ $json.source_platform || 'mini4pro' }} --processing-job-id {{ $json.processing_job_id }}"
  },
  "type": "n8n-nodes-base.executeCommand",
  "typeVersion": 1
}
```

### Pattern 5: Step Status Update via n8n Code Node
**What:** Update a specific step in the processing_jobs.steps JSONB array
**Why not use PipelineStatusReporter:** The scripts themselves handle their own status via --processing-job-id. But the n8n workflow also needs to update step status for steps that are about to start (set to "running" before Execute Command) and handle failures detected at the n8n level.

The recommended approach: Let the Python scripts handle their own start/complete/fail via PipelineStatusReporter. The n8n workflow only needs to:
1. Pass --processing-job-id to each Execute Command
2. Check exit codes after each script
3. Handle failures at the workflow level (stop further execution)

### Anti-Patterns to Avoid
- **Double status updates:** Do NOT update step status to "running" from both n8n AND the Python script. The script's PipelineStatusReporter.start() handles this. n8n should only handle failure detection via exit codes.
- **Hardcoding folder paths:** Always use `$env.SENTINEL_SCRIPTS` and `$json.folder_path` from the normalized payload.
- **Blocking on long scripts:** video_color_grade.py can take minutes per video. n8n execution timeout is 7200s but Path A should be fast (photos only, no video).
- **Using shell=True:** Execute Command node handles command parsing. Keep commands as simple argument lists.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Payload normalization | Custom Code node | package_router_normalizer.js (exists) | Already tested with Python mirror |
| Step mapping per package type | Custom mapping | build_processing_steps() from integration test | Already covers all 8 types |
| Template defaults | Custom config | package_router_patch.json template_defaults | Already defines per-package config |
| Step status tracking | Custom PATCH logic | PipelineStatusReporter in each script | Scripts self-report; n8n just passes --processing-job-id |
| Deduplication logic | Custom check | package_router_patch.json deduplication_check pattern | Already designed |
| Mission ID lookup | Custom query | package_router_patch.json mission_lookup_node pattern | Already designed |

**Key insight:** Phase 19 (completed out-of-order) already built the normalizer, manual path workflow, and integration tests. Phase 16 primarily needs to ASSEMBLE these components into working n8n workflow JSON files.

## Common Pitfalls

### Pitfall 1: delivery_packaging.py Requires --address and --city
**What goes wrong:** delivery_packaging.py has REQUIRED --address and --city arguments that n8n must provide
**Why it happens:** Real estate missions need client-facing naming (e.g., "Sentinel_123_Main_St_Virginia_Beach.zip")
**How to avoid:** The Package Router must pass address/city from either the webhook payload or a Supabase lookup. If not available, the delivery step must be skipped or use a placeholder.
**Warning signs:** delivery_packaging.py exits with error about missing required arguments

### Pitfall 2: video_color_grade.py is for VIDEO, Not Photos
**What goes wrong:** PHA-01 says "executes photo color grading script" but video_color_grade.py processes videos in video/full/ subfolder
**Why it happens:** Real estate photo missions may have NO videos. video_color_grade.py gracefully handles this (exits with "No video files found -- skipped")
**How to avoid:** For Path A (real estate photos), the color_grade step may be a no-op. The script handles it gracefully. n8n should treat exit code 0 as success regardless of whether videos were processed.
**Alternative:** If there is a separate photo color grading script (not found in codebase), it should be used instead. Based on code review, there is NO dedicated photo color grading script -- video_color_grade.py is the only color grading tool.

### Pitfall 3: Processing Job ID Must Be Passed Through Sub-Workflow
**What goes wrong:** Sub-workflow doesn't receive the processing_job_id, so PipelineStatusReporter becomes a no-op
**Why it happens:** Execute Sub Workflow node must explicitly pass parameters
**How to avoid:** Package Router must pass processing_job_id (from the INSERT response) to the sub-workflow. Sub-workflow must pass it to each Execute Command as --processing-job-id.

### Pitfall 4: Supabase INSERT Returns UUID
**What goes wrong:** After creating processing_jobs row, the job ID is needed for downstream --processing-job-id args
**Why it happens:** POST to Supabase REST API with `Prefer: return=representation` returns the created row including its UUID
**How to avoid:** Use `Prefer: return=representation` header and parse `$json[0].id` from the response

### Pitfall 5: folder_path May Not Exist in Payload
**What goes wrong:** ingest_sorter uses `sorted_folder` key, folder_watcher uses `folder_path` key
**Why it happens:** Different payload shapes from different sources
**How to avoid:** The normalizer already handles this (maps sorted_folder to folder_path). Always use `$json.folder_path` after normalization.

### Pitfall 6: RE Photo Missions May Not Need Color Grading
**What goes wrong:** Spending time running video_color_grade.py on photo-only missions
**Why it happens:** Real estate packages typically have photos, not videos
**How to avoid:** The build_processing_steps mapping for re_standard/real_estate includes ["color_grade", "delivery_packaging"]. If color_grade is truly not needed for photo missions, the step can be marked "skipped" instead. However, some real estate packages DO include video walkthroughs, so keeping it is correct -- the script gracefully skips when no videos exist.

## Code Examples

### ingest_sorter Webhook Payload (from fire_webhook)
```json
{
  "mission_id": "uuid-from-supabase",
  "mission_number": 47,
  "package_type": "re_standard",
  "photo_count": 120,
  "video_count": 0,
  "has_ppk_data": true,
  "source_platform": "mini4pro",
  "ingested_at": "2026-03-05T15:30:00Z"
}
```

### folder_watcher Webhook Payload (from build_inventory + fire_webhook)
```json
{
  "folder_path": "E:\\Sentinel\\Incoming\\SAI_M0047_re_standard_20260218",
  "folder_name": "SAI_M0047_re_standard_20260218",
  "mission_number": 47,
  "photo_count": 120,
  "video_count": 0,
  "has_ppk_data": false,
  "total_size_bytes": 5242880000,
  "detected_at": "2026-03-05T15:30:00Z"
}
```

### Normalized Payload (output of Code node)
```json
{
  "mission_id": "uuid-from-supabase",
  "mission_number": 47,
  "package_type": "re_standard",
  "photo_count": 120,
  "video_count": 0,
  "has_ppk_data": true,
  "source": "ingest_sorter",
  "needs_mission_lookup": false,
  "is_fallback": false,
  "folder_path": "E:\\Sentinel\\Incoming\\SAI_M0047_re_standard_20260218"
}
```

### processing_jobs Row After INSERT
```json
{
  "id": "generated-uuid",
  "mission_id": "uuid-from-supabase",
  "package_type": "re_standard",
  "status": "pending",
  "current_step": null,
  "steps": [
    {"name": "color_grade", "status": "pending"},
    {"name": "delivery_packaging", "status": "pending"}
  ],
  "error_message": null
}
```

### video_color_grade.py Execute Command
```
python "{{ $env.SENTINEL_SCRIPTS }}\video_color_grade.py" "{{ $json.folder_path }}" --platform {{ $json.source_platform || 'mini4pro' }} --processing-job-id {{ $json.processing_job_id }}
```

### delivery_packaging.py Execute Command
```
python "{{ $env.SENTINEL_SCRIPTS }}\delivery_packaging.py" "{{ $json.folder_path }}" --address "{{ $json.address }}" --city "{{ $json.city }}" --photos-only
```

**CRITICAL NOTE:** delivery_packaging.py does NOT accept --processing-job-id. It does not import PipelineStatusReporter. For PHA-03, either:
1. Add --processing-job-id support to delivery_packaging.py (requires code change), OR
2. Update step status from n8n Code nodes before/after Execute Command

### Switch Node Configuration for Package Routing
```json
{
  "parameters": {
    "dataType": "string",
    "value1": "={{ $json.package_type }}",
    "rules": {
      "rules": [
        { "value2": "re_standard", "output": 0 },
        { "value2": "real_estate", "output": 0 },
        { "value2": "mapping", "output": 1 },
        { "value2": "site_survey", "output": 1 },
        { "value2": "environmental_survey", "output": 1 },
        { "value2": "video", "output": 2 },
        { "value2": "construction_hybrid", "output": 3 },
        { "value2": "adiat", "output": 3 }
      ]
    },
    "fallbackOutput": 3
  },
  "type": "n8n-nodes-base.switch",
  "typeVersion": 3
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual script execution | n8n webhook-triggered automation | v3.0 (Phase 16) | Eliminates operator intervention for Path A |
| No processing tracking | processing_jobs JSONB step array | v3.0 (Phase 15) | Full step-level status visibility |
| Separate webhook endpoints | Single Package Router entry point | v3.0 (Phase 19/16) | Both sources flow through same normalization |

## Open Questions

1. **How does Path A get address/city for delivery_packaging.py?**
   - What we know: delivery_packaging.py requires --address and --city (argparse required=True)
   - What's unclear: Neither ingest_sorter nor folder_watcher payloads include address/city
   - Recommendation: Package Router should fetch address/city from drone_jobs Supabase table (which has client and property info) OR the processing_templates table should include default address fields. If not available, use mission folder name components as placeholder.

2. **Should delivery_packaging.py get --processing-job-id support?**
   - What we know: delivery_packaging.py does NOT import PipelineStatusReporter or accept --processing-job-id
   - What's unclear: Whether PHA-03 requires the script itself to report status or if n8n Code nodes can handle it
   - Recommendation: Add PipelineStatusReporter to delivery_packaging.py (small code change, follows pipeline contract pattern). This keeps status reporting consistent with all other scripts.

3. **Is video_color_grade.py the right script for photo color grading?**
   - What we know: video_color_grade.py processes video files only (video/full/). It gracefully exits with "No video files found" when no videos exist. There is no separate photo color grading script.
   - What's unclear: Does the "color_grade" step in Path A actually grade photos or is it for video files in real estate packages?
   - Recommendation: For RE photo-only missions, the color_grade step should either (a) be skipped if no videos, or (b) a new photo-specific color grading script should be created. Based on current codebase, option (a) is simplest -- let video_color_grade.py run, it exits cleanly with no videos.

4. **What source_platform value should Path A use?**
   - What we know: video_color_grade.py requires --platform for LUT selection. ingest_sorter payload includes source_platform.
   - What's unclear: Whether the source_platform survives through normalization to the sub-workflow
   - Recommendation: Add source_platform to the normalized payload (normalizer already includes it if present in input). Pass it through to sub-workflow parameters.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x |
| Config file | pytest.ini |
| Quick run command | `python -m pytest tests/test_n8n_workflow_validation.py -x` |
| Full suite command | `python -m pytest tests/ -x --ignore=tests/integration` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RTR-01 | Webhook receives ingest_sorter payload | integration | `python -m pytest tests/integration/test_package_router_integration.py::TestPackageRouterIntegration::test_ingest_sorter_payload_creates_processing_job -x` | Yes |
| RTR-02 | Switch routes by package_type | integration | `python -m pytest tests/integration/test_package_router_integration.py::TestPackageRouterIntegration::test_processing_steps_for_each_package_type -x` | Yes |
| RTR-03 | Fetch processing_templates + merge | unit | n/a - verified by n8n workflow JSON structure | Wave 0 |
| RTR-04 | Creates processing_jobs row | integration | `python -m pytest tests/integration/test_package_router_integration.py::TestPackageRouterIntegration::test_ingest_sorter_payload_creates_processing_job -x` | Yes |
| RTR-05 | Normalizes both payload types | unit | `python -m pytest tests/test_payload_normalization.py -x` | Yes |
| PHA-01 | Color grade script execution | manual-only | Requires n8n running + real mission folder | Manual |
| PHA-02 | Delivery packaging execution | manual-only | Requires n8n running + real mission folder | Manual |
| PHA-03 | Step status updates | manual-only | Requires n8n + Supabase connection | Manual |
| TST-03 | Workflow JSON valid | unit | `python -m pytest tests/test_n8n_workflow_validation.py -x` | Yes |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_n8n_workflow_validation.py tests/test_payload_normalization.py -x`
- **Per wave merge:** `python -m pytest tests/ -x --ignore=tests/integration`
- **Phase gate:** Full suite green before verify-work

### Wave 0 Gaps
- [ ] package_router.json must pass test_n8n_workflow_validation.py (auto-covered by parametrized test)
- [ ] path_a_workflow.json must pass test_n8n_workflow_validation.py (auto-covered by parametrized test)
- [ ] delivery_packaging.py needs --processing-job-id support added (if PHA-03 requires script-level status reporting)

## Sources

### Primary (HIGH confidence)
- Project source code: ingest_sorter.py, folder_watcher.py, video_color_grade.py, delivery_packaging.py -- CLI interfaces and payload shapes
- Project source code: pipeline_status.py -- PipelineStatusReporter API
- Project source code: n8n/manual_path_workflow.json, n8n/path_e_workflow.json -- established n8n workflow patterns
- Project source code: n8n/package_router_normalizer.js, scripts/payload_normalizer.py -- normalization logic
- Project source code: n8n/package_router_patch.json -- template defaults and routing design
- Project source code: tests/integration/test_package_router_integration.py -- step mapping and job creation patterns
- Project source code: db_migrations/migrations/20260305000001_processing_jobs.sql -- table schema

### Secondary (MEDIUM confidence)
- Phase 14 summary: n8n 2.10.3 native, Execute Command enabled, env vars configured
- Phase 15 summaries: processing_jobs schema, mipmap_launcher, ortho_harvester complete

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all tools already installed and verified in Phase 14
- Architecture: HIGH - existing workflows provide exact patterns to follow
- Pitfalls: HIGH - identified from direct code review of all involved scripts
- Open questions: MEDIUM - address/city sourcing and photo vs video grading need decisions

**Research date:** 2026-03-05
**Valid until:** 2026-04-05 (stable -- project-specific, no external API changes expected)
