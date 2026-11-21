# CLAUDE.md

This file provides guidance to agents when working with code in this repository.
Read `@AGENTS.md`.

## Facts
Every time you get new information about this project, or new way of interaction with 
library/models/services, or specific instructions from user on how to test/implement new feature,
add short description of acquired knowledge here in bulleted list:
- After work is done in worktrees - merge worktree branch into HEAD locally (`git merge`); do NOT push worktree branches to remote; Delete worktree after successful merge;
- If needed DTO model - create pydantic schema in separate schemas.py file related to working module
- Never add anything to `__init__.py`. Use full-path imports.
- Repo is indexed with DOX: root `AGENTS.md` → `src/AGENTS.md` → `src/director_app/AGENTS.md`, `src/inverter_app/AGENTS.md`; update the owning AGENTS.md after meaningful changes.
- Don't add predicted-energy limits (kWh caps) to policies — job energy can't be predicted; measure actual consumption instead via planned `JobConsumption` model (inverter before/after delta or PC-reported power), later feeding an experimental recommendation system (details in `src/director_app/AGENTS.md`).
- Tests: `uv run python manage.py test src.director_app` (Django `TestCase` + plain DRF `APIClient`, no auth).
- `EnergySnapshot` is a logging/ledger model (append-only inverter read history) kept as training data for future model trainings / the recommendation system
- `inverter_app.inverter_service` (e.g. `InverterStats`, provider) never leaves inverter_app; other apps use `inverter_app.models` / `schemas.EnergySnapshotSchema` / `scripts`
- All authentication logic was removed (no auth/permission classes on `OperatorAPIView`, no app tokens / `rotate-token/`, no `RegisteredApp.token_hash` / `last_seen_at`); auth will be redesigned in a future update — don't add any unasked
- Available PV is estimated in software: Deye PV string V/I (regs 109-112) + battery charge headroom classify readings as curtailed/unconstrained (`inverter_app/curtailment.py`); Open-Meteo satellite GTI + pvlib clear-sky are a proof of concept (`compare_pv_estimate`). Follow-ups live in the Notion Feature Backlog (Home Server)
- `collect_energy_snapshot` management command, run every `INVERTER_WORKER_CRON_CYCLE_MINUTES` (`.env`, default 5) minutes by the `inverter-worker` compose service (`deploy/inverter_worker/`: `entrypoint.sh` builds the crontab at start, supercronic, image holds only `src/inverter_app` + `src/utils`, settings `worker_settings`), collects `EnergySnapshot` training data
- Conditions are `Rule`s, never new `Policy` columns: `Rule.combination` is a JSON expression tree (`{op: [args]}`, ops eq/ne/gt/ge/lt/le/in, and/or/not, add/sub/mul/div; grammar in `src/director_app/rules.py`) over `EnergySnapshotSchema` fields + `weekday`/`local_time` (`RuleContext`), built in the Django admin rule builder or sent to `/api/rules/`; `Policy.operator` (`and`/`or`) combines its rules; Rule ↔ Policy M2M via `PolicyRuleRelation`
- Each `RegisteredApp` has one `policy` (FK); a policy serves many apps
- `EnergySnapshot` model is write-only; rules read `EnergySnapshotSchema` from `read_latest_energy_and_save()` (one read per evaluation, shared by all rules of a policy)
- Rules fail closed: null reading / division by zero = unknown → rule fails (also under `not`); a policy with no effective rules fails
- To update the Postman collection, edit the files under `postman/` directly (v3 YAML, `postman/collections/`); do not use the Postman CLI for it
- Never connect to Postman cloud: no Postman MCP, no cloud push/publish/monitors/mocks, no Postman CLI runs (they report runs to the cloud by default); the user tests locally by opening `postman/` in the Postman app, so after changing the collection say which requests to run there
- DB is a shared Postgres container (`compose.yaml`, `docker compose up -d db` must run before `migrate`/tests); app tables go to schema `apps` via `Meta.db_table = apps_table(...)` (`src/utils/db.py`), Django tables stay in `public`; each app owns its migrations (developed in parallel); `db.sqlite3` is the legacy DB — never delete it
- Surplus can't be computed as `solar - load`: solar panels curtail output when nothing consumes it, so solar power reflects consumption, not availability; the `surplus_threshold_w` policy rule was removed for this reason
- The old jobs design (job types, jobs, job events, `/api/scheduler/decision/` dispatcher, defer/opportunistic/force modes, kWh estimates) was removed from README/schema as outdated; a new jobs architecture is being designed. `Policy.max_concurrent_jobs` and the `JobConsumption` idea are kept for it
- New jobs start as `director_app.Job` (`app` FK nullable/SET_NULL, `model`, `data` = list of public http(s) URLs, `prompt`, `status` queued|in-process|success|failed) with plain operator CRUD at `/api/jobs/`; its OpenAPI contract is `postman/specs/jobs.yaml` (spec first, validated with `uvx openapi-spec-validator`, no Postman CLI)
- Rules have operator CRUD at `/api/rules/` (contract `postman/specs/rules.yaml`); `DELETE` is `409` while the rule is linked to policies, `POST /api/rules/{id}/unlink/` removes all its links; policies set links through writable `rules` (`[{"rule": id, "is_active": bool}]`, replaces the links when sent)

## Scope discipline
- Implement only the fields and enums I ask for. Propose extra fields (e.g. content_type) as suggestions, and don't add them to code.
- Prefer the simplest design. Avoid caching or singletons unless I ask for them.
- When an instruction is ambiguous (e.g. 'items do leave X'), ask with AskUserQuestion instead of guessing.