#!/bin/sh
# Builds the crontab from INVERTER_WORKER_CRON_CYCLE_MINUTES (.env) and
# hands over to supercronic.
set -eu

cycle="${INVERTER_WORKER_CRON_CYCLE_MINUTES:-5}"
case "$cycle" in
    '' | *[!0-9]*)
        echo "INVERTER_WORKER_CRON_CYCLE_MINUTES must be 1-59, got '$cycle'" >&2
        exit 1
        ;;
esac
if [ "$cycle" -lt 1 ] || [ "$cycle" -gt 59 ]; then
    echo "INVERTER_WORKER_CRON_CYCLE_MINUTES must be 1-59, got '$cycle'" >&2
    exit 1
fi

crontab=/tmp/crontab
echo "*/$cycle * * * * python manage.py collect_energy_snapshot" > "$crontab"

# Job output goes to stdout as-is instead of escaped inside supercronic's
# own logfmt `msg=` field
exec supercronic -passthrough-logs "$crontab"
