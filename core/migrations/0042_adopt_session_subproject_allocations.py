from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0041_sessions_uuid_sessions_unique_session_uuid_per_user'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name='SessionSubproject',
                    fields=[
                        (
                            'id',
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name='ID',
                            ),
                        ),
                        (
                            'session',
                            models.ForeignKey(
                                db_column='sessions_id',
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name='subproject_links',
                                to='core.sessions',
                            ),
                        ),
                        (
                            'subproject',
                            models.ForeignKey(
                                db_column='subprojects_id',
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name='session_links',
                                to='core.subprojects',
                            ),
                        ),
                    ],
                    options={
                        'db_table': 'core_sessions_subprojects',
                        'unique_together': {('session', 'subproject')},
                    },
                ),
                migrations.AlterField(
                    model_name='sessions',
                    name='subprojects',
                    field=models.ManyToManyField(
                        related_name='sessions',
                        through='core.SessionSubproject',
                        through_fields=('session', 'subproject'),
                        to='core.subprojects',
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name='sessionsubproject',
            name='allocation_bp',
            field=models.IntegerField(db_default=10000, default=10000),
        ),
        migrations.AddConstraint(
            model_name='sessionsubproject',
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ('allocation_bp__gte', 1),
                    ('allocation_bp__lte', 10000),
                ),
                name='session_subproject_allocation_bp_range',
            ),
        ),
        migrations.AddField(
            model_name='sessions',
            name='allocation_mode',
            field=models.CharField(
                choices=[
                    ('legacy_full', 'legacy_full'),
                    ('partitioned', 'partitioned'),
                ],
                db_default='legacy_full',
                default='legacy_full',
                max_length=16,
            ),
        ),
    ]
