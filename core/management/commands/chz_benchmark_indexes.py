"""Benchmark candidate-for-drop indexes against the hot query set.

The S5 slice added end_time-based partial/completed indexes and moved the
active/auto-stop scans onto them, superseding three older Sessions indexes
and (potentially) the redundant single-column sessions_id index on the
through table. The plan requires a Postgres benchmark before dropping the
predecessors. This command:

  1. seeds a synthetic dataset (~10x current production scale) for a
     dedicated bench user,
  2. times the hot queries,
  3. drops the candidate indexes inside a transaction, re-times, and rolls
     everything back (data and DDL; both SQLite and Postgres roll DDL back).

Run it against Postgres via DATABASE_URL (the CI workflow has a manual job
for this). SQLite results are indicative only.
"""

import statistics
import time
import uuid as uuid_lib
from datetime import datetime, timedelta, timezone as dt_tz

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import connection, transaction

from core.models import Projects, Sessions, SessionSubproject, SubProjects

BENCH_USERNAME = "chz-bench-user"

# (table, columns) -> superseded by the S5 indexes / composite unique.
DROP_CANDIDATES = [
    ("core_sessions", ["is_active", "end_time"]),
    ("core_sessions", ["user_id", "project_id"]),
    ("core_sessions", ["user_id", "is_active", "end_time"]),
    ("core_sessions_subprojects", ["sessions_id"]),
]


def _find_index_names(cursor, table, columns):
    constraints = connection.introspection.get_constraints(cursor, table)
    return [
        name
        for name, meta in constraints.items()
        if meta.get("index")
        and not meta.get("unique")
        and meta.get("columns") == columns
    ]


class Command(BaseCommand):
    help = "Time hot queries with and without the candidate-for-drop indexes."

    def add_arguments(self, parser):
        parser.add_argument("--projects", type=int, default=100)
        parser.add_argument("--sessions", type=int, default=40000)
        parser.add_argument("--runs", type=int, default=15)
        parser.add_argument(
            "--explain", action="store_true", help="Print query plans in both states."
        )
        parser.add_argument(
            "--unsafe-sqlite",
            action="store_true",
            help=(
                "Allow running against a SQLite database (results are "
                "indicative only, and the seed/rollback touches the "
                "configured default DB). Intended target is Postgres."
            ),
        )

    def handle(self, *args, **options):
        if connection.vendor != "postgresql" and not options["unsafe_sqlite"]:
            self.stderr.write(
                "Refusing to run against non-Postgres storage; the benchmark "
                "is meant for the production engine. Pass --unsafe-sqlite for "
                "an indicative local run against a scratch database."
            )
            return
        self.stdout.write(f"vendor: {connection.vendor}")
        runs = options["runs"]

        with transaction.atomic():
            user = self._seed(options["projects"], options["sessions"])
            queries = self._queries(user)

            self.stdout.write("\n=== WITH old indexes ===")
            before = self._time_all(queries, runs, explain=options["explain"])

            dropped = []
            with connection.cursor() as cursor:
                for table, columns in DROP_CANDIDATES:
                    for name in _find_index_names(cursor, table, columns):
                        cursor.execute(f'DROP INDEX "{name}"')
                        dropped.append(name)
            self.stdout.write(f"\ndropped for comparison: {dropped}")

            self.stdout.write("\n=== WITHOUT old indexes ===")
            after = self._time_all(queries, runs, explain=options["explain"])

            self.stdout.write("\n%-28s %12s %12s %8s" % ("query", "with(ms)", "without(ms)", "ratio"))
            for label in before:
                b, a = before[label], after[label]
                ratio = a / b if b else float("inf")
                self.stdout.write("%-28s %12.3f %12.3f %8.2fx" % (label, b, a, ratio))

            # Roll everything back: synthetic rows AND the index drops.
            transaction.set_rollback(True)
        self.stdout.write(self.style.SUCCESS("\nrolled back (no data or schema changes persisted)"))

    def _seed(self, n_projects, n_sessions):
        user = User.objects.create_user(username=f"{BENCH_USERNAME}-{uuid_lib.uuid4().hex[:8]}")
        base = datetime(2024, 1, 1, 8, 0, tzinfo=dt_tz.utc)

        projects = [
            Projects.objects.create(user=user, name=f"Bench P{i}") for i in range(n_projects)
        ]
        subprojects = []
        for p in projects:
            for j in range(5):
                subprojects.append(
                    SubProjects.objects.create(user=user, parent_project=p, name=f"sub{j}")
                )

        sessions = []
        for i in range(n_sessions):
            start = base + timedelta(minutes=17 * i)
            sessions.append(
                Sessions(
                    user=user,
                    project=projects[i % n_projects],
                    start_time=start,
                    end_time=start + timedelta(minutes=13),
                    is_active=False,
                    uuid=uuid_lib.uuid4(),
                )
            )
        Sessions.objects.bulk_create(sessions, batch_size=2000)

        links = []
        for i, s in enumerate(sessions):
            if i % 4 == 0:
                continue  # leave some unlinked
            p_index = i % n_projects
            sub = subprojects[p_index * 5 + (i % 5)]
            links.append(SessionSubproject(session=s, subproject=sub, allocation_bp=10000))
        SessionSubproject.objects.bulk_create(links, batch_size=2000)

        # a few active timers so the partial-index scans return rows
        now = datetime.now(dt_tz.utc).replace(microsecond=0)
        for k in range(3):
            Sessions.objects.create(
                user=user,
                project=projects[k],
                start_time=now - timedelta(minutes=30 + k),
                is_active=True,
                auto_stop_at=now + timedelta(minutes=60),
                uuid=uuid_lib.uuid4(),
            )
        self.stdout.write(
            f"seeded: {n_projects} projects, {len(subprojects)} subprojects, "
            f"{n_sessions + 3} sessions, {len(links)} links"
        )
        return user

    def _queries(self, user):
        window_start = datetime(2024, 6, 1, tzinfo=dt_tz.utc)
        window_end = datetime(2024, 9, 1, tzinfo=dt_tz.utc)
        project = Projects.objects.filter(user=user).first()
        return {
            "active-scan": lambda: Sessions.objects.filter(
                user=user, end_time__isnull=True
            ).order_by("-start_time"),
            "auto-stop-scan": lambda: Sessions.objects.filter(
                user=user, end_time__isnull=True, auto_stop_at__isnull=False
            ).order_by("auto_stop_at"),
            "completed-range": lambda: Sessions.objects.filter(
                user=user,
                end_time__gte=window_start,
                end_time__lt=window_end,
            ).order_by("-end_time", "id")[:500],
            "project-range": lambda: Sessions.objects.filter(
                user=user,
                project=project,
                end_time__gte=window_start,
                end_time__lt=window_end,
            ).order_by("-end_time", "id"),
            "subproject-tally-join": lambda: SessionSubproject.objects.filter(
                session__user=user,
                session__end_time__gte=window_start,
                session__end_time__lt=window_end,
            )
            .values("subproject__name")
            .order_by("subproject__name"),
        }

    def _time_all(self, queries, runs, explain=False):
        results = {}
        for label, make_qs in queries.items():
            list(make_qs())  # warmup
            samples = []
            for _ in range(runs):
                t0 = time.perf_counter()
                list(make_qs())
                samples.append((time.perf_counter() - t0) * 1000)
            results[label] = statistics.median(samples)
            if explain:
                self.stdout.write(f"--- plan: {label}")
                self.stdout.write(make_qs().explain())
        return results
