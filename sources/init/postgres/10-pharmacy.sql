-- Pharmacy system on PostgreSQL 16 (simulated, synthetic data only). Own patient IDs, 'SURNAME, Given' names, YYYYMMDD dates of birth.
-- Tables live in the default "public" schema so Zetaris LIST/REGISTER finds them.
CREATE TABLE pharmacy_patients (pharm_patient_id text PRIMARY KEY, full_name text, birth_date text, sex text);
CREATE TABLE prescriptions (rx_id text PRIMARY KEY, pharm_patient_id text REFERENCES pharmacy_patients,
  rxnorm_code text, medication text, status text, intent text, authored_on timestamptz,
  dose_value double precision, dose_unit text, frequency int, period double precision, period_unit text,
  as_needed text, dosage_text text, prescriber text);
CREATE TABLE administrations (admin_id text PRIMARY KEY, pharm_patient_id text REFERENCES pharmacy_patients,
  rxnorm_code text, medication text, status text, administered_at timestamptz);
COPY pharmacy_patients FROM '/data/pharmacy_patients.csv' WITH (FORMAT csv, HEADER true, NULL '');
COPY prescriptions     FROM '/data/prescriptions.csv'     WITH (FORMAT csv, HEADER true, NULL '');
COPY administrations   FROM '/data/administrations.csv'   WITH (FORMAT csv, HEADER true, NULL '');
CREATE INDEX ON prescriptions (pharm_patient_id, status);
