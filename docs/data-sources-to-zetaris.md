# Registering the ClinAssist data sources in Zetaris

Register the three synthetic source systems in Zetaris, then prove federation
with one query across all three engines. Run every statement in the Zetaris SQL
editor (<http://localhost:3000>), one statement at a time, and replace each
`TYPE_*_PASSWORD_HERE` placeholder with the read-only password from
`sources\.env`.

| Datasource | Engine | Port | Read-only user | Main table | Expected rows |
| --- | --- | --- | --- | --- | --- |
| `hospital_ehr` | SQL Server | 55432 | `hospital_ro` | `patients` | 112 |
| `lab_lis` | MySQL | 55433 | `lab_ro` | `lab_results` | 19,903 |
| `pharmacy_rx` | PostgreSQL | 55434 | `pharmacy_ro` | `prescriptions` | 3,221 |

## Step 1: remove the old registrations

Three runs:

```sql
DROP DATASOURCE hospital_ehr
DROP DATASOURCE lab_lis
DROP DATASOURCE pharmacy_rx
```

## Step 2: hospital (SQL Server)

First the connection test. It should list the 6 tables:

```sql
LIST DATABASE TABLES OPTIONS (
  jdbcdriver "com.microsoft.sqlserver.jdbc.SQLServerDriver",
  jdbcurl "jdbc:sqlserver://host.docker.internal:55432;databaseName=hospital_ehr;encrypt=false",
  username "hospital_ro",
  password "TYPE_HOSPITAL_PASSWORD_HERE"
)
```

If that worked, register the hospital:

```sql
CREATE DATASOURCE hospital_ehr DESCRIBE BY "Hospital EHR on SQL Server - synthetic" OPTIONS (
  jdbcdriver "com.microsoft.sqlserver.jdbc.SQLServerDriver",
  jdbcurl "jdbc:sqlserver://host.docker.internal:55432;databaseName=hospital_ehr;encrypt=false",
  username "hospital_ro",
  password "TYPE_HOSPITAL_PASSWORD_HERE",
  fetchsize "1000"
)
```

```sql
REGISTER DATASOURCE TABLES FROM hospital_ehr
```

## Step 3: lab (MySQL)

```sql
LIST DATABASE TABLES OPTIONS (
  jdbcdriver "com.mysql.cj.jdbc.Driver",
  jdbcurl "jdbc:mysql://host.docker.internal:55433/lab_lis?useSSL=false&allowPublicKeyRetrieval=true",
  username "lab_ro",
  password "TYPE_LAB_PASSWORD_HERE"
)
```

```sql
CREATE DATASOURCE lab_lis DESCRIBE BY "Laboratory LIS on MySQL - synthetic" OPTIONS (
  jdbcdriver "com.mysql.cj.jdbc.Driver",
  jdbcurl "jdbc:mysql://host.docker.internal:55433/lab_lis?useSSL=false&allowPublicKeyRetrieval=true",
  username "lab_ro",
  password "TYPE_LAB_PASSWORD_HERE",
  fetchsize "1000"
)
```

```sql
REGISTER DATASOURCE TABLES FROM lab_lis
```

## Step 4: pharmacy (PostgreSQL)

```sql
LIST DATABASE TABLES OPTIONS (
  jdbcdriver "org.postgresql.Driver",
  jdbcurl "jdbc:postgresql://host.docker.internal:55434/pharmacy_rx",
  username "pharmacy_ro",
  password "TYPE_PHARMACY_PASSWORD_HERE"
)
```

```sql
CREATE DATASOURCE pharmacy_rx DESCRIBE BY "Pharmacy system on PostgreSQL - synthetic" OPTIONS (
  jdbcdriver "org.postgresql.Driver",
  jdbcurl "jdbc:postgresql://host.docker.internal:55434/pharmacy_rx",
  username "pharmacy_ro",
  password "TYPE_PHARMACY_PASSWORD_HERE",
  fetchsize "1000"
)
```

```sql
REGISTER DATASOURCE TABLES FROM pharmacy_rx
```

## Step 5: see the table names

Send me a screenshot of these:

```sql
SHOW DATASOURCE TABLES hospital_ehr
```

```sql
SHOW DATASOURCE TABLES lab_lis
```

```sql
SHOW DATASOURCE TABLES pharmacy_rx
```

## Step 6: one query across all three engines

Expected counts: **112**, **19,903** and **3,221**.

```sql
SELECT 'hospital patients (SQL Server)' AS item, COUNT(*) AS n FROM hospital_ehr.patients
UNION ALL SELECT 'lab results (MySQL)', COUNT(*) FROM lab_lis.lab_results
UNION ALL SELECT 'pharmacy prescriptions (PostgreSQL)', COUNT(*) FROM pharmacy_rx.prescriptions
```
