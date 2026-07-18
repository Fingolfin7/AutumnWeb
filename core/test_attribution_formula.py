import random
from datetime import datetime, timedelta, timezone as datetime_timezone

from django.contrib.auth import get_user_model
from django.db.models import DurationField, ExpressionWrapper, F
from django.test import TestCase
from django.utils import timezone

from core.api_helpers import _get_active_sessions
from core.attribution import (
    BASIS_POINTS,
    hierarchy_child_credit,
    subproject_tally,
)
from core.models import Projects, Sessions, SessionSubproject, SubProjects
from core.services import even_split_bps
from core.utils import stop_expired_timers


UTC = datetime_timezone.utc


def _duration_expression():
    return ExpressionWrapper(
        F("end_time") - F("start_time"), output_field=DurationField()
    )


class AttributionFormulaTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="attribution-formula"
        )
        self.project = Projects.objects.create(
            user=self.user, name="Weighted Project"
        )
        self.sub_a = SubProjects.objects.create(
            user=self.user, parent_project=self.project, name="A"
        )
        self.sub_b = SubProjects.objects.create(
            user=self.user, parent_project=self.project, name="B"
        )
        self.sub_c = SubProjects.objects.create(
            user=self.user, parent_project=self.project, name="C"
        )

    def _session(self, offset_seconds, duration_seconds):
        start = datetime(2026, 1, 1, 9, tzinfo=UTC) + timedelta(
            seconds=offset_seconds
        )
        return Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=start,
            end_time=start + timedelta(seconds=duration_seconds),
            is_active=False,
        )

    def _link(self, session, subproject, allocation_bp):
        return SessionSubproject.objects.create(
            session=session,
            subproject=subproject,
            allocation_bp=allocation_bp,
        )

    def test_weighted_credit_and_zero_link_residual_bucket(self):
        rng = random.Random(20260716)
        subprojects = (self.sub_a, self.sub_b, self.sub_c)
        expected_numerators = {sub.name: 0 for sub in subprojects}
        expected_numerators["no subproject"] = 0

        for index in range(8):
            duration_seconds = rng.randint(1, 240) * 60
            session = self._session(index * 20000, duration_seconds)
            link_count = rng.randint(0, len(subprojects))
            linked = rng.sample(subprojects, link_count)
            split = even_split_bps(subproject.pk for subproject in linked)
            for subproject in linked:
                self._link(session, subproject, split[subproject.pk])
                expected_numerators[subproject.name] += (
                    duration_seconds * 1000000 * split[subproject.pk]
                )
            if not linked:
                expected_numerators["no subproject"] += (
                    duration_seconds * 1000000 * BASIS_POINTS
                )

        sessions = Sessions.objects.filter(user=self.user)
        actual = subproject_tally(sessions)
        actual_by_name = {row["name"]: row for row in actual}
        expected_numerators = {
            name: numerator
            for name, numerator in expected_numerators.items()
            if numerator
        }
        self.assertEqual(
            {
                name: row["total_numerator"]
                for name, row in actual_by_name.items()
            },
            expected_numerators,
        )

    def test_numerators_are_additive_and_include_residual(self):
        split = self._session(0, 100)
        self._link(split, self.sub_a, 3000)
        self._link(split, self.sub_b, 7000)

        residual = self._session(200, 40)
        self._link(residual, self.sub_a, 2500)

        split_rows = {
            row["name"]: row["total_numerator"]
            for row in subproject_tally(Sessions.objects.filter(pk=split.pk))
        }
        self.assertEqual(
            split_rows,
            {
                "A": 100 * 1000000 * 3000,
                "B": 100 * 1000000 * 7000,
            },
        )
        self.assertEqual(
            sum(split_rows.values()),
            100 * 1000000 * BASIS_POINTS,
        )

        residual_rows = {
            row["name"]: row["total_numerator"]
            for row in subproject_tally(
                Sessions.objects.filter(pk=residual.pk)
            )
        }
        self.assertEqual(
            residual_rows,
            {
                "A": 40 * 1000000 * 2500,
                "no subproject": 40 * 1000000 * 7500,
            },
        )
        self.assertEqual(
            sum(residual_rows.values()),
            40 * 1000000 * BASIS_POINTS,
        )

    def test_hierarchy_children_receive_link_credit_without_residual(self):
        session = self._session(0, 40)
        self._link(session, self.sub_a, 2500)

        rows = hierarchy_child_credit(Sessions.objects.filter(pk=session.pk))

        self.assertEqual(
            rows,
            [
                {
                    "subproject_id": self.sub_a.id,
                    "total_numerator": 40 * 1000000 * 2500,
                    "total": timedelta(seconds=10),
                }
            ],
        )

    def test_partitioned_api_consumers_share_weighted_semantics(self):
        split = self._session(0, 120)
        self._link(split, self.sub_a, 3000)
        self._link(split, self.sub_b, 7000)
        residual = self._session(200, 40)
        self._link(residual, self.sub_a, 2500)
        self.client.force_login(self.user)

        # Ported to v2 after v1 removal: same weighted semantics, 2dp minutes.
        tally = {
            (row["name"] if row.get("kind") != "residual" else "no subproject"):
                row["total_minutes"]
            for row in self.client.get(
                "/api/v2/reports/tallies/", {"by": "subproject"}
            ).json()["entries"]
        }
        self.assertEqual(
            tally,
            {
                "A": round(46 / 60, 2),
                "B": round(84 / 60, 2),
                "no subproject": round(30 / 60, 2),
            },
        )

        hierarchy = self.client.get("/api/v2/reports/hierarchy/").json()
        project_row = hierarchy["projects"][0]
        self.assertEqual(project_row["total_minutes"], round(160 / 60, 2))
        self.assertEqual(
            {
                child["name"]: child["total_minutes"]
                for child in project_row["children"]
            },
            {
                "A": round(46 / 60, 2),
                "B": round(84 / 60, 2),
                None: round(30 / 60, 2),
            },
        )

        scatter = self.client.get(
            "/api/v2/reports/charts/",
            {"chart_type": "scatter", "project_name": self.project.name},
        ).json()
        self.assertEqual(
            {(row["series"], row["y"]) for row in scatter},
            {
                ("A", 36 / 3600),
                ("A", 10 / 3600),
                ("B", 84 / 3600),
                ("no subproject", 30 / 3600),
            },
        )

        line = self.client.get(
            "/api/v2/reports/charts/",
            {"chart_type": "line", "project_name": self.project.name},
        ).json()
        self.assertEqual(
            {(row["series"], row["hours"]) for row in line},
            {
                ("A", 46 / 3600),
                ("B", 84 / 3600),
                ("no subproject", 30 / 3600),
            },
        )


class ActiveSessionPredicateTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="active-predicate"
        )
        self.project = Projects.objects.create(
            user=self.user, name="Active Predicate Project"
        )

    def test_aligned_active_and_expired_sessions_use_end_time_predicates(self):
        now = timezone.now().replace(microsecond=0)
        active = Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=now - timedelta(minutes=10),
            end_time=None,
            auto_stop_at=now + timedelta(minutes=10),
            is_active=True,
        )

        active_qs = _get_active_sessions(self.user)
        self.assertEqual(list(active_qs), [active])
        where_sql = str(active_qs.query).split(" WHERE ", 1)[1].split(
            " ORDER BY", 1
        )[0]
        self.assertIn("end_time", where_sql)
        self.assertIn("IS NULL", where_sql)
        self.assertNotIn("is_active", where_sql)

        expired = Sessions.objects.create(
            user=self.user,
            project=self.project,
            start_time=now - timedelta(hours=1),
            end_time=None,
            auto_stop_at=now - timedelta(minutes=1),
            is_active=True,
        )
        self.assertEqual(stop_expired_timers(self.user, now=now), [expired])
        expired.refresh_from_db()
        self.assertEqual(expired.end_time, now - timedelta(minutes=1))
        self.assertFalse(expired.is_active)
