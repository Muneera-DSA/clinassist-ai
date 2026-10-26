#!/bin/bash
# Read-only account for Zetaris: SELECT on lab_lis only. Runs once, on first start.
# Uses the mysql client directly: files mounted from Windows look executable, so the image runs this script in its
# own process, where the entrypoint's helper functions (docker_process_sql) are not available.
set -euo pipefail
mysql --protocol=socket -uroot -p"${MYSQL_ROOT_PASSWORD}" <<-EOSQL
	CREATE USER '${LAB_DB_USER}'@'%' IDENTIFIED BY '${LAB_DB_PASSWORD}';
	GRANT SELECT ON lab_lis.* TO '${LAB_DB_USER}'@'%';
	FLUSH PRIVILEGES;
EOSQL
echo "[clinassist] read-only user ${LAB_DB_USER} created"
