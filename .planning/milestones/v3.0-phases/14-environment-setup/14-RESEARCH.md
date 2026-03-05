# Phase 14: Environment Setup - Research

**Researched:** 2026-03-05
**Domain:** n8n self-hosted Docker configuration, Execute Command node, environment variables
**Confidence:** HIGH

## Summary

Phase 14 must solve three configuration problems before any v3.0 workflow development begins: (1) re-enable the Execute Command node which n8n 2.0+ disables by default, (2) configure execution timeout to support 2-hour MipMap jobs, and (3) inject six new environment variables accessible from n8n Code node expressions.

A critical discovery during research: **n8n runs inside a Docker container (Alpine Linux 3.22)** with no Python installed and no volume mounts to the Windows host drives (E:\, D:\, F:\) or the scripts directory. The existing Path E workflow JSON references Windows paths like `E:\Sentinel\.venv-path-e\Scripts\python.exe` -- these paths do not exist on the current rig. The docker-compose.yml must be updated with volume mounts so the Execute Command node can reach host scripts and data. Additionally, n8n 2.0 blocks `$env` access in Code nodes by default, requiring `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`.

**Primary recommendation:** Update `docker-compose.yml` to add volume mounts for scripts and drives, update `.env` with all required n8n configuration and custom variables, then restart the container and run a verification workflow.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| ENV-01 | n8n Execute Command node is verified enabled and functional before any workflow development | Set `NODES_EXCLUDE="[]"` in .env, mount scripts directory as Docker volume, install Python in container or use host Python via mounted venv |
| ENV-02 | n8n EXECUTIONS_TIMEOUT is set to 7200s (2 hours) to support long-running MipMap jobs | Set `EXECUTIONS_TIMEOUT=7200` and `EXECUTIONS_TIMEOUT_MAX=7200` in .env |
| ENV-03 | Six new n8n environment variables are configured (MIPMAP_ENGINE_PATH, MIPMAP_WORKSPACE, SENTINEL_INCOMING, SENTINEL_SCRIPTS, VENV_PATH_E_PYTHON, N8N_BASE_URL) | Add to .env file, set `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` to allow $env access in Code nodes |
</phase_requirements>

## Standard Stack

### Core
| Component | Version | Purpose | Why Standard |
|-----------|---------|---------|--------------|
| n8n | 2.10.3 | Workflow orchestration | Already deployed, self-hosted via Docker |
| Docker | Desktop (WSL2) | Container runtime | n8n runs as `docker.n8n.io/n8nio/n8n` image |
| Python | 3.12.10 (system) | Script execution | Host Python at `C:\Users\redle.SOULAAN\AppData\Local\Programs\Python\Python312\python.exe` |

### Supporting
| Component | Purpose | When to Use |
|-----------|---------|-------------|
| docker-compose.yml | Container configuration | Single source of truth for n8n Docker config |
| .env file | Environment variable injection | All n8n env vars and custom pipeline vars |

### Current State (as found on rig)
| Item | Status | Location |
|------|--------|----------|
| n8n container | Running (Up 15 min) | `docker.n8n.io/n8nio/n8n` Alpine 3.22, Node 24.13.1 |
| docker-compose.yml | Exists, needs updates | `C:\Users\redle.SOULAAN\n8n\docker-compose.yml` |
| .env | Exists (SUPABASE_URL + KEY only) | `C:\Users\redle.SOULAAN\n8n\.env` |
| Python in container | NOT installed | Alpine image has no python3 |
| E:\Sentinel\ | DOES NOT EXIST | Old rig path; new rig E:\ has only video files |
| .venv-path-e | DOES NOT EXIST | Needs to be created on new rig |
| Volume mounts for scripts/drives | NONE | Only `n8n_data` and `./backup` are mounted |
| NODES_EXCLUDE | NOT SET | Execute Command disabled by default |
| N8N_BLOCK_ENV_ACCESS_IN_NODE | NOT SET | $env blocked in Code nodes by default |
| EXECUTIONS_TIMEOUT | NOT SET | Default -1 (no timeout), but MAX defaults to 3600 (1 hour) |

## Architecture Patterns

### Docker Volume Mount Strategy

The n8n container must access host filesystem paths. Two approaches:

**Approach A: Mount host directories into container (RECOMMENDED)**
```yaml
services:
  n8n:
    volumes:
      - n8n_data:/home/node/.n8n
      - ./backup:/backup
      - /c/Users/redle.SOULAAN/Documents/drone-pipeline:/scripts:ro
      - /e:/host-e
      - /d:/host-d
      - /f:/host-f
```
Then Execute Command references `/scripts/canopy_detection.py` and `/host-e/incoming/` inside the container.

**Problem:** Python is not installed in the Alpine container. Scripts cannot run inside the container without Python + all dependencies (PyTorch, rasterio, etc.).

