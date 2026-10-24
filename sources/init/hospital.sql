-- Hospital EHR (simulated). ISO dates, canonical names, MRN identifiers.
-- Tables live in the default "public" schema so Zetaris LIST/REGISTER finds them.
CREATE TABLE patients (mrn text PRIMARY KEY, given_name text, middle_name text, family_name text,
  birth_date date, sex text, deceased_at timestamptz, city text, postcode text);
CREATE TABLE encounters (encounter_id text PRIMARY KEY, mrn text REFERENCES patients, encounter_class text,
  type_code text, type_display text, status text, start_at timestamptz, end_at timestamptz,
  reason_code text, reason_display text, provider_org text);
CREATE TABLE conditions (condition_id text PRIMARY KEY, mrn text REFERENCES patients, encounter_id text,
  snomed_code text, display text, clinical_status text, verification_status text,
  onset_at timestamptz, abatement_at timestamptz, recorded_at timestamptz);
CREATE TABLE procedures (procedure_id text PRIMARY KEY, mrn text REFERENCES patients, encounter_id text,
  snomed_code text, display text, status text, performed_start timestamptz, performed_end timestamptz);
CREATE TABLE observations (observation_id text PRIMARY KEY, mrn text REFERENCES patients, encounter_id text,
  category text, loinc_code text, test_name text, value_num double precision, value_text text, unit text,
  status text, observed_at timestamptz);
COPY patients     FROM '/data/patients.csv'     WITH (FORMAT csv, HEADER true, NULL '');
COPY encounters   FROM '/data/encounters.csv'   WITH (FORMAT csv, HEADER true, NULL '');
COPY conditions   FROM '/data/conditions.csv'   WITH (FORMAT csv, HEADER true, NULL '');
COPY procedures   FROM '/data/procedures.csv'   WITH (FORMAT csv, HEADER true, NULL '');
COPY observations FROM '/data/observations.csv' WITH (FORMAT csv, HEADER true, NULL '');
CREATE INDEX ON encounters (mrn, start_at);
CREATE INDEX ON conditions (mrn);
CREATE INDEX ON procedures (mrn);
CREATE INDEX ON observations (mrn, loinc_code);
