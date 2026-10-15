"""Create a deterministic, entirely fictional demo account.

Used by the Playwright suite (``frontend/e2e``) and handy for screenshots and
local poking. Nothing here is real data, and AI features stay off for the
account so nothing ever reaches an LLM or embedding provider.
"""

from datetime import datetime, time, timedelta, timezone as dt_timezone

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import Context, Projects, SubProjects, Tag
from core.services import SessionMutationService
from core.services.commitments import CommitmentEditService

DEFAULT_USERNAME = "demo"
DEFAULT_PASSWORD = "demo-pass-123"
DEMO_EMAIL_DOMAIN = "example.com"
DEMO_TIMEZONE = "UTC"

CONTEXTS = {
    "Work": "Paid work and client projects",
    "Study": "Languages and music",
    "Personal": "Home, reading and hobbies",
}

TAGS = {
    "deep-work": "#4f7cac",
    "learning": "#7a9e7e",
    "creative": "#c47d5a",
}

# name -> (context, status, tags, description, subprojects)
PROJECTS = {
    "Garden Planner App": (
        "Work", "active", ("deep-work",),
        "A small app for planning vegetable beds.",
        ("Backend", "Frontend"),
    ),
    "Quarterly Report": (
        "Work", "complete", (),
        "Numbers and charts for the quarterly review.",
        ("Charts", "Summary"),
    ),
    "Czech Language": (
        "Study", "active", ("learning",),
        "Daily practice towards a B1 exam.",
        ("Vocabulary", "Listening", "Cases"),
    ),
    "Piano Practice": (
        "Study", "active", ("learning", "creative"),
        "Scales and a few short pieces.",
        ("Scales", "Repertoire"),
    ),
    "Home Reading": (
        "Personal", "active", ("creative",),
        "Novels and long essays.",
        ("Fiction", "Essays"),
    ),
    "Woodworking": (
        "Personal", "paused", ("creative",),
        "A workbench and some shelves, on hold until spring.",
        ("Bench", "Shelves"),
    ),
}

# project -> [(subproject names, note)]; cycled in order. Only the Czech
# notes mention "grammar", so a search for it narrows the list.
NOTES = {
    "Garden Planner App": [
        (("Backend",), "Sketched the bed layout model"),
        (("Frontend",), "Drag and drop for the bed grid"),
        (("Backend", "Frontend"), "Wired the crop list to the API"),
    ],
    "Quarterly Report": [
        (("Charts",), "Rebuilt the revenue chart"),
        (("Summary",), "Drafted the executive summary"),
    ],
    "Czech Language": [
        (("Vocabulary",), "Forty new words about the kitchen"),
        (("Cases",), "Worked through grammar drills on the dative case"),
        (("Listening",), "Slow news podcast, second pass"),
        (("Cases",), "More grammar practice, mixed cases"),
        (("Vocabulary", "Listening"), "Flashcards while walking"),
    ],
    "Piano Practice": [
        (("Scales",), "Major scales at a slower tempo"),
        (("Repertoire",), "First page of the waltz"),
    ],
    "Home Reading": [
        (("Fiction",), "Two chapters of the lighthouse novel"),
        (("Essays",), "An essay on walking"),
    ],
    "Woodworking": [
        (("Bench",), "Planed the bench top"),
        (("Shelves",), "Cut the shelf brackets"),
    ],
}

# (days ago, start hour, minutes, project): a fixed three-week rhythm.
# Done as a table so the data never depends on randomness.
SCHEDULE = []
_ACTIVE_ROTATION = (
    "Czech Language", "Garden Planner App", "Piano Practice",
    "Home Reading", "Czech Language", "Garden Planner App",
)
for _days_ago in range(1, 22):
    _busy = (_days_ago * 3) % 7  # arbitrary but fixed: five of seven days get a second session
    _primary = _ACTIVE_ROTATION[_days_ago % len(_ACTIVE_ROTATION)]
    SCHEDULE.append((_days_ago, 8, 25 + (_days_ago % 4) * 10, _primary))
    if _busy < 5:
        _second = _ACTIVE_ROTATION[(_days_ago + 2) % len(_ACTIVE_ROTATION)]
        SCHEDULE.append((_days_ago, 13, 40 + (_days_ago % 3) * 15, _second))
    if 12 <= _days_ago <= 20 and _days_ago % 2 == 0:
        SCHEDULE.append((_days_ago, 17, 35, "Woodworking"))
    if 14 <= _days_ago <= 21 and _days_ago % 3 == 0:
        SCHEDULE.append((_days_ago, 11, 50, "Quarterly Report"))


