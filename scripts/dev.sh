#!/usr/bin/env bash
# Запуск команд внутри контейнера backend (локальная разработка).
# Использование: ./scripts/dev.sh pytest tests -q
#
# Скрипт работает поверх инфраструктуры из docker-compose (сеть forumos_default),
# поэтому перед запуском тестов нужно выполнить: make infra
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ ! -f "$ROOT/.env" ]; then
  echo "ERR: нет $ROOT/.env — выполните 'make setup'." >&2
  exit 1
fi

# Значения из .env должны попасть в окружение до подстановки значений по умолчанию.
set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a

NETWORK="${FORUMOS_DOCKER_NETWORK:-forumos_default}"
DB_HOST="${POSTGRES_HOST:-postgres}"
DB_NAME="${POSTGRES_DB:-forumos}"
DB_USER="${POSTGRES_USER:-forumos}"
DB_PASSWORD="${POSTGRES_PASSWORD:-forumos}"
IMAGE="${FORUMOS_BACKEND_IMAGE:-forumos-backend:latest}"

if ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
  echo "ERR: нет docker-сети $NETWORK — выполните 'make infra'." >&2
  exit 1
fi

docker run --rm \
  --user "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  --network "$NETWORK" \
  -v "$ROOT/backend:/app" \
  -w /app \
  -e DJANGO_SETTINGS_MODULE="${FORUMOS_SETTINGS:-config.settings.test}" \
  -e DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-dev-secret-key}" \
  -e DJANGO_DEBUG=false \
  -e DJANGO_ALLOWED_HOSTS=localhost \
  -e APP_HOST="${APP_HOST:-http://localhost:8080}" \
  -e APP_VERSION="${APP_VERSION:-0.1.0}" \
  -e LOG_LEVEL="${LOG_LEVEL:-WARNING}" \
  -e POSTGRES_DB="$DB_NAME" \
  -e POSTGRES_USER="$DB_USER" \
  -e POSTGRES_PASSWORD="$DB_PASSWORD" \
  -e POSTGRES_HOST="$DB_HOST" \
  -e POSTGRES_TEST_DB="test_${DB_NAME}" \
  "$IMAGE" \
  "$@"
