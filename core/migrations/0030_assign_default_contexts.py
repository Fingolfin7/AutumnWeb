from django.db import migrations


def assign_default_contexts(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    Projects = apps.get_model('core', 'Projects')
    Context = apps.get_model('core', 'Context')

    for user in User.objects.all():
        user_projects = Projects.objects.filter(user=user, context__isnull=True)
        if not user_projects.exists():
            continue

        ctx, _ = Context.objects.get_or_create(
            user=user,
            name='General',
            defaults={'description': 'Default context for existing projects'},
        )
        user_projects.update(context=ctx)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0029_context_tag_models'),
    ]

    operations = [
        migrations.RunPython(assign_default_contexts, migrations.RunPython.noop),
    ]


