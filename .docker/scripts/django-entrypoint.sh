#!/usr/bin/env bash
set -euo pipefail

if [ "${RUN_DJANGO_SETUP:-True}" != "False" ]; then
  if [ -d /app/media_seed ]; then
    cp -rn /app/media_seed/. /app/media/
  fi

  python manage.py migrate --noinput
  python manage.py collectstatic --noinput
fi

exec "$@"
