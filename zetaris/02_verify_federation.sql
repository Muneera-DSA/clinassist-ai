-- ClinAssist AI - verified cross-source queries (Zetaris 2.4.3.1, 23 Oct 2026).
-- Run one statement at a time in the SQL Editor.

-- 1. All three systems in one query. Verified: 112 / 19903 / 3221
SELECT 'hospital patients' AS item, COUNT(*) AS n FROM hospital_ehr.patients
UNION ALL SELECT 'lab results', COUNT(*) FROM lab_lis.lab_results
UNION ALL SELECT 'pharmacy prescriptions', COUNT(*) FROM pharmacy_rx.prescriptions

-- 2. Naive identity match hospital <-> lab on exact surname + date of birth.
--    Verified: 99 of 112. The 13 misses are typos / swapped dates the
--    reconciliation step (Meterless World Model) must recover.
--    Note: single-letter aliases returned "Bad Request"; use AS hp / AS lp.
SELECT COUNT(*) AS exact_matches
FROM hospital_ehr.patients AS hp
INNER JOIN lab_lis.lab_patients AS lp
  ON upper(hp.family_name) = lp.surname
 AND date_format(hp.birth_date, 'dd/MM/yyyy') = lp.dob
