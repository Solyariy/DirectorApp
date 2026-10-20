# LLM Task Director

## Description

**LLM Task Director** is a "dispatcher" service for a home server running local large language models (LLMs) and powered by solar panels.

Heavy background LLM jobs (batch text processing, building embeddings, fine-tuning, research runs) consume a lot of electricity. The idea of the site is to run them when energy is effectively free: the solar panels produce more than the house consumes and the battery is sufficiently charged. If there is not enough energy, a job waits in the queue, and it can be started by force if needed.

What the site contains (business logic):

- **Energy system status** — current solar output, household consumption, battery charge, grid exchange, and the history of these readings.
- **Job types** — kinds of work (for example "batch generation", "embeddings", "fine-tuning") with their average energy consumption and duration. These figures are refined after every completed run.
- **Jobs** — concrete tasks submitted by the user for local models. Each job has a mode:
  - `defer` — run only when there is surplus energy;
  - `opportunistic` — run on surplus, or when the deadline approaches;
  - `force` — start immediately regardless of energy.
- **Energy forecast** — before creating a job you can find out how many kWh and how much time it will likely need.
- **Registered apps** — external applications that send jobs to the Director. An app is registered manually by the operator and must be connected to at least one active policy; requests from unregistered apps, or from apps without an active policy, are rejected.
- **Rules (policies)** — reusable, named run configurations for apps: when work may run (date/time window, weekdays, daily hours), how much power the inverter must provide (solar output, battery floor, allowed grid import) and how many of the app's jobs may run at once. Policies are connected to apps many-to-many; both the policy itself and each app↔policy connection can be switched on and off (`is_active`). If an app has several active policies, work may start when **any** of them allows it.
- **Dispatcher decisions** — an explanation of why a job was started or why it is waiting, plus an event log for each job.

## General API rules

- Base URL: `/api/`. All data is exchanged as **JSON** (`Content-Type: application/json`).
- Resources are plural nouns; actions on a resource that do not fit CRUD are sub-resources (`/jobs/{id}/cancel/`).
- Lists support pagination: `?page=1&page_size=20`. List response:
  `{"count": 42, "next": "...", "previous": null, "results": [ ... ]}`.