**Approach B: Mount host Python + venv into container**
Mount the host Windows Python executable -- this WILL NOT WORK because the container runs Linux (Alpine) and Windows .exe files are not compatible.

**Approach C: Use SSH from container to host (COMPLEX)**
Install SSH client in container, SSH to localhost to run scripts. Adds complexity and fragility.

**Approach D: HTTP wrapper on host (NOT RECOMMENDED for this project)**
Run a small HTTP server on the host that n8n calls via HTTP Request node instead of Execute Command. Requires building and maintaining a separate service.

**Approach E: Run n8n natively on Windows (SIMPLEST)**
Install n8n via npm on Windows directly, bypassing Docker entirely. Execute Command then runs in Windows shell with full access to Python, drives, and venvs.

**Approach F: Custom Docker image with Python (VIABLE)**
Build a custom n8n Docker image based on `n8nio/n8n` that includes Python 3.12 and required packages. Mount script and data directories as volumes.

### Recommended Architecture Decision

**The planner must address a fundamental architectural question:** The current Docker setup cannot run Python scripts via Execute Command because Python is not in the container and Windows Python cannot run in Linux.

**Strongest options ranked:**

1. **Native n8n on Windows** (simplest) -- `npm install -g n8n`, run as Windows service. Execute Command runs in Windows shell. All paths work natively. Matches Path E workflow JSON which already uses Windows paths.
2. **Custom Docker image + volume mounts** (more isolated) -- Build `Dockerfile` FROM `n8nio/n8n`, `apk add python3`, pip install deps. Requires rewriting all workflow paths to Linux container paths.

**Recommendation: Native Windows install.** The Path E workflow already uses Windows paths (`E:\Sentinel\...`). All 18 pipeline scripts expect Windows paths. GPU access (CUDA) is needed for Path E. Docker adds a translation layer that creates ongoing friction. The existing WF1-WF5 workflows in backup also reference Windows-style commands (`if exist`).

### n8n Environment Variable Architecture

```
C:\Users\redle.SOULAAN\n8n\
  docker-compose.yml     # Container config (if staying Docker)
  .env                   # All env vars (loaded by docker-compose OR native n8n)
  backup/                # Workflow JSON backups
```

n8n reads environment variables from three sources (priority order):
1. `environment:` block in docker-compose.yml
2. `env_file:` (.env) in docker-compose.yml
3. System environment variables (if running natively)

For native Windows: set vars in system environment or create a `.env` file and use `npx dotenv -e .env -- n8n start`.

### Pattern: Verify-Then-Configure

Phase 14 should follow this sequence:
1. **Decide Docker vs Native** (architectural decision)
2. **Configure environment** (env vars, timeout, node enablement)
3. **Verify Execute Command** (run a simple Python test script)
4. **Verify $env access** (read custom vars from Code node)
5. **Document verified paths** (so all subsequent phases use correct paths)

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| n8n process management | Custom Windows service wrapper | `nssm` (Non-Sucking Service Manager) or Task Scheduler | Proven Windows service management |
| Environment variable validation | Custom startup script | n8n Code node test workflow | n8n itself can verify its own env access |
| Execute Command verification | Manual testing | Automated test workflow JSON | Importable, repeatable verification |

## Common Pitfalls

### Pitfall 1: Execute Command Disabled in n8n 2.0+
**What goes wrong:** Workflows with Execute Command nodes fail with "Unrecognized node type: n8n-nodes-base.executeCommand"
**Why it happens:** n8n 2.0 disables Execute Command and LocalFileTrigger by default for security
**How to avoid:** Set `NODES_EXCLUDE="[]"` in environment before importing any workflows
**Warning signs:** Node not appearing in node selector panel

### Pitfall 2: $env Blocked in Code Nodes
**What goes wrong:** `$env.SUPABASE_URL` returns undefined in Code node expressions
**Why it happens:** n8n 2.0 sets `N8N_BLOCK_ENV_ACCESS_IN_NODE=true` by default
**How to avoid:** Set `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` in environment
**Warning signs:** Code nodes that reference $env silently return undefined

### Pitfall 3: EXECUTIONS_TIMEOUT_MAX Caps Per-Workflow Timeout
**What goes wrong:** Setting EXECUTIONS_TIMEOUT=7200 has no effect because EXECUTIONS_TIMEOUT_MAX defaults to 3600
**Why it happens:** MAX is the ceiling users can set per workflow; must be >= desired timeout
**How to avoid:** Set BOTH `EXECUTIONS_TIMEOUT=7200` AND `EXECUTIONS_TIMEOUT_MAX=7200`
**Warning signs:** Workflows killed after 1 hour despite setting 2-hour timeout

