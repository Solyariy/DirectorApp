# src

## Purpose

- All application code: Django apps and shared helpers

## Ownership

- `inverter_app/` — energy system status (see child doc)
- `director_app/` — registered apps, rules, policies, policy evaluation, jobs (see child doc)
- `utils/` — shared helpers:
  - `annotations.py` — pydantic-annotated `NewType`s (`StrUUID`, `LocalFilePath`, `Timestamp`)
  - `order.py` — UTC/Kyiv `datetime` helpers, `get_uuid_str()`, `get_log_id()` (lazily sets the `LOG_ID` context var)
  - `db.py` — `APPS_SCHEMA` and `apps_table(name)`, the schema-qualified `db_table` for app models
  - `logs.py` — structlog setup; `Logger` (static `info/debug/warning/error`, adds caller name, file:line and `log_id`; ANSI colors off when `NO_COLOR` is set) and `LoggerMixin` (`log_info/log_warning/log_error` prefixed with class name)
- `settings.py` — `LOG_ID` `ContextVar` shared by logging utils (not Django settings)

## Local Contracts

- A new app is created under `src/<name>_app/`, its `AppConfig.name` is `src.<name>_app`, and it is added to `INSTALLED_APPS` and mounted under `api/` in `config/urls.py`
- Use `src.utils.logs.Logger` / `LoggerMixin` for logging instead of `print` in app code
- Import from full module paths; package `__init__.py` files stay empty
- Every app model sets `Meta.db_table = apps_table("<app>_<model>")` (`src/utils/db.py`) so its table lives in the Postgres `apps` schema; auto-created M2M tables are avoided (use an explicit through model with its own `db_table`)
- Moving an existing table between schemas needs a hand-written migration: `SeparateDatabaseAndState` with state `AlterModelTable` + db `RunSQL("ALTER TABLE ... SET SCHEMA ...")` (plain `AlterModelTable` emits invalid SQL); each app's migration creates the schema itself (`CREATE SCHEMA IF NOT EXISTS apps`) so apps stay migration-independent — see `director_app/migrations/0004_apps_schema.py`
- Cross-app imports go through an app's `models.py`, `schemas.py` or `scripts.py`; `inverter_app.inverter_service` stays private to inverter_app

## Work Guidance

- DTOs: pydantic models in a `schemas.py` next to the consuming module
- DRF serializers in the app's `serializers.py`, views as `APIView` classes in `views.py`, routes in the app's `urls.py`

## Verification

- `uv run python manage.py check`
- `pyfmt --check src` (global formatter, `~/.local/bin/pyfmt`)
- `uv run python manage.py test src.director_app src.inverter_app`

## Child DOX Index

- `director_app/AGENTS.md` — `Rule` expressions, CRUD + admin rule builder, `Policy` (`and`/`or` over rules), `PolicyRuleRelation`, `RegisteredApp` (one policy), `Job` CRUD, policy evaluation, planned `JobConsumption`
- `inverter_app/AGENTS.md` — `EnergySnapshot` ledger model, `/api/energy/` endpoints, `inverter_service/` Solarman V5 client, curtailment classification, irradiance proof of concept, snapshot collector command
