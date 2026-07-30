#!/usr/bin/env bash
set -euo pipefail

ENV_FILE=".docker/.env.production"
ROOT_COMPOSE=".docker/docker-compose.production.yaml"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE. Create it from .docker/.env.example first." >&2
  exit 2
fi

set -a
. "$ENV_FILE"
set +a

compose() {
  docker compose --env-file "$ENV_FILE" -f "$ROOT_COMPOSE" "$@"
}

is_ip_address() {
  case "${1:-}" in
    *:*)
      return 0
      ;;
  esac

  printf "%s" "${1:-}" | grep -Eq '^([0-9]{1,3}\.){3}[0-9]{1,3}$'
}

cert_exists() {
  docker run --rm \
    -v WESTWISE_CERTBOT_CONF:/etc/letsencrypt \
    alpine \
    test -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
}

issue_certificate() {
  local force="${1:-}"

  if [ -z "${DOMAIN:-}" ] || [ "${DOMAIN:-}" = "localhost" ] || is_ip_address "${DOMAIN:-}"; then
    echo "Skipping certificate issuance because DOMAIN is not a public DNS name."
    return 0
  fi

  if [ -z "${EMAIL:-}" ]; then
    echo "EMAIL is required to issue a certificate." >&2
    exit 2
  fi

  if [ "$force" != "force" ] && cert_exists; then
    echo "Certificate already exists for $DOMAIN; skipping issuance."
    return 0
  fi

  compose down >/dev/null 2>&1 || true

  docker run --rm \
    -p "${PROXY_HTTP_PORT:-80}:80" \
    -v WESTWISE_CERTBOT_CONF:/etc/letsencrypt \
    certbot/certbot certonly \
      --standalone \
      -d "$DOMAIN" \
      --email "$EMAIL" \
      --agree-tos \
      --no-eff-email \
      --non-interactive
}

renew_certificate() {
  compose run --rm certbot renew \
    --webroot \
    -w /var/www/certbot \
    --quiet

  compose exec proxy nginx -s reload
}

case "${1:-help}" in
  issue)
    issue_certificate
    ;;
  force-issue)
    issue_certificate force
    ;;
  renew)
    renew_certificate
    ;;
  help|-h|--help)
    echo "Usage: ./.docker/scripts/certbot.sh [issue|force-issue|renew]"
    ;;
  *)
    echo "Unknown command: $1" >&2
    exit 2
    ;;
esac
