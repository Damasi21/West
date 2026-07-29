#!/usr/bin/env bash
set -euo pipefail

if [ -d /app/media_seed ]; then
  cp -an /app/media_seed/. /app/media/
fi

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"
