# LLM Task Director

## Description

**LLM Task Director** is a "dispatcher" service for a home server running local large language models (LLMs) and powered by solar panels.

Heavy background LLM work (batch text processing, building embeddings, fine-tuning, research runs) consumes a lot of electricity. The idea of the site is to let it run when energy is effectively free: the solar panels produce more than the house consumes and the battery is sufficiently charged.

What the site contains (business logic):

- **Energy system status** — current solar output, household consumption, battery charge, grid exchange, and the history of these readings.
- **Registered apps** — external applications that ask the Director whether they may run now. An app is registered manually by the operator and is assigned one policy.
- **Rules** — reusable conditions over one energy reading, managed over the API or built in the Django admin: arithmetic, comparison and logic operators over the reading's fields (solar output, battery charge, grid exchange, PV strings, weekday, local time …). A rule is True or False.
- **Policies** — named run configurations: a policy combines its rules with one logic operator (`and` / `or`) into a single True / False and caps how many of the app's jobs may run at once. Rules and policies are many-to-many; rules, policies and each policy↔rule link can be switched on and off (`is_active`). Every app has one policy; a policy can serve many apps.
- **Jobs** — LLM work items: the `model` to run, the public `data` URLs it works on, the `prompt`, and a `status` (`queued` → `in-process` → `success` / `failed`). A job may belong to a registered app. For now jobs are plain records managed over the API; nothing dispatches them yet.

## General API rules

- Base URL: `/api/`. All data is exchanged as **JSON** (`Content-Type: application/json`).
- Resources are plural nouns; actions on a resource that do not fit CRUD are sub-resources (`/apps/{id}/evaluate/`).
- Lists support pagination: `?page=1&page_size=20`. List response:
  `{"count": 42, "next": "...", "previous": null, "results": [ ... ]}`.
- Validation error: `400` + `{"field": ["message"]}`; not found: `404` + `{"detail": "Not found."}`; state conflict: `409` + `{"detail": "..."}`.
- Time is ISO 8601 (UTC), power is in watts (`W`), energy is in kWh.
- No authentication for now: every endpoint is open. Authentication will be redesigned in a future update.

## Endpoints

### Energy system status

| Method | URL | Purpose |
|---|---|---|
| GET | `/api/energy/snapshots/` | History of system readings |
| POST | `/api/energy/snapshots/` | Add a new snapshot (sent by the inverter / Home Assistant) |
| GET | `/api/energy/current/` | Current state |

**GET `/api/energy/snapshots/`**
- Parameters: `from`, `to` (datetime), `page`, `page_size`.
- Response `200`:
```json
{
  "count": 1, "next": null, "previous": null,
  "results": [
    {"id": 1, "ts": "2026-10-11T10:00:00Z", "solar_w": 3200, "load_w": 900,
     "battery_pct": 82, "grid_w": 0}
  ]
}
```

**POST `/api/energy/snapshots/`**
- Body:
```json
{"ts": "2026-10-11T10:00:00Z", "solar_w": 3200, "load_w": 900,
 "battery_pct": 82, "grid_w": 0}
```
- Response: `201` + the created object; `400` — invalid data (e.g. `battery_pct` outside 0–100).

**GET `/api/energy/current/`**
- Response `200` (or `404` if there are no snapshots yet):
```json
{"ts": "2026-10-11T10:00:00Z", "solar_w": 3200, "load_w": 900,
 "battery_pct": 82}
```

