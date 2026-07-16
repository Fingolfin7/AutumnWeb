from django.urls import path

from core.api_v2.views import (
    MeView,
    SessionDetailView,
    SessionsView,
    TimerDetailView,
    TimerRestartView,
    TimersView,
    TimerStopView,
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
]
