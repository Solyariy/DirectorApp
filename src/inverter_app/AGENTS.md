# inverter_app

## Purpose

- Energy system status: reads the solar inverter over LAN, stores readings as `EnergySnapshot`, exposes them under `/api/energy/`
- `EnergySnapshot` is a logging/ledger model: append-only history of every inverter read, kept as training data for the future recommendation system (with `JobConsumption`, see `src/director_app/AGENTS.md`)

## Ownership

- `models.py` — `EnergySnapshot` (`timestamp`, `solar_power_w`, `load_power_w`, `grid_power_w`, `battery_power_w`, `battery_charge_pct`, `battery_voltage_v`, `grid_voltage_v`; nullable `pv1_/pv2_voltage_v`, `_current_a`, `_power_w`, `battery_max_charge_current_a` — null on rows recorded before they were read)
- `serializers.py` — `EnergySnapshotSerializer` (all fields)
- `schemas.py` — `EnergySnapshotSchema` (pydantic, `from_attributes`): DTO other apps use for snapshots; `PvSiteSchema` (array location, tilt, compass azimuth, peak W, performance ratio)
- `curtailment.py` — `classify(snapshot, mpp_voltages) -> PvState` (`dark` / `unconstrained` / `curtailed` / `unknown`) and `estimate_mpp_voltages(snapshots)`: per-string reference MPP voltage = median voltage while the battery had headroom. Unconstrained = battery charging below 90% of its limit and < 95% SOC, or strings at MPP voltage; curtailed = string voltage > 1.08 × reference (Deye moves toward Voc when curtailing). Thresholds are proof-of-concept constants
- `irradiance.py` — proof of concept: `get_pv_site()` (`PV_SITE_*` env, read lazily, `ImproperlyConfigured` if missing), `fetch_satellite_gti()` (Open-Meteo Satellite Radiation API, `global_tilted_irradiance_instant`, native 10-15 min, UTC), `clear_sky_gti()` (pvlib Ineichen → plane of array), `gti_to_power_w()`
- `management/commands/`:
  - `collect_energy_snapshot` — one inverter read → `EnergySnapshot`; exits non-zero when the inverter is unreachable. Run every `INVERTER_WORKER_CRON_CYCLE_MINUTES` minutes (`.env`, 1-59, default 5) by the `inverter-worker` compose service (`deploy/inverter_worker/`; `entrypoint.sh` validates it and writes the crontab at container start, so a change needs only `docker compose up -d inverter-worker`)
  - `compare_pv_estimate --date --reference-days --csv` — one day of snapshots vs satellite estimate and clear-sky ceiling; calibrates the performance ratio on unconstrained rows, reports bias/MAE and estimated unused PV while curtailed
- `scripts.py` — `read_latest_energy_and_save()`: live read + persisted `EnergySnapshot`; entry point for other apps
- `views.py` / `urls.py`:
  - `GET snapshots/` — newest first, `from`/`to` ISO 8601 filters (`400` on bad datetime), `PageNumberPagination` (`page_size` 20, max 100)
  - `POST snapshots/` — create snapshot, `201`
  - `GET current/` — live read from inverter via `scripts.read_latest_energy_and_save()`, persists and returns the snapshot; `503` when inverter unreachable (`OSError`, `V5FrameError`, `NoSocketAvailableError`)
- `inverter_service/`:
  - `settings.py` — `INVERTER_LOGGER_IP`, `INVERTER_LOGGER_SERIAL` from `.env`
  - `manager.py` — `InverterManager` context manager over `PySolarmanV5` (port 8899); reads holding registers 150-210 and 109-112 and maps them to `InverterStats` dataclass (signed 16-bit for grid/battery power). Deye hybrid map: 109/110 PV1 V/A ×0.1, 111/112 PV2, 186/187 PV1/PV2 W, 190 battery W (negative = charging), 210 battery max charge current A (211 is the discharge limit)
  - `provider.py` — `get_inverter_manager()`: lock-serialized connection (logger handles few clients); views must use this, not `InverterManager` directly
  - `detector.py` — standalone UDP broadcast script (`WIFIKIT-214028-READ` to port 48899) to discover the logger IP/serial; needs `DEVICE_LAN_IP`, `BROADCAST`
- `migrations/` — Django-generated; do not hand-edit

## Local Contracts

- The `inverter-worker` image (`deploy/inverter_worker/Dockerfile`) contains only `src/inverter_app`, `src/utils`, `src/settings.py` and deps django/psycopg/pysolarmanv5/pydantic/structlog/dotenv, with `deploy/inverter_worker/settings.py` (`INSTALLED_APPS = ["src.inverter_app"]`): code loaded by `collect_energy_snapshot` must not import director_app, DRF, pandas or pvlib; new runtime deps of that path go into the Dockerfile install list. Other commands (`compare_pv_estimate`) don't run in the worker
- Treat `EnergySnapshot` rows as ledger entries: create, never update; any live read that matters is persisted (`scripts.read_latest_energy_and_save()`)
- `inverter_service` types (`InverterStats`, provider) must not be imported outside inverter_app; expose `EnergySnapshot` / `EnergySnapshotSchema` instead
- `EnergySnapshotSchema` fields with a number, `time` or `datetime` type are director_app rule fields automatically (`director_app.rules.rule_fields()`); renaming or removing one makes stored rules that read it evaluate as unknown (fail)
- `InverterStats` field names must match `EnergySnapshot` fields: `current/` does `EnergySnapshot.objects.create(**asdict(stats))`
- Register mapping changes belong in `InverterManager._format_registers_response`
- `inverter_service/settings.py` runs `int(os.getenv("INVERTER_LOGGER_SERIAL"))` at import; since `views.py` imports the provider, a missing `.env` key breaks Django startup
- Implementation field names and the `current/` error code (`503`) differ from README.md (`ts`, `solar_w`, `load_w`, `battery_pct`, `grid_w`; `404`); reconcile one or the other when touching this API

## Work Guidance

- Open-Meteo azimuth is 0 = south (±180 north); pvlib and `PV_SITE_AZIMUTH_DEG` use compass 180 = south — `fetch_satellite_gti` converts. Satellite data lags real time (~20 min for MTG, up to hours), so it suits backfill/analysis, not live decisions
- `solar - load` is not surplus: panels curtail output when nothing consumes it, so `solar_power_w` shows used power, not available power; don't compute `surplus_w` from it
- `EnergySnapshot.timestamp` uses `auto_created=True` (not `auto_now_add`), so callers must set it explicitly

## Verification

- `uv run python manage.py check`
- Live check needs the inverter on LAN: `uv run python -m src.inverter_app.inverter_service.manager`
- `uv run python manage.py test src.inverter_app` — curtailment classification, register mapping, both management commands (inverter and Open-Meteo mocked)

## Child DOX Index

- None
