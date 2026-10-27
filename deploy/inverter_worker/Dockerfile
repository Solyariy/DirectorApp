# Inverter snapshot worker: only inverter_app + src/utils, scheduled by
# supercronic. Build from the repo root:
#   docker compose build inverter-worker

FROM python:3.11-slim AS deps

COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv

WORKDIR /build
COPY pyproject.toml uv.lock ./
# uv.lock pins the versions; only the worker's runtime deps are installed
RUN uv export --frozen --no-dev --no-hashes --no-emit-project \
        -o constraints.txt \
 && uv pip install --system --no-cache -c constraints.txt \
        django "psycopg[binary]" pysolarmanv5 pydantic structlog dotenv


FROM python:3.11-slim

ARG TARGETARCH
ARG SUPERCRONIC_VERSION=v0.2.49
ARG SUPERCRONIC_SHA1SUM_amd64=e63c11a9726b775a6a11801e81af4f3fb926aa68
ARG SUPERCRONIC_SHA1SUM_arm64=0b6c5bb743e0b0dafed1132198c81807927ac413

ADD https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${TARGETARCH} /usr/local/bin/supercronic
RUN if [ "$TARGETARCH" = "arm64" ]; then \
        sum="$SUPERCRONIC_SHA1SUM_arm64"; \
    else \
        sum="$SUPERCRONIC_SHA1SUM_amd64"; \
    fi \
 && echo "${sum}  /usr/local/bin/supercronic" | sha1sum -c - \
 && chmod +x /usr/local/bin/supercronic

COPY --from=deps /usr/local/lib/python3.11/site-packages \
    /usr/local/lib/python3.11/site-packages

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NO_COLOR=1 \
    DJANGO_SETTINGS_MODULE=worker_settings

WORKDIR /app
COPY manage.py ./
COPY src/__init__.py src/settings.py src/
COPY src/utils src/utils
COPY src/inverter_app src/inverter_app
COPY deploy/inverter_worker/settings.py worker_settings.py
COPY deploy/inverter_worker/entrypoint.sh entrypoint.sh

RUN useradd --system --no-create-home worker
USER worker

# Schedule from INVERTER_WORKER_CRON_CYCLE_MINUTES, see entrypoint.sh
CMD ["/app/entrypoint.sh"]
