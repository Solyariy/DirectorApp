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
  - `force` — start immediately regardless of energy (within a limit).
- **Energy forecast** — before creating a job you can find out how many kWh and how much time it will likely need.
- **Rules (policy)** — minimum battery charge, surplus power threshold, maximum energy for a forced start, limit of concurrent jobs.
- **Dispatcher decisions** — an explanation of why a job was started or why it is waiting, plus an event log for each job.

## General API rules

- Base URL: `/api/`. All data is exchanged as **JSON** (`Content-Type: application/json`).
- Resources are plural nouns; actions on a resource that do not fit CRUD are sub-resources (`/jobs/{id}/cancel/`).
- Lists support pagination: `?page=1&page_size=20`. List response:
  `{"count": 42, "next": "...", "previous": null, "results": [ ... ]}`.
- Validation error: `400` + `{"field": ["message"]}`; not found: `404` + `{"detail": "Not found."}`; state conflict: `409` + `{"detail": "..."}`.
- Time is ISO 8601 (UTC), power is in watts (`W`), energy is in kWh.

## Endpoints

### Energy system status

| Method | URL | Purpose |
|---|---|---|
| GET | `/api/energy/snapshots/` | History of system readings |
| POST | `/api/energy/snapshots/` | Add a new snapshot (sent by the inverter / Home Assistant) |
| GET | `/api/energy/current/` | Current state and computed surplus |

**GET `/api/energy/snapshots/`**
- Parameters: `from`, `to` (datetime), `page`, `page_size`.
- Response `200`:
```json
{
  "count": 1, "next": null, "previous": null,
  "results": [
    {"id": 1, "ts": "2026-10-11T10:00:00Z", "solar_w": 3200, "load_w": 900,
     "battery_pct": 82, "grid_w": 0, "source": "victron"}
  ]
}
```

**POST `/api/energy/snapshots/`**
- Body:
```json
{"ts": "2026-10-11T10:00:00Z", "solar_w": 3200, "load_w": 900,
 "battery_pct": 82, "grid_w": 0, "source": "victron"}
```
- Response: `201` + the created object; `400` — invalid data (e.g. `battery_pct` outside 0–100).

**GET `/api/energy/current/`**
- Response `200` (or `404` if there are no snapshots yet):
```json
{"ts": "2026-10-11T10:00:00Z", "solar_w": 3200, "load_w": 900,
 "battery_pct": 82, "surplus_w": 2300, "has_surplus": true}
```

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
- Errors: `404`; `409` — the job is not `queued`; `422` — predicted energy exceeds `max_force_kwh` from the policy.

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

### Policy and dispatcher decisions

| Method | URL | Purpose |
|---|---|---|
| GET | `/api/policy/` | Current rules |
| PUT | `/api/policy/` | Update rules |
| GET | `/api/scheduler/decision/` | What the dispatcher would do right now (dry run, nothing is started) |

**GET `/api/policy/`** — `200`:
```json
{"surplus_threshold_w": 500, "battery_floor_pct": 30, "max_force_kwh": 2.0, "max_concurrent_jobs": 1}
```

**PUT `/api/policy/`** — body as above; `200` + updated policy; `400` (negative values, `battery_floor_pct` outside 0–100).

**GET `/api/scheduler/decision/`**
- Response `200`:
```json
{"energy": {"solar_w": 3200, "load_w": 900, "battery_pct": 82, "surplus_w": 2300},
 "decisions": [
   {"job_id": 15, "decision": "START", "reason": "Surplus 2300 W >= required 700 W, battery above floor"},
   {"job_id": 16, "decision": "WAIT", "reason": "Concurrent jobs limit reached"}
 ]}
```
- `decision` ∈ `START | WAIT | FORCE_START`. `404` if there are no energy snapshots.

## Database schema

![Database schema](docs/db-schema.png)

Relations: one job type → many jobs (`JOB.job_type_id`); one job → many events (`JOB_EVENT.job_id`). The `ENERGY_SNAPSHOT` and `POLICY` tables are standalone: the dispatcher reads the latest snapshot and the single policy row to make its decision.
