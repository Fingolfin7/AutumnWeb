"""Retire fixed credentials after clients have moved to user-consented OAuth."""
from django.db import migrations
from django.utils import timezone


def revoke_legacy_grants(apps, schema_editor):
    grants = apps.get_model("core", "MCPGrant")
    grants.objects.using(schema_editor.connection.alias).filter(
        oauth_application__isnull=True, revoked_at__isnull=True,
    ).update(revoked_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [("core", "0056_mcpaccountlink_mcpgrant_oauth_application_and_more")]
    operations = [migrations.RunPython(revoke_legacy_grants, migrations.RunPython.noop)]
