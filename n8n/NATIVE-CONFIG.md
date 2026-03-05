# n8n Native Windows Configuration

**Decision:** Native Windows install (not Docker)
**Date:** 2026-03-05
**Phase:** 14-environment-setup, Plan 01

## Why Native

- Docker Alpine container has no Python, cannot run pipeline scripts
- All existing workflows reference Windows paths (E:\, D:\, C:\)
- GPU/CUDA needed for Path E scripts (not accessible from Docker)
- Docker adds ongoing path translation friction

## Configuration Location

All n8n config files live OUTSIDE this repo at:
```
C:\Users\redle.SOULAAN\n8n\
  .env                 # All environment variables
  docker-compose.yml   # Docker config (retained for reference, not active)
  start-n8n.ps1        # PowerShell script to load .env and start n8n
  backup/              # Workflow JSON backups
```

## How to Start n8n

```powershell
cd C:\Users\redle.SOULAAN\n8n
powershell -ExecutionPolicy Bypass -File start-n8n.ps1
```

Or from bash:
```bash
cd /c/Users/redle.SOULAAN/n8n
export $(grep -v '^#' .env | grep -v '^$' | xargs)
n8n start
```

## Environment Variables Configured

### Security Overrides
- `NODES_EXCLUDE=[]` -- Re-enables Execute Command node (disabled by default in n8n 2.0+)
- `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` -- Allows $env access in Code nodes

### Execution Timeout
- `EXECUTIONS_TIMEOUT=7200` -- 2-hour global default (for MipMap jobs)
- `EXECUTIONS_TIMEOUT_MAX=7200` -- 2-hour per-workflow ceiling

### Custom Pipeline Variables
- `MIPMAP_ENGINE_PATH` -- Path to reconstruct_full_engine.exe (PLACEHOLDER - not installed)
- `MIPMAP_WORKSPACE=D:\MipMapWorkspace` -- MipMap output directory
- `SENTINEL_INCOMING=E:\incoming` -- Incoming drone data directory
- `SENTINEL_SCRIPTS=C:\Users\redle.SOULAAN\Documents\drone-pipeline` -- This repo
- `VENV_PATH_E_PYTHON` -- Path E virtual environment Python (to be created)
- `N8N_BASE_URL=http://localhost:5678` -- n8n base URL

## Pending Items

- MipMap Desktop not installed on new rig -- MIPMAP_ENGINE_PATH is placeholder
- .venv-path-e not created yet -- deferred to later phase
- Docker container stopped but not removed (can restart if needed)
