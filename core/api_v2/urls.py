from django.urls import path

from core.api_v2.views import (
    MeView,
    ProjectDetailView,
    ProjectMergeView,
    ProjectsView,
    ProjectSubprojectsView,
    SessionDetailView,
    SessionsView,
    TimerDetailView,
    TimerRestartView,
    TimersView,
    TimerStopView,
    SubprojectDetailView,
    SubprojectMergeView,
)


app_name = "api_v2"

urlpatterns = [
    path("me/", MeView.as_view(), name="me"),
    path("timers/", TimersView.as_view(), name="timers"),
    path("timers/<int:session_id>", TimerDetailView.as_view(), name="timer-detail"),
    path(
        "timers/<int:session_id>/stop/",
        TimerStopView.as_view(),
        name="timer-stop",
    ),
    path(
        "timers/<int:session_id>/restart/",
        TimerRestartView.as_view(),
        name="timer-restart",
    ),
    path("sessions/", SessionsView.as_view(), name="sessions"),
    path(
        "sessions/<int:session_id>",
        SessionDetailView.as_view(),
        name="session-detail",
    ),
    path("projects/", ProjectsView.as_view(), name="projects"),
    path("projects/merge/", ProjectMergeView.as_view(), name="project-merge"),
    path(
        "projects/<int:project_id>",
        ProjectDetailView.as_view(),
        name="project-detail",
    ),
    path(
        "projects/<int:project_id>/subprojects/",
        ProjectSubprojectsView.as_view(),
        name="project-subprojects",
    ),
    path(
        "subprojects/merge/",
        SubprojectMergeView.as_view(),
        name="subproject-merge",
    ),
    path(
        "subprojects/<int:subproject_id>",
        SubprojectDetailView.as_view(),
        name="subproject-detail",
    ),
]
