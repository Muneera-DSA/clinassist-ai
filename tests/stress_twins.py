r"""Stress test: add 50 look-alike "twins" to the hospital and check no lab record is wrongly auto-linked.
Run from the project folder:  .\.venv\Scripts\python.exe .\tests\stress_twins.py
"""
import csv, sys, random
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from clinassist import matching as m
d = "data/derived/holdout_seed7"
rd = lambda p: list(csv.DictReader(open(f"{d}/{p}", encoding="utf-8")))
hosp = [m.from_hospital(r) for r in rd("hospital/patients.csv")]
lab = [m.from_laboratory(r) for r in rd("laboratory/lab_patients.csv")]
truth = {r["lab_patient_id"]: r["mrn"] for r in rd("_truth/identity_crosswalk.csv")}
rng = random.Random(1)
names = [h.given for h in hosp]
twins = []
for h in rng.sample(hosp, 40):  # 40 patients get a twin in the hospital
    g = rng.choice([n for n in names if n != h.given and n[:3] != h.given[:3]])
    twins.append(m.Person("hospital", "TWIN-" + h.record_id, h.family, g, h.dob, h.sex))
# hardest case: twin given name differs by ONE letter from the real patient
for h in rng.sample(hosp, 10):
    g = h.given[:-1] + ("A" if h.given[-1] != "A" else "E")
    twins.append(m.Person("hospital", "TWIN1-" + h.record_id, h.family, g, h.dob, h.sex))
links = m.link_system(hosp + twins, lab)
wrong_auto = [l for l in links if l.decision == "auto-link" and truth[l.record_id] != l.mrn]
ok_auto = sum(l.decision == "auto-link" and truth[l.record_id] == l.mrn for l in links)
rev = [l for l in links if l.decision == "review"]
print("hospital now", len(hosp + twins), "incl.", len(twins), "twins")
print("auto-link correct", ok_auto, " wrong merges", len(wrong_auto), " review", len(rev),
      " review top correct", sum(truth[l.record_id] == l.mrn for l in rev))
for l in wrong_auto: print("WRONG", l.record_label, "->", l.mrn, l.hospital_label, l.score)
for l in rev[:6]: print("REVIEW", l.record_label, "->", l.mrn, "|", l.reasons[-1])
