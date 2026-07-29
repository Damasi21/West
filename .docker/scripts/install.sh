#!/usr/bin/env bash
set -euo pipefail

ENV_FILE=".docker/.env.production"
ENV_EXAMPLE=".docker/.env.example"
ROOT_COMPOSE=".docker/docker-compose.production.yaml"
LOG_DIR=".docker/logs"
INSTALL_LOG="$LOG_DIR/install.log"

REQUIRED_ENV_VARS=(
  "DOMAIN"
  "EMAIL"
  "SECRET_KEY"
  "OMIE_CREDENTIALS_ENCRYPTION_KEY"
  "ALLOWED_HOSTS"
  "CSRF_TRUSTED_ORIGINS"
  "POSTGRES_DB"
  "POSTGRES_USER"
  "POSTGRES_PASSWORD"
)

SECRET_ENV_VARS=(
  "SECRET_KEY"
  "OMIE_CREDENTIALS_ENCRYPTION_KEY"
  "POSTGRES_PASSWORD"
)

mkdir -p "$LOG_DIR"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [WESTWISE_INSTALL] $1" | tee -a "$INSTALL_LOG"
}

fail() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [WESTWISE_INSTALL_ERROR] $1" | tee -a "$INSTALL_LOG" >&2
  exit 1
}

compose() {
  docker compose --env-file "$ENV_FILE" -f "$ROOT_COMPOSE" "$@"
}

load_env() {
  if [ ! -f "$ENV_FILE" ]; then
    fail "Missing $ENV_FILE. Create it from $ENV_EXAMPLE."
  fi

  set -a
  . "$ENV_FILE"
  set +a
}

validate_env() {
  for var_name in "${REQUIRED_ENV_VARS[@]}"; do
    [ -n "${!var_name:-}" ] || fail "Required production environment variable is missing: $var_name"
  done

  for var_name in "${SECRET_ENV_VARS[@]}"; do
    case "${!var_name:-}" in
      ""|CHANGE_ME|change_me|changeme|troque-esta-chave|troque-esta-senha)
        fail "Production secret '$var_name' still has a template value."
        ;;
    esac
  done
}

validate_dependencies() {
  command -v docker >/dev/null 2>&1 || fail "Docker is not installed or not available in PATH."
  docker compose version >/dev/null 2>&1 || fail "Docker Compose plugin is not available."
  command -v curl >/dev/null 2>&1 || fail "curl is not installed or not available in PATH."
}

install() {
  : > "$INSTALL_LOG"
  log "Loading production environment"
  load_env
  log "Validating production environment"
  validate_env
  log "Validating host dependencies"
  validate_dependencies
  log "Building production image"
  compose build
  log "Issuing SSL certificate when needed"
  ./.docker/scripts/certbot.sh issue
  log "Starting production stack"
  compose up -d
  log "Validating HTTPS health endpoint"
  curl -fsSL --max-time 30 "https://${DOMAIN}/healthz" >/dev/null
  log "Production installation completed"
}

case "${1:-install}" in
  install)
    install
    ;;
  help|-h|--help)
    echo "Usage: ./.docker/scripts/install.sh [install]"
    ;;
  *)
    echo "Unknown command: $1" >&2
    exit 2
    ;;
esac
