# director_app

## Purpose

- README domain, mounted at `api/` in `config/urls.py`
- Implemented: registered apps (one policy each), policies, rules (admin-only), policy evaluation (`/api/apps/…`, `/api/policies/…`, `/admin/director_app/…`)
- Not yet: jobs (old job types / jobs / job events / dispatcher design removed; new design pending), `JobConsumption`

## Ownership

- `models.py`:
  - `Rule` — `name` (unique), `description`, `combination` (JSON expression, `validators=[validate_combination]`), `is_active`; `passed(energy=None) -> bool` (`evaluate(...) is True`)
  - `Policy` — `operator` (`Policy.Operator`: `and` / `or`), `is_active`, `max_concurrent_jobs`, `rules` M2M through `PolicyRuleRelation`; `effective_rules()` (rule and link active, by id), `combine(results)`, `passed(energy=None)`; `with_counts()` annotates `apps_count` and re-applies `order_by("id")`
  - `PolicyRuleRelation` — unique `(policy, rule)`, own `is_active`, `effective` = link and rule active; related names `rule_relations` / `policy_relations`
  - `RegisteredApp` — `token_hash` = sha256 of a `tdk_…` token (`generate_token()` / `hash_token()`); plain token shown once on create / rotate; `last_seen_at`; `policy` FK (nullable, `PROTECT`, reverse `apps`); `effective_policy` = the policy when set and active
- `rules.py` — the rule engine:
  - `OPERATORS` (`Operator(kind, symbol, types, func)`): logic `and`/`or`/`not`, comparison `eq`/`ne`/`gt`/`ge`/`lt`/`le`, membership `in`, arithmetic `add`/`sub`/`mul`/`div`
  - `rule_fields()` (cached) — operands from `RuleContext` fields + computed fields, without `id`; type from the annotation (int/float → number, `datetime`, `time`; `X | None` → nullable)
  - `catalog()` (fields + operators for the admin widget), `validate_combination()` (Django `ValidationError` with node paths like `and[1].ge[0]`), `evaluate()` (three-valued: True / False / None), `describe()` (readable text)
- `schemas.py` — `RuleContext(EnergySnapshotSchema)` adds computed `weekday` (0 = Mon) and `local_time` from `timestamp` in `settings.TIME_ZONE`, `from_energy()`; DTOs `RuleEvaluation`, `PolicyEvaluation` (`policy`, `operator`, `passed`, `rules`), `AppEvaluation` (`can_run`, `energy`, `policy`)
- `evaluation.py` — `evaluate_policy(policy, energy)` (each effective rule once, `policy.combine()`), `evaluate_app(app, energy)` (`policy: None`, `can_run: False` without an effective policy)
- `admin.py` — `RuleAdmin` (builder widget on `combination`, `RulePolicyInline`), `PolicyAdmin` (`PolicyRuleInline` with rule autocomplete and a readable expression column)
- `widgets.py` — `RuleCombinationWidget(Textarea)`: template `templates/director_app/widgets/rule_combination.html`, catalog via `json_script`, media `static/director_app/rule_builder.js` / `.css`
- `static/director_app/rule_builder.js` — vanilla JS builder: ALL/ANY groups, NOT toggle, conditions (field / value / calculation operands, ops filtered by type, list for `in`), live preview mirroring `describe()`; the JSON textarea (under "JSON") stays the form value and is editable by hand
- `authentication.py`:
  - `AppTokenAuthentication` — `Authorization: Bearer <token>` → `request.auth` = app, `request.user` = `AnonymousUser`; updates `last_seen_at`
  - `IsAdmittedApp` — admission gate for future app-facing endpoints: `401` not registered, `403` no effective policy
- `serializers.py` — `PolicySerializer` (`rules` read-only from `rule_relations`), `PolicyRuleSerializer`, `RuleBriefSerializer`, `RegisteredAppSerializer` (writable nullable `policy` pk), `AppBriefSerializer`
- `views.py` / `urls.py`:
  - `OperatorAPIView` base (no auth for now) — `get_or_404()`, `parse_bool()`, `paginate()` (`DirectorPagination`: `page_size` 20, max 100)
  - `apps/` (list `search`, create → token), `apps/<id>/` (get/patch incl. `policy`/delete), `apps/<id>/rotate-token/`
  - `apps/<id>/evaluate/` — live inverter read via `inverter_app.scripts.read_latest_energy_and_save()` (persists an `EnergySnapshot`), returns `AppEvaluation`; `503` on `ConnectionError`
  - `policies/` (list `is_active`/`search`, create), `policies/<id>/` (get/put/patch; delete `409` while apps use it), `policies/<id>/apps/` (`[{id, name}]`)
