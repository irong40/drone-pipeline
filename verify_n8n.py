#!/usr/bin/env python3
"""Minimal test script for n8n Execute Command verification.

Used by Phase 14 to prove ENV-01: Execute Command node can run Python
and get structured JSON output back.
"""
import json
import sys
import os

result = {
    "status": "ok",
    "python_version": sys.version,
    "platform": sys.platform,
    "executable": sys.executable,
    "cwd": os.getcwd(),
    "message": "Execute Command node is working"
}
print(json.dumps(result))
sys.exit(0)
