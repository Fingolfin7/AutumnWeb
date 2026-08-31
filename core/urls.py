# urls.py
from django.urls import path, re_path
from django.http import JsonResponse
from core.views.charts import ChartsView
from core.views.commitments import (
    CreateCommitmentView,
    DeleteCommitmentView,
    UpdateCommitmentView,
)
from core.views.contexts_tags import (
    DeleteContextView,
    DeleteTagView,
    UpdateContextView,
    UpdateTagView,
    manage_contexts,
    manage_tags,
    switch_context,
)
from core.views.dashboard import DashboardView, timeline_fragment
from core.views.import_export import export_view, import_stream, import_view
from core.views.notifications import (
    cancel_scheduled_reminder,
    edit_scheduled_reminder,
    notifications,
    snooze_scheduled_reminder,
    weekly_review,
)
from core.views.projects import (
    CreateProjectView,
    CreateSubProjectView,
    DeleteProjectView,
    DeleteSubProjectView,
    ProjectsListView,
    UpdateProjectView,
    UpdateSubProjectView,
    merge_projects,
    merge_subprojects,
)
from core.views.push import (
    cancel_timer_reminder,
    push_status,
    push_subscribe,
    push_test,
    push_unsubscribe,
)
from core.views.sessions import DeleteSessionView, SessionsListView, update_session
from core.views.timers import (
    TimerListView,
    active_timers_fragment,
    remove_timer,
    restart_timer,
    start_timer,
    stop_timer,
    update_timer_note,
)


def healthz(request):
    return JsonResponse({"status": "ok"})

urlpatterns = [
    path("healthz/", healthz, name="healthz"),
    # pages
    path("", DashboardView.as_view(), name="home"),
    path("timeline/fragment/", timeline_fragment, name="timeline_fragment"),
    path("projects/", ProjectsListView.as_view(), name="projects"),
    path("timers/", TimerListView.as_view(), name="timers"),
    path(
        "timers/active-fragment/",
        active_timers_fragment,
        name="active_timers_fragment",
    ),
    path("start_timer/", start_timer, name="start_timer"),
    path("stop_timer/<int:session_id>/", stop_timer, name="stop_timer"),
    path("timers/<int:session_id>/note/", update_timer_note, name="update_timer_note"),
    path("restart_timer/<int:session_id>/", restart_timer, name="restart_timer"),
    path("remove_timer/<int:session_id>/", remove_timer, name="remove_timer"),
    path("push/status/", push_status, name="push_status"),
    path("push/subscribe/", push_subscribe, name="push_subscribe"),
    path("push/unsubscribe/", push_unsubscribe, name="push_unsubscribe"),
    path("push/test/", push_test, name="push_test"),
    path(
        "timers/<int:session_id>/reminders/<int:reminder_id>/cancel/",
        cancel_timer_reminder,
        name="cancel_timer_reminder",
    ),
    path("notifications/", notifications, name="notifications"),
    path("review/weekly/", weekly_review, name="weekly_review"),
    path(
        "notifications/schedules/<int:reminder_id>/edit/",
        edit_scheduled_reminder,
        name="edit_scheduled_reminder",
    ),
    path(
        "notifications/schedules/<int:reminder_id>/snooze/",
        snooze_scheduled_reminder,
        name="snooze_scheduled_reminder",
    ),
    path(
        "notifications/schedules/<int:reminder_id>/cancel/",
        cancel_scheduled_reminder,
        name="cancel_scheduled_reminder",
    ),
    # Was served at "create_subproject/" — a copy-paste slip. Only the URL name
    # is ever used to build links, so nothing referenced the wrong path, but it
    # made the address bar lie on the create-project page.
    path("create_project/", CreateProjectView.as_view(), name="create_project"),
    path(
        "create_subproject/<int:pk>/",
        CreateSubProjectView.as_view(),
        name="create_subproject",
    ),
    path(
        "update_project/<int:pk>/", UpdateProjectView.as_view(), name="update_project"
    ),
    path(
        "update_subproject/<int:pk>/",
        UpdateSubProjectView.as_view(),
        name="update_subproject",
    ),
    path(
        "delete_project/<int:pk>/", DeleteProjectView.as_view(), name="delete_project"
    ),
    path(
        "delete_subproject/<int:pk>/",
        DeleteSubProjectView.as_view(),
        name="delete_subproject",
    ),
    path("sessions/", SessionsListView.as_view(), name="sessions"),
    path("update_session/<int:session_id>/", update_session, name="update_session"),
    path(
        "update_session/<uuid:session_uuid>/",
        update_session,
        name="update_session",
    ),
    path(
        "delete_session/<int:session_id>/",
        DeleteSessionView.as_view(),
        name="delete_session",
    ),
    path("charts/", ChartsView, name="charts"),
    path("export/", export_view, name="export"),
    path("import/", import_view, name="import"),
    path("import/stream/", import_stream, name="import_stream"),
    path("merge_projects/", merge_projects, name="merge_projects"),
    path(
        "merge_subprojects/<int:project_id>/",
        merge_subprojects,
        name="merge_subprojects",
    ),
    path("contexts/", manage_contexts, name="contexts"),
    path("tags/", manage_tags, name="tags"),
    path("set-context/", switch_context, name="set_active_context"),
    # context/tag update/delete
    path(
        "update_context/<int:pk>/", UpdateContextView.as_view(), name="update_context"
    ),
    path(
        "delete_context/<int:pk>/", DeleteContextView.as_view(), name="delete_context"
    ),
    path("update_tag/<int:pk>/", UpdateTagView.as_view(), name="update_tag"),
    path("delete_tag/<int:pk>/", DeleteTagView.as_view(), name="delete_tag"),
    # commitment management
    path(
        "create_commitment/",
        CreateCommitmentView.as_view(),
        name="create_commitment_generic",
    ),
    path(
        "create_commitment/<int:project_pk>/",
        CreateCommitmentView.as_view(),
        name="create_commitment",
    ),
    path(
        "update_commitment/<int:pk>/",
        UpdateCommitmentView.as_view(),
        name="update_commitment",
    ),
    path(
        "delete_commitment/<int:pk>/",
        DeleteCommitmentView.as_view(),
        name="delete_commitment",
    ),
]
