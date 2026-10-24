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
- Tests: `uv run python manage.py test src.director_app` (Django `TestCase` + plain DRF `APIClient`, no auth; auth tests were removed while auth is disabled).
- `EnergySnapshot` is a logging/ledger model (append-only inverter read history) kept as training data for future model trainings / the recommendation system
- `inverter_app.inverter_service` (e.g. `InverterStats`, provider) never leaves inverter_app; other apps use `inverter_app.models` / `schemas.EnergySnapshotSchema` / `scripts`
- Authentication on operator endpoints is intentionally disabled for now (`OperatorAPIView` has no auth/permission classes); it will be brought back in a future update — don't re-add it unasked
- Available PV is estimated in software: Deye PV string V/I (regs 109-112) + battery charge headroom classify readings as curtailed/unconstrained (`inverter_app/curtailment.py`); Open-Meteo satellite GTI + pvlib clear-sky are a proof of concept (`compare_pv_estimate`). Follow-ups live in the Notion Feature Backlog (Home Server)
- `collect_energy_snapshot` management command, run from cron every minute, collects `EnergySnapshot` training data
- Conditions are `Rule`s, never new `Policy` columns: `Rule.combination` is a JSON expression tree (`{op: [args]}`, ops eq/ne/gt/ge/lt/le/in, and/or/not, add/sub/mul/div; grammar in `src/director_app/rules.py`) over `EnergySnapshotSchema` fields + `weekday`/`local_time` (`RuleContext`), built in the Django admin rule builder; `Policy.operator` (`and`/`or`) combines its rules; Rule ↔ Policy M2M via `PolicyRuleRelation`; rules have no REST API
- Each `RegisteredApp` has one `policy` (FK); a policy serves many apps
- `EnergySnapshot` model is write-only; rules read `EnergySnapshotSchema` from `read_latest_energy_and_save()` (one read per evaluation, shared by all rules of a policy)
- Rules fail closed: null reading / division by zero = unknown → rule fails (also under `not`); a policy with no effective rules fails
- To update the Postman collection, edit the files under `postman/` directly (v3 YAML, `postman/collections/`); do not use the Postman CLI for it
- Never connect to Postman cloud: no Postman MCP, no cloud push/publish/monitors/mocks, no Postman CLI runs (they report runs to the cloud by default); the user tests locally by opening `postman/` in the Postman app, so after changing the collection say which requests to run there
- Surplus can't be computed as `solar - load`: solar panels curtail output when nothing consumes it, so solar power reflects consumption, not availability; the `surplus_threshold_w` policy rule was removed for this reason
