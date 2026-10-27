# DOX framework

- DOX is highly performant AGENTS.md hierarchy installed here
- Agent must follow DOX instructions across any edits

## Core Contract

- AGENTS.md files are binding work contracts for their subtrees
- Work products, source materials, instructions, records, assets, and durable docs must stay understandable from the nearest applicable AGENTS.md plus every parent AGENTS.md above it

## Read Before Editing

1. Read the root AGENTS.md
2. Identify every file or folder you expect to touch
3. Walk from the repository root to each target path
4. Read every AGENTS.md found along each route
5. If a parent AGENTS.md lists a child AGENTS.md whose scope contains the path, read that child and continue from there
6. Use the nearest AGENTS.md as the local contract and parent docs for repo-wide rules
7. If docs conflict, the closer doc controls local work details, but no child doc may weaken DOX

Do not rely on memory. Re-read the applicable DOX chain in the current session before editing.

## Update After Editing

Every meaningful change requires a DOX pass before the task is done.

Update the closest owning AGENTS.md when a change affects:

- purpose, scope, ownership, or responsibilities
- durable structure, contracts, workflows, or operating rules
- required inputs, outputs, permissions, constraints, side effects, or artifacts
- user preferences about behavior, communication, process, organization, or quality
- AGENTS.md creation, deletion, move, rename, or index contents

Update parent docs when parent-level structure, ownership, workflow, or child index changes. Update child docs when parent changes alter local rules. Remove stale or contradictory text immediately. Small edits that do not change behavior or contracts may leave docs unchanged, but the DOX pass still must happen.

## Hierarchy

- Root AGENTS.md is the DOX rail: project-wide instructions, global preferences, durable workflow rules, and the top-level Child DOX Index
- Child AGENTS.md files own domain-specific instructions and their own Child DOX Index
- Each parent explains what its direct children cover and what stays owned by the parent
- The closer a doc is to the work, the more specific and practical it must be

## Child Doc Shape

- Create a child AGENTS.md when a folder becomes a durable boundary with its own purpose, rules, responsibilities, workflow, materials, or quality standards
- Work Guidance must reflect the current standards of the project or user instructions; if there are no specific standards or instructions yet, leave it empty
- Verification must reflect an existing check; if no verification framework exists yet, leave it empty and update it when one exists

Default section order:
- Purpose
- Ownership
- Local Contracts
- Work Guidance
- Verification
- Child DOX Index

## Style

- Keep docs concise, current, and operational
- Document stable contracts, not diary entries
- Put broad rules in parent docs and concrete details in child docs
- Prefer direct bullets with explicit names
- Do not duplicate rules across many files unless each scope needs a local version
- Delete stale notes instead of explaining history
- Trim obvious statements, repeated rules, misplaced detail, and warnings for risks that no longer exist

## Closeout

1. Re-check changed paths against the DOX chain
2. Update nearest owning docs and any affected parents or children
3. Refresh every affected Child DOX Index
4. Remove stale or contradictory text
5. Run existing verification when relevant
6. Report any docs intentionally left unchanged and why

## Project

- LLM Task Director: Django + DRF service that decides whether registered home-server LLM apps may run, from policies over live solar inverter readings; README.md is the API contract
- Stack: Python 3.11+, Django 5.2, DRF, django-filter, pydantic, structlog, pysolarmanv5, pvlib (+pandas), requests; deps managed by `uv` (`pyproject.toml`, `uv.lock`)
- DB: shared Postgres 17 from `compose.yaml` (`db` service; start with `docker compose up -d db`, needed for tests too), connection from `POSTGRES_*` in `.env`; project tables in schema `apps`, Django's own in `public`; `db.sqlite3` is the legacy pre-Postgres DB, kept untouched (never delete); settings module `config.settings`
- Secrets/env: `.env` (untracked) loaded via `python-dotenv`; keys listed in `.env.example`
- Commands: `uv run python manage.py runserver`, `uv run python manage.py makemigrations`/`migrate`, `pyfmt [--check] [paths]`

## Work Guidance

- Apps live under `src/` and are registered as `src.<app>` in `config/settings.py` `INSTALLED_APPS`
- Use full-path imports (`from src.inverter_app.models import ...`); never add code to `__init__.py`
- DTOs are pydantic models in a `schemas.py` next to the module that uses them
- Style: ruff (line length 79, double quotes, PEP 8 naming, isort); `pyfmt` (global, `~/.local/bin/pyfmt`) adds trailing commas so calls/defs with >2 params go one per line; migrations are excluded
- Keep README.md endpoint docs and `docs/db-schema.mmd` in sync with models/API; re-render `docs/db-schema.png` with the mermaid-cli command in README.md
- Worktree flow: merge worktree branch into `main` locally, never push worktree branches, delete the worktree after merge

## Verification

- `uv run python manage.py check`
- `pyfmt --check` (ruff lint + format check)
- `uv run python manage.py test` (tests exist for `src.director_app` and `src.inverter_app`)

## User Preferences

When the user requests a durable behavior change, record it here or in the relevant child AGENTS.md

- Project facts and user instructions are also collected in `CLAUDE.md` "Facts"; keep both consistent
- To update the Postman collection, edit the files under `postman/` directly (v3 YAML, `postman/collections/`); do not use the Postman CLI for it
- Never connect to Postman cloud: no Postman MCP, no cloud push/publish/monitors/mocks, no Postman CLI runs (they report runs to the cloud by default); the user tests locally by opening `postman/` in the Postman app, so after changing the collection say which requests to run there; this overrides the cloud publish and CLI run steps of `postman/skills/api-builder/SKILL.md`

## Child DOX Index

- `src/AGENTS.md` — application code: Django apps, shared utils, logging, app boundaries
  - `src/director_app/AGENTS.md` — registered apps (one policy each), rules CRUD + admin rule builder, policies (writable rule links), jobs CRUD, policy evaluation
  - `src/inverter_app/AGENTS.md` — energy snapshot ledger, `/api/energy/` API, the Solarman inverter client, curtailment/irradiance proof of concept
- Owned by root (no child doc):
  - `config/` — Django project package: settings, root URLconf (`admin/`, `api/energy/` → `src.inverter_app.urls`, `api/` → `src.director_app.urls`), ASGI/WSGI
  - `docs/` — `db-schema.mmd` (Mermaid ER source of truth) and rendered `db-schema.png`
  - `postman/` — Postman workspace files; `collections/DirectorApp` is the API collection (v3 YAML, edited by hand); `specs/jobs.yaml` / `specs/rules.yaml` are the OpenAPI 3 contracts for `/api/jobs/` / `/api/rules/` (validate locally with `uvx openapi-spec-validator`, never the Postman CLI)
  - `deploy/inverter_worker/` — `inverter-worker` image: supercronic runs `collect_energy_snapshot` every `INVERTER_WORKER_CRON_CYCLE_MINUTES` minutes (crontab generated by `entrypoint.sh`) with minimal inverter_app-only settings (contract in `src/inverter_app/AGENTS.md`)
  - `manage.py`, `pyproject.toml`, `uv.lock`, `.env.example`, `README.md`, `compose.yaml` (Postgres `db` service, `inverter-worker` service)

<API_TASKS>
Before responding to any non-trivial API engineering task — designing, implementing, mocking, testing, monitoring, documenting, or deploying an API or Postman Flow — read `postman/skills/api-builder/SKILL.md` and follow it. It is the default entry point for API work in this repository. Pure questions and trivial one-line edits do not need it.
</API_TASKS>
