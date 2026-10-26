-- Laboratory information system on MySQL 8.4 (simulated, synthetic data only).
-- Runs once from /docker-entrypoint-initdb.d on first start (database lab_lis is created by the image).
-- Own patient IDs, UPPERCASE surnames, DD/MM/YYYY dates of birth stored as text (as many LIS exports do).
-- CSVs sit in /var/lib/mysql-files (the server's secure_file_priv folder).
USE lab_lis;
CREATE TABLE lab_patients (
  `lab_patient_id` VARCHAR(40) NOT NULL PRIMARY KEY,
  `surname` VARCHAR(40),
  `forenames` VARCHAR(40),
  `dob` VARCHAR(40),
  `gender` VARCHAR(16)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
LOAD DATA INFILE '/var/lib/mysql-files/lab_patients.csv' INTO TABLE lab_patients
  CHARACTER SET utf8mb4 FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '\n' IGNORE 1 LINES
  (@lab_patient_id, @surname, @forenames, @dob, @gender)
  SET `lab_patient_id` = NULLIF(TRIM(TRAILING '\r' FROM @lab_patient_id), ''),
      `surname` = NULLIF(TRIM(TRAILING '\r' FROM @surname), ''),
      `forenames` = NULLIF(TRIM(TRAILING '\r' FROM @forenames), ''),
      `dob` = NULLIF(TRIM(TRAILING '\r' FROM @dob), ''),
      `gender` = NULLIF(TRIM(TRAILING '\r' FROM @gender), '');
CREATE TABLE lab_results (
  `result_id` VARCHAR(40) NOT NULL PRIMARY KEY,
  `lab_patient_id` VARCHAR(40),
  `accession_no` VARCHAR(40),
  `loinc_code` VARCHAR(16),
  `test_name` VARCHAR(255),
  `value_num` DOUBLE,
  `value_text` VARCHAR(255),
  `unit` VARCHAR(40),
  `status` VARCHAR(16),
  `collected_at` DATETIME,
  `reported_at` DATETIME,
  `reference_range` VARCHAR(16)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
LOAD DATA INFILE '/var/lib/mysql-files/lab_results.csv' INTO TABLE lab_results
  CHARACTER SET utf8mb4 FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '\n' IGNORE 1 LINES
  (@result_id, @lab_patient_id, @accession_no, @loinc_code, @test_name, @value_num, @value_text, @unit, @status, @collected_at, @reported_at, @reference_range)
  SET `result_id` = NULLIF(TRIM(TRAILING '\r' FROM @result_id), ''),
      `lab_patient_id` = NULLIF(TRIM(TRAILING '\r' FROM @lab_patient_id), ''),
      `accession_no` = NULLIF(TRIM(TRAILING '\r' FROM @accession_no), ''),
      `loinc_code` = NULLIF(TRIM(TRAILING '\r' FROM @loinc_code), ''),
      `test_name` = NULLIF(TRIM(TRAILING '\r' FROM @test_name), ''),
      `value_num` = CAST(NULLIF(TRIM(TRAILING '\r' FROM @value_num), '') AS DOUBLE),
      `value_text` = NULLIF(TRIM(TRAILING '\r' FROM @value_text), ''),
      `unit` = NULLIF(TRIM(TRAILING '\r' FROM @unit), ''),
      `status` = NULLIF(TRIM(TRAILING '\r' FROM @status), ''),
      `collected_at` = STR_TO_DATE(LEFT(NULLIF(TRIM(TRAILING '\r' FROM @collected_at), ''), 19), '%Y-%m-%dT%H:%i:%s'),
      `reported_at` = STR_TO_DATE(LEFT(NULLIF(TRIM(TRAILING '\r' FROM @reported_at), ''), 19), '%Y-%m-%dT%H:%i:%s'),
      `reference_range` = NULLIF(TRIM(TRAILING '\r' FROM @reference_range), '');
CREATE TABLE lab_reports (
  `report_id` VARCHAR(40) NOT NULL PRIMARY KEY,
  `lab_patient_id` VARCHAR(40),
  `loinc_code` VARCHAR(16),
  `report_name` VARCHAR(255),
  `status` VARCHAR(16),
  `issued_at` DATETIME,
  `effective_at` DATETIME,
  `result_ids` VARCHAR(500)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
LOAD DATA INFILE '/var/lib/mysql-files/lab_reports.csv' INTO TABLE lab_reports
  CHARACTER SET utf8mb4 FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '\n' IGNORE 1 LINES
  (@report_id, @lab_patient_id, @loinc_code, @report_name, @status, @issued_at, @effective_at, @result_ids)
  SET `report_id` = NULLIF(TRIM(TRAILING '\r' FROM @report_id), ''),
      `lab_patient_id` = NULLIF(TRIM(TRAILING '\r' FROM @lab_patient_id), ''),
      `loinc_code` = NULLIF(TRIM(TRAILING '\r' FROM @loinc_code), ''),
      `report_name` = NULLIF(TRIM(TRAILING '\r' FROM @report_name), ''),
      `status` = NULLIF(TRIM(TRAILING '\r' FROM @status), ''),
      `issued_at` = STR_TO_DATE(LEFT(NULLIF(TRIM(TRAILING '\r' FROM @issued_at), ''), 19), '%Y-%m-%dT%H:%i:%s'),
      `effective_at` = STR_TO_DATE(LEFT(NULLIF(TRIM(TRAILING '\r' FROM @effective_at), ''), 19), '%Y-%m-%dT%H:%i:%s'),
      `result_ids` = NULLIF(TRIM(TRAILING '\r' FROM @result_ids), '');
CREATE INDEX ix_results_patient ON lab_results (lab_patient_id, loinc_code, collected_at);
CREATE INDEX ix_reports_patient ON lab_reports (lab_patient_id);