Snapshots also carry the per-string PV operating point and the battery charge limit (`pv1_voltage_v`, `pv1_current_a`, `pv1_power_w`, `pv2_*`, `battery_max_charge_current_a`; `null` on older rows). They are used to tell curtailed solar readings from ones that show the real available power. The `inverter-worker` container (`deploy/inverter_worker/`, supercronic) stores one snapshot every `INVERTER_WORKER_CRON_CYCLE_MINUTES` minutes (`.env`, default 5; values that don't divide 60 also restart at each full hour) as training data. It writes to the compose `db` service; run `migrate` from the host first:
```
docker compose up -d db inverter-worker
docker compose logs -f inverter-worker
```
`uv run python manage.py compare_pv_estimate --date YYYY-MM-DD [--csv out.csv]` is a proof of concept. It compares one day of snapshots with satellite irradiance (Open-Meteo) and the clear-sky ceiling (pvlib), and needs the `PV_SITE_*` keys from `.env.example`.

---

### Registered apps

Apps are registered manually by the operator; the app's policy decides *when* its work may run.

| Method | URL | Purpose |
|---|---|---|
| GET | `/api/apps/` | List registered apps |
| POST | `/api/apps/` | Register an app |
| GET | `/api/apps/{id}/` | Get one app |
| PUT / PATCH | `/api/apps/{id}/` | Update `name` / `description` / `policy` |
| DELETE | `/api/apps/{id}/` | Unregister an app (its policy stays) |
| GET | `/api/apps/{id}/evaluate/` | Could the app run right now (dry run, nothing is started) |

**GET `/api/apps/`**
- Parameters: `search` (by name), `page`, `page_size`.
- Response `200`: paginated list of app objects (format below).

**POST `/api/apps/`**
- Body:
```json
{"name": "doc-indexer", "description": "Nightly embeddings for the home wiki", "policy": 3}
```
- `policy` — id of the app's policy, optional (`null` until one is assigned).
- Response `201`:
```json
{"id": 4, "name": "doc-indexer", "description": "Nightly embeddings for the home wiki",
 "policy": 3, "created_at": "2026-10-11T09:00:00Z"}
```
- Errors: `400` (empty or duplicate `name`, unknown `policy`).

**GET `/api/apps/{id}/`** — `200` + app object, `404`.

**PUT / PATCH `/api/apps/{id}/`** — body as in POST (PUT needs `name`; PATCH: any subset of `name`, `description`, `policy`); `{"policy": 3}` assigns a policy, `{"policy": null}` removes it; `200` + updated object; `400` (missing, empty or duplicate `name`, unknown `policy`); `404`.

**DELETE `/api/apps/{id}/`** — `204`; `404`. The app's policy stays.

**GET `/api/apps/{id}/evaluate/`**
- Reads the inverter live (the reading is saved as an energy snapshot) and evaluates the app's policy against it; time rules use the reading's `timestamp`.
- Response `200`:
```json
{"can_run": false,
 "energy": {"timestamp": "2026-10-14T20:30:00Z", "solar_power_w": 3200, "battery_charge_pct": 82, "grid_power_w": 0, "...": "..."},
 "policy": {"policy": 3, "operator": "and", "passed": false,
            "rules": [{"rule": 1, "name": "Sunny", "passed": true},
                      {"rule": 2, "name": "Weekday daytime", "passed": false}]}}
```
- `rules` lists the policy's effective rules (rule and link both active); `passed` combines them with `operator`. A policy without effective rules does not pass.
- `can_run` is `policy.passed`. An app without an active policy returns `can_run: false` and `"policy": null`.
- Errors: `404` — the app does not exist; `503` — the inverter is unreachable.

---

### Policies

A policy combines rules into one decision and is assigned to apps (see [Registered apps](#registered-apps)). Rules are linked to a policy through its `rules` field (or on the policy page in the Django admin); see [Rules](#rules) for the rules themselves.

| Method | URL | Purpose |
|---|---|---|
| GET | `/api/policies/` | List policies |
| POST | `/api/policies/` | Create a policy |
| GET | `/api/policies/{id}/` | Get one policy |
| PUT / PATCH | `/api/policies/{id}/` | Update a policy (e.g. `{"is_active": false}`) |
| DELETE | `/api/policies/{id}/` | Delete a policy |
| GET | `/api/policies/{id}/apps/` | Apps the policy is assigned to |

| Field | Type | Meaning |
|---|---|---|
| `operator` | `and` / `or` | `and` — every effective rule must pass; `or` — one is enough. Default `and` |
| `max_concurrent_jobs` | int | Running jobs of the app at the same time (not checked until jobs are connected to apps) |
| `rules` | list | Linked rules. Written as `{"rule": <rule id>, "is_active": true}` (`is_active` optional, default `true`), read as `{"rule": {"id", "name", "is_active"}, "is_active", "effective"}`; `is_active` is the link switch, `effective` = link and rule both active |

**GET `/api/policies/`**
- Parameters: `is_active`, `search` (by name), `page`, `page_size`.
- Response `200`: paginated list of policy objects (format below).

**POST `/api/policies/`**
- Body:
```json
{"name": "Sunny weekdays", "description": "Daytime surplus only", "is_active": true,
 "operator": "and", "max_concurrent_jobs": 1, "rules": [{"rule": 1}]}
```
- `rules` is optional (no links when left out); each rule can be linked once.
- Response `201`: the same object plus `id`, `apps_count`, `rules`, `created_at`, `updated_at`:
```json
{"id": 3, "name": "Sunny weekdays", "description": "Daytime surplus only", "operator": "and",
 "is_active": true, "max_concurrent_jobs": 1, "apps_count": 0,
 "rules": [{"rule": {"id": 1, "name": "Sunny", "is_active": true}, "is_active": true, "effective": true}],
 "created_at": "2026-10-11T09:00:00Z", "updated_at": "2026-10-11T09:00:00Z"}
```
- Errors: `400` — duplicate `name`, `operator` other than `and` / `or`, `max_concurrent_jobs` below 1, an unknown or repeated rule in `rules`.

**GET `/api/policies/{id}/`** — `200` + policy object, `404`.

**PUT / PATCH `/api/policies/{id}/`** — body as in POST (PUT needs `name`; PATCH: any subset); `200` + updated object; `400`; `404`. `rules`, when sent, replaces the policy's links (`[]` removes them all; links that stay keep their `created_at`); when left out, the links stay. Setting `"is_active": false` turns the policy off for every app it is assigned to.

**DELETE `/api/policies/{id}/`** — `204`; `404`; `409` — the policy is still assigned to apps (move them to another policy first).

**GET `/api/policies/{id}/apps/`**
- Response `200`:
```json
[{"id": 4, "name": "doc-indexer"}]
```
- `404` if the policy does not exist.

---

### Jobs

Operator CRUD over jobs. The OpenAPI 3 contract is [`postman/specs/jobs.yaml`](postman/specs/jobs.yaml). Nothing runs jobs yet: `status` is set by whoever calls the API.

| Method | URL | Purpose |
|---|---|---|
| GET | `/api/jobs/` | List jobs |
| POST | `/api/jobs/` | Create a job |
| GET | `/api/jobs/{id}/` | Get one job |
| PUT / PATCH | `/api/jobs/{id}/` | Update a job (e.g. `{"status": "in-process"}`) |
| DELETE | `/api/jobs/{id}/` | Delete a job |

| Field | Type | Meaning |
|---|---|---|
| `app` | int, nullable | Registered app that owns the job; becomes `null` when the app is deleted |
| `model` | string, max 200 | LLM model name |
| `data` | list of URLs | Public `http` / `https` URLs of the job input, at least one |
| `prompt` | string | What to do with the data |
| `status` | `queued` / `in-process` / `success` / `failed` | Default `queued` |

**GET `/api/jobs/`**
- Parameters: `status`, `page`, `page_size`.
- Response `200`: paginated list of job objects, ordered by `id`; `400` — `status` is not one of the four values.

**POST `/api/jobs/`**
- Body:
```json
{"app": 4, "model": "llama3.1:8b",
 "data": ["https://example.com/docs/report.pdf"],
 "prompt": "Summarize the document in five bullet points."}
```
- Response `201`:
```json
{"id": 7, "app": 4, "model": "llama3.1:8b",
 "data": ["https://example.com/docs/report.pdf"],
 "prompt": "Summarize the document in five bullet points.", "status": "queued",
 "created_at": "2026-10-27T09:00:00Z", "updated_at": "2026-10-27T09:00:00Z"}
```
- Errors: `400` — missing or empty `model` / `prompt` / `data`, a `data` item that is not an `http(s)` URL (`{"data": {"0": ["Enter a valid URL."]}}`), unknown `status` or `app`.

**GET `/api/jobs/{id}/`** — `200` + job object, `404`.

**PUT / PATCH `/api/jobs/{id}/`** — body as in POST (PUT needs `model`, `data`, `prompt`; PATCH: any subset); `200` + updated object; `400`; `404`.

**DELETE `/api/jobs/{id}/`** — `204`; `404`.

---

### Rules

Operator CRUD over rules. The OpenAPI 3 contract is [`postman/specs/rules.yaml`](postman/specs/rules.yaml). Rules are linked to policies through the policy's `rules` field (see [Policies](#policies)). The Django admin (`/admin/director_app/rule/`) has a rule builder that lists the available fields and only offers the operators each field type allows.

| Method | URL | Purpose |
|---|---|---|
| GET | `/api/rules/` | List rules |
| POST | `/api/rules/` | Create a rule |
| GET | `/api/rules/{id}/` | Get one rule |
| PUT / PATCH | `/api/rules/{id}/` | Update a rule (e.g. `{"is_active": false}`) |
| DELETE | `/api/rules/{id}/` | Delete a rule that no policy uses |
| POST | `/api/rules/{id}/unlink/` | Remove the rule from every policy |

**GET `/api/rules/`**
- Parameters: `is_active`, `search` (by name), `page`, `page_size`.
- Response `200`: paginated list of rule objects, ordered by `id`.

**POST `/api/rules/`**
- Body (`description` and `is_active` are optional, `is_active` defaults to `true`):
```json
{"name": "Sunny", "description": "Solar output above 1.5 kW",
 "combination": {"ge": [{"field": "solar_power_w"}, 1500]}}
```
- Response `201`: the same object plus `id`, `is_active`, `created_at`, `updated_at`.
- Errors: `400` — empty or duplicate `name`, missing or invalid `combination` (`{"combination": ["and[1].ge[0].field: unknown field 'nope'"]}`).

**GET `/api/rules/{id}/`** — `200` + rule object, `404`.

**PUT / PATCH `/api/rules/{id}/`** — body as in POST (PUT needs `name` and `combination`; PATCH: any subset); `200` + updated object; `400`; `404`. A change applies to every policy the rule is linked to.

**DELETE `/api/rules/{id}/`** — `204`; `404`; `409` — the rule is linked to policies (unlink it first, so a policy's decision does not change silently).

**POST `/api/rules/{id}/unlink/`** — deletes every policy link of the rule; the rule and the policies stay. `204` (also when the rule had no links); `404`.

A rule is stored as a JSON expression tree in `combination`; every operator node is a single-key object `{"op": [arguments]}`:

| Kind | Operators | Arguments → result |
|---|---|---|
| logic | `and`, `or` (one or more conditions), `not` (one condition) | conditions → condition |
| comparison | `eq` (=), `ne` (≠), `gt` (>), `ge` (≥), `lt` (<), `le` (≤) | two values → condition |
| membership | `in` | a value and a non-empty list of constants → condition |
| arithmetic | `add` (+), `sub` (−), `mul` (×), `div` (÷) | two numbers → number |

Operands: `{"field": "<name>"}`, a number, or a string — `"HH:MM"` for time fields, ISO 8601 for `timestamp` (without an offset it is local time). The root must be a condition, every comparison must use at least one field, and both sides must have the same type (number, time or datetime). The API and the admin reject invalid rules with the path of the bad node, e.g. `and[1].ge[0].field: unknown field 'nope'`.

Fields are the fields of the energy reading (`EnergySnapshotSchema`, without `id`) plus two local-time fields; local time is the project `TIME_ZONE` (Europe/Kyiv):

| Field | Type | Meaning |
|---|---|---|
| `solar_power_w`, `load_power_w`, `grid_power_w`, `battery_power_w`, `battery_charge_pct`, `battery_voltage_v`, `grid_voltage_v` | number | Inverter reading; `grid_power_w` positive = import, `battery_power_w` negative = charging |
| `pv1_*`, `pv2_*`, `battery_max_charge_current_a` | number, may be empty | Per-string PV operating point and the battery charge limit |
| `timestamp` | datetime | When the reading was taken (absolute date windows) |
| `weekday` | number | `0` = Monday … `6` = Sunday, local time |
| `local_time` | time | Time of day, local time |

Example — weekdays, at night, both PV strings together above 2 kW, no grid import:
```json
{"and": [
  {"in": [{"field": "weekday"}, [0, 1, 2, 3, 4]]},
  {"or": [{"ge": [{"field": "local_time"}, "22:00"]},
          {"lt": [{"field": "local_time"}, "06:00"]}]},
  {"gt": [{"add": [{"field": "pv1_power_w"}, {"field": "pv2_power_w"}]}, 2000]},
  {"le": [{"field": "grid_power_w"}, 0]}
]}
```

**Missing readings fail closed.** An empty field (e.g. `pv1_voltage_v` on old snapshots) or a division by zero makes a comparison *unknown*; `not` keeps it unknown, `and` / `or` decide only when another condition settles the result, and a rule passes only when the result is exactly true.

> `solar_power_w` follows consumption (the panels curtail when nothing uses the power), so a high-solar rule can fail exactly when the battery is full and the house is idle.

## Database schema

Postgres runs in Docker (`compose.yaml`, connection settings `POSTGRES_*` in `.env`): `docker compose up -d db`, then `uv run python manage.py migrate`. Project tables live in the `apps` schema, Django's built-in tables in `public`.

![Database schema](docs/db-schema.png)

The diagram is rendered from [`docs/db-schema.mmd`](docs/db-schema.mmd):
`npx -y @mermaid-js/mermaid-cli -i docs/db-schema.mmd -o docs/db-schema.png -b white -s 2`.

Relations:
- one policy → many registered apps (`REGISTERED_APP.policy_id`, nullable; a policy cannot be deleted while apps use it);
- policies ↔ rules — many-to-many through `POLICY_RULE_RELATION` (`policy_id`, `rule_id`, unique pair). The link has its own `is_active`, and so do every rule and policy; a rule counts for a policy only when the link and the rule are active. A rule cannot be deleted over the API while it is linked;
- one registered app → many jobs (`JOB.app_id`, nullable; deleting the app keeps its jobs with `app_id` set to null);
- `ENERGY_SNAPSHOT` is standalone and append-only: every evaluation reads the inverter live, saves the reading, and evaluates the app's policy against it.
