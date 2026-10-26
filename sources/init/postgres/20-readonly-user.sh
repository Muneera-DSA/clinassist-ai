#!/bin/bash
# Read-only role for Zetaris: SELECT on pharmacy_rx only. Runs once, on first start.
set -e
psql -v ON_ERROR_STOP=1 -v ro_user="$PHARMACY_DB_USER" -v ro_pass="$PHARMACY_DB_PASSWORD" \
     --username "$POSTGRES_USER" --dbname pharmacy_rx <<'EOSQL'
CREATE ROLE :"ro_user" LOGIN PASSWORD :'ro_pass';
GRANT CONNECT ON DATABASE pharmacy_rx TO :"ro_user";
GRANT USAGE ON SCHEMA public TO :"ro_user";
GRANT SELECT ON ALL TABLES IN SCHEMA public TO :"ro_user";
EOSQL
echo "[clinassist] read-only role $PHARMACY_DB_USER created"
