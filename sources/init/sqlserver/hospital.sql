-- Hospital EHR on Microsoft SQL Server 2022 (simulated, synthetic data only).
-- Run once by init/sqlserver/start.sh when the hospital_ehr database does not exist yet.
-- CSVs are bulk-loaded into staging tables as text, then typed (ISO-8601 UTC -> datetime2).
-- sqlcmd variables: RO_USER, RO_PASSWORD (from sources/.env).
SET NOCOUNT ON;
CREATE DATABASE hospital_ehr;
GO
USE hospital_ehr;
GO
CREATE TABLE dbo.patients (
  [mrn] nvarchar(40) NOT NULL PRIMARY KEY,
  [given_name] nvarchar(40),
  [middle_name] nvarchar(40),
  [family_name] nvarchar(40),
  [birth_date] date,
  [sex] nvarchar(16),
  [deceased_at] datetime2(0),
  [city] nvarchar(40),
  [postcode] nvarchar(16)
);
CREATE TABLE #stage_patients ([mrn] nvarchar(4000), [given_name] nvarchar(4000), [middle_name] nvarchar(4000), [family_name] nvarchar(4000), [birth_date] nvarchar(4000), [sex] nvarchar(4000), [deceased_at] nvarchar(4000), [city] nvarchar(4000), [postcode] nvarchar(4000));
BULK INSERT #stage_patients FROM '/data/patients.csv' WITH (FORMAT = 'CSV', FIRSTROW = 2, FIELDQUOTE = '"', FIELDTERMINATOR = ',', ROWTERMINATOR = '0x0a', CODEPAGE = '65001', TABLOCK);
INSERT INTO dbo.patients ([mrn], [given_name], [middle_name], [family_name], [birth_date], [sex], [deceased_at], [city], [postcode])
SELECT NULLIF(REPLACE([mrn], CHAR(13), ''), ''), NULLIF(REPLACE([given_name], CHAR(13), ''), ''), NULLIF(REPLACE([middle_name], CHAR(13), ''), ''), NULLIF(REPLACE([family_name], CHAR(13), ''), ''), TRY_CONVERT(date, NULLIF(REPLACE([birth_date], CHAR(13), ''), ''), 23), NULLIF(REPLACE([sex], CHAR(13), ''), ''), TRY_CONVERT(datetime2(0), LEFT(NULLIF(REPLACE([deceased_at], CHAR(13), ''), ''), 19), 126), NULLIF(REPLACE([city], CHAR(13), ''), ''), NULLIF(REPLACE([postcode], CHAR(13), ''), '')
FROM #stage_patients;
DROP TABLE #stage_patients;
GO
CREATE TABLE dbo.encounters (
  [encounter_id] nvarchar(128) NOT NULL PRIMARY KEY,
  [mrn] nvarchar(40),
  [encounter_class] nvarchar(16),
  [type_code] nvarchar(40),
  [type_display] nvarchar(255),
  [status] nvarchar(16),
  [start_at] datetime2(0),
  [end_at] datetime2(0),
  [reason_code] nvarchar(40),
  [reason_display] nvarchar(255),
  [provider_org] nvarchar(255)
);
CREATE TABLE #stage_encounters ([encounter_id] nvarchar(4000), [mrn] nvarchar(4000), [encounter_class] nvarchar(4000), [type_code] nvarchar(4000), [type_display] nvarchar(4000), [status] nvarchar(4000), [start_at] nvarchar(4000), [end_at] nvarchar(4000), [reason_code] nvarchar(4000), [reason_display] nvarchar(4000), [provider_org] nvarchar(4000));
BULK INSERT #stage_encounters FROM '/data/encounters.csv' WITH (FORMAT = 'CSV', FIRSTROW = 2, FIELDQUOTE = '"', FIELDTERMINATOR = ',', ROWTERMINATOR = '0x0a', CODEPAGE = '65001', TABLOCK);
INSERT INTO dbo.encounters ([encounter_id], [mrn], [encounter_class], [type_code], [type_display], [status], [start_at], [end_at], [reason_code], [reason_display], [provider_org])
SELECT NULLIF(REPLACE([encounter_id], CHAR(13), ''), ''), NULLIF(REPLACE([mrn], CHAR(13), ''), ''), NULLIF(REPLACE([encounter_class], CHAR(13), ''), ''), NULLIF(REPLACE([type_code], CHAR(13), ''), ''), NULLIF(REPLACE([type_display], CHAR(13), ''), ''), NULLIF(REPLACE([status], CHAR(13), ''), ''), TRY_CONVERT(datetime2(0), LEFT(NULLIF(REPLACE([start_at], CHAR(13), ''), ''), 19), 126), TRY_CONVERT(datetime2(0), LEFT(NULLIF(REPLACE([end_at], CHAR(13), ''), ''), 19), 126), NULLIF(REPLACE([reason_code], CHAR(13), ''), ''), NULLIF(REPLACE([reason_display], CHAR(13), ''), ''), NULLIF(REPLACE([provider_org], CHAR(13), ''), '')
FROM #stage_encounters;
DROP TABLE #stage_encounters;
GO
CREATE TABLE dbo.conditions (
  [condition_id] nvarchar(128) NOT NULL PRIMARY KEY,
  [mrn] nvarchar(40),
  [encounter_id] nvarchar(128),
  [snomed_code] nvarchar(40),
  [display] nvarchar(255),
  [clinical_status] nvarchar(16),
  [verification_status] nvarchar(40),
  [onset_at] datetime2(0),
  [abatement_at] datetime2(0),
  [recorded_at] datetime2(0)
);
CREATE TABLE #stage_conditions ([condition_id] nvarchar(4000), [mrn] nvarchar(4000), [encounter_id] nvarchar(4000), [snomed_code] nvarchar(4000), [display] nvarchar(4000), [clinical_status] nvarchar(4000), [verification_status] nvarchar(4000), [onset_at] nvarchar(4000), [abatement_at] nvarchar(4000), [recorded_at] nvarchar(4000));
BULK INSERT #stage_conditions FROM '/data/conditions.csv' WITH (FORMAT = 'CSV', FIRSTROW = 2, FIELDQUOTE = '"', FIELDTERMINATOR = ',', ROWTERMINATOR = '0x0a', CODEPAGE = '65001', TABLOCK);
INSERT INTO dbo.conditions ([condition_id], [mrn], [encounter_id], [snomed_code], [display], [clinical_status], [verification_status], [onset_at], [abatement_at], [recorded_at])
SELECT NULLIF(REPLACE([condition_id], CHAR(13), ''), ''), NULLIF(REPLACE([mrn], CHAR(13), ''), ''), NULLIF(REPLACE([encounter_id], CHAR(13), ''), ''), NULLIF(REPLACE([snomed_code], CHAR(13), ''), ''), NULLIF(REPLACE([display], CHAR(13), ''), ''), NULLIF(REPLACE([clinical_status], CHAR(13), ''), ''), NULLIF(REPLACE([verification_status], CHAR(13), ''), ''), TRY_CONVERT(datetime2(0), LEFT(NULLIF(REPLACE([onset_at], CHAR(13), ''), ''), 19), 126), TRY_CONVERT(datetime2(0), LEFT(NULLIF(REPLACE([abatement_at], CHAR(13), ''), ''), 19), 126), TRY_CONVERT(datetime2(0), LEFT(NULLIF(REPLACE([recorded_at], CHAR(13), ''), ''), 19), 126)
FROM #stage_conditions;
DROP TABLE #stage_conditions;
GO
CREATE TABLE dbo.procedures (
  [procedure_id] nvarchar(128) NOT NULL PRIMARY KEY,
  [mrn] nvarchar(40),
  [encounter_id] nvarchar(128),
  [snomed_code] nvarchar(40),
  [display] nvarchar(500),
  [status] nvarchar(40),
  [performed_start] datetime2(0),
  [performed_end] datetime2(0)
);
CREATE TABLE #stage_procedures ([procedure_id] nvarchar(4000), [mrn] nvarchar(4000), [encounter_id] nvarchar(4000), [snomed_code] nvarchar(4000), [display] nvarchar(4000), [status] nvarchar(4000), [performed_start] nvarchar(4000), [performed_end] nvarchar(4000));
BULK INSERT #stage_procedures FROM '/data/procedures.csv' WITH (FORMAT = 'CSV', FIRSTROW = 2, FIELDQUOTE = '"', FIELDTERMINATOR = ',', ROWTERMINATOR = '0x0a', CODEPAGE = '65001', TABLOCK);
INSERT INTO dbo.procedures ([procedure_id], [mrn], [encounter_id], [snomed_code], [display], [status], [performed_start], [performed_end])
SELECT NULLIF(REPLACE([procedure_id], CHAR(13), ''), ''), NULLIF(REPLACE([mrn], CHAR(13), ''), ''), NULLIF(REPLACE([encounter_id], CHAR(13), ''), ''), NULLIF(REPLACE([snomed_code], CHAR(13), ''), ''), NULLIF(REPLACE([display], CHAR(13), ''), ''), NULLIF(REPLACE([status], CHAR(13), ''), ''), TRY_CONVERT(datetime2(0), LEFT(NULLIF(REPLACE([performed_start], CHAR(13), ''), ''), 19), 126), TRY_CONVERT(datetime2(0), LEFT(NULLIF(REPLACE([performed_end], CHAR(13), ''), ''), 19), 126)
FROM #stage_procedures;
DROP TABLE #stage_procedures;
GO
CREATE TABLE dbo.observations (
  [observation_id] nvarchar(128) NOT NULL PRIMARY KEY,
  [mrn] nvarchar(40),
  [encounter_id] nvarchar(128),
  [category] nvarchar(40),
  [loinc_code] nvarchar(40),
  [test_name] nvarchar(500),
  [value_num] float,
  [value_text] nvarchar(500),
  [unit] nvarchar(40),
  [status] nvarchar(16),
  [observed_at] datetime2(0)
);
CREATE TABLE #stage_observations ([observation_id] nvarchar(4000), [mrn] nvarchar(4000), [encounter_id] nvarchar(4000), [category] nvarchar(4000), [loinc_code] nvarchar(4000), [test_name] nvarchar(4000), [value_num] nvarchar(4000), [value_text] nvarchar(4000), [unit] nvarchar(4000), [status] nvarchar(4000), [observed_at] nvarchar(4000));
BULK INSERT #stage_observations FROM '/data/observations.csv' WITH (FORMAT = 'CSV', FIRSTROW = 2, FIELDQUOTE = '"', FIELDTERMINATOR = ',', ROWTERMINATOR = '0x0a', CODEPAGE = '65001', TABLOCK);
INSERT INTO dbo.observations ([observation_id], [mrn], [encounter_id], [category], [loinc_code], [test_name], [value_num], [value_text], [unit], [status], [observed_at])
SELECT NULLIF(REPLACE([observation_id], CHAR(13), ''), ''), NULLIF(REPLACE([mrn], CHAR(13), ''), ''), NULLIF(REPLACE([encounter_id], CHAR(13), ''), ''), NULLIF(REPLACE([category], CHAR(13), ''), ''), NULLIF(REPLACE([loinc_code], CHAR(13), ''), ''), NULLIF(REPLACE([test_name], CHAR(13), ''), ''), TRY_CONVERT(float, NULLIF(REPLACE([value_num], CHAR(13), ''), '')), NULLIF(REPLACE([value_text], CHAR(13), ''), ''), NULLIF(REPLACE([unit], CHAR(13), ''), ''), NULLIF(REPLACE([status], CHAR(13), ''), ''), TRY_CONVERT(datetime2(0), LEFT(NULLIF(REPLACE([observed_at], CHAR(13), ''), ''), 19), 126)
FROM #stage_observations;
DROP TABLE #stage_observations;
GO
CREATE TABLE dbo.allergies (
  [allergy_id] nvarchar(128) NOT NULL PRIMARY KEY,
  [mrn] nvarchar(40),
  [snomed_code] nvarchar(40),
  [substance] nvarchar(64),
  [category] nvarchar(40),
  [criticality] nvarchar(16),
  [clinical_status] nvarchar(16),
  [verification_status] nvarchar(40),
  [reaction] nvarchar(128),
  [recorded_at] datetime2(0)
);
CREATE TABLE #stage_allergies ([allergy_id] nvarchar(4000), [mrn] nvarchar(4000), [snomed_code] nvarchar(4000), [substance] nvarchar(4000), [category] nvarchar(4000), [criticality] nvarchar(4000), [clinical_status] nvarchar(4000), [verification_status] nvarchar(4000), [reaction] nvarchar(4000), [recorded_at] nvarchar(4000));
BULK INSERT #stage_allergies FROM '/data/allergies.csv' WITH (FORMAT = 'CSV', FIRSTROW = 2, FIELDQUOTE = '"', FIELDTERMINATOR = ',', ROWTERMINATOR = '0x0a', CODEPAGE = '65001', TABLOCK);
INSERT INTO dbo.allergies ([allergy_id], [mrn], [snomed_code], [substance], [category], [criticality], [clinical_status], [verification_status], [reaction], [recorded_at])
SELECT NULLIF(REPLACE([allergy_id], CHAR(13), ''), ''), NULLIF(REPLACE([mrn], CHAR(13), ''), ''), NULLIF(REPLACE([snomed_code], CHAR(13), ''), ''), NULLIF(REPLACE([substance], CHAR(13), ''), ''), NULLIF(REPLACE([category], CHAR(13), ''), ''), NULLIF(REPLACE([criticality], CHAR(13), ''), ''), NULLIF(REPLACE([clinical_status], CHAR(13), ''), ''), NULLIF(REPLACE([verification_status], CHAR(13), ''), ''), NULLIF(REPLACE([reaction], CHAR(13), ''), ''), TRY_CONVERT(datetime2(0), LEFT(NULLIF(REPLACE([recorded_at], CHAR(13), ''), ''), 19), 126)
FROM #stage_allergies;
DROP TABLE #stage_allergies;
GO
CREATE INDEX ix_encounters_mrn ON dbo.encounters (mrn, start_at);
CREATE INDEX ix_conditions_mrn ON dbo.conditions (mrn);
CREATE INDEX ix_procedures_mrn ON dbo.procedures (mrn);
CREATE INDEX ix_observations_mrn ON dbo.observations (mrn, loinc_code);
CREATE INDEX ix_allergies_mrn ON dbo.allergies (mrn);
GO
-- Read-only login for Zetaris: can SELECT, nothing else.
USE master;
GO
CREATE LOGIN [$(RO_USER)] WITH PASSWORD = '$(RO_PASSWORD)', CHECK_POLICY = OFF, DEFAULT_DATABASE = hospital_ehr;
GO
USE hospital_ehr;
GO
CREATE USER [$(RO_USER)] FOR LOGIN [$(RO_USER)];
ALTER ROLE db_datareader ADD MEMBER [$(RO_USER)];
GO
-- Row counts (shown in the container log), then a marker in master that the health check reads.
SELECT 'patients' AS t, COUNT(*) AS n FROM dbo.patients UNION ALL SELECT 'encounters', COUNT(*) FROM dbo.encounters UNION ALL SELECT 'conditions', COUNT(*) FROM dbo.conditions UNION ALL SELECT 'procedures', COUNT(*) FROM dbo.procedures UNION ALL SELECT 'observations', COUNT(*) FROM dbo.observations UNION ALL SELECT 'allergies', COUNT(*) FROM dbo.allergies;
GO
USE master;
GO
CREATE TABLE dbo.clinassist_load_complete (finished_at datetime2(0) NOT NULL DEFAULT SYSUTCDATETIME());
INSERT INTO dbo.clinassist_load_complete DEFAULT VALUES;
GO