class Command(BaseCommand):
    help = "Create a deterministic fictional demo account (default: demo / demo-pass-123)."

    def add_arguments(self, parser):
        parser.add_argument("--username", default=DEFAULT_USERNAME)
        parser.add_argument("--password", default=DEFAULT_PASSWORD)
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete the user (and all its data) first, then recreate it.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Allow --reset when DEBUG is off.",
        )

    def handle(self, *args, **options):
        username = options["username"]
        if options["reset"] and not (settings.DEBUG or options["force"]):
            raise CommandError(
                "Refusing to --reset with DEBUG off. Pass --force if you really "
                "mean to delete that user."
            )

        existing = User.objects.filter(username=username).first()
        if existing is not None and not options["reset"]:
            raise CommandError(
                f"User '{username}' already exists. Pass --reset to recreate it."
            )

        with transaction.atomic():
            if existing is not None:
                existing.delete()
                self.stdout.write(f"Deleted user '{username}'.")
            user = self._create_user(username, options["password"])
            counts = self._seed(user)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded '{username}': {counts['projects']} projects, "
                f"{counts['sessions']} sessions, {counts['commitments']} commitment."
            )
        )

    def _create_user(self, username, password):
        user = User.objects.create_user(
            username=username,
            email=f"{username}@{DEMO_EMAIL_DOMAIN}",
            password=password,
        )
        profile = user.profile
        profile.timezone = DEMO_TIMEZONE
        profile.ai_features_enabled = False
        profile.save()
        return user

    def _seed(self, user):
        contexts = {
            name: Context.objects.create(user=user, name=name, description=desc)
            for name, desc in CONTEXTS.items()
        }
        tags = {
            name: Tag.objects.create(user=user, name=name, color=color)
            for name, color in TAGS.items()
        }

        now = timezone.now()
        projects = {}
        subprojects = {}
        for name, (context, status, tag_names, description, subs) in PROJECTS.items():
            project = Projects.objects.create(
                user=user,
                name=name,
                status=status,
                description=description,
                context=contexts[context],
                start_date=now - timedelta(days=30),
            )
            project.tags.set([tags[t] for t in tag_names])
            projects[name] = project
            for sub in subs:
                subprojects[(name, sub)] = SubProjects.objects.create(
                    user=user,
                    name=sub,
                    parent_project=project,
                    start_date=now - timedelta(days=30),
                )

        cursor = {name: 0 for name in NOTES}
        sessions = 0
        today = now.astimezone(dt_timezone.utc).date()
        for days_ago, hour, minutes, project_name in SCHEDULE:
            sub_names, note = NOTES[project_name][cursor[project_name] % len(NOTES[project_name])]
            cursor[project_name] += 1
            start = datetime.combine(
                today - timedelta(days=days_ago), time(hour, 0), tzinfo=dt_timezone.utc
            )
            SessionMutationService.create_session(
                user=user,
                project=projects[project_name],
                subprojects=[subprojects[(project_name, s)] for s in sub_names],
                start_time=start,
                end_time=start + timedelta(minutes=minutes),
                note=note,
            )
            sessions += 1

        CommitmentEditService.create(
            user,
            {
                "aggregation_type": "project",
                "project": projects["Czech Language"],
                "commitment_type": "time",
                "period": "weekly",
                "target": 180,
                "start_date": today - timedelta(days=21),
                "timezone": DEMO_TIMEZONE,
            },
        )
        return {"projects": len(projects), "sessions": sessions, "commitments": 1}
