# urls.py
from django.urls import path
from django.http import JsonResponse
from core.views.recommendation_usage import recommendation_usage
from core.views.contexts_tags import switch_context


def healthz(request):
    return JsonResponse({"status": "ok"})

from core.spa import reminder_action, spa

urlpatterns = [
    path("healthz/", healthz, name="healthz"),
    # pages
    path("", spa, name="home"),
    path("projects/", spa, name="projects"),
    path("timers/", spa, name="timers"),
    path("start_timer/", spa, name="start_timer"),
    path("timers/recommendation-usage/", recommendation_usage, name="recommendation_usage"),
    path("stop_timer/<int:session_id>/", spa, name="stop_timer"),
    path("remove_timer/<int:session_id>/", spa, name="remove_timer"),
    path("notifications/", spa, name="notifications"),
    path("review/weekly/", spa, name="weekly_review"),
    path(
        "notifications/schedules/<int:reminder_id>/edit/",
        reminder_action,
        {"action": "edit"},
        name="edit_scheduled_reminder",
    ),
    path(
        "notifications/schedules/<int:reminder_id>/snooze/",
        reminder_action,
        {"action": "snooze"},
        name="snooze_scheduled_reminder",
    ),
    path(
        "notifications/schedules/<int:reminder_id>/cancel/",
        reminder_action,
        {"action": "cancel"},
        name="cancel_scheduled_reminder",
    ),
    # Was served at "create_subproject/" — a copy-paste slip. Only the URL name
    # is ever used to build links, so nothing referenced the wrong path, but it
    # made the address bar lie on the create-project page.
    path("create_project/", spa, name="create_project"),
    path("create_subproject/<int:pk>/", spa, name="create_subproject"),
    path("update_project/<int:pk>/", spa, name="update_project"),
    path("update_subproject/<int:pk>/", spa, name="update_subproject"),
    path("delete_project/<int:pk>/", spa, name="delete_project"),
    path("delete_subproject/<int:pk>/", spa, name="delete_subproject"),
    path("sessions/", spa, name="sessions"),
    path("update_session/<int:session_id>/", spa, name="update_session"),
    path("update_session/<uuid:session_uuid>/", spa, name="update_session"),
    path("delete_session/<int:session_id>/", spa, name="delete_session"),
    path("charts/", spa, name="charts"),
    path("export/", spa, name="export"),
    path("import/", spa, name="import"),
    path("merge_projects/", spa, name="merge_projects"),
    path("merge_subprojects/<int:project_id>/", spa, name="merge_subprojects"),
    path("contexts/", spa, name="contexts"),
    path("tags/", spa, name="tags"),
    path("set-context/", switch_context, name="set_active_context"),
    # context/tag update/delete
    path("update_context/<int:pk>/", spa, name="update_context"),
    path("delete_context/<int:pk>/", spa, name="delete_context"),
    path("update_tag/<int:pk>/", spa, name="update_tag"),
    path("delete_tag/<int:pk>/", spa, name="delete_tag"),
    # commitment management
    path("create_commitment/", spa, name="create_commitment_generic"),
    path("create_commitment/<int:project_pk>/", spa, name="create_commitment"),
    path("update_commitment/<int:pk>/", spa, name="update_commitment"),
    path("delete_commitment/<int:pk>/", spa, name="delete_commitment"),
]
