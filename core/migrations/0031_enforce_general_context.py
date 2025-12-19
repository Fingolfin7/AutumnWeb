from django.db import migrations


def ensure_general_context_for_orphaned_projects(apps, schema_editor):
    """Ensure every user has a 'General' Context and assign it to Projects with NULL context.

    This is important for imports/older data that predate Contexts.
    """
    User = apps.get_model('auth', 'User')
    Projects = apps.get_model('core', 'Projects')
    Context = apps.get_model('core', 'Context')

    for user in User.objects.all():
        # create per-user General context if missing
        general, _ = Context.objects.get_or_create(
            user=user,
            name='General',
            defaults={'description': 'Default context'},
        )
        Projects.objects.filter(user=user, context__isnull=True).update(context=general)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0030_assign_default_contexts'),
    ]

    operations = [
        migrations.RunPython(ensure_general_context_for_orphaned_projects, migrations.RunPython.noop),
    ]

