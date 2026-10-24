-- Laboratory information system (simulated). Own patient IDs, UPPERCASE surnames,
-- Tables live in the default "public" schema so Zetaris LIST/REGISTER finds them.
-- DD/MM/YYYY dates of birth stored as text (as many LIS exports do).
CREATE TABLE lab_patients (lab_patient_id text PRIMARY KEY, surname text, forenames text, dob text, gender text);
CREATE TABLE lab_results (result_id text PRIMARY KEY, lab_patient_id text REFERENCES lab_patients,
  accession_no text, loinc_code text, test_name text, value_num double precision, value_text text, unit text,
  status text, collected_at timestamptz, reported_at timestamptz, reference_range text);
CREATE TABLE lab_reports (report_id text PRIMARY KEY, lab_patient_id text REFERENCES lab_patients,
  loinc_code text, report_name text, status text, issued_at timestamptz, effective_at timestamptz, result_ids text);
COPY lab_patients FROM '/data/lab_patients.csv' WITH (FORMAT csv, HEADER true, NULL '');
COPY lab_results  FROM '/data/lab_results.csv'  WITH (FORMAT csv, HEADER true, NULL '');
COPY lab_reports  FROM '/data/lab_reports.csv'  WITH (FORMAT csv, HEADER true, NULL '');
CREATE INDEX ON lab_results (lab_patient_id, loinc_code, collected_at);
