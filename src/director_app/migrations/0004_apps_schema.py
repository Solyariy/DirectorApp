# AlterModelTable alone would emit `RENAME TO "apps"."x"`, which
# Postgres rejects, so the tables are moved with SET SCHEMA instead.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("director_app", "0003_rule_remove_registeredapp_policies_and_more"),
    ]

    operations = [
        # Both apps create the schema, so neither depends on the other.
        migrations.RunSQL(
            "CREATE SCHEMA IF NOT EXISTS apps",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterModelTable(
                    name="rule",
                    table='"apps"."director_app_rule"',
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    "ALTER TABLE public.director_app_rule SET SCHEMA apps",
                    reverse_sql="ALTER TABLE apps.director_app_rule SET SCHEMA public",
                ),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterModelTable(
                    name="policy",
                    table='"apps"."director_app_policy"',
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    "ALTER TABLE public.director_app_policy SET SCHEMA apps",
                    reverse_sql="ALTER TABLE apps.director_app_policy SET SCHEMA public",
                ),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterModelTable(
                    name="policyrulerelation",
                    table='"apps"."director_app_policyrulerelation"',
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    "ALTER TABLE public.director_app_policyrulerelation SET SCHEMA apps",
                    reverse_sql="ALTER TABLE apps.director_app_policyrulerelation SET SCHEMA public",
                ),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterModelTable(
                    name="registeredapp",
                    table='"apps"."director_app_registeredapp"',
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    "ALTER TABLE public.director_app_registeredapp SET SCHEMA apps",
                    reverse_sql="ALTER TABLE apps.director_app_registeredapp SET SCHEMA public",
                ),
            ],
        ),
    ]
