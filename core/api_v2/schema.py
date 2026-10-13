def v2_endpoints_only(endpoints):
    return [endpoint for endpoint in endpoints if endpoint[0].startswith("/api/v2/")]


MCP_INCLUDED_OPERATION_IDS = {
    "commitments_adjustments_create",
    "commitments_create",
    "commitments_destroy",
    "commitments_list",
    "commitments_partial_update",
    "commitments_periods_list",
    "commitments_restart",
    "commitments_retrieve",
    "contexts_create",
    "contexts_destroy",
    "contexts_list",
    "contexts_partial_update",
    "dashboard_retrieve",
    "export_retrieve",
    "import_create",
    "me_retrieve",
    "project_subprojects_create",
    "project_subprojects_list",
    "projects_create",
    "projects_destroy",
    "projects_list",
    "projects_merge",
    "projects_partial_update",
    "projects_retrieve",
    "recommendations_luna_retrieve",
    "recommendations_timers_retrieve",
    "reports_charts_list",
    "reports_hierarchy_retrieve",
    "reports_tallies_retrieve",
    "reports_timeline_retrieve",
    "reports_totals_retrieve",
    "sessions_create",
    "sessions_destroy",
    "sessions_list",
    "sessions_partial_update",
    "sessions_retrieve",
    "subprojects_destroy",
    "subprojects_merge",
    "subprojects_partial_update",
    "subprojects_retrieve",
    "tags_create",
    "tags_destroy",
    "tags_list",
    "tags_partial_update",
    "timers_create",
    "timers_destroy",
    "timers_partial_update",
    "timers_restart_create",
    "timers_retrieve",
    "timers_stop_create",
}

MCP_EXCLUDED_OPERATION_IDS = {
    "me_preferences_partial_update",
    "me_preferences_retrieve",
    "recommendations_luna_refresh_create",
    "recommendations_usage_create",
    "timers_reminders_destroy",
    "timers_reminders_retrieve",
}


def mark_mcp_operations(result, generator, request, public):
    """Require an explicit MCP decision for every generated v2 operation."""
    for path, path_item in result.get("paths", {}).items():
        for method, operation in path_item.items():
            if not isinstance(operation, dict) or "operationId" not in operation:
                continue
            operation_id = operation["operationId"]
            if operation_id in MCP_INCLUDED_OPERATION_IDS:
                operation["x-autumn-mcp"] = "include"
            elif operation_id in MCP_EXCLUDED_OPERATION_IDS:
                operation["x-autumn-mcp"] = "exclude"
            else:
                raise RuntimeError(
                    "OpenAPI operation requires an explicit x-autumn-mcp decision: "
                    f"{method.upper()} {path} ({operation_id})"
                )
    return result
