from datetime import date

from . import script


@script("get_patient_details", kind="fetch",
        does="Give the patient's registration details, no clinical data: name, MRN, date of birth, age, sex, and the IDs of "
             "the laboratory and pharmacy records linked to them.",
        returns="name, mrn, birth_date, age, sex, deceased date if any, linked and pending record ids",
        tags=["details", "demographics", "registration", "age", "date of birth", "sex", "identity", "linked records"])
def run(ctx):
    rec = ctx.need_record()
    p = rec.patient
    born = str(p.get("birth_date") or "")[:10]
    try:
        b = date.fromisoformat(born)
        age = rec.as_of.year - b.year - ((rec.as_of.month, rec.as_of.day) < (b.month, b.day))
    except ValueError:
        age = None
    return {"mrn": rec.mrn, "name": f"{p.get('family_name', '')}, {p.get('given_name', '')}".strip(", "), "birth_date": born or None,
            "age": age, "age_on": rec.as_of.isoformat(), "sex": p.get("sex") or None, "deceased": (p.get("deceased_at") or "")[:10] or None,
            "linked_records": rec.linked, "pending_review": rec.pending}
