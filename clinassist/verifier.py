"""The fact-checker: verifies every sentence of a draft against the source records. Deterministic on purpose:
its job is exact lookup (do the cited records exist and were they retrieved, does every number and date appear in
them, is every HIGH finding covered, does a "connection" stand on two findings, is there a treatment order), and an
AI checking its own writing would not be an independent check. Meterless runs it on every draft (verify_draft);
the boss cannot skip it. A Nemotron judge adds a meaning-level review after it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .patient_record import PatientRecord

# ---------------------------------------------------------------------------- evidence ids

EID = re.compile(r"E-[a-z_]+-[A-Za-z0-9:-]+")  # ids may contain ":" (blood-pressure components)


def ids_in(obj: Any) -> set[str]:
    return set(EID.findall(json.dumps(obj, default=str)))


# ---------------------------------------------------------------------------- evaluator

NUM = re.compile(r"(?<![A-Za-z0-9.\-])\d+(?:\.\d+)?(?![A-Za-z0-9])")
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
CITE = re.compile(r"\[(E-[^\]]+)\]")
TREAT_VERB = r"(start\w*|stop\w*|discontinu\w*|increas\w*|decreas\w*|switch\w*|prescrib\w*|chang\w*|reduc\w*|withh[oe]ld\w*|titrat\w*|cease\w*|hold|held)"
DIRECTIVE = re.compile(r"\b(should|must|need(?:s)? to|ought to|recommend(?:ed|s)?(?: to| that)?|advis(?:e|ed|es)(?: to)?|consider)\s+"
                       r"(?:(?:be|being|not)\s+)*" + TREAT_VERB + r"\b", re.I)
DIAGNOSE = re.compile(r"\b(is diagnosed with|we diagnose|diagnosis is|confirms? (a |the )?diagnosis)\b", re.I)


def sentences(text: str) -> list[str]:
    return [s for _, s in sectioned(text)]


SECTION_CONNECT = re.compile(r"connect|link|together|picture", re.I)
SECTION_QUESTIONS = re.compile(r"question", re.I)
SECTION_IDENTITY = re.compile(r"identity|linked record", re.I)
RECORD_ID = re.compile(r"\b(?:MRN|LP|RX)[0-9A-F]{6,9}\b")


def sectioned(text: str) -> list[tuple[str, str]]:
    """(section, sentence) pairs: section is 'summary', 'connections' or 'questions', from the heading above."""
    out, section = [], "summary"
    for line in text.splitlines():
        raw = line.strip()
        if raw.startswith("#"):
            h = raw.lstrip("#").strip()
            section = ("questions" if SECTION_QUESTIONS.search(h) else "identity" if SECTION_IDENTITY.search(h)
                       else "connections" if SECTION_CONNECT.search(h) else "summary")
            continue
        line = raw.lstrip("-*• ").strip()
        if not line:
            continue
        out += [(section, s.strip()) for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", line) if s.strip()]
    return out


@dataclass
class Verdict:
    passed: bool
    issues: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _guideline_texts() -> dict[str, str]:
    """Guideline titles from the approved rule file (config/clinical_rules.json), by source id."""
    try:
        from .analysis import load_rules
        return {k: (v.get("title") or "") for k, v in (load_rules().get("sources") or {}).items() if isinstance(v, dict)}
    except Exception:  # noqa: BLE001 - without the rule file only record values count as support
        return {}


def fact_text(rec: PatientRecord, result: dict) -> dict[str, str]:
    """For every evidence id: the source row plus any finding/trend text built on it."""
    facts = {}
    for i in (rec.items if rec is not None else []):
        # The raw row, plus "value unit" written side by side: in the row the unit sits in its own field, so
        # "459.23 mg/g" in a draft could not be matched to it (found in the 26 Oct Nemotron benchmark).
        pairs = [f"{i.row.get(v)} {i.row.get(u) or ''}" for v, u in (("value_num", "unit"), ("dose_value", "dose_unit"))
                 if i.row.get(v) not in (None, "")]
        facts[i.eid] = json.dumps(i.row, default=str) + (" | " + " ; ".join(pairs) if pairs else "")
    sources = _guideline_texts()
    for f in result["findings"]:
        # The finding's own guideline text (from the approved rule file) counts as support for the guideline's numbers,
        # e.g. NICE NG203 "25% or more ... 15 ml/min/1.73 m2 per year". Found 26 Oct: Nemotron quoted the criterion
        # correctly and the checker rejected it. Patient values must still match the patient's records.
        guide = sources.get(f.get("source") or "", "")
        for e in f["evidence"]:
            facts[e] = facts.get(e, "") + " " + f["title"] + " " + f["detail"] + (" | guideline: " + guide if guide else "")
    for t in result["trends"].values():
        txt = json.dumps({k: v for k, v in t.items() if k not in ("points", "evidence")}, default=str)
        for e in t["evidence"]:
            facts[e] = facts.get(e, "") + " " + txt
    for e in result["timeline"]:
        for x in e["evidence"]:
            facts[x] = facts.get(x, "") + f" {e['date']} {e['text']}"
    for e, txt in (result.get("script_facts") or {}).items():
        facts[e] = facts.get(e, "") + txt
    return facts


UNIT_AFTER = re.compile(r"^\s*(mg|mcg|g|ml|l|%|mmol|umol|unt|units?|iu|meq|mm|cm|kg)\b", re.I)
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ][\d:.]+(?:[+-]\d{2}:\d{2}|Z)?)?")
UNIT_WORDS = {"mg", "mcg", "g", "ml", "l", "%", "mmol", "umol", "unt", "unit", "units", "iu", "meq", "mm", "cm", "kg",
              "day", "days", "week", "weeks", "month", "months", "year", "years"}


def _unit(after: str) -> str:
    """The unit word right after a number ('10 MG' -> 'mg', '12 months' -> 'months'), or '' if none."""
    m = re.match(r"^\s*(%|[A-Za-z]+)", after)
    w = m.group(1).lower() if m else ""
    return w.rstrip("s") if w in UNIT_WORDS else ""


def _num_ok(n: str, after: str, text: str) -> bool:
    """A number is supported if a cited source holds the same value (at the same precision) with the same unit."""
    x = float(n)
    if x < 10 and "." not in n and not UNIT_AFTER.match(after):
        return True  # small counts ("2 visits", "type 2") are not checked; doses and measurements always are
    dec = len(n.split(".")[1]) if "." in n else 0
    unit = _unit(after)
    clean = TIMESTAMP.sub(" ", text)  # times of day inside timestamps are not evidence for values
    for m in NUM.finditer(clean):
        try:
            if round(float(m.group(0)), dec) == round(x, dec) and _unit(clean[m.end():]) == unit:
                return True
        except ValueError:
            continue
    return False


def evaluate(draft: str, retrieved: set[str], rec: PatientRecord, result: dict, required_rules: set[str] | None = None,
             identity_ids: set[str] | None = None) -> Verdict:
    """required_rules: the HIGH rules this request must cover; None = every HIGH rule.
    identity_ids: record ids an 'Identity links' section may name (that section lists records, so it needs no citations)."""
    facts = fact_text(rec, result)
    issues: list[dict] = []
    cited_all: set[str] = set()
    per_sentence: list[set[str]] = []
    pairs = sectioned(draft)
    sents = [x for _, x in pairs]
    counts = {"connections": 0, "questions": 0}
    findings = [set(f["evidence"]) for f in result["findings"] if f["evidence"]]
    for section, s in pairs:
        if section == "identity":
            unknown_records = [r for r in RECORD_ID.findall(s) if r not in (identity_ids or set())]
            if unknown_records or identity_ids is None:
                issues.append({"type": "unknown-record", "sentence": s, "ids": unknown_records})
            continue
        cites = [c.strip() for grp in CITE.findall(s) for c in grp.split(",")]
        body = CITE.sub("", s)
        if not cites:
            issues.append({"type": "uncited", "sentence": s})
            continue
        unknown = [c for c in cites if c not in retrieved]
        if unknown:
            issues.append({"type": "unknown-evidence", "sentence": s, "ids": unknown})
        known = [c for c in cites if c in retrieved]
        cited_all.update(known)
        per_sentence.append(set(known))
        ctx = " ".join(facts.get(c, "") for c in known)
        for d in DATE.findall(body):
            if d not in ctx:
                issues.append({"type": "unsupported-date", "sentence": s, "value": d})
        nodates = DATE.sub("", body)
        for m in NUM.finditer(nodates):
            if not _num_ok(m.group(0), nodates[m.end():], ctx):
                issues.append({"type": "unsupported-number", "sentence": s, "value": m.group(0)})
        if DIRECTIVE.search(body) or DIAGNOSE.search(body):
            issues.append({"type": "treatment-directive", "sentence": s})
        if section in counts:
            counts[section] += 1
        # A sentence that claims findings connect must stand on at least two different findings' evidence:
        # Nemotron may reason across findings, but not invent a link that no finding supports.
        if section == "connections":
            touched = sum(1 for ev in findings if ev & set(known))
            if touched < 2:
                issues.append({"type": "connection-not-grounded", "sentence": s, "findings_cited": touched})
    # A HIGH finding counts as covered only if ONE sentence cites at least two of its evidence records (or its
    # only record). Overlap anywhere in the summary is not enough: a trend sentence can cite one of the same lab
    # results while the alert itself has been dropped (found in notebook 05, fixed 25 Oct).
    for f in result["findings"]:
        ev = set(f["evidence"])
        need = min(2, len(ev))
        if required_rules is not None and f["rule"] not in required_rules:
            continue
        if f["severity"] == "high" and ev and not any(len(ev & s) >= need for s in per_sentence):
            issues.append({"type": "missing-high-finding", "finding": f["title"], "rule": f["rule"], "evidence": f["evidence"][:3]})
    if not sents:
        issues.append({"type": "empty"})
    return Verdict(not issues, issues, {"sentences": len(sents), "cited_ids": len(cited_all), **counts})


# ---------------------------------------------------------------------------- writers

def template_summary(result: dict) -> str:
    """Deterministic, rule-based summary: the fallback when AI is unavailable or fails verification."""
    L = [f"# Pre-visit summary: {result['patient']['label']}"]
    for f in result["findings"]:
        if f["severity"] in ("high", "review") and f["evidence"]:
            L.append(f"- {f['title']} [{', '.join(f['evidence'][:4])}].")
    for key in ("egfr", "hba1c"):
        t = result["trends"].get(key)
        if t and t["direction"] != "too few results":
            L.append(f"- {t['label']} is {t['direction']}: {t['first']['value']:g} on {t['first']['date']} and "
                     f"{t['latest']['value']:g} on {t['latest']['date']} [{t['first']['eid']}, {t['latest']['eid']}].")
    for e in result["timeline"]:
        if e["type"] == "emergency":
            L.append(f"- Emergency visit on {e['date']}: {e['text']} [{', '.join(e['evidence'])}].")
    return "\n".join(L)
