from django.urls import path

from core.api_v2.views import (
    ContextDetailView,
    ContextsView,
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
    TagDetailView,
    TagsView,
)
from core.api_v2.commitments import (
    CommitmentAdjustmentsView,
    CommitmentDetailView,
    CommitmentPeriodsView,
    CommitmentRestartView,
    CommitmentsView,
)
from core.api_v2.reports import (
    ReportChartsView,
    ReportHierarchyView,
    ReportTalliesView,
    ReportTotalsView,
)
from core.api_v2.import_export import ExportView, ImportView


app_name = "api_v2"

urlpatterns = [
    path("me/", MeView.as_view(), name="me"),
    path("export/", ExportView.as_view(), name="export"),
    path("import/", ImportView.as_view(), name="import"),
    path("commitments/", CommitmentsView.as_view(), name="commitments"),
    path(
        "commitments/<int:commitment_id>",
        CommitmentDetailView.as_view(),
        name="commitment-detail",
    ),
    path(
        "commitments/<int:commitment_id>/restart/",
        CommitmentRestartView.as_view(),
        name="commitment-restart",
    ),
    path(
        "commitments/<int:commitment_id>/adjustments/",
        CommitmentAdjustmentsView.as_view(),
        name="commitment-adjustments",
    ),
    path(
        "commitments/<int:commitment_id>/periods/",
        CommitmentPeriodsView.as_view(),
        name="commitment-periods",
    ),
    path("contexts/", ContextsView.as_view(), name="contexts"),
    path(
        "contexts/<int:context_id>",
        ContextDetailView.as_view(),
        name="context-detail",
    ),
    path("tags/", TagsView.as_view(), name="tags"),
    path("tags/<int:tag_id>", TagDetailView.as_view(), name="tag-detail"),
    path("reports/totals/", ReportTotalsView.as_view(), name="report-totals"),
    path("reports/tallies/", ReportTalliesView.as_view(), name="report-tallies"),
    path(
        "reports/hierarchy/",
        ReportHierarchyView.as_view(),
        name="report-hierarchy",
    ),
    path("reports/charts/", ReportChartsView.as_view(), name="report-charts"),
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
