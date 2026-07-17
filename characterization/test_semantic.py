"""Representation-independent numeric characterization of v2 read endpoints.

The raw byte-level golden suite retired with the v1 API (S12): the v2
contract is guarded by the committed OpenAPI artifact and the unit suites.
This semantic suite keeps protecting the NUMBERS the API computes from the
real (cloned) dataset across future slices.
"""

from characterization.grids import (
    context_names,
    date_grids,
    tag_names,
    top_projects,
)
from characterization.harness import CharacterizationTestCase, safe_slug
from core.models import Commitment, Projects


class SemanticContractTests(CharacterizationTestCase):
    def _check(self, path, params=None):
        self.semantic_request(path, params or {}, safe_slug(path, params))

    def _project_ids(self):
        names = top_projects(self.user)
        rows = Projects.objects.filter(user=self.user, name__in=names)
        by_name = {p.name: p.id for p in rows}
        return [(name, by_name[name]) for name in names if name in by_name]

    def test_all_general_read_endpoints(self):
        for path in (
            "/api/v2/me/",
            "/api/v2/timers/",
            "/api/v2/sessions/",
            "/api/v2/projects/",
            "/api/v2/contexts/",
            "/api/v2/tags/",
            "/api/v2/commitments/",
            "/api/v2/reports/totals/",
            "/api/v2/reports/hierarchy/",
            "/api/v2/export/",
        ):
            self._check(path)
        for kind in ("project", "subproject", "context", "status", "tag"):
            self._check("/api/v2/reports/tallies/", {"by": kind})

    def test_all_date_grids(self):
        for label, params in date_grids(self.meta):
            if not params:
                continue
            self._check("/api/v2/sessions/", params)
            self._check("/api/v2/reports/totals/", params)
            self._check("/api/v2/reports/hierarchy/", params)
            self._check("/api/v2/export/", params)
            for kind in ("project", "subproject", "context", "status", "tag"):
                self._check("/api/v2/reports/tallies/", dict(params, by=kind))

    def test_project_grids(self):
        for name, project_id in self._project_ids():
            self._check(f"/api/v2/projects/{project_id}")
            self._check(f"/api/v2/projects/{project_id}/subprojects/")
            self._check("/api/v2/sessions/", {"project_ids": str(project_id)})
            self._check(
                "/api/v2/reports/totals/", {"project_ids": str(project_id)}
            )
            self._check(
                "/api/v2/reports/tallies/",
                {"by": "subproject", "project_ids": str(project_id)},
            )
            self._check("/api/v2/export/", {"project_ids": str(project_id)})

    def test_context_and_tag_grids(self):
        from core.models import Context, Tag

        for name in context_names(self.user):
            ctx = Context.objects.get(user=self.user, name=name)
            self._check("/api/v2/sessions/", {"context_ids": str(ctx.id)})
        for name in tag_names(self.user):
            tag = Tag.objects.get(user=self.user, name=name)
            self._check("/api/v2/sessions/", {"tag_ids": str(tag.id)})
        commitment = Commitment.objects.filter(user=self.user).order_by("id").first()
        if commitment:
            self._check(f"/api/v2/commitments/{commitment.id}")

    def test_all_chart_types_and_project_variants(self):
        # Includes the legacy-shaped kinds the web charts page consumes.
        projects = top_projects(self.user)
        for chart_type in (
            "scatter", "line", "stacked_area", "calendar", "cumulative",
            "heatmap", "histogram", "wordcloud",
            "pie", "bar", "context", "status", "bubble", "treemap", "radar",
        ):
            self._check("/api/v2/reports/charts/", {"chart_type": chart_type})
            for label, params in date_grids(self.meta):
                if params:
                    self._check(
                        "/api/v2/reports/charts/",
                        dict(params, chart_type=chart_type),
                    )
            if projects:
                self._check(
                    "/api/v2/reports/charts/",
                    {"chart_type": chart_type, "project_name": projects[0]},
                )
