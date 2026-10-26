
# Home Server Executor Service: Handoff
 
*Updated: 2026-10-26 (second chat) · Purpose: LLM job executor beside the director app · Companion to `home-server-context.md` and `inverter-poller-handoff.md`*
 
## 1. Where things stand
 
- Repo read directly this chat (connected folder `DirectorApp`, branch `openapi-jobs`). Stack decisions in section 3 are **user-confirmed**. Still **no code**: next step is the OpenAPI contract.
- HEAD `be7d725 [update] remove old jobs` removed the old jobs design. Local working-tree diffs are CRLF only.
## 2. Repo facts (verified against code)
 
| Item | Detail |
|---|---|
| Project | `pyproject` name `book-store-rest-ha`; README title "LLM Task Director" |
| Python / Django | `.python-version` 3.11 → Django **5.2.18**; `uv.lock` already resolves Django 6.1.2 for Python ≥3.12 |
| REST | DRF 3.18 `APIView` classes, django-filter, pydantic DTOs in `schemas.py`, structlog `Logger` |
| Apps | `src/director_app` (Rule, Policy, PolicyRuleRelation, RegisteredApp + app-token auth, `evaluation.py`), `src/inverter_app` (EnergySnapshot ledger, `scripts.read_latest_energy_and_save()`) |
| Repo rules | apps in `src/<name>_app`, registered as `src.<name>_app`; tables in Postgres `apps` schema via `apps_table()`; each app owns migrations; cross-app imports only via `models`/`schemas`/`scripts`; never code in `__init__.py`; DOX AGENTS.md chain must be updated; CLAUDE.md "Facts"; scope discipline (only requested fields) |
| API workflow | `postman/skills/api-builder/SKILL.md`: contract first, OpenAPI spec in `postman/specs/` (none yet), collection edited by hand, never Postman cloud |
| Worker pattern | `deploy/inverter_worker/`: minimal image, own settings with one app, supercronic |
| Compose | `db` (Postgres 17, bound to 127.0.0.1:5444), `inverter-worker` |
| Kept for jobs | `Policy.max_concurrent_jobs` (not evaluated), planned `JobConsumption` |
| Auth | operator endpoints intentionally unauthenticated for now; `AppTokenAuthentication` + `IsAdmittedApp` exist for future app-facing endpoints |
 
## 3. Decisions (user-confirmed)
 
- **Topology**: `src/executor_app/` lives beside `director_app` in the same Django project on the **always-on host** and does all the work: accepts job IDs, prep (URL loading, JSON→TOON, chunking), grouping by model, **waking the PC**, sending data to the GPU, saving results, unloading and suspending the PC.
- **PC = dumb inference node**: only llama-swap with llama-server (and Strata as a `cmd`) waiting for raw data. No Django, no DB access, no workers on the PC.
- Director ↔ executor are in-process (same project): director→executor and executor→director via `scripts.py` calls (an HTTP webhook only needed for external registered apps — to confirm when designing).
- Results stay in Postgres on the host (PC never needs waking to read them; Postgres can stay localhost-bound).
- **Model downloads**: executor runs `hf download …` on the PC over SSH in the background while llama-swap serves other models.
- **Fit check**: hardware stats stored as JSON on the node record; if empty, collect once via SSH probe (`nvidia-smi`, `free`, etc.).
- **Task layer**: upgrade to **Python 3.12 + Django 6.1** and use built-in `django.tasks`; production DB backend package to adopt is likely `django-tasks-db` (Debian packages `python-django-tasks-db` 0.12.0) — confirm exact name/backend path before installing. Worker runs as its own compose container on the host.
- llama-swap config rendered by the executor from model profiles and pushed to the PC (scp); llama-swap appears to support `-watch-config` for reload — confirm on install.
- "Add director endpoint to make server load a requested model" ticket → belongs to the executor.
## 4. Still-valid design points (from first chat)
 
- Model registry (repo, file, revision, checksum, size) + profiles (runner, launch flags, resources, ctx/parallel slots, chunk params, prompt template + JSON output schema, expected load time).
- Schedule loaded model first, then group by model; concurrent requests into parallel slots; tokenizer-based chunk sizes; JSON-schema-constrained output.
- Job state machine (received → preparing → ready → waiting_for_model → running → succeeded / failed / cancelled), idempotent re-submit, chunk checkpoints, profile/prompt version stored with each result.
- TOON per-job option, measure tokens. No Celery/Redis.
## 5. Gotchas
 
- Cold model load blocks the first request (Strata 1–3 min, may freeze PC): long client timeouts; poll llama-swap `/health` after WoL.
- llama-swap `ttl: 0` never unloads: call `/unload` before suspend.
- Strata with 32 GB RAM → Coder variant only.
- Upgrading to Python 3.12: update `.python-version`, `requires-python`, `ruff target-version`, worker Dockerfile base image (`python:3.11-slim`), and the DOX docs.
- WoL must be enabled in BIOS/NIC on the PC; host needs SSH key access to the PC.
## 6. Next steps
 
- [ ] Python 3.12 / Django 6.1 upgrade (separate small change).
- [ ] OpenAPI spec for executor endpoints in `postman/specs/` (submit job IDs, job status/result, node status, pause/drain/cancel).
- [ ] Define model / profile / node / job / chunk schemas (only fields the user asks for).
- [ ] Decide webhook need for external registered apps.
- [ ] Then code.
*Sources: repo files read 2026-10-26; user decisions in chat; web research (llama-swap, Strata, Django Tasks).*