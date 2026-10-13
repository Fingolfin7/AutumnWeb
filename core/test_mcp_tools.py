import json
from pathlib import Path

from django.test import SimpleTestCase


EXPECTED_TOOLS = sorted(
    [
        "commitments_adjustments_create",
        "commitments_periods_list",
        "create_commitment",
        "create_context",
        "create_project",
        "create_subproject",
        "create_tag",
        "delete_commitment",
        "delete_context",
        "delete_project",
        "delete_session",
        "delete_subproject",
        "delete_tag",
        "delete_timer",
        "export_data",
        "get_commitment",
        "get_dashboard",
        "get_project",
        "get_session",
        "get_subproject",
        "get_timeline",
        "import_data",
        "list_commitments",
        "list_contexts",
        "list_projects",
        "list_sessions",
        "list_tags",
        "luna_recommendations",
        "me",
        "merge_projects",
        "merge_subprojects",
        "reports_charts_list",
        "reports_hierarchy_retrieve",
        "reports_tallies_retrieve",
        "reports_totals_retrieve",
        "restart",
        "restart_commitments",
        "start",
        "status",
        "stop",
        "subprojects",
        "timer_suggestions",
        "track",
        "update_commitment",
        "update_context",
        "update_project",
        "update_session",
        "update_subproject",
        "update_tag",
        "update_timer",
    ]
)


class McpToolSnapshotTests(SimpleTestCase):
    def test_generated_tool_names_are_explicit(self):
        path = Path(__file__).resolve().parents[1] / "integrations" / "mcp" / "src" / "operations.json"
        operations = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(sorted(operation["name"] for operation in operations), EXPECTED_TOOLS)
