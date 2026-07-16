"""Representation-independent numeric characterization of v1 read endpoints."""

from characterization.grids import (
    context_names,
    date_grids,
    tag_names,
    top_projects,
)
from characterization.harness import CharacterizationTestCase, safe_slug
from core.models import Commitment


class SemanticContractTests(CharacterizationTestCase):
    def _check(self, path, params=None):
        self.semantic_request(path, params or {}, safe_slug(path, params))

    def test_all_general_read_endpoints(self):
        for path in (
            "/api/me/",
            "/api/timer/status/",
            "/api/log/",
            "/api/list_sessions/",
            "/api/projects/",
            "/api/projects/grouped/",
            "/api/projects_with_stats/",
            "/api/list_projects/",
            "/api/search_projects/",
            "/api/contexts/",
            "/api/tags/",
            "/api/commitments/",
            "/api/tally_by_sessions/",
            "/api/tally_by_subprojects/",
            "/api/tally_by_context/",
            "/api/tally_by_status/",
            "/api/tally_by_tags/",
            "/api/hierarchy/",
            "/api/export/",
            "/api/list_active_sessions/",
        ):
            self._check(path)

    def test_all_date_grids(self):
        paths = (
            "/api/log/",
            "/api/list_sessions/",
            "/api/projects/grouped/",
            "/api/list_projects/",
            "/api/projects_with_stats/",
            "/api/tally_by_sessions/",
            "/api/tally_by_subprojects/",
            "/api/tally_by_context/",
            "/api/tally_by_status/",
            "/api/tally_by_tags/",
            "/api/hierarchy/",
            "/api/export/",
        )
        for label, params in date_grids(self.meta):
            if not params:
                continue
            for path in paths:
                self._check(path, params)
            self._check("/api/sessions/search/", params)

    def test_project_grids(self):
        for project in top_projects(self.user):
            self._check("/api/get_project/%s/" % project)
            self._check("/api/subprojects/", {"project": project})
            self._check("/api/list_subprojects/", {"project_name": project})
            self._check("/api/search_subprojects/", {"project": project})
            self._check("/api/sessions/search/", {"project": project})
            self._check("/api/log/", {"project": project})
            self._check("/api/list_sessions/", {"project_name": project})
            self._check("/api/totals/", {"project": project})
            self._check("/api/export/", {"project_name": project})
            for path in (
                "/api/tally_by_sessions/",
                "/api/tally_by_subprojects/",
                "/api/projects/grouped/",
                "/api/projects_with_stats/",
                "/api/hierarchy/",
            ):
                self._check(path, {"project_name": project})

    def test_context_and_tag_grids(self):
        for name in context_names(self.user):
            self._check("/api/projects/", {"context": name})
        for name in tag_names(self.user):
            self._check("/api/projects/", {"tags": name})
        commitment = Commitment.objects.filter(user=self.user).order_by("id").first()
        if commitment:
            self._check("/api/commitments/%s/" % commitment.id)

    def test_all_chart_types_and_project_variants(self):
        projects = top_projects(self.user)
        for chart_type in (
            "scatter", "line", "stacked_area", "calendar", "cumulative",
            "heatmap", "histogram", "wordcloud",
        ):
            self._check("/api/chart_data/", {"chart_type": chart_type})
            for label, params in date_grids(self.meta):
                if params:
                    self._check(
                        "/api/chart_data/", dict(params, chart_type=chart_type)
                    )
            if projects:
                self._check(
                    "/api/chart_data/",
                    {"chart_type": chart_type, "project_name": projects[0]},
                )
