r"""One-time fetch of official US FDA drug labels (openFDA) for every medicine in the synthetic pharmacy data.

    .\.venv\Scripts\python.exe .\reference\fetch_drug_labels.py

Needs internet once. Writes reference\drug_labels.json, which the prescription finder reads offline. For each distinct
medicine (by RxNorm code) it looks up the FDA label: first by RxNorm code, then by generic name. A label found by name is
kept only if its active ingredients are exactly the medicine's (so a hydrocodone-only medicine never gets a
hydrocodone + acetaminophen label); otherwise the medicine is listed as having no exact label. It keeps the label's own
wording for: boxed warning, indications, contraindications, warnings and precautions, adverse reactions, drug interactions,
plus the label id, version date and a DailyMed link to the source. Medicines with no FDA label match are listed as
"no label found" - nothing is ever filled in from anywhere else.

openFDA is public, free and needs no key (limit 240 requests a minute; this script waits between requests).
Reference information from the label, not advice: it does not say what a particular patient should take.
"""
from __future__ import annotations

import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clinassist.analysis import ingredient  # noqa: E402

URL = "https://api.fda.gov/drug/label.json"
OUT = ROOT / "reference" / "drug_labels.json"
SECTIONS = {
    "boxed_warning": ["boxed_warning"],
    "indications": ["indications_and_usage"],
    "contraindications": ["contraindications"],
    "warnings": ["warnings_and_cautions", "warnings"],
    "adverse_reactions": ["adverse_reactions"],
    "drug_interactions": ["drug_interactions"],
}
MAX_CHARS = 1500  # per section; the full text is one click away on DailyMed


SALT_AND_FORM = set("""hydrochloride hcl sulfate bitartrate sodium potassium maleate hyclate propionate acetate porcine calcium
succinate tartrate phosphate hydrobromide bromide mesylate besylate citrate monohydrate macrocrystals human usp hfa and with
low dose extended release tablets tablet capsules capsule injection oral solution suspension of the in for""".split())
ALIAS = {"vitamin b12": "cyanocobalamin"}


def cores(text: str) -> frozenset[str]:
    """Active-ingredient words, ignoring salts, dose forms and numbers: 'Oxycodone and Acetaminophen' -> {oxycodone, acetaminophen}."""
    words = re.findall(r"[a-z]+", (text or "").lower())
    return frozenset(w for w in words if len(w) > 2 and w not in SALT_AND_FORM)


def label_generic(lab: dict) -> str:
    of = lab.get("openfda") or {}
    return " / ".join(of.get("generic_name") or of.get("substance_name") or [])


def query(search: str, limit: int = 1):
    for attempt in range(3):
        try:
            r = requests.get(URL, params={"search": search, "limit": limit}, timeout=30)
        except requests.RequestException as e:
            if attempt == 2:
                raise SystemExit(f"Cannot reach openFDA ({type(e).__name__}). Check the internet connection and run again.")
            time.sleep(3)
            continue
        if r.status_code == 404:
            return None  # openFDA answers 404 when nothing matches
        if r.status_code == 429:
            time.sleep(20)
            continue
        r.raise_for_status()
        res = r.json().get("results") or []
        return res if limit > 1 else (res[0] if res else None)
    return None


def exact(search: str, want: frozenset[str]):
    """Among up to 25 labels for a name search, the first whose active ingredients are exactly `want`."""
    for lab in query(search, limit=25) or []:
        if cores(label_generic(lab)) == want:
            return lab
    return None


def clean(text: str) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    return t if len(t) <= MAX_CHARS else t[:MAX_CHARS].rsplit(" ", 1)[0] + " … (shortened; full text on DailyMed)"


def find_label(rxcui: str, ing: str):
    lab = query(f'openfda.rxcui:"{rxcui}"')
    if lab:
        return lab, "RxNorm code"
    low = ing.lower()
    for k, v in ALIAS.items():
        if low.startswith(k):
            ing = v
    names = [n.strip() for n in ing.split(" / ") if n.strip()]
    want = cores(" ".join(names))
    if not want:
        return None, ""
    if len(names) == 1:
        lab = exact(f'openfda.generic_name:"{names[0]}"', want)
        if lab:
            return lab, "generic name, same ingredients"
        base = names[0].split()[0]  # 'metformin hydrochloride' -> 'metformin'
        lab = exact(f'openfda.generic_name:"{base}"', want)
        if lab:
            return lab, "generic name, same ingredients"
    else:
        lab = exact(" AND ".join(f'openfda.generic_name:"{n.split()[0]}"' for n in names), want)
        if lab:
            return lab, "generic names, same ingredients"
    return None, ""


def main() -> None:
    meds: dict[str, str] = {}
    with (ROOT / "data" / "derived" / "pharmacy" / "prescriptions.csv").open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            meds.setdefault(row["rxnorm_code"].strip(), row["medication"].strip())
    print(f"{len(meds)} distinct medicines in the pharmacy data. Fetching FDA labels (about {len(meds) * 0.6:.0f} s)...")
    labels, missing = {}, []
    for i, (rxcui, med) in enumerate(sorted(meds.items(), key=lambda kv: kv[1].lower()), 1):
        ing = ingredient(med)
        lab, how = find_label(rxcui, ing)
        time.sleep(0.3)
        if not lab:
            missing.append({"rxnorm_code": rxcui, "medication": med, "ingredient": ing})
            print(f"  {i:3}/{len(meds)}  no exact label   {med}")
            continue
        of = lab.get("openfda") or {}
        sections = {}
        for key, fields in SECTIONS.items():
            for fld in fields:
                if lab.get(fld):
                    sections[key] = clean(" ".join(lab[fld]))
                    break
        set_id = lab.get("set_id") or (of.get("spl_set_id") or [None])[0]
        labels[rxcui] = {
            "medication": med, "ingredient": ing, "matched_by": how,
            "label_title": ", ".join((of.get("brand_name") or of.get("generic_name") or [med])[:2]),
            "label_generic": label_generic(lab),
            "manufacturer": (of.get("manufacturer_name") or [""])[0],
            "label_id": lab.get("id"), "set_id": set_id, "label_version_date": lab.get("effective_time"),
            "source_url": f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={set_id}" if set_id else None,
            "sections": sections,
        }
        print(f"  {i:3}/{len(meds)}  found ({how:<31}) {med}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "_note": "Sections quoted from official US FDA drug labels via openFDA (api.fda.gov). Reference information, not advice. "
                 "Matched to the synthetic pharmacy data by RxNorm code, else by generic name with exactly the same active "
                 "ingredients; the matched label may be a different manufacturer's version of the same medicine.",
        "source": "openFDA drug label endpoint, https://api.fda.gov/drug/label.json",
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "labels": labels, "not_found": missing}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nDone: {len(labels)} labels found, {len(missing)} without an exact label. Saved {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
