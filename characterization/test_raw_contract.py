"""Byte-level v1 response contracts consumed by CLI, MCP, and web charts."""

from datetime import datetime, timedelta

from characterization.grids import date_grids, top_projects
from characterization.harness import CharacterizationTestCase, safe_slug
from core.models import Commitment, Context, Projects, Sessions, SubProjects, Tag


COMPACT_READS = {
    "/api/timer/status/",
    "/api/log/",
    "/api/sessions/search/",
    "/api/projects/",
    "/api/projects/grouped/",
    "/api/subprojects/",
    "/api/contexts/",
    "/api/tags/",
    "/api/commitments/",
    "/api/totals/",
    "/api/export/",
}


class RawContractTests(CharacterizationTestCase):
    def _read(self, path, params=None, slug_suffix=None):
        params = params or {}
        self.raw_request(
            "GET",
            path,
            params=params,
            slug=safe_slug(path, params) + ("--" + slug_suffix if slug_suffix else ""),
        )
        if path in COMPACT_READS and "compact" not in params:
            full = dict(params, compact="false")
            self.raw_request("GET", path, params=full)

    def test_identity_timer_and_session_reads(self):
        self._read("/api/me/")
        self._read("/api/timer/status/")
        self._read("/api/log/")

        bounded = date_grids(self.meta)[1][1]
        self._read("/api/log/", bounded)
        self._read("/api/list_sessions/")
        self._read("/api/list_sessions/", bounded)
        self._read("/api/sessions/search/", bounded)

        projects = top_projects(self.user)
        if projects:
            project = projects[0]
            self._read("/api/log/", {"project": project})
            self._read("/api/list_sessions/", {"project_name": project})
            self._read("/api/sessions/search/", {"project": project})
        session = Sessions.objects.filter(user=self.user, is_active=False).order_by("id").first()
        if session:
            # The consumer inventory calls this a read, but the current URL is PATCH-only.
            self._read("/api/session/%s/" % session.id)

    def test_project_and_subproject_reads(self):
        bounded = date_grids(self.meta)[1][1]
        for path in (
            "/api/projects/",
            "/api/projects/grouped/",
            "/api/projects_with_stats/",
            "/api/list_projects/",
            "/api/search_projects/",
            "/api/hierarchy/",
        ):
            self._read(path)
        for path in ("/api/projects/grouped/", "/api/projects_with_stats/", "/api/list_projects/", "/api/hierarchy/"):
            self._read(path, bounded)

        projects = top_projects(self.user)
        if projects:
            project = projects[0]
            self._read("/api/get_project/%s/" % project)
            self._read("/api/subprojects/")
            self._read("/api/subprojects/", {"project": project})
            self._read("/api/list_subprojects/", {"project_name": project})
            self._read("/api/search_subprojects/", {"project": project})
            for path in ("/api/projects/grouped/", "/api/projects_with_stats/", "/api/hierarchy/"):
                self._read(path, {"project_name": project})

    def test_context_tag_and_commitment_reads(self):
        self._read("/api/contexts/")
        context = Context.objects.filter(user=self.user).order_by("name").first()
        if context:
            self._read("/api/contexts/%s/" % context.id)
            self._read("/api/contexts/%s/" % context.id, {"compact": "false"})
        self._read("/api/tags/")
        tag = Tag.objects.filter(user=self.user).order_by("name").first()
        if tag:
            self._read("/api/tags/%s/" % tag.id)
            self._read("/api/tags/%s/" % tag.id, {"compact": "false"})
        self._read("/api/commitments/")
        commitment = Commitment.objects.filter(user=self.user).order_by("id").first()
        if commitment:
            self._read("/api/commitments/%s/" % commitment.id)

    def test_tallies_totals_and_export_reads(self):
        tally_paths = (
            "/api/tally_by_sessions/",
            "/api/tally_by_subprojects/",
            "/api/tally_by_context/",
            "/api/tally_by_status/",
            "/api/tally_by_tags/",
        )
        bounded = date_grids(self.meta)[1][1]
        for path in tally_paths:
            self._read(path)
            self._read(path, bounded)
        self._read("/api/totals/")
        self._read("/api/export/")
        self._read("/api/export/", bounded)
        for project in top_projects(self.user):
            for path in tally_paths:
                self._read(path, {"project_name": project})
            self._read("/api/totals/", {"project": project})
            self._read("/api/export/", {"project_name": project})

    def test_chart_data_variants(self):
        projects = top_projects(self.user)
        bounded = date_grids(self.meta)[1][1]
        for chart_type in (
            "scatter",
            "line",
            "stacked_area",
            "calendar",
            "cumulative",
            "heatmap",
            "histogram",
            "wordcloud",
        ):
            self._read("/api/chart_data/", {"chart_type": chart_type})
            self._read(
                "/api/chart_data/", dict(bounded, chart_type=chart_type)
            )
            if projects:
                self._read(
                    "/api/chart_data/",
                    {"chart_type": chart_type, "project_name": projects[0]},
                )

    def test_project_mutation_chain(self):
        created = self.raw_request("POST", "/api/create_project/", body={"name": "CHZ Project"})
        project_id = created.json()["id"]
        self.raw_request(
            "POST",
            "/api/create_subproject/",
            body={"name": "CHZ Subproject", "parent_project": project_id},
        )
        self.raw_request(
            "PATCH",
            "/api/project/update/",
            body={"project": "CHZ Project", "description": "CHZ description"},
        )
        self.raw_request(
            "POST",
            "/api/rename/",
            body={"type": "subproject", "project": "CHZ Project", "subproject": "CHZ Subproject", "new_name": "CHZ Renamed Subproject"},
        )
        self.raw_request(
            "POST",
            "/api/rename/",
            body={"type": "project", "project": "CHZ Project", "new_name": "CHZ Renamed Project"},
            slug="api-rename-project",
        )
        self.raw_request(
            "POST", "/api/mark/", body={"project": "CHZ Renamed Project", "status": "paused"}
        )
        self.raw_request(
            "DELETE", "/api/project/delete/", body={"project": "CHZ Renamed Project"}
        )

    def test_timer_track_edit_and_delete_chain(self):
        project = Projects.objects.create(user=self.user, name="CHZ Timer Project")
        start = self.raw_request("POST", "/api/timer/start/", body={"project": project.name, "note": "CHZ timer"})
        session_id = start.json()["session"]["id"]
        self.raw_request("POST", "/api/timer/restart/", body={"session_id": session_id})
        self.raw_request("POST", "/api/timer/stop/", body={"session_id": session_id})

        frozen = datetime.fromisoformat(self.meta["frozen_at"].replace("Z", "+00:00"))
        tracked = self.raw_request(
            "POST",
            "/api/track/",
            body={
                "project": project.name,
                "start": (frozen - timedelta(hours=2)).isoformat(),
                "end": (frozen - timedelta(hours=1)).isoformat(),
                "note": "CHZ tracked",
            },
        )
        tracked_id = tracked.json()["session"]["id"]
        self.raw_request(
            "PATCH", "/api/session/%s/" % tracked_id, body={"note": "CHZ edited"}
        )
        self.raw_request("DELETE", "/api/delete_session/%s/" % tracked_id, body={})

        delete_start = self.raw_request(
            "POST", "/api/timer/start/", body={"project": project.name}, slug="api-timer-start-for-delete"
        )
        delete_id = delete_start.json()["session"]["id"]
        self.raw_request("DELETE", "/api/timer/delete/", body={"session_id": delete_id})

    def test_delete_subproject_chain(self):
        project = Projects.objects.create(user=self.user, name="CHZ Delete Parent")
        SubProjects.objects.create(user=self.user, parent_project=project, name="CHZ Delete Child")
        self.raw_request(
            "DELETE",
            "/api/delete_subproject/CHZ Delete Parent/CHZ Delete Child/",
            body={},
        )

    def test_merge_chains(self):
        parent = Projects.objects.create(user=self.user, name="CHZ Merge Parent")
        SubProjects.objects.create(user=self.user, parent_project=parent, name="CHZ Merge A")
        SubProjects.objects.create(user=self.user, parent_project=parent, name="CHZ Merge B")
        self.raw_request(
            "POST",
            "/api/merge_subprojects/",
            body={"project_id": parent.id, "subproject1": "CHZ Merge A", "subproject2": "CHZ Merge B", "new_subproject_name": "CHZ Merge Result"},
        )

        Projects.objects.create(user=self.user, name="CHZ Project A")
        Projects.objects.create(user=self.user, name="CHZ Project B")
        self.raw_request(
            "POST",
            "/api/merge_projects/",
            body={"project1": "CHZ Project A", "project2": "CHZ Project B", "new_project_name": "CHZ Project Result"},
        )

    def test_import_and_audit_mutations(self):
        frozen = datetime.fromisoformat(self.meta["frozen_at"].replace("Z", "+00:00"))
        date_text = frozen.strftime("%m-%d-%Y")
        payload = {
            "CHZ Imported Project": {
                "Start Date": date_text,
                "Last Updated": date_text,
                "Total Time": 60.0,
                "Status": "active",
                "Description": "CHZ import",
                "Sub Projects": {},
                "Session History": [],
            }
        }
        self.raw_request("POST", "/api/import/", body={"data": payload})
        self.raw_request("POST", "/api/audit/", body={"dry_run": False})