- Validation error: `400` + `{"field": ["message"]}`; not authenticated: `401`; forbidden: `403`; not found: `404` + `{"detail": "Not found."}`; state conflict: `409` + `{"detail": "..."}`.
- Time is ISO 8601 (UTC), power is in watts (`W`), energy is in kWh.
- Access levels:
  - **operator** — the Director owner: a Django staff user, via HTTP Basic or session authentication. Only the operator manages apps and policies (`/api/apps/…`, `/api/policies/…`); apps calling these endpoints get `403`.
  - **app** — requests from registered apps carry `Authorization: Bearer <app token>` and must pass the [admission gate](#registered-apps) (`401` — app not registered, `403` — app has no active policy).

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

Snapshots also carry the per-string PV operating point and the battery charge limit (`pv1_voltage_v`, `pv1_current_a`, `pv1_power_w`, `pv2_*`, `battery_max_charge_current_a`; `null` on older rows). They are used to tell curtailed solar readings from ones that show the real available power. A cron job stores one snapshot per minute as training data:
```
* * * * * cd /path/to/repo && uv run python manage.py collect_energy_snapshot >> collector.log 2>&1
```
`uv run python manage.py compare_pv_estimate --date YYYY-MM-DD [--csv out.csv]` is a proof of concept. It compares one day of snapshots with satellite irradiance (Open-Meteo) and the clear-sky ceiling (pvlib), and needs the `PV_SITE_*` keys from `.env.example`.

---

### Job types

| Method | URL | Purpose |
|---|---|---|
| GET | `/api/job-types/` | List types |
| POST | `/api/job-types/` | Create a type |
| GET | `/api/job-types/{id}/` | Get one type |
| PUT / PATCH | `/api/job-types/{id}/` | Update a type |
| DELETE | `/api/job-types/{id}/` | Delete a type |

- POST/PUT body:
```json
{"name": "embeddings", "avg_kwh": 0.35, "avg_duration_s": 1800}
```
- Response `200`/`201`:
```json
{"id": 2, "name": "embeddings", "avg_kwh": 0.35, "avg_duration_s": 1800, "runs_count": 0}
```
- Statuses: `200` (GET, PUT, PATCH), `201` (POST), `204` (DELETE, no body), `400`, `404`, `409` — a type cannot be deleted while jobs reference it.

---

### Registered apps

**Admission gate.** A request from an app is processed **only** if the app was **manually registered** in the Director by the operator **and** is connected to at least one *effective* policy. A policy is effective for an app when both the policy and the app↔policy connection are active (`policy.is_active AND app_policy.is_active`).
- Apps cannot register themselves — there is no self-signup endpoint; all endpoints below are operator-only.
- Missing or unknown token → `401` `{"detail": "App is not registered."}`.
- Registered app without an effective policy (no connections, or all connections / connected policies inactive) → `403` `{"detail": "App has no active policy."}`. The request is rejected, not queued.
- Once the gate is passed, the app's effective policies decide *when* the work runs (it may run when **any** of them allows it).

| Method | URL | Purpose |
|---|---|---|
| GET | `/api/apps/` | List registered apps |
| POST | `/api/apps/` | Register an app (manual, operator only) |
| GET | `/api/apps/{id}/` | Get one app |
| PATCH | `/api/apps/{id}/` | Update `name` / `description` |
| DELETE | `/api/apps/{id}/` | Unregister an app (its policy connections are removed) |
| POST | `/api/apps/{id}/rotate-token/` | Issue a new token, the old one stops working |
| GET | `/api/apps/{id}/policies/` | Policies connected to the app |
| POST | `/api/apps/{id}/policies/` | Connect a policy to the app |
| PATCH | `/api/apps/{id}/policies/{policy_id}/` | Activate / deactivate a connection |
| DELETE | `/api/apps/{id}/policies/{policy_id}/` | Disconnect a policy |
| GET | `/api/apps/{id}/evaluate/` | Could the app run right now (dry run, nothing is started) |

**GET `/api/apps/`**
- Parameters: `search` (by name), `page`, `page_size`.
- Response `200`: paginated list of app objects (format below, without `token`).

**POST `/api/apps/`**
- Body:
```json
{"name": "doc-indexer", "description": "Nightly embeddings for the home wiki"}
```
- Response `201` — `token` is returned **only once**, the Director stores just its hash:
```json
{"id": 4, "name": "doc-indexer", "description": "Nightly embeddings for the home wiki",
 "token": "tdk_9f2c1e7a4b0d4c58a1e3", "active_policies_count": 0,
 "created_at": "2026-10-11T09:00:00Z", "last_seen_at": null}
```
- Errors: `400` (empty or duplicate `name`).

**GET `/api/apps/{id}/`** — `200` + app object (without `token`), `404`.

**PATCH `/api/apps/{id}/`** — body: any of `name`, `description`; `200` + updated object; `400`; `404`.

**DELETE `/api/apps/{id}/`** — `204`; `404`. The app's connections to policies are deleted, the policies themselves stay.

**POST `/api/apps/{id}/rotate-token/`**
- Body: none. Response `200`: app object with a new one-time `token`; `404`.

**GET `/api/apps/{id}/policies/`**
- Parameters: `is_active` (connection state), `effective` (`true` — both policy and connection active).
- Response `200`:
```json
[{"policy": {"id": 3, "name": "Sunny weekdays", "is_active": true},
  "is_active": true, "effective": true, "created_at": "2026-10-11T09:05:00Z"},
 {"policy": {"id": 5, "name": "Night on battery", "is_active": false},
  "is_active": true, "effective": false, "created_at": "2026-10-11T09:06:00Z"}]
```
- `404` if the app does not exist.

**POST `/api/apps/{id}/policies/`**
- Body: `{"policy": 3, "is_active": true}` (`is_active` defaults to `true`).
- Response `201`: connection object (format as in the list above).
- Errors: `400` (unknown policy); `404` (unknown app); `409` — the policy is already connected to this app.

**PATCH `/api/apps/{id}/policies/{policy_id}/`**
- Body: `{"is_active": false}`.
- Response `200`: updated connection object; `400`; `404` — the app, the policy or the connection does not exist.

**DELETE `/api/apps/{id}/policies/{policy_id}/`** — `204`; `404`.

**GET `/api/apps/{id}/evaluate/`**
- Evaluates every effective policy of the app against the latest energy snapshot and the current time.
- Response `200`:
```json
{"can_run": true, "matched_policy": 3,
 "energy": {"solar_w": 3200, "load_w": 900, "battery_pct": 82, "grid_w": 0},
 "policies": [
   {"policy": 3, "passed": true, "failed_rules": []},
   {"policy": 7, "passed": false, "failed_rules": ["time_window", "min_solar_w"]}
 ]}
```
- `can_run` is `true` when **any** effective policy passed; `matched_policy` is the first passed one (or `null`). An app without effective policies returns `can_run: false` and an empty `policies` list.
- Errors: `404` — the app does not exist or there are no energy snapshots.

---

### Jobs

| Method | URL | Purpose |
|---|---|---|
| GET | `/api/jobs/` | List jobs |
| POST | `/api/jobs/` | Put a job in the queue |
| GET | `/api/jobs/{id}/` | Job details |
| PATCH | `/api/jobs/{id}/` | Update a job (only while `queued`) |
| DELETE | `/api/jobs/{id}/` | Delete a job (only finished/cancelled) |
| POST | `/api/jobs/estimate/` | Energy and time forecast |
| POST | `/api/jobs/{id}/force-start/` | Start by force |
| POST | `/api/jobs/{id}/cancel/` | Cancel a job |
| POST | `/api/jobs/{id}/complete/` | Worker reports completion |
| GET | `/api/jobs/{id}/events/` | Job event log |

**GET `/api/jobs/`**
- Parameters: `status` (`queued|running|done|failed|cancelled`), `mode` (`defer|opportunistic|force`), `job_type` (id), `ordering` (`priority`, `-priority`, `deadline`, `created_at`), `search` (by name), `page`, `page_size`.
- Response `200`: paginated list of job objects (format below).

**POST `/api/jobs/`**
- Body:
```json
{"name": "Embed docs batch 7", "job_type": 2, "mode": "defer", "priority": 5,
 "deadline": "2026-10-12T18:00:00Z", "payload": {"model": "bge-m3", "input": "s3://docs/7"}}
```
- Response `201`:
```json
{"id": 15, "name": "Embed docs batch 7", "job_type": 2, "mode": "defer", "priority": 5,
 "status": "queued", "deadline": "2026-10-12T18:00:00Z",
 "payload": {"model": "bge-m3", "input": "s3://docs/7"},
 "predicted_kwh": 0.35, "actual_kwh": null, "reason": null,
 "created_at": "2026-10-11T10:05:00Z", "started_at": null, "finished_at": null}
```
- Errors: `400` (unknown type, invalid mode, deadline in the past).

**GET `/api/jobs/{id}/`** — `200` + job object, `404`.

**PATCH `/api/jobs/{id}/`**
- Body: any of `name`, `mode`, `priority`, `deadline`, `payload`.
- Response: `200` + updated object; `400`; `404`; `409` — the job is no longer `queued`.

**DELETE `/api/jobs/{id}/`** — `204`; `404`; `409` — the job is `queued`/`running` (cancel it first).

**POST `/api/jobs/estimate/`**
- Body: `{"job_type": 2, "payload": {"batch_size": 64}}`
- Response `200`: `{"predicted_kwh": 0.35, "predicted_duration_s": 1800, "predicted_power_w": 700}`; `400`.

**POST `/api/jobs/{id}/force-start/`**
- Body: none.
- Response `200`: job object with `status: "running"` and `reason: "forced by user"`.
- Errors: `404`; `409` — the job is not `queued`.

**POST `/api/jobs/{id}/cancel/`**
- Body: none. Response `200`: job object with `status: "cancelled"`; `404`; `409` — the job has already finished.

**POST `/api/jobs/{id}/complete/`**
- Body: `{"success": true, "actual_kwh": 0.31, "duration_s": 1650}`
- Response `200`: job object with `status: "done"` (or `"failed"`) and `actual_kwh`. The job type's averages are updated.
- Errors: `400`; `404`; `409` — the job is not `running`.

**GET `/api/jobs/{id}/events/`**
- Response `200`:
```json
[{"id": 1, "ts": "2026-10-11T10:05:00Z", "kind": "queued", "message": "Job created"},
 {"id": 2, "ts": "2026-10-11T10:06:00Z", "kind": "waiting", "message": "Surplus 300 W < required 700 W"},
 {"id": 3, "ts": "2026-10-11T11:00:00Z", "kind": "started", "message": "Surplus 2300 W, battery 82%"}]
```
- `404` if the job does not exist.

---

### Policies

A policy is a named run configuration that is connected to apps (see [Registered apps](#registered-apps)). All endpoints are operator-only.

| Method | URL | Purpose |
|---|---|---|
| GET | `/api/policies/` | List policies |
| POST | `/api/policies/` | Create a policy |
| GET | `/api/policies/{id}/` | Get one policy |
| PUT / PATCH | `/api/policies/{id}/` | Update a policy (e.g. `{"is_active": false}`) |
| DELETE | `/api/policies/{id}/` | Delete a policy |
| GET | `/api/policies/{id}/apps/` | Apps the policy is connected to |

**Policy rules.** A policy passes when **all** of its rules pass; a rule left `null` is not checked.

| Field | Type | Rule `failed_rules` name | Meaning |
|---|---|---|---|
| `active_from`, `active_until` | datetime | `date_window` | Absolute period in which the policy applies |
| `weekdays` | list of int | `weekday` | Allowed days, `0` = Monday … `6` = Sunday |
| `time_from`, `time_to` | time (`HH:MM`) | `time_window` | Daily window; `time_from > time_to` wraps over midnight (e.g. `22:00`–`06:00`) |
| `timezone` | string | — | IANA zone for `weekdays` and the daily window, default `UTC` |
| `min_solar_w` | int | `min_solar_w` | Minimum solar output from the inverter |
| `battery_floor_pct` | int | `battery_floor_pct` | Minimum battery charge, 0–100 |
| `max_grid_import_w` | int | `max_grid_import_w` | Maximum power drawn from the grid (positive `grid_w`; negative is export), `0` = none |
| `max_concurrent_jobs` | int | `max_concurrent_jobs` | Running jobs of the app at the same time (not checked until jobs are connected to apps) |

**GET `/api/policies/`**
- Parameters: `is_active`, `search` (by name), `page`, `page_size`.
- Response `200`: paginated list of policy objects (format below).

**POST `/api/policies/`**
- Body:
```json
{"name": "Sunny weekdays", "description": "Daytime surplus only", "is_active": true,
 "active_from": "2026-10-01T00:00:00Z", "active_until": null,
 "weekdays": [0, 1, 2, 3, 4], "time_from": "10:00", "time_to": "16:00", "timezone": "Europe/Kyiv",
 "min_solar_w": 1500, "battery_floor_pct": 30, "max_grid_import_w": 0,
 "max_concurrent_jobs": 1}
```
- Response `201`: the same object plus `id`, `apps_count`, `created_at`, `updated_at`.
- Errors: `400` — duplicate `name`, negative values, `battery_floor_pct` outside 0–100, `max_concurrent_jobs` below 1, `active_until` not after `active_from`, weekday outside 0–6 or an empty `weekdays` list (use `null` for every day), only one of `time_from` / `time_to` set or both equal, unknown `timezone`.

**GET `/api/policies/{id}/`** — `200` + policy object, `404`.

**PUT / PATCH `/api/policies/{id}/`** — body as in POST (PATCH: any subset); `200` + updated object; `400`; `404`. Setting `"is_active": false` turns the policy off for every connected app at once.

**DELETE `/api/policies/{id}/`** — `204`; `404`; `409` — the policy still has active connections to apps (deactivate or disconnect them first).

**GET `/api/policies/{id}/apps/`**
- Response `200`:
```json
[{"app": {"id": 4, "name": "doc-indexer"}, "is_active": true, "created_at": "2026-10-11T09:05:00Z"}]
```
- `404` if the policy does not exist.

> Connecting jobs to apps (which policy governs a job) will be added in a later step; until then the Jobs endpoints above are unchanged.

---

### Dispatcher decisions

| Method | URL | Purpose |
|---|---|---|
| GET | `/api/scheduler/decision/` | What the dispatcher would do right now (dry run, nothing is started) |

**GET `/api/scheduler/decision/`**
- Response `200`:
```json
{"energy": {"solar_w": 3200, "load_w": 900, "battery_pct": 82},
 "decisions": [
   {"job_id": 15, "decision": "START", "reason": "Solar 3200 W, battery above floor"},
   {"job_id": 16, "decision": "WAIT", "reason": "Concurrent jobs limit reached"}
 ]}
```
- `decision` ∈ `START | WAIT | FORCE_START`. `404` if there are no energy snapshots.

## Database schema

![Database schema](docs/db-schema.png)

The diagram is rendered from [`docs/db-schema.mmd`](docs/db-schema.mmd):
`npx -y @mermaid-js/mermaid-cli -i docs/db-schema.mmd -o docs/db-schema.png -b white -s 2`.

Relations:
- one job type → many jobs (`JOB.job_type_id`); one job → many events (`JOB_EVENT.job_id`);
- registered apps ↔ policies — many-to-many through `APP_POLICY` (`app_id`, `policy_id`, unique pair). The connection has its own `is_active`, and so does every policy; a policy applies to an app only when both are active;
- `ENERGY_SNAPSHOT` is standalone: the dispatcher reads the latest snapshot and evaluates it against the effective policies.
