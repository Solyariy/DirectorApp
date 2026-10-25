"""
Minimal Django settings for the inverter-worker container.

Only `src.inverter_app` is installed: the worker runs
`collect_energy_snapshot` and must not load director_app, DRF or admin.
Selected with DJANGO_SETTINGS_MODULE=worker_settings (copied into the
image as /app/worker_settings.py).
"""

import os

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "inverter-worker-no-http")

DEBUG = False

INSTALLED_APPS = [
    "src.inverter_app",
]

# Same shared Postgres as config/settings.py; inside compose POSTGRES_HOST
# is the `db` service and POSTGRES_PORT the in-container 5432.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB"),
        "USER": os.getenv("POSTGRES_USER"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD"),
        "HOST": os.getenv("POSTGRES_HOST", "db"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}

TIME_ZONE = "Europe/Kyiv"

USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
