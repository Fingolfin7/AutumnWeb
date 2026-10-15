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
    "notifications_schedules_create",
    "notifications_schedules_list",
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
    "reports_weekly_review_retrieve",
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
    "me_account_partial_update",
    "me_account_retrieve",
    "me_api_keys_destroy",
    "me_api_keys_update",
    "me_avatar_destroy",
    "me_avatar_update",
    "me_background_destroy",
    "me_background_download_retrieve",
    "me_background_update",
    "me_chatgpt_login_create",
    "me_chatgpt_login_destroy",
    "me_chatgpt_login_retrieve",
    "me_social_accounts_destroy",
    "me_social_accounts_retrieve",
    "import_uploads_create",
    "import_uploads_stream_retrieve",
    "insights_chats_destroy",
    "insights_chats_list",
    "insights_chats_retrieve",
    "insights_options_retrieve",
    "insights_selection_retrieve",
    "insights_stream_create",
    "me_preferences_partial_update",
    "me_preferences_retrieve",
    "notifications_preferences_partial_update",
    "notifications_preferences_retrieve",
    "notifications_schedules_destroy",
    "notifications_schedules_partial_update",
    "notifications_schedules_snooze_create",
    "push_status_retrieve",
    "push_subscriptions_create",
    "push_subscriptions_destroy",
    "push_test_create",
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


# Response fields a serializer drops unless asked for (?include=) or unless
# they apply (a celebration only follows a stop or completion). drf-spectacular
# marks every read-only field required, which would tell typed clients they
# are always present.
CONDITIONAL_RESPONSE_FIELDS = {
    "SessionResource": {"note_html", "active_reminders", "celebration"},
    "SessionListItem": {"note_html", "active_reminders", "celebration"},
    "ProjectResource": {"celebration"},
    "ProjectDetailResource": {"celebration"},
}


def relax_conditional_fields(result, generator, request, public):
    """Mark CONDITIONAL_RESPONSE_FIELDS optional in their components."""
    schemas = result.get("components", {}).get("schemas", {})
    for name, fields in CONDITIONAL_RESPONSE_FIELDS.items():
        component = schemas.get(name)
        if component is None:
            raise RuntimeError(f"OpenAPI component {name} is missing")
        missing = fields - set(component.get("properties", {}))
        if missing:
            raise RuntimeError(f"{name} has no {sorted(missing)}")
        required = [field for field in component.get("required", []) if field not in fields]
        if required:
            component["required"] = required
        else:
            component.pop("required", None)
    return result
