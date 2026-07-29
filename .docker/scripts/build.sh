#!/usr/bin/env bash
set -euo pipefail

ENV_FILE=".docker/.env.production"
ROOT_COMPOSE=".docker/docker-compose.production.yaml"

compose() {
  docker compose --env-file "$ENV_FILE" -f "$ROOT_COMPOSE" "$@"
}

case "${1:-help}" in
  build)
    compose build
    ;;
  up)
    compose up -d --build
    ;;
  down)
    compose down
    ;;
  restart)
    compose down
    compose up -d --build
    ;;
  logs)
    compose logs -f --tail=200
    ;;
  ps)
    compose ps
    ;;
  migrate)
    compose exec app python manage.py migrate
    ;;
  collectstatic)
    compose exec app python manage.py collectstatic --noinput
    ;;
  cert)
    ./.docker/scripts/certbot.sh issue
    ;;
  renew)
    ./.docker/scripts/certbot.sh renew
    ;;
  help|-h|--help)
    echo "Usage: ./.docker/scripts/build.sh [build|up|down|restart|logs|ps|migrate|collectstatic|cert|renew]"
    ;;
  *)
    echo "Unknown command: $1" >&2
    exit 2
    ;;
esac
