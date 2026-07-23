import os
from datetime import date, datetime, time, timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files import File
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFilter

from core.models import Commitment, Context, Projects, Sessions, SubProjects, Tag
from llm_insights.models import LLMChat, LLMMessage


USERNAME = "Finrod"
EMAIL = "finrod.felagund@houseoffinwe.ea"


def aware(day_offset, start_hour, start_minute, duration_minutes):
    current_day = timezone.localdate() - timedelta(days=day_offset)
    start = timezone.make_aware(datetime.combine(current_day, time(start_hour, start_minute)))
    return start, start + timedelta(minutes=duration_minutes)


def make_background(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 2400, 1500
    image = Image.new("RGB", (width, height), "#101214")
    draw = ImageDraw.Draw(image)

    for y in range(height):
        t = y / height
        r = int(14 + 34 * t)
        g = int(18 + 42 * (1 - abs(t - 0.45)))
        b = int(20 + 22 * (1 - t))
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    bands = [
        ((-220, 980), (720, 80), "#c98245"),
        ((340, 1460), (1260, 280), "#4e9a8e"),
        ((960, 1280), (2100, 160), "#b9a66a"),
        ((1400, 1550), (2600, 380), "#be675f"),
    ]
    for (x1, y1), (x2, y2), color in bands:
        draw.rounded_rectangle(
            (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)),
            radius=90,
            fill=color,
        )

    for x in range(-200, width + 200, 120):
        draw.line((x, 0, x + 620, height), fill=(255, 255, 255), width=2)

    image = image.filter(ImageFilter.GaussianBlur(18))
    veil = Image.new("RGBA", (width, height), (8, 10, 12, 45))
    image = Image.alpha_composite(image.convert("RGBA"), veil).convert("RGB")
    image.save(path, "PNG", optimize=True)


