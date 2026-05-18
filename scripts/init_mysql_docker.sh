#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SQL_DIR="${ROOT_DIR}/database/sql"
ENV_FILE="${ROOT_DIR}/backend/.env"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

# 使用 mysql 的 lts 版本
MYSQL_IMAGE="${MYSQL_IMAGE:-mysql:lts}"
MYSQL_CONTAINER_NAME="${MYSQL_CONTAINER_NAME:-liferoute-mysql}"
DATABASE_HOST="${DATABASE_HOST:-127.0.0.1}"
DATABASE_PORT="${DATABASE_PORT:-3306}"
DATABASE_USER="${DATABASE_USER:-root}"
# 密码从环境变量里面读取
DATABASE_PASSWORD="${DATABASE_PASSWORD:-}"
DATABASE_NAME="${DATABASE_NAME:-life_route_agent}"
MYSQL_ROOT_PASSWORD="${MYSQL_ROOT_PASSWORD:-${DATABASE_PASSWORD}}"

SQL_FILES=(
  "poi_attractions.sql"
  "poi_shoppings.sql"
  "poi_activities.sql"
  "poi_restaurant.sql"
  "poi_fitness.sql"
  "poi_entertainment.sql"
  "poi_beauty.sql"
)



docker pull "${MYSQL_IMAGE}"

if docker ps -a --format '{{.Names}}' | grep -Fxq "${MYSQL_CONTAINER_NAME}"; then
  if docker ps --format '{{.Names}}' | grep -Fxq "${MYSQL_CONTAINER_NAME}"; then
    echo "Container ${MYSQL_CONTAINER_NAME} is already running."
  else
    echo "Starting existing container ${MYSQL_CONTAINER_NAME}..."
    docker start "${MYSQL_CONTAINER_NAME}" >/dev/null
  fi
else
  echo "Creating MySQL container ${MYSQL_CONTAINER_NAME} on ${DATABASE_HOST}:${DATABASE_PORT}..."
  docker_run_args=(
    run
    --name "${MYSQL_CONTAINER_NAME}"
    -d
    -p "${DATABASE_HOST}:${DATABASE_PORT}:3306"
    -e "MYSQL_DATABASE=${DATABASE_NAME}"
    -e "TZ=Asia/Shanghai"
  )

  if [[ -n "${MYSQL_ROOT_PASSWORD}" ]]; then
    docker_run_args+=(-e "MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD}")
  else
    docker_run_args+=(-e "MYSQL_ALLOW_EMPTY_PASSWORD=yes")
  fi

  docker_run_args+=("${MYSQL_IMAGE}" --character-set-server=utf8mb4 --collation-server=utf8mb4_general_ci)
  docker "${docker_run_args[@]}" >/dev/null
fi

mysql_auth_args=(-u"${DATABASE_USER}" --default-character-set=utf8mb4)
if [[ -n "${DATABASE_PASSWORD}" ]]; then
  mysql_auth_args+=(-p"${DATABASE_PASSWORD}")
fi

echo "Waiting for MySQL to accept connections..."
for _ in {1..60}; do
  if docker exec "${MYSQL_CONTAINER_NAME}" mysqladmin "${mysql_auth_args[@]}" ping --silent >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if ! docker exec "${MYSQL_CONTAINER_NAME}" mysqladmin "${mysql_auth_args[@]}" ping --silent >/dev/null 2>&1; then
  echo "MySQL did not become ready in time. Check container logs:" >&2
  echo "  docker logs ${MYSQL_CONTAINER_NAME}" >&2
  exit 1
fi

echo "Ensuring database ${DATABASE_NAME} exists..."
docker exec -i "${MYSQL_CONTAINER_NAME}" mysql "${mysql_auth_args[@]}" <<SQL
CREATE DATABASE IF NOT EXISTS \`${DATABASE_NAME}\`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_general_ci;
SQL

for sql_file in "${SQL_FILES[@]}"; do
  echo "Importing ${sql_file}..."
  docker exec -i "${MYSQL_CONTAINER_NAME}" mysql "${mysql_auth_args[@]}" "${DATABASE_NAME}" < "${SQL_DIR}/${sql_file}"
done

echo "Imported database/sql into ${DATABASE_NAME}."
echo "Container: ${MYSQL_CONTAINER_NAME}"
echo "Connection: ${DATABASE_HOST}:${DATABASE_PORT}, user=${DATABASE_USER}, database=${DATABASE_NAME}"