- `tests.py` — `RegisteredAppTests`, `PolicyTests`, `EvaluateTests`, `RuleEngineTests`, `PolicyModelTests`, `RuleAdminTests`; no auth tests while auth is off
- `migrations/` — Django-generated; do not hand-edit

## Local Contracts

- Operator endpoints subclass `OperatorAPIView`; authentication is intentionally off for now (no auth/permission classes, DRF default `AllowAny`); staff-only access returns in a future update, so don't add auth until then
- Future app-facing endpoints (once auth returns) use `authentication_classes = [AppTokenAuthentication]` + `permission_classes = [IsAdmittedApp]`
- Import only `inverter_app.models`, `inverter_app.schemas`, `inverter_app.scripts` from inverter_app; never `inverter_app.inverter_service`
- New conditions are rules, never new `Policy` columns: a rule is an expression over `RuleContext` fields; a policy only combines rules with `and` / `or`
- `combination` grammar: every node is `{op: [args]}`; operands are `{"field": name}`, numbers, or strings (`HH:MM` time / ISO 8601 datetime, naive = local) typed by the other side; root is a condition, comparisons need a field and matching types, `in` takes a non-empty constant list, arithmetic is numbers only
- Rules read `EnergySnapshotSchema` (from `read_latest_energy_and_save()`), never the `EnergySnapshot` model (write-only ledger) or snapshot history; `Rule.passed()` / `Policy.passed()` read live only when no energy is passed, and a policy passes one reading to all its rules
- Fail closed: a null reading or division by zero is unknown, `not` keeps it unknown, a rule passes only on True, and a policy without effective rules does not pass
- Fields appear in the rule catalog by being on `RuleContext` / `EnergySnapshotSchema` with a number, `time` or `datetime` type; local time is `settings.TIME_ZONE` (no per-policy time zone)
- Rules have no REST endpoints (admin only); the policy API lists them read-only
- One policy per app (`RegisteredApp.policy`); a policy serves many apps and can't be deleted while apps use it
- `EnergySnapshot` is a logging/ledger record (one row per inverter read, incl. every `evaluate/` call), kept as training history for the future recommendation system
- `grid_power_w`: positive = grid import, negative = export
- No surplus rule: panels curtail output when nothing consumes it, so `solar - load` does not show available power; don't add `surplus_threshold_w`-style rules back
- `parse_bool()` accepts `true`/`false`/`1`/`0` (case-insensitive), anything else → `400`
- `max_concurrent_jobs` is stored but not evaluated; kept for the new jobs design
- Policies have no predicted-energy limits (no `max_job_kwh`, `daily_budget_kwh`, `max_force_kwh`): job energy can't be predicted reliably; energy figures come from measured `JobConsumption` history
- Planned model `JobConsumption` — measured energy of one job run, one row per run:
  - links to a run in the new jobs design (and to its `app`), `started_at`, `finished_at`
  - `method`: `inverter_delta` (household load from `EnergySnapshot` ledger during the run minus the baseline before start; noisy, other loads leak in) or `host_reported` (power reported by the PC itself, e.g. GPU/CPU sensors)
  - `energy_wh`, `avg_power_w`, `peak_power_w`, `baseline_load_w`, `sample_count`; `host_metrics` JSON for raw PC data
  - Experimental follow-up: a recommendation system trained on `JobConsumption` + `EnergySnapshot` history that suggests run windows, policy thresholds and PC load settings (batch size, power cap) to balance PC and inverter load

## Work Guidance

- Tests: Django `TestCase` + plain DRF `APIClient` (`OperatorTestCase`, no authentication); add auth / admission-gate tests back together with auth
- Tests touching `evaluate/` must not hit the real inverter; `EvaluateTests.read_energy()` patches `src.director_app.views.read_latest_energy_and_save`; `Policy.passed()` / `Rule.passed()` without energy read through `src.director_app.models.read_latest_energy_and_save`
- The builder JS has no test runner; check it in a browser (admin `/admin/director_app/rule/add/`) after changing it

## Verification

- `uv run python manage.py test src.director_app`

## Child DOX Index

- None
