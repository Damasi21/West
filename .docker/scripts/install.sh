#!/usr/bin/env bash
set -euo pipefail

ENV_FILE=".docker/.env.production"
ENV_EXAMPLE=".docker/.env.example"
ROOT_COMPOSE=".docker/docker-compose.production.yaml"
LOG_DIR=".docker/logs"
INSTALL_LOG="$LOG_DIR/install.log"

REQUIRED_ENV_VARS=(
  "SECRET_KEY"
  "OMIE_CREDENTIALS_ENCRYPTION_KEY"
  "ALLOWED_HOSTS"
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
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [WEST_INSTALL] $1" | tee -a "$INSTALL_LOG"
}

fail() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [WEST_INSTALL_ERROR] $1" | tee -a "$INSTALL_LOG" >&2
  exit 1
}

compose() {
  docker compose --env-file "$ENV_FILE" -f "$ROOT_COMPOSE" "$@"
}

append_env() {
  printf "%s=%s\n" "$1" "$2" >> "$ENV_FILE"
}

is_ip_address() {
  case "${1:-}" in
    *:*)
      return 0
      ;;
  esac

  printf "%s" "${1:-}" | grep -Eq '^([0-9]{1,3}\.){3}[0-9]{1,3}$'
}

ssl_enabled() {
  case "${ENABLE_SSL:-auto}" in
    1|true|TRUE|yes|YES|on|ON)
      [ -n "${DOMAIN:-}" ] && ! is_ip_address "$DOMAIN"
      ;;
    0|false|FALSE|no|NO|off|OFF)
      return 1
      ;;
    auto|"")
      [ -n "${DOMAIN:-}" ] && [ "$DOMAIN" != "localhost" ] && ! is_ip_address "$DOMAIN"
      ;;
    *)
      fail "ENABLE_SSL must be auto, true, or false."
      ;;
  esac
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

  if ssl_enabled && [ -z "${EMAIL:-}" ]; then
    fail "EMAIL is required when SSL is enabled."
  fi

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

configure_proxy() {
  log "Using host nginx/certbot. Docker proxy is disabled for this deployment."
}

validate_health() {
  local app_host_port="${APP_HOST_PORT:-127.0.0.1:8000}"
  local health_url="http://${app_host_port}/healthz"
  local attempt=1

  log "Validating health endpoint"
  while [ "$attempt" -le 30 ]; do
    if curl -fsSL --max-time 10 "$health_url" >/dev/null; then
      return 0
    fi

    sleep 2
    attempt=$((attempt + 1))
  done

  fail "Health endpoint did not become ready: $health_url"
}

dump_diagnostics() {
  log "Collecting Docker diagnostics"
  compose ps || true
  compose logs --tail=120 app scheduler postgres || true
}

install() {
  : > "$INSTALL_LOG"
  trap 'status=$?; if [ "$status" -ne 0 ]; then dump_diagnostics; fi; exit "$status"' EXIT
  log "Loading production environment"
  load_env
  log "Validating production environment"
  validate_env
  log "Validating host dependencies"
  validate_dependencies
  configure_proxy
  log "Building production image"
  compose build
  log "Starting production stack"
  compose up -d
  validate_health
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
