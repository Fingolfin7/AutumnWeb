# urls.py
from django.urls import path, re_path
from django.http import JsonResponse
from core.views import (
    DashboardView,
    ProjectsListView,
    TimerListView,
    start_timer,
    stop_timer,
    restart_timer,
    remove_timer,
    active_timers_fragment,
    CreateProjectView,
    CreateSubProjectView,
    UpdateProjectView,
    UpdateSubProjectView,
    DeleteProjectView,
    DeleteSubProjectView,
    SessionsListView,
    update_session,
    DeleteSessionView,
    ChartsView,
    import_view,
    import_stream,
    export_view,
    merge_projects,
    merge_subprojects,
    set_active_context,
    manage_contexts,
    manage_tags,
    UpdateContextView,
    DeleteContextView,
    UpdateTagView,
    DeleteTagView,
    CreateCommitmentView,
    UpdateCommitmentView,
    DeleteCommitmentView,
)


def healthz(request):
    return JsonResponse({"status": "ok"})

urlpatterns = [
    path("healthz/", healthz, name="healthz"),
    # pages
    path("", DashboardView.as_view(), name="home"),
    path("projects/", ProjectsListView.as_view(), name="projects"),
    path("timers/", TimerListView.as_view(), name="timers"),
    path(
        "timers/active-fragment/",
        active_timers_fragment,
        name="active_timers_fragment",
    ),
    path("start_timer/", start_timer, name="start_timer"),
    path("stop_timer/<int:session_id>/", stop_timer, name="stop_timer"),
    path("restart_timer/<int:session_id>/", restart_timer, name="restart_timer"),
    path("remove_timer/<int:session_id>/", remove_timer, name="remove_timer"),
    path("create_subproject/", CreateProjectView.as_view(), name="create_project"),
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
    path("set-context/", set_active_context, name="set_active_context"),
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
