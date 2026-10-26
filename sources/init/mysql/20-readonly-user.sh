#!/bin/bash
# Read-only account for Zetaris: SELECT on lab_lis only. Runs once, on first start.
docker_process_sql --database=mysql <<-EOSQL
	CREATE USER '${LAB_DB_USER}'@'%' IDENTIFIED BY '${LAB_DB_PASSWORD}';
	GRANT SELECT ON lab_lis.* TO '${LAB_DB_USER}'@'%';
	FLUSH PRIVILEGES;
EOSQL
echo "[clinassist] read-only user ${LAB_DB_USER} created"
