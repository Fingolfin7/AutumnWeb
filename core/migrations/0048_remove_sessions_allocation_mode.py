from django.db import migrations
from django.db.models import Count, Sum


def partition_legacy_sessions(apps, schema_editor):
    Sessions = apps.get_model("core", "Sessions")
    SessionSubproject = apps.get_model("core", "SessionSubproject")

    legacy_ids = list(
        Sessions.objects.filter(allocation_mode="legacy_full")
        .annotate(link_count=Count("subproject_links"))
        .filter(link_count__gte=2)
        .values_list("id", flat=True)
    )
    if legacy_ids:
        links = list(
            SessionSubproject.objects.filter(session_id__in=legacy_ids).order_by(
                "session_id", "subproject_id"
            )
        )
        links_by_session = {}
        for link in links:
            links_by_session.setdefault(link.session_id, []).append(link)
        for session_links in links_by_session.values():
            quotient, remainder = divmod(10000, len(session_links))
            for index, link in enumerate(session_links):
                link.allocation_bp = quotient + (remainder if index == 0 else 0)
        SessionSubproject.objects.bulk_update(links, ["allocation_bp"])

    overallocated = list(
        SessionSubproject.objects.values("session_id")
        .annotate(total=Sum("allocation_bp"))
        .filter(total__gt=10000)
        .values_list("session_id", flat=True)[:10]
    )
    if overallocated:
        raise RuntimeError(
            "Session allocation totals exceed 10000 basis points: "
            + ", ".join(map(str, overallocated))
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0047_remove_sessions_core_sessio_user_id_509018_idx_and_more")
    ]

    operations = [
        migrations.RunPython(partition_legacy_sessions, migrations.RunPython.noop),
        migrations.RemoveField(model_name="sessions", name="allocation_mode"),
    ]