### Pitfall 4: Docker Container Cannot Run Windows Python
**What goes wrong:** Execute Command node tries to run `python.exe` but gets "not found"
**Why it happens:** n8n Docker runs Alpine Linux; Windows executables don't work
**How to avoid:** Either switch to native Windows install or build custom image with Linux Python
**Warning signs:** Any workflow referencing `.exe` files or Windows drive letters

### Pitfall 5: Path E Workflow References Non-Existent Paths
**What goes wrong:** Path E workflow references `E:\Sentinel\.venv-path-e\` and `E:\Sentinel\Scripts\`
**Why it happens:** Workflow JSON was created for old rig; new rig has different paths
**How to avoid:** Update all workflow JSON paths after determining correct script/venv locations
**Warning signs:** `E:\Sentinel\` does not exist on current rig

### Pitfall 6: Forgetting to Set EXECUTIONS_TIMEOUT_MAX
**What goes wrong:** After setting EXECUTIONS_TIMEOUT=7200, individual workflow timeouts still limited to 3600
**Why it happens:** EXECUTIONS_TIMEOUT_MAX is the per-workflow ceiling separate from the global default
**How to avoid:** Always set both values together

## Code Examples

### Required .env File (complete)
```bash
# --- Existing ---
SUPABASE_URL=https://qjpujskwqaehxnqypxzu.supabase.co
SUPABASE_SERVICE_KEY=<existing-key>

# --- n8n 2.0 Security Overrides ---
NODES_EXCLUDE=[]
N8N_BLOCK_ENV_ACCESS_IN_NODE=false

# --- Execution Timeout (2 hours for MipMap) ---
EXECUTIONS_TIMEOUT=7200
EXECUTIONS_TIMEOUT_MAX=7200

# --- Custom Pipeline Variables (ENV-03) ---
MIPMAP_ENGINE_PATH=<path-to-reconstruct_full_engine.exe>
MIPMAP_WORKSPACE=<path-to-mipmap-workspace-dir>
SENTINEL_INCOMING=E:\incoming
SENTINEL_SCRIPTS=C:\Users\redle.SOULAAN\Documents\drone-pipeline
VENV_PATH_E_PYTHON=<path-to-.venv-path-e\Scripts\python.exe>
N8N_BASE_URL=http://localhost:5678
```

### Verification Test Script (Python)
```python
#!/usr/bin/env python3
"""Minimal test script for n8n Execute Command verification."""
import json
import sys

result = {
    "status": "ok",
    "python_version": sys.version,
    "platform": sys.platform,
    "message": "Execute Command node is working"
}
print(json.dumps(result))
sys.exit(0)
```

### Verification Workflow Snippet (n8n JSON)
```json
{
  "nodes": [
    {
      "parameters": {
        "command": "python \"{{ $env.SENTINEL_SCRIPTS }}\\verify_n8n.py\""
      },
      "name": "Test Execute Command",
      "type": "n8n-nodes-base.executeCommand",
      "typeVersion": 1
    },
    {
      "parameters": {
        "jsCode": "const vars = ['MIPMAP_ENGINE_PATH','MIPMAP_WORKSPACE','SENTINEL_INCOMING','SENTINEL_SCRIPTS','VENV_PATH_E_PYTHON','N8N_BASE_URL'];\nconst results = {};\nfor (const v of vars) { results[v] = $env[v] || 'MISSING'; }\nreturn [{json: results}];"
      },
      "name": "Test Env Vars",
      "type": "n8n-nodes-base.code",
      "typeVersion": 2
    }
  ]
}
```

### Native Windows n8n Start Command
```bash
# Install globally
npm install -g n8n

# Start with .env file
cd C:\Users\redle.SOULAAN\n8n
set /a N8N_PORT=5678
n8n start
```

Or with environment file loaded:
```powershell
# PowerShell - load .env and start
Get-Content .env | ForEach-Object {
    if ($_ -match '^([^#=]+)=(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), 'Process')
    }
}
n8n start
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Execute Command enabled by default | Disabled by default, opt-in | n8n 2.0 (2025) | Must set NODES_EXCLUDE=[] |
| $env accessible in Code nodes | Blocked by default | n8n 2.0 (2025) | Must set N8N_BLOCK_ENV_ACCESS_IN_NODE=false |
| EXECUTIONS_TIMEOUT_MAX not enforced | Defaults to 3600s ceiling | n8n 2.0+ | Must raise MAX for long jobs |

## Open Questions

1. **Docker vs Native n8n**
   - What we know: Docker cannot run Windows Python; all existing workflows use Windows paths; GPU (CUDA) needed for Path E scripts
   - What's unclear: Whether user prefers to stay on Docker (custom image) or switch to native Windows
   - Recommendation: Switch to native Windows install. All evidence points this direction. Flag for user decision.

