#!/bin/bash
# Hospital EHR container (SQL Server 2022): start the server, load the synthetic data once, keep running.
# The load is idempotent: if a previous load did not finish, the half-built database is dropped and rebuilt.
set -u
/opt/mssql/bin/sqlservr &
SERVER_PID=$!

if [ -x /opt/mssql-tools18/bin/sqlcmd ]; then SQLCMD=(/opt/mssql-tools18/bin/sqlcmd -C); else SQLCMD=(/opt/mssql-tools/bin/sqlcmd); fi
SA=("${SQLCMD[@]}" -S localhost -U sa -P "$MSSQL_SA_PASSWORD")

echo "[clinassist] waiting for SQL Server to accept connections..."
for i in $(seq 1 120); do
  "${SA[@]}" -Q "SELECT 1" >/dev/null 2>&1 && break
  sleep 2
done
# After a restart, existing databases (including a half-built hospital_ehr) are still being recovered for a while.
# Wait until every database is ONLINE before checking or dropping anything.
echo "[clinassist] waiting for all databases to be online..."
for i in $(seq 1 90); do
  LEFT=$("${SA[@]}" -h -1 -W -Q "SET NOCOUNT ON; SELECT COUNT(*) FROM sys.databases WHERE state_desc <> 'ONLINE'" 2>/dev/null | tr -d '[:space:]')
  [ "$LEFT" = "0" ] && break
  sleep 2
done

DONE=$("${SA[@]}" -h -1 -W -Q "SET NOCOUNT ON; SELECT CASE WHEN OBJECT_ID('master.dbo.clinassist_load_complete') IS NULL THEN 0 ELSE 1 END" 2>/dev/null | tr -d '[:space:]')
if [ "$DONE" != "1" ]; then
  echo "[clinassist] loading hospital_ehr from /data ..."
  "${SA[@]}" -Q "IF DB_ID('hospital_ehr') IS NOT NULL BEGIN ALTER DATABASE hospital_ehr SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE hospital_ehr; END; IF SUSER_ID('$HOSPITAL_DB_USER') IS NOT NULL DROP LOGIN [$HOSPITAL_DB_USER];"
  # BULK INSERT on SQL Server for Linux decodes char files as CP437 regardless of the column's
  # UTF-8 collation, corrupting accented names. Convert the mounted UTF-8 CSVs to UTF-16LE with
  # a BOM instead; hospital.sql loads them as DATAFILETYPE = 'widechar'.
  mkdir -p /tmp/csv-utf16
  for f in /data/*.csv; do
    printf '\xff\xfe' > "/tmp/csv-utf16/$(basename "$f")"
    iconv -f UTF-8 -t UTF-16LE "$f" >> "/tmp/csv-utf16/$(basename "$f")"
  done
  echo "[clinassist] converted $(ls /tmp/csv-utf16/*.csv | wc -l) CSV files to UTF-16LE"
  if "${SA[@]}" -b -i /init/hospital.sql -v RO_USER="$HOSPITAL_DB_USER" RO_PASSWORD="$HOSPITAL_DB_PASSWORD"; then
    echo "[clinassist] hospital_ehr loaded."
  else
    echo "[clinassist] LOAD FAILED - see the error above. Fix it, then: docker compose restart hospital-db"
  fi
else
  echo "[clinassist] hospital_ehr already loaded."
fi

wait $SERVER_PID
