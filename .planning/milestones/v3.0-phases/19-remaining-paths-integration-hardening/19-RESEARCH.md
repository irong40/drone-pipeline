# Phase 19: Remaining Paths + Integration + Hardening - Research

**Researched:** 2026-03-05
**Domain:** n8n workflow authoring (Path B/D stubs, folder watcher normalization), JSON validation, integration testing
**Confidence:** HIGH

## Summary

Phase 19 ties together the final loose ends of the v3.0 Package Router pipeline. It has four distinct work areas: (1) Path B and Path D manual-handling sub-workflows that set status to "manual" and email the operator, (2) normalizing folder_watcher.py webhook payloads so they route through the same Package Router entry point as ingest_sorter.py, (3) validating all n8n workflow JSON files are syntactically correct and importable, and (4) an integration test proving the Package Router webhook creates a processing_jobs row in Supabase with correct step structure.

All four areas build on established patterns already in the codebase. The n8n workflow JSON structure follows the path_e_workflow.json pattern. The test infrastructure uses pytest with mock Supabase clients (conftest.py fixtures). The pipeline_status.py PipelineStatusReporter already handles step-level status updates. This phase is primarily assembly and verification work -- no new Python scripts are needed.

**Primary recommendation:** Implement a single shared n8n sub-workflow for manual paths (B and D), add a Code node to the Package Router for payload normalization, write a JSON schema validator test for all n8n/*.json files, and create an integration test using mocked Supabase and mocked HTTP to verify webhook-to-processing_jobs flow.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Use n8n Send Email node via SMTP for operator notification when B/D missions arrive
- Recipient address from OPERATOR_EMAIL environment variable (single address, configurable without workflow edit)
- Single shared "manual path" sub-workflow for both Path B and Path D -- package type passed as parameter, not two separate workflows
- Sub-workflow sets processing_jobs status to "manual" in Supabase AND sends notification email
- Package Router Code node normalizes folder_watcher.py payload to match ingest_sorter.py format before routing
- Both folder_watcher webhook and ingest_sorter webhook route to the same Package Router entry point (FWI-02)

### Claude's Discretion
- Email body content and formatting (mission number, package type, folder path, inventory summary)
- How to derive package_type from folder_watcher payload (recommended: parse from SAI_MNNNN_TYPE_DATE folder name pattern)
- How to resolve mission_id from folder_watcher payload (recommended: Supabase lookup by mission_number since ingest_sorter creates mission record first)
- Workflow JSON validation approach (TST-03) -- syntax check, schema validation, or n8n API import test
- Integration test strategy (TST-04) -- mock vs live n8n, mock vs real Supabase, test fixture design
- Error handling when folder name doesn't match expected pattern (fallback to manual status?)

### Deferred Ideas (OUT OF SCOPE)
- Full Path B (construction) automation beyond stub -- v3.1 (PBD-03)
- Full Path D (ADIAT) automation beyond stub -- v3.1 (PBD-04)
- Slack/Discord notifications as alternative to email -- future enhancement
- n8n dashboard for real-time mission status monitoring -- v3.1 (AUT-03)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PBD-01 | n8n Path B sub-workflow sets processing status to manual and sends operator notification | Shared manual-path sub-workflow pattern, n8n Send Email node, OPERATOR_EMAIL env var, PipelineStatusReporter for status updates |
| PBD-02 | n8n Path D sub-workflow sets processing status to manual and sends operator notification | Same shared sub-workflow as PBD-01 with package_type parameter |
| FWI-01 | Package Router Code node normalizes folder_watcher.py webhook payload to match ingest_sorter payload format | Payload field mapping documented, folder name parsing regex, Supabase lookup pattern |
| FWI-02 | Folder watcher webhook and ingest_sorter webhook both route to the same Package Router entry point | Single webhook endpoint with Code node normalization before Switch routing |
| TST-03 | All n8n workflow JSON files are syntactically valid and importable | JSON syntax validation + n8n structural checks (nodes array, connections object) |
| TST-04 | Integration test validates Package Router webhook -> Supabase processing_jobs creation | pytest integration test with mocked Supabase and HTTP, verifies processing_jobs row creation |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| n8n | 1.x self-hosted | Workflow orchestration | Already deployed, all workflows use it |
| pytest | latest | Test framework | Already configured in pytest.ini, 402+ tests |
| pytest-mock | latest | Mock fixtures | Already used in conftest.py (mocker fixture) |
| requests | latest | HTTP testing | Already a project dependency |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| json (stdlib) | builtin | JSON validation for TST-03 | Validate n8n workflow files |
| re (stdlib) | builtin | Folder name parsing | Extract package_type from SAI_MNNNN_TYPE_DATE pattern |
| unittest.mock | builtin | Mock Supabase in integration test | TST-04 integration test |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| json.loads validation | jsonschema + n8n schema | Overkill -- n8n has no published JSON schema; structural checks suffice |
| Live n8n API import test | Mocked JSON validation | Live test requires running n8n instance; too fragile for automated test suite |
| Real Supabase in TST-04 | Mocked Supabase client | Real Supabase requires network, credentials; mock follows established test pattern |

## Architecture Patterns

### n8n Workflow File Structure (established pattern from path_e_workflow.json)
```json
{
  "id": "unique-workflow-id",
  "name": "Human-readable workflow name",
  "nodes": [
    {
      "parameters": { ... },
      "id": "node-id",
      "name": "Node Display Name",
      "type": "n8n-nodes-base.nodeType",
      "typeVersion": 1.1,
      "position": [x, y]
    }
  ],
  "connections": {
    "Node Name": {
      "main": [[{ "node": "Next Node Name", "type": "main", "index": 0 }]]
    }
  }
}
```

### Pattern 1: Shared Manual-Path Sub-Workflow
**What:** A single n8n workflow JSON file that handles both Path B and Path D missions. Receives package_type as a parameter, sets processing_jobs status to "manual" via Supabase HTTP Request node, and sends an email notification via Send Email node.
**When to use:** Any time a mission type doesn't have automated processing (construction, ADIAT).

The workflow structure:
1. **Trigger**: Receives `{ mission_id, package_type, mission_number, folder_path }` from Package Router Execute Sub Workflow node
2. **Supabase Update**: PATCH processing_jobs status to "manual" using HTTP Request node
3. **Send Email**: n8n Send Email node with SMTP config, recipient from `{{ $env.OPERATOR_EMAIL }}`

### Pattern 2: Payload Normalization Code Node
**What:** A JavaScript Code node in the Package Router that detects the webhook source (folder_watcher vs ingest_sorter) and normalizes to a common format.
**When to use:** At the Package Router entry point, before the Switch routing node.

Key normalization logic:
```javascript
// Detect source by checking for fields unique to each payload
const isIngestSorter = !!items[0].json.mission_id;
const isFolderWatcher = !!items[0].json.folder_name && !items[0].json.mission_id;

if (isFolderWatcher) {
  // Parse package_type from folder name: SAI_MNNNN_TYPE_DATE
  const match = items[0].json.folder_name.match(/^SAI_M\d{4}_(.+?)_\d{8}$/);
  const package_type = match ? match[1] : 'unknown';

  // mission_id must be looked up from Supabase by mission_number
  // (ingest_sorter creates the mission record first)
  return [{
    json: {
      mission_number: items[0].json.mission_number,
      package_type: package_type,
      photo_count: items[0].json.photo_count,
      video_count: items[0].json.video_count,
      has_ppk_data: items[0].json.has_ppk_data,
      source: 'folder_watcher',
      folder_path: items[0].json.folder_path,
      needs_mission_lookup: true
    }
  }];
} else {
  // ingest_sorter payload already has mission_id and package_type
  return [{
    json: {
      ...items[0].json,
      source: 'ingest_sorter',
      needs_mission_lookup: false
    }
  }];
}
```

### Pattern 3: Integration Test with Mocked External Services
**What:** pytest integration test that simulates the webhook-to-Supabase flow by mocking both the HTTP webhook call and the Supabase client.
**When to use:** TST-04 -- verifying Package Router creates processing_jobs row.

Established pattern from conftest.py: use `mock_supabase_client` fixture, patch `supabase.create_client`, verify `.table("processing_jobs").insert()` is called with correct step structure.

### Anti-Patterns to Avoid
- **Separate sub-workflows for B and D:** User explicitly decided on a shared sub-workflow. Don't create `path_b_workflow.json` and `path_d_workflow.json` separately.
- **Live n8n in tests:** Don't require a running n8n instance for TST-03 or TST-04. Tests must run in pytest without external services.
- **Hardcoded email addresses in workflow JSON:** Use `{{ $env.OPERATOR_EMAIL }}` -- never embed an email address in the workflow file.
- **Custom email sending from Python:** Use n8n's Send Email node, not a Python SMTP script.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Email notifications | Custom Python SMTP script | n8n Send Email node | n8n handles SMTP config, retries, and error reporting natively |
| JSON validation | Custom parser | json.loads() + structural key checks | json module handles all syntax validation; structural checks are 5-10 lines |
| Supabase status updates | Raw HTTP calls in workflow | Existing PipelineStatusReporter pattern via Execute Command | Consistent with all other path sub-workflows |
| Webhook payload routing | Multiple webhook endpoints | Single endpoint + Code node normalization | FWI-02 explicitly requires single entry point |

**Key insight:** This phase assembles existing building blocks. Every component (email, Supabase updates, webhook routing, test fixtures) already has an established pattern in the codebase. The work is wiring, not invention.

## Common Pitfalls

### Pitfall 1: folder_watcher.py payload lacks mission_id
**What goes wrong:** folder_watcher.py does NOT include mission_id in its webhook payload (it only has mission_number parsed from folder name). The Package Router Switch node and processing_jobs creation both require mission_id (UUID from Supabase).
**Why it happens:** folder_watcher fires when files appear on disk -- before or after ingest_sorter has created the mission record in Supabase.
**How to avoid:** After normalization Code node, add a Supabase HTTP Request node that looks up mission_id by mission_number from drone_jobs table. If not found, either queue for retry or fall through to manual handling.
**Warning signs:** processing_jobs rows created with null mission_id.

### Pitfall 2: folder_name regex fails on unexpected formats
**What goes wrong:** The SAI_MNNNN_TYPE_DATE pattern assumes all folder names follow the convention. Edge cases: underscores in package_type (e.g., `re_standard` has an underscore), non-SAI folders in the watch directory.
**Why it happens:** `build_mission_folder_name()` in ingest_sorter.py produces `SAI_M{num:04d}_{pkg}_{date}` where pkg can contain underscores.
**How to avoid:** Use a greedy-but-bounded regex: `/^SAI_M(\d{4})_(.+?)_(\d{8})$/` -- the date anchor at the end disambiguates the package_type from the date portion. Test with known package_types: `re_standard`, `construction_hybrid`, `site_survey`, `environmental_survey`, `video`, `mapping`.
**Warning signs:** package_type parsed as empty string or includes the date suffix.

### Pitfall 3: n8n Send Email node requires SMTP configuration
**What goes wrong:** The Send Email node silently fails or errors if n8n doesn't have SMTP credentials configured.
**Why it happens:** n8n's email node uses credentials stored in n8n's credential manager, not just env vars. OPERATOR_EMAIL is the recipient, but SMTP server/auth must be configured separately in n8n.
**How to avoid:** Document that SMTP credentials must be configured in n8n's credential manager (Settings > Credentials > SMTP). The workflow JSON references the credential by name.
**Warning signs:** Workflow executes but no email arrives; n8n execution log shows credential not found error.

### Pitfall 4: Circular webhook calls between folder_watcher and ingest_sorter
**What goes wrong:** Both folder_watcher and ingest_sorter fire to the Package Router. If the router processes both, the same mission could be handled twice.
**Why it happens:** folder_watcher fires when files land in Incoming. ingest_sorter fires after sorting files into mission folders. Both events happen for the same mission.
**How to avoid:** The Code node normalization must include a `source` field. The Package Router should handle deduplication: if a mission_id already has a processing_jobs row, skip creation. The typical flow is: ingest_sorter fires first (with full payload including mission_id), folder_watcher fires later (with partial payload). The folder_watcher path is a fallback for cases where ingest_sorter was not used.
**Warning signs:** Duplicate processing_jobs rows for the same mission.

### Pitfall 5: n8n workflow JSON "importable" vs "syntactically valid"
**What goes wrong:** TST-03 says "syntactically valid and importable." JSON syntax is easy to check, but "importable" implies n8n can actually load the file. Without a running n8n instance, we can only verify structural correctness.
**Why it happens:** Ambiguous requirement scope.
**How to avoid:** Define "importable" as: valid JSON + has required top-level keys (nodes array, connections object) + all nodes have required fields (id, name, type, parameters). This is a reasonable proxy without requiring a live n8n instance.
**Warning signs:** Test passes but workflow fails on actual import due to missing connection references or invalid node type names.

## Code Examples

### Folder Name Parsing (Python -- for test fixtures)
```python
# Source: ingest_sorter.py build_mission_folder_name() output format
import re

def parse_folder_name(folder_name: str) -> dict | None:
    """Parse SAI_MNNNN_TYPE_DATE folder name into components."""
    m = re.match(r'^SAI_M(\d{4})_(.+?)_(\d{8})$', folder_name)
    if not m:
        return None
    return {
        'mission_number': int(m.group(1)),
        'package_type': m.group(2),
        'date': m.group(3),
    }
```

### Payload Comparison (for normalization reference)
```python
# folder_watcher.py payload (build_inventory output):
folder_watcher_payload = {
    "folder_path": "E:\\Sentinel\\Incoming\\SAI_M0047_re_standard_20260218",
    "folder_name": "SAI_M0047_re_standard_20260218",
    "mission_number": 47,
    "photo_count": 24,
    "video_count": 0,
    "has_ppk_data": True,
    "total_size_bytes": 1048576,
    "detected_at": "2026-02-18T12:00:00Z"
}

# ingest_sorter.py payload (fire_webhook output):
ingest_sorter_payload = {
    "mission_id": "uuid-from-supabase",
    "mission_number": 47,
    "package_type": "re_standard",
    "photo_count": 24,
    "video_count": 0,
    "has_ppk_data": True,
    "source_platform": "mini4pro",
    "ingested_at": "2026-02-18T12:00:00Z"
}

# Normalized common format (output of Code node):
normalized = {
    "mission_id": "uuid-from-supabase",       # from payload or Supabase lookup
    "mission_number": 47,
    "package_type": "re_standard",             # from payload or folder name parse
    "photo_count": 24,
    "video_count": 0,
    "has_ppk_data": True,
    "source": "ingest_sorter",                 # or "folder_watcher"
    "needs_mission_lookup": False,             # True for folder_watcher source
}
```

### n8n Workflow JSON Validation Test
```python
# Source: Project pattern (pytest + json stdlib)
import json
import glob
import os
import pytest

N8N_DIR = os.path.join(os.path.dirname(__file__), '..', 'n8n')
REQUIRED_TOP_KEYS = {'nodes'}
REQUIRED_NODE_KEYS = {'id', 'name', 'type', 'parameters'}

def get_workflow_files():
    return glob.glob(os.path.join(N8N_DIR, '*.json'))

@pytest.mark.parametrize('filepath', get_workflow_files(), ids=lambda p: os.path.basename(p))
def test_workflow_json_valid_and_importable(filepath):
    """TST-03: Workflow JSON is syntactically valid with required structure."""
    with open(filepath, 'r') as f:
        data = json.load(f)  # Raises JSONDecodeError if invalid

    # Structural checks
    assert 'nodes' in data or 'template_defaults' in data, \
        f"Missing 'nodes' key in {os.path.basename(filepath)}"

    if 'nodes' in data:
        assert isinstance(data['nodes'], list), "'nodes' must be a list"
        for node in data['nodes']:
            missing = REQUIRED_NODE_KEYS - set(node.keys())
            assert not missing, f"Node '{node.get('name', '?')}' missing keys: {missing}"
```

### Integration Test Pattern (TST-04)
```python
# Source: Project pattern (conftest.py mock_supabase_client + requests mock)
import json
import pytest
from unittest.mock import MagicMock, patch

@pytest.mark.integration
def test_package_router_webhook_creates_processing_job(mock_supabase_client):
    """TST-04: Webhook payload -> processing_jobs row with correct steps."""
    # Simulate ingest_sorter webhook payload
    payload = {
        "mission_id": "test-uuid-001",
        "mission_number": 47,
        "package_type": "re_standard",
        "photo_count": 24,
        "video_count": 0,
        "has_ppk_data": False,
    }

    # Mock the Supabase insert to capture what gets written
    mock_insert = mock_supabase_client.table.return_value.insert
    mock_insert.return_value.execute.return_value.data = [{"id": "job-uuid"}]

    # ... invoke the router logic ...

    # Verify processing_jobs row was created with steps array
    call_args = mock_insert.call_args[0][0]  # First positional arg
    assert call_args["mission_id"] == "test-uuid-001"
    assert isinstance(call_args["steps"], list)
    assert len(call_args["steps"]) > 0
    assert all("name" in s and "status" in s for s in call_args["steps"])
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Separate webhook endpoints per source | Single Package Router with Code node normalization | v3.0 (this phase) | Reduces n8n webhook proliferation |
| Silent drop for unsupported paths | Manual status + email notification | v3.0 (this phase) | Operator never misses a mission |
| No workflow JSON validation | Automated pytest validation | v3.0 (this phase) | Catches JSON errors before n8n import |

## Open Questions

1. **SMTP Credential Configuration**
   - What we know: n8n Send Email node requires SMTP credentials in n8n credential manager
   - What's unclear: Whether the user has SMTP configured in their n8n instance, which provider they use
   - Recommendation: Document the SMTP setup requirement. The workflow JSON references the credential by name; user configures once in n8n UI. Use a sensible default credential name like "SMTP - Operator Notifications".

2. **Folder Watcher vs Ingest Sorter Ordering**
   - What we know: Both fire to the Package Router. ingest_sorter has mission_id; folder_watcher does not.
   - What's unclear: Whether folder_watcher always fires after ingest_sorter (i.e., mission record exists in Supabase when folder_watcher fires).
   - Recommendation: The normalization Code node should handle the "mission not found" case gracefully -- set package_type from folder name parsing, and if Supabase lookup fails, route to manual handling rather than erroring.

3. **package_router_patch.json is a patch doc, not a workflow**
   - What we know: `package_router_patch.json` is structured as a configuration/patch document (has `template_defaults`, `routing_condition`, etc.) -- NOT an n8n importable workflow.
   - What's unclear: Whether TST-03 should validate it as a workflow or treat it differently.
   - Recommendation: TST-03 validation should distinguish between workflow files (have `nodes` array) and config/patch files. Both should be valid JSON, but structural node checks only apply to workflows.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (configured in pytest.ini) |
| Config file | `pytest.ini` at project root |
| Quick run command | `pytest tests/ -x -q` |
| Full suite command | `pytest tests/ -ra --tb=short` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PBD-01 | Path B sets status=manual and sends email | unit | `pytest tests/test_manual_path_workflow.py -x` | No -- Wave 0 |
| PBD-02 | Path D sets status=manual and sends email | unit | `pytest tests/test_manual_path_workflow.py -x` | No -- Wave 0 |
| FWI-01 | Code node normalizes folder_watcher payload | unit | `pytest tests/test_payload_normalization.py -x` | No -- Wave 0 |
| FWI-02 | Both webhooks route to same entry point | integration | `pytest tests/integration/test_package_router_integration.py -x` | No -- Wave 0 |
| TST-03 | All n8n JSON files valid and importable | unit | `pytest tests/test_n8n_workflow_validation.py -x` | No -- Wave 0 |
| TST-04 | Webhook creates processing_jobs row | integration | `pytest tests/integration/test_package_router_integration.py -x` | No -- Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/ -x -q`
- **Per wave merge:** `pytest tests/ -ra --tb=short`
- **Phase gate:** Full suite green before verify

### Wave 0 Gaps
- [ ] `tests/test_n8n_workflow_validation.py` -- covers TST-03 (JSON syntax + structure)
- [ ] `tests/test_payload_normalization.py` -- covers FWI-01 (folder_watcher payload normalization logic)
- [ ] `tests/integration/test_package_router_integration.py` -- covers FWI-02, TST-04 (webhook routing + processing_jobs creation)

Note: PBD-01 and PBD-02 tests depend on how the manual path logic is implemented. If the sub-workflow is purely n8n JSON (no Python), then PBD-01/PBD-02 validation is covered by TST-03 (workflow JSON is valid) plus manual smoke test of email delivery. If any Python helper is involved, unit tests should be added.

## Sources

### Primary (HIGH confidence)
- `folder_watcher.py` -- exact webhook payload structure (build_inventory output)
- `ingest_sorter.py` -- exact webhook payload structure (fire_webhook output), folder naming convention (build_mission_folder_name)
- `pipeline_status.py` -- PipelineStatusReporter API, processing_jobs table interaction pattern
- `n8n/path_e_workflow.json` -- established n8n workflow JSON structure and conventions
- `n8n/package_router_patch.json` -- template defaults and routing configuration
- `tests/conftest.py` -- mock_supabase_client fixture pattern
- `tests/test_folder_watcher.py` -- established test patterns for webhook and payload testing
- `tests/integration/test_ingest_flow.py` -- established integration test patterns
- `pytest.ini` -- test configuration and markers

### Secondary (MEDIUM confidence)
- n8n Send Email node documentation -- SMTP credential configuration requirements

### Tertiary (LOW confidence)
- n8n workflow JSON import requirements -- no official JSON schema published; structural checks are inferred from existing workflow files

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already in use in the project
- Architecture: HIGH -- all patterns derived from existing codebase (path_e_workflow.json, conftest.py, pipeline_status.py)
- Pitfalls: HIGH -- derived from direct analysis of payload structures and code paths
- Validation: MEDIUM -- test file names and structure are recommendations; PBD-01/PBD-02 testability depends on implementation approach

**Research date:** 2026-03-05
**Valid until:** 2026-04-05 (stable -- no external dependency changes expected)
