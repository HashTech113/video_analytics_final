#!/bin/bash
# One-time PostgreSQL setup for video_analytics.
# Run with: bash setup_postgres.sh
set -e

DB_NAME="video_analytics"
DB_USER="va_user"
DB_PASS="va_pass_2026"

echo "==> Setting up PostgreSQL for video_analytics..."

sudo -u postgres psql <<SQL
-- Create dedicated user
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
    CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASS}';
  ELSE
    ALTER USER ${DB_USER} WITH PASSWORD '${DB_PASS}';
  END IF;
END \$\$;

-- Create database (ignore error if already exists)
SELECT 'CREATE DATABASE ${DB_NAME} OWNER ${DB_USER}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${DB_NAME}')\gexec

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};
SQL

echo "==> PostgreSQL setup complete."
echo ""
echo "==> Updating backend/.env ..."

ENV_FILE="$(dirname "$0")/.env"

# Update or insert each postgres variable
update_env() {
  local key="$1" val="$2"
  if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
  else
    echo "${key}=${val}" >> "$ENV_FILE"
  fi
}

update_env POSTGRES_HOST   localhost
update_env POSTGRES_PORT   5432
update_env POSTGRES_DB     "$DB_NAME"
update_env POSTGRES_USER   "$DB_USER"
update_env POSTGRES_PASSWORD "$DB_PASS"

echo ""
echo "==> Done! .env updated with:"
grep "^POSTGRES" "$ENV_FILE"
echo ""
echo "==> Restart the backend (npm run full) for changes to take effect."