2. **MipMap Engine Path**
   - What we know: ENV-03 requires `MIPMAP_ENGINE_PATH` pointing to `reconstruct_full_engine.exe`
   - What's unclear: Where MipMap Desktop is installed on this new rig (or if it is installed yet)
   - Recommendation: Planner should include a step to locate or install MipMap and record the path

3. **MipMap Workspace Path**
   - What we know: ENV-03 requires `MIPMAP_WORKSPACE` - MipMap writes output to a workspace directory
   - What's unclear: Whether D:\ is the intended workspace on new rig (old workflows referenced D:/)
   - Recommendation: Planner should verify or create workspace directory

4. **Path E Venv Location**
   - What we know: `.venv-path-e` does not exist on new rig; old path `E:\Sentinel\.venv-path-e` invalid
   - What's unclear: Whether venv should be created now or deferred to a later phase
   - Recommendation: Record planned path in env var; actual venv creation can be deferred if Path E already works from v2.0

5. **SENTINEL_INCOMING Path**
   - What we know: E:\ drive exists but has old video files, not drone incoming data
   - What's unclear: Whether E:\incoming needs to be created or if a different path is used
   - Recommendation: Planner should create the directory or confirm the correct incoming path

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x (existing, 402 tests) |
| Config file | `C:\Users\redle.SOULAAN\Documents\drone-pipeline\pytest.ini` or similar |
| Quick run command | `python -m pytest tests/ -x --timeout=30` |
| Full suite command | `python -m pytest tests/ -v` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ENV-01 | Execute Command node runs Python script | manual + smoke | Import verification workflow in n8n, execute, check JSON output | N/A (n8n UI test) |
| ENV-02 | Timeout survives 2-hour job | manual | Check `EXECUTIONS_TIMEOUT` and `EXECUTIONS_TIMEOUT_MAX` values in container env | N/A (config check) |
| ENV-03 | Six env vars accessible from Code node | manual + smoke | Run Code node that reads all 6 vars, verify none are "MISSING" | N/A (n8n UI test) |

### Sampling Rate
- **Per task:** Run verification workflow after each config change
- **Phase gate:** All three success criteria verified via n8n UI execution

### Wave 0 Gaps
- [ ] `verify_n8n.py` -- minimal Python script that outputs JSON (for ENV-01 verification)
- [ ] `14-env-verification.json` -- n8n workflow JSON that tests Execute Command + env vars
- [ ] Decide Docker vs Native architecture before any configuration work

## Sources

### Primary (HIGH confidence)
- **n8n container inspection** -- `docker exec n8n env`, `docker exec n8n n8n --version` confirmed v2.10.3, Alpine 3.22, no Python
- **docker-compose.yml** -- Verified current volume mounts (n8n_data + backup only)
- **n8n .env** -- Verified only SUPABASE_URL and SUPABASE_SERVICE_KEY present
- **Path E workflow JSON** -- Verified Execute Command references Windows paths (E:\Sentinel\...)
- [n8n v2.0 breaking changes](https://docs.n8n.io/2-0-breaking-changes/) -- Execute Command disabled by default
- [n8n blocking nodes docs](https://docs.n8n.io/hosting/securing/blocking-nodes/) -- NODES_EXCLUDE configuration

### Secondary (MEDIUM confidence)
- [n8n community: re-enable Execute Command](https://community.n8n.io/t/unable-to-re-enable-execute-command-node-in-n8n-2-0-using-documented-environment-variables/238232) -- `NODES_EXCLUDE="[]"` solution
- [n8n execution timeout docs](https://docs.n8n.io/hosting/configuration/configuration-examples/execution-timeout/) -- EXECUTIONS_TIMEOUT and EXECUTIONS_TIMEOUT_MAX
- [DeepWiki n8n env vars](https://deepwiki.com/n8n-io/n8n-docs/4.2-environment-variables-reference) -- EXECUTIONS_TIMEOUT defaults (-1) and EXECUTIONS_TIMEOUT_MAX (3600)
- [n8n community: Execute Command from Docker](https://community.n8n.io/t/execute-command-node-from-docker/9881) -- Volume mount and SSH approaches

### Tertiary (LOW confidence)
- [naskio/n8n-python Docker image](https://hub.docker.com/r/naskio/n8n-python) -- Community image with Python; maintenance status unclear

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- verified directly on running system via Docker inspect
- Architecture: HIGH -- Docker vs native tradeoff clearly documented from system evidence
- Pitfalls: HIGH -- all pitfalls verified against n8n 2.0 docs and current container state
- Environment variables: HIGH -- verified current state, docs confirm re-enablement approach

**Research date:** 2026-03-05
**Valid until:** 2026-04-05 (stable -- n8n config patterns don't change frequently)
