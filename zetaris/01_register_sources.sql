-- ClinAssist AI - register the three simulated source systems in Zetaris.
-- Run in the Zetaris SQL Editor (http://localhost:3000), ONE statement at a time.
-- Replace <...password...> with the values from sources\.env when you run it.
-- Do NOT save real passwords back into this file.
--
-- host.docker.internal lets the Zetaris containers reach the databases published
-- on your Windows host (ports 55432-55434). Syntax: docs/guides/zetaris-lightning-sql-commands.md 4.1-4.3

-- 1. Read-only connectivity check (registers nothing)
LIST DATABASE TABLES OPTIONS (
  jdbcdriver "org.postgresql.Driver",
  jdbcurl "jdbc:postgresql://host.docker.internal:55432/hospital_ehr",
  username "hospital_ro",
  password "<hospital password>"
)

-- 2. Hospital EHR
CREATE DATASOURCE hospital_ehr DESCRIBE BY "Simulated hospital EHR - synthetic" OPTIONS (
  jdbcdriver "org.postgresql.Driver",
  jdbcurl "jdbc:postgresql://host.docker.internal:55432/hospital_ehr",
  username "hospital_ro",
  password "<hospital password>",
  fetchsize "1000"
)

REGISTER DATASOURCE TABLES FROM hospital_ehr

-- 3. Laboratory information system
CREATE DATASOURCE lab_lis DESCRIBE BY "Simulated laboratory LIS - synthetic" OPTIONS (
  jdbcdriver "org.postgresql.Driver",
  jdbcurl "jdbc:postgresql://host.docker.internal:55433/lab_lis",
  username "lab_ro",
  password "<lab password>",
  fetchsize "1000"
)

REGISTER DATASOURCE TABLES FROM lab_lis

-- 4. Pharmacy system
CREATE DATASOURCE pharmacy_rx DESCRIBE BY "Simulated pharmacy system - synthetic" OPTIONS (
  jdbcdriver "org.postgresql.Driver",
  jdbcurl "jdbc:postgresql://host.docker.internal:55434/pharmacy_rx",
  username "pharmacy_ro",
  password "<pharmacy password>",
  fetchsize "1000"
)

REGISTER DATASOURCE TABLES FROM pharmacy_rx

-- 5. See exactly how Zetaris named the tables before writing any queries
SHOW DATASOURCES
