"""
n8n workflow JSON validation tests (TST-03).

Parametrized validation for all n8n/*.json files:
- All files must be valid JSON
- Workflow files (containing "nodes" key) must have valid node structure
- Config/patch files (containing "_meta" or "template_defaults") need JSON syntax only
"""
import glob
import json
import os

import pytest

# Resolve n8n/ directory relative to this test file
N8N_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "n8n"))

REQUIRED_NODE_KEYS = {"id", "name", "type", "parameters"}


def get_workflow_files():
    """Discover all JSON files in the n8n/ directory."""
    return sorted(glob.glob(os.path.join(N8N_DIR, "*.json")))


def _is_config_file(data: dict) -> bool:
    """Return True if the JSON is a config/patch file, not a workflow."""
    return ("_meta" in data or "template_defaults" in data) and "nodes" not in data


@pytest.mark.parametrize(
    "filepath",
    get_workflow_files(),
    ids=lambda p: os.path.basename(p),
)
class TestN8nWorkflowValidation:
    """Parametrized validation suite for n8n JSON files."""

    def test_valid_json(self, filepath):
        """Each n8n/*.json file loads without JSONDecodeError."""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, dict), f"{filepath} root element should be a dict"

    def test_workflow_nodes_structure(self, filepath):
        """Workflow files have nodes as a list with required keys."""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        if _is_config_file(data):
            pytest.skip("Config/patch file — no node validation required")

        if "nodes" not in data:
            pytest.skip("No nodes key — not a workflow file")

        assert isinstance(data["nodes"], list), "nodes must be a list"

        for i, node in enumerate(data["nodes"]):
            missing = REQUIRED_NODE_KEYS - set(node.keys())
            assert not missing, (
                f"Node {i} ({node.get('name', 'unnamed')}) missing keys: {missing}"
            )

    def test_connections_structure(self, filepath):
        """If connections exist, each value has a 'main' key with list of lists."""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        if _is_config_file(data):
            pytest.skip("Config/patch file — no connection validation required")

        if "connections" not in data:
            pytest.skip("No connections key in file")

        connections = data["connections"]
        assert isinstance(connections, dict), "connections must be a dict"

        for node_name, conn_data in connections.items():
            assert "main" in conn_data, (
                f"Connection for '{node_name}' missing 'main' key"
            )
            assert isinstance(conn_data["main"], list), (
                f"Connection 'main' for '{node_name}' must be a list"
            )
            for idx, output_list in enumerate(conn_data["main"]):
                assert isinstance(output_list, list), (
                    f"Connection 'main[{idx}]' for '{node_name}' must be a list"
                )
