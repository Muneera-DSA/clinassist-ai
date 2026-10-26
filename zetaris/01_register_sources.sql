-- ClinAssist AI - register the three simulated source systems in Zetaris.
-- Three different engines: SQL Server (hospital), MySQL (laboratory), PostgreSQL (pharmacy).
-- The JDBC drivers for all three ship inside the Zetaris driver image (checked 26 Oct:
-- mssql-jdbc 6.2.1, mysql-connector-j 8.4.0, PostgreSQL).
--
-- Run in the Zetaris SQL Editor (http://localhost:3000), ONE statement at a time.
-- Replace <...password...> with the READ-ONLY passwords from sources\.env when you run it.
-- Do NOT save real passwords back into this file.
--
-- host.docker.internal lets the Zetaris containers reach the databases published on your
-- Windows host (ports 55432-55434).

-- 0. Only if you registered the old PostgreSQL versions before: remove them first.
--    (If the editor rejects DROP DATASOURCE, delete them in the Zetaris UI data-source list instead.)
DROP DATASOURCE hospital_ehr
DROP DATASOURCE lab_lis
DROP DATASOURCE pharmacy_rx

-- 1. Read-only connectivity checks (register nothing). Each should list the tables.
LIST DATABASE TABLES OPTIONS (
  jdbcdriver "com.microsoft.sqlserver.jdbc.SQLServerDriver",
  jdbcurl "jdbc:sqlserver://host.docker.internal:55432;databaseName=hospital_ehr;encrypt=false",
  username "hospital_ro",
  password "<hospital read-only password>"
)

LIST DATABASE TABLES OPTIONS (
  jdbcdriver "com.mysql.cj.jdbc.Driver",
  jdbcurl "jdbc:mysql://host.docker.internal:55433/lab_lis?useSSL=false&allowPublicKeyRetrieval=true",
  username "lab_ro",
  password "<lab read-only password>"
)

LIST DATABASE TABLES OPTIONS (
  jdbcdriver "org.postgresql.Driver",
  jdbcurl "jdbc:postgresql://host.docker.internal:55434/pharmacy_rx",
  username "pharmacy_ro",
  password "<pharmacy read-only password>"
)

-- 2. Hospital EHR - Microsoft SQL Server
CREATE DATASOURCE hospital_ehr DESCRIBE BY "Hospital EHR on SQL Server - synthetic" OPTIONS (
  jdbcdriver "com.microsoft.sqlserver.jdbc.SQLServerDriver",
  jdbcurl "jdbc:sqlserver://host.docker.internal:55432;databaseName=hospital_ehr;encrypt=false",
  username "hospital_ro",
  password "<hospital read-only password>",
  fetchsize "1000"
)

REGISTER DATASOURCE TABLES FROM hospital_ehr

-- 3. Laboratory information system - MySQL
CREATE DATASOURCE lab_lis DESCRIBE BY "Laboratory LIS on MySQL - synthetic" OPTIONS (
  jdbcdriver "com.mysql.cj.jdbc.Driver",
  jdbcurl "jdbc:mysql://host.docker.internal:55433/lab_lis?useSSL=false&allowPublicKeyRetrieval=true",
  username "lab_ro",
  password "<lab read-only password>",
  fetchsize "1000"
)

REGISTER DATASOURCE TABLES FROM lab_lis

-- 4. Pharmacy system - PostgreSQL
CREATE DATASOURCE pharmacy_rx DESCRIBE BY "Pharmacy system on PostgreSQL - synthetic" OPTIONS (
  jdbcdriver "org.postgresql.Driver",
  jdbcurl "jdbc:postgresql://host.docker.internal:55434/pharmacy_rx",
  username "pharmacy_ro",
  password "<pharmacy read-only password>",
  fetchsize "1000"
)

REGISTER DATASOURCE TABLES FROM pharmacy_rx

-- 5. See exactly how Zetaris named the tables. The code expects hospital_ehr.patients,
--    lab_lis.lab_results, pharmacy_rx.prescriptions, ... If Zetaris shows other names
--    (for example with a dbo prefix), put them in config/sources.json - nothing else changes.
SHOW DATASOURCES

SHOW DATASOURCE TABLES hospital_ehr

SHOW DATASOURCE TABLES lab_lis

SHOW DATASOURCE TABLES pharmacy_rx

-- 6. Quick proof: one query across three engines
SELECT 'hospital patients (SQL Server)' AS item, COUNT(*) AS n FROM hospital_ehr.patients
UNION ALL SELECT 'lab results (MySQL)', COUNT(*) FROM lab_lis.lab_results
UNION ALL SELECT 'pharmacy prescriptions (PostgreSQL)', COUNT(*) FROM pharmacy_rx.prescriptions