def reset_finrod():
    password = os.environ.get("FINROD_PASSWORD")
    if not password:
        raise RuntimeError(
            "Set FINROD_PASSWORD to the demo account password before seeding."
        )

    user, _ = User.objects.get_or_create(
        username=USERNAME,
        defaults={"email": EMAIL},
    )
    user.email = EMAIL
    user.set_password(password)
    user.save()

    Commitment.objects.filter(user=user).delete()
    LLMChat.objects.filter(user=user).delete()
    Sessions.objects.filter(user=user).delete()
    SubProjects.objects.filter(user=user).delete()
    Projects.objects.filter(user=user).delete()
    Context.objects.filter(user=user).exclude(name="General").delete()
    Tag.objects.filter(user=user).delete()

    general, _ = Context.objects.get_or_create(
        user=user,
        name="General",
        defaults={"description": "Everyday personal work and maintenance."},
    )
    study, _ = Context.objects.get_or_create(
        user=user,
        name="Study",
        defaults={"description": "Reading, practice, and structured learning."},
    )
    craft, _ = Context.objects.get_or_create(
        user=user,
        name="Craft",
        defaults={"description": "Creative work and long-form projects."},
    )
    health, _ = Context.objects.get_or_create(
        user=user,
        name="Health",
        defaults={"description": "Training, recovery, and outdoor time."},
    )

    tag_specs = [
        ("reading", "#7896b8"),
        ("language", "#4e9a8e"),
        ("deep-work", "#c98245"),
        ("fitness", "#7ca36a"),
        ("writing", "#b9a66a"),
    ]
    tags = {
        name: Tag.objects.create(user=user, name=name, color=color)
        for name, color in tag_specs
    }

    project_specs = [
        ("The Name of the Wind", study, ["reading"], "Close reading with chapter notes."),
        ("Czech", study, ["language"], "Vocabulary, listening, and grammar drills."),
        ("Autumn Polish", craft, ["deep-work", "writing"], "Refining the app and documentation."),
        ("Gym", health, ["fitness"], "Strength training and mobility."),
        ("Bible", study, ["reading"], "Slow reading with summaries."),
        ("Speech", craft, ["language", "deep-work"], "Voice practice and prepared delivery."),
    ]
    projects = {}
    for name, context, tag_names, description in project_specs:
        project = Projects.objects.create(
            user=user,
            name=name,
            context=context,
            description=description,
            status="active",
        )
        project.tags.add(*[tags[tag_name] for tag_name in tag_names])
        projects[name] = project

    sub_specs = [
        ("The Name of the Wind", ["Notes", "Reread"]),
        ("Czech", ["Grammar", "Listening", "Speaking"]),
        ("Autumn Polish", ["Frontend", "Docs"]),
        ("Gym", ["Strength", "Mobility"]),
        ("Bible", ["Genesis", "Psalms"]),
        ("Speech", ["Warmups", "Recording"]),
    ]
    subs = {}
    for project_name, names in sub_specs:
        for name in names:
            subs[(project_name, name)] = SubProjects.objects.create(
                user=user,
                parent_project=projects[project_name],
                name=name,
                description=f"{name} work for {project_name}.",
            )

    session_specs = [
        (0, 8, 15, 45, "Autumn Polish", ["Frontend"], "Tuned the Night Ledger theme, checked spacing, and captured README screenshots."),
        (0, 10, 30, 35, "Czech", ["Listening"], "Shadowed a short interview and collected useful phrases for review."),
        (1, 7, 20, 50, "Gym", ["Strength"], "Squats, rows, and a careful cooldown. Energy was steady."),
        (1, 14, 0, 70, "The Name of the Wind", ["Notes"], "Stopped on chapter 73. Marked a few passages about pacing and voice."),
        (2, 9, 10, 30, "Bible", ["Genesis"], "Read Genesis 18-19 and wrote a short summary."),
        (2, 19, 30, 55, "Speech", ["Recording"], "Recorded a practice take, noted breath pauses, and improved cadence."),
        (3, 8, 0, 40, "Czech", ["Grammar"], "Past tense drills, then a small translation exercise."),
        (3, 13, 45, 65, "Autumn Polish", ["Docs"], "Prepared demo data and refreshed the project README."),
        (4, 7, 10, 42, "Gym", ["Mobility"], "Mobility circuit and incline dumbbell press."),
        (4, 21, 0, 62, "The Name of the Wind", ["Reread"], "Reread earlier notes and tightened the reading backlog."),
        (5, 6, 50, 25, "Bible", ["Psalms"], "Read Psalm selections and tagged a few reflection notes."),
        (5, 20, 20, 48, "Speech", ["Warmups"], "Articulation warmups with emphasis on clarity and tempo."),
        (6, 9, 30, 75, "Autumn Polish", ["Frontend", "Docs"], "Cleaned chart sizing, profile background controls, and dark-mode README copy."),
        (7, 11, 15, 37, "Czech", ["Speaking"], "Spoken prompts with corrections on cases and word order."),
        (8, 16, 10, 58, "The Name of the Wind", ["Notes"], "Long reading session, summarized chapter structure and character beats."),
        (9, 7, 40, 45, "Gym", ["Strength"], "Deadlifts, rows, and easy accessory work."),
        (10, 18, 20, 33, "Bible", ["Genesis"], "Stopped on Genesis 24 after a focused note pass."),
        (11, 15, 5, 52, "Speech", ["Recording"], "Compared two practice takes and marked the stronger sections."),
        (12, 8, 25, 68, "Autumn Polish", ["Frontend"], "Reduced visual noise and tested dashboard interactions."),
        (13, 10, 40, 41, "Czech", ["Listening"], "Listening review and sentence mining."),
        (16, 19, 20, 80, "The Name of the Wind", ["Reread"], "Weekend reading block with notes on scene transitions."),
        (18, 8, 5, 55, "Gym", ["Strength"], "Bench, pull-downs, and steady accessory work."),
        (22, 12, 30, 90, "Autumn Polish", ["Docs"], "Outlined README sections and checked screenshots."),
        (26, 20, 0, 36, "Bible", ["Psalms"], "Short evening reading and summary."),
        (31, 9, 45, 72, "Czech", ["Grammar"], "Review of cases and plural endings."),
        (38, 13, 0, 65, "Speech", ["Warmups"], "Prepared short delivery notes and timing marks."),
    ]
    for day_offset, hour, minute, duration, project_name, sub_names, note in session_specs:
        start, end = aware(day_offset, hour, minute, duration)
        session = Sessions.objects.create(
            user=user,
            project=projects[project_name],
            start_time=start,
            end_time=end,
            note=note,
            is_active=False,
        )
        session.subprojects.add(*[subs[(project_name, sub_name)] for sub_name in sub_names])

    active_start = timezone.now() - timedelta(minutes=23)
    active = Sessions.objects.create(
        user=user,
        project=projects["Autumn Polish"],
        start_time=active_start,
        note="Drafting final README screenshot polish.",
        is_active=True,
    )
    active.subprojects.add(subs[("Autumn Polish", "Docs")])

    Commitment.objects.create(
        user=user,
        aggregation_type="project",
        project=projects["Autumn Polish"],
        commitment_type="time",
        period="weekly",
        start_date=timezone.localdate() - timedelta(days=28),
        target=180,
        balance=35,
        max_balance=360,
        min_balance=-240,
        banking_enabled=True,
        active=True,
    )
    Commitment.objects.create(
        user=user,
        aggregation_type="project",
        project=projects["Czech"],
        commitment_type="sessions",
        period="weekly",
        start_date=timezone.localdate() - timedelta(days=28),
        target=3,
        balance=1,
        max_balance=8,
        min_balance=-4,
        banking_enabled=True,
        active=True,
    )
    Commitment.objects.create(
        user=user,
        aggregation_type="tag",
        tag=tags["fitness"],
        commitment_type="time",
        period="weekly",
        start_date=timezone.localdate() - timedelta(days=28),
        target=90,
        balance=20,
        max_balance=240,
        min_balance=-120,
        banking_enabled=True,
        active=True,
    )

    profile = user.profile
    background_path = Path(settings.MEDIA_ROOT) / "background_pics" / "readme_demo_background.png"
    make_background(background_path)
    if profile.background_image.name != "background_pics/readme_demo_background.png":
        with background_path.open("rb") as handle:
            profile.background_image.save("readme_demo_background.png", File(handle), save=False)
    profile.automatic_background = False
    profile.bing_background = False
    profile.nasa_apod_background = False
    profile.background_dimming = 48
    profile.save()

    chat = LLMChat.objects.create(
        user=user,
        title="Weekly focus review",
        model="demo:readme",
        filters={
            "start_date": str(timezone.localdate() - timedelta(days=14)),
            "end_date": str(timezone.localdate()),
        },
    )
    LLMMessage.objects.create(
        chat=chat,
        role="user",
        content="What patterns stand out in the last two weeks?",
    )
    LLMMessage.objects.create(
        chat=chat,
        role="assistant",
        content=(
            "The demo data shows a steady rhythm: language practice appears in shorter "
            "daily blocks, while Autumn Polish and reading sessions cluster into longer "
            "deep-work periods. Gym sessions are less frequent but consistent enough to "
            "support the weekly fitness commitment."
        ),
        metadata={"usage": {"prompt": 420, "response": 96}},
    )

    return user


user = reset_finrod()
print(f"Seeded {user.username} ({user.email}) with demo Autumn data.")
