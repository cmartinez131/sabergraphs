#!/bin/sh
# Provisions the SELECT-only Postgres role used to execute NL->SQL
# statements (AUDIT B2). Runs automatically on the FIRST boot of a fresh
# postgres volume via /docker-entrypoint-initdb.d. Existing volumes are
# covered by the backend, which performs the same idempotent provisioning
# at startup (backend/app/db/database.py::ensure_readonly_role).
set -e

RO_USER="${NL2SQL_RO_USER:-nl2sql_ro}"
RO_PASSWORD="${NL2SQL_RO_PASSWORD:-nl2sql_ro}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${RO_USER}') THEN
        CREATE ROLE ${RO_USER} LOGIN;
    END IF;
END
\$\$;
ALTER ROLE ${RO_USER} LOGIN PASSWORD '${RO_PASSWORD}';
GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO ${RO_USER};
GRANT USAGE ON SCHEMA public TO ${RO_USER};
GRANT SELECT ON ALL TABLES IN SCHEMA public TO ${RO_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO ${RO_USER};
ALTER ROLE ${RO_USER} SET statement_timeout = '5s';
ALTER ROLE ${RO_USER} SET default_transaction_read_only = on;
EOSQL
