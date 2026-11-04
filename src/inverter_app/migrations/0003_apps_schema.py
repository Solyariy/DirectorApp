# AlterModelTable alone would emit `RENAME TO "apps"."x"`, which
# Postgres rejects, so the tables are moved with SET SCHEMA instead.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("inverter_app", "0002_pv_strings_and_charge_limit"),
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
                    name="energysnapshot",
                    table='"apps"."inverter_app_energysnapshot"',
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    "ALTER TABLE public.inverter_app_energysnapshot SET SCHEMA apps",
                    reverse_sql="ALTER TABLE apps.inverter_app_energysnapshot SET SCHEMA public",
                ),
            ],
        ),
    ]
