"""API v2 Related-slider summaries, with fictional locally faked embeddings."""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from core.models import (
    Projects,
)
from core.test_semantic_search import SemanticSearchTestCase


class RelatedSummaryApiTests(SemanticSearchTestCase):
    def setUp(self):
        super().setUp()
        self.mixed = self._session(
            self.identity,
            "Login for the invoice, watered plants",
        )
        self.accounts = Projects.objects.create(
            user=self.user,
            name="Accounts",
            description="OAuth login provider",
            context=self.work,
            status="paused",
            start_date=timezone.now() - timedelta(days=20),
        )
        self.direct_project = Projects.objects.create(
            user=self.user,
            name="Sign-in failure handbook",
            context=self.work,
        )
        self._sync()

    def _summary(self, resource, **params):
        response = self.client.get(
            reverse(f"api_v2:{resource}-related-summary"),
            params,
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response

    def test_session_counts_agree_with_related_list_rows_at_several_cutoffs(self):
        for cutoff in (0.25, 0.40, 0.45, 0.60):
            with self.subTest(cutoff=cutoff):
                params = {
                    "search": "sign-in failure",
                    "related": "true",
                    "similarity": cutoff,
                }
                summary = self._summary("sessions", **params)
                listed = self.client.get(
                    reverse("api_v2:sessions"),
                    {**params, "ordering": "relevance", "limit": 500},
                )
                self.assertEqual(listed.status_code, 200, listed.content)
                related_count = sum(
                    row["match"] == "related"
                    for row in listed.json()["sessions"]
                )
                index = round((cutoff - 0.25) / 0.01)
                payload = summary.json()
                self.assertEqual(payload["counts"][index], related_count)
                self.assertEqual(payload["count"], related_count)
                self.assertEqual(summary["X-Autumn-Related"], "included")
                self.assertEqual(
                    summary["X-Autumn-Related-Similarity"], f"{cutoff:.2f}"
                )


    def test_session_summary_applies_list_filters_before_scoring(self):
        old = (timezone.localdate() - timedelta(days=5)).isoformat()
        cases = (
            ({}, 2),
            ({"project_ids": self.identity.pk}, 2),
            ({"context_ids": self.work.pk}, 2),
            ({"tag_ids": self.security.pk}, 2),
            ({"subproject_ids": self.tokens.pk}, 1),
            ({"exclude_subproject_ids": self.tokens.pk}, 1),
            ({"note_snippet": "invoice"}, 1),
            ({"end_date": old}, 1),
            ({"exclude_project_ids": self.identity.pk}, 0),
            ({"exclude_tag_ids": self.security.pk}, 0),
            ({"project_ids": self.garden.pk}, 0),
        )
        for filters, expected in cases:
            with self.subTest(filters=filters):
                payload = self._summary(
                    "sessions",
                    search="sign-in failure",
                    similarity=0.25,
                    **filters,
                ).json()
                self.assertEqual(payload["count"], expected)

    def test_other_accounts_are_excluded(self):
        other = self._user("summary-other", "other-key")
        foreign_project = Projects.objects.create(user=other, name="Foreign")
        self._session(
            foreign_project,
            "Repaired OAuth sign-in login",
            user=other,
        )
        self._sync()
        payload = self._summary(
            "sessions", search="sign-in failure", similarity=0.25
        ).json()
        self.assertEqual(payload["count"], 2)
        projects = self._summary(
            "projects", search="sign-in failure", similarity=0.25
        ).json()
        self.assertEqual(
            projects["count"],
            self._project_related_total(search="sign-in failure", similarity=0.25),
        )
        listed = self.client.get(
            reverse("api_v2:projects"),
            {"search": "sign-in failure", "similarity": 0.25, "related": "true"},
        ).json()
        self.assertNotIn(foreign_project.pk, [row["id"] for row in listed["projects"]])


    def test_project_counts_agree_with_related_minus_keyword_list(self):
        for cutoff in (0.25, 0.45, 0.60):
            with self.subTest(cutoff=cutoff):
                params = {"search": "sign-in failure", "similarity": cutoff}
                summary = self._summary("projects", **params).json()
                keyword = self.client.get(
                    reverse("api_v2:projects"), params
                ).json()["total"]
                related = self.client.get(
                    reverse("api_v2:projects"),
                    {**params, "related": "true"},
                ).json()["total"]
                index = round((cutoff - 0.25) / 0.01)
                self.assertEqual(summary["counts"][index], related - keyword)
                self.assertEqual(summary["count"], related - keyword)

    def _project_related_total(self, **params):
        """Related-only projects the list gives for these params."""
        keyword = self.client.get(reverse("api_v2:projects"), params)
        related = self.client.get(
            reverse("api_v2:projects"), {**params, "related": "true"}
        )
        self.assertEqual(keyword.status_code, 200, keyword.content)
        self.assertEqual(related.status_code, 200, related.content)
        return related.json()["total"] - keyword.json()["total"]
