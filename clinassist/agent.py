"""ClinAssist agent loop: Planner <-> Executor <-> Writer <-> Evaluator, with repair and escalation.

    Planner   decides which evidence tools the task needs (LLM, validated against a whitelist).
    Executor  runs the tools over the patient record (deterministic, Zetaris-backed data).
    Writer    drafts the clinician summary, citing evidence ids on every sentence (LLM).
    Evaluator checks the draft independently and deterministically:
                every sentence cites evidence; every cited id was actually retrieved;
                every number and date is present in the cited evidence; every HIGH finding
                is covered; no treatment directives.
    Repair    missing evidence  -> the Planner's plan is extended with the tool that holds it;
              unsupported text  -> the Writer redrafts with the Evaluator's exact issues.
    Escalate  if the draft still fails after the allowed rounds, the AI text is NOT shown:
              the verified rule-based summary is used and the case is flagged for a person.

Scout   (optional, recommended) the request first passes Scout (clinassist/scout.py), which issues a
        signed execution contract. With a contract the agent verifies it, uses only the tools it allows
        and the Nightshift lane it assigns to each role; with require_contract=True it refuses to run without one.

Every step is written to a trace so a reviewer can see how the output was reached.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .analysis import series
from .llm import LLMError, extract_json, final_answer
from .patient_record import PatientRecord
from .scout import verify_contract

# ---------------------------------------------------------------------------- tools

TOOL_HELP = {
    "findings": "rule-based flags with severity, detail and evidence ids (always useful)",
    "trends": "lab trend summaries; args: {\"analytes\": [one or more of the analyte keys]}",
    "medications": "medication list with status and prescribing history; args: {\"active_only\": true|false}",
    "problems": "active problem list (diagnoses)",
    "timeline": "key dated events: diagnoses, emergency visits, medication starts, flags",
    "identity": "which source records were linked to this patient, and any still waiting for identity review",
    "lab_series": "every result for one analyte; args: {\"analyte\": key}",
    "encounters": "emergency and inpatient encounters in the window",
}
DEFAULT_PLAN = [{"tool": "findings", "args": {}}, {"tool": "trends", "args": {"analytes": ["egfr", "creatinine", "hba1c", "potassium"]}},
                {"tool": "medications", "args": {"active_only": True}}, {"tool": "timeline", "args": {}},
                {"tool": "identity", "args": {}}]


def run_tool(step: dict, rec: PatientRecord, result: dict, rules: dict) -> Any:
    tool, args = step["tool"], step.get("args") or {}
    if tool == "findings":
        return result["findings"]
    if tool == "trends":
        keys = [k for k in args.get("analytes", list(result["trends"])) if k in result["trends"]]
        return {k: {x: v for x, v in result["trends"][k].items() if x != "points"} for k in keys}
    if tool == "medications":
        meds = result["medications"]
        return [m for m in meds if m["status"] == "active"] if args.get("active_only", True) else meds
    if tool == "problems":
        return result["active_conditions"]
    if tool == "timeline":
        return result["timeline"]
    if tool == "identity":
        return result["identity"]
    if tool == "lab_series":
        a = rules["analytes"].get(args.get("analyte", ""))
        if not a:
            raise ValueError(f"unknown analyte {args.get('analyte')!r}")
        return [{"date": p.when.date().isoformat(), "value": p.value, "eid": p.eid} for p in series(rec, a["loinc"])]
    if tool == "encounters":
        return [{"date": i.when.date().isoformat(), "class": i.row["encounter_class"], "type": i.row["type_display"],
                 "reason": i.row["reason_display"], "eid": i.eid}
                for i in rec.of("encounter") if i.row["encounter_class"] in ("EMER", "IMP")]
    raise ValueError(f"unknown tool {tool!r}")


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
    out = []
    for line in text.splitlines():
        line = line.strip().lstrip("-*• ").strip()
        if not line or line.startswith("#"):
            continue
        out += [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", line) if s.strip()]
    return out


@dataclass
class Verdict:
    passed: bool
    issues: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def fact_text(rec: PatientRecord, result: dict) -> dict[str, str]:
    """For every evidence id: the source row plus any finding/trend text built on it."""
    facts = {}
    for i in rec.items:
        # The raw row, plus "value unit" written side by side: in the row the unit sits in its own field, so
        # "459.23 mg/g" in a draft could not be matched to it (found in the 26 Oct Nemotron benchmark).
        pairs = [f"{i.row.get(v)} {i.row.get(u) or ''}" for v, u in (("value_num", "unit"), ("dose_value", "dose_unit"))
                 if i.row.get(v) not in (None, "")]
        facts[i.eid] = json.dumps(i.row, default=str) + (" | " + " ; ".join(pairs) if pairs else "")
    for f in result["findings"]:
        for e in f["evidence"]:
            facts[e] = facts.get(e, "") + " " + f["title"] + " " + f["detail"]
    for t in result["trends"].values():
        txt = json.dumps({k: v for k, v in t.items() if k not in ("points", "evidence")}, default=str)
        for e in t["evidence"]:
            facts[e] = facts.get(e, "") + " " + txt
    for e in result["timeline"]:
        for x in e["evidence"]:
            facts[x] = facts.get(x, "") + f" {e['date']} {e['text']}"
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


def evaluate(draft: str, retrieved: set[str], rec: PatientRecord, result: dict) -> Verdict:
    facts = fact_text(rec, result)
    issues: list[dict] = []
    cited_all: set[str] = set()
    per_sentence: list[set[str]] = []
    sents = sentences(draft)
    for s in sents:
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
    # A HIGH finding counts as covered only if ONE sentence cites at least two of its evidence records (or its
    # only record). Overlap anywhere in the summary is not enough: a trend sentence can cite one of the same lab
    # results while the alert itself has been dropped (found in notebook 05, fixed 25 Oct).
    for f in result["findings"]:
        ev = set(f["evidence"])
        need = min(2, len(ev))
        if f["severity"] == "high" and ev and not any(len(ev & s) >= need for s in per_sentence):
            issues.append({"type": "missing-high-finding", "finding": f["title"], "evidence": f["evidence"][:3]})
    if not sents:
        issues.append({"type": "empty"})
    return Verdict(not issues, issues, {"sentences": len(sents), "cited_ids": len(cited_all)})


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


WRITER_SYSTEM = """You write concise pre-visit summaries for a clinician, using ONLY the evidence provided.
Rules (a separate checker enforces every one; failing drafts are discarded):
- Every sentence ends with citations in square brackets, e.g. [E-lab_result-R123, E-prescription-RXN9]. Use only ids that appear in the evidence.
- Every number and date you write must appear in the evidence you cite for that sentence. Do not calculate new numbers.
- Cover every finding with severity "high".
- Do not diagnose and do not tell anyone to start, stop, increase, decrease or switch a treatment. Describe what the evidence shows and what needs a clinician's review.
- Plain clinical English, 6-10 bullet sentences, most important first. Start with a heading line '# Pre-visit summary'."""

PLANNER_SYSTEM = """You plan evidence retrieval for a clinical summary agent. Reply with JSON only:
{"steps": [{"tool": "<name>", "args": {...}, "why": "<short reason>"}]}
Choose only tools from the catalog. Prefer a small plan (3-6 steps) that covers what the task needs."""


@dataclass
class AgentResult:
    status: str               # "verified-ai" | "verified-rules" | "escalated" | "refused" (no valid Scout contract)
    summary: str
    verdict: dict
    plan: list[dict]
    rounds: int
    trace: list[dict]


class Agent:
    def __init__(self, llm=None, max_rounds: int = 3, log: Callable[[dict], None] | None = None, writer_deep: bool = True):
        self.llm = llm
        self.writer_deep = writer_deep
        self.max_rounds = max_rounds
        self.trace: list[dict] = []
        self._log = log
        self.contract: dict | None = None

    def _lane(self, role: str) -> str | None:
        return (self.contract or {}).get("lanes", {}).get(role)

    def _allowed(self, steps: list[dict]) -> list[dict]:
        if not self.contract:
            return steps
        tools = set(self.contract["tools"])
        kept = [s for s in steps if s.get("tool") in tools]
        if len(kept) < len(steps):
            self._t("scout", "steps-outside-contract-dropped", dropped=[s.get("tool") for s in steps if s.get("tool") not in tools])
        return kept

    def _ask(self, role: str, system: str, user: str, **kw):
        """One AI call for a role, on the lane the Scout contract assigns. If that lane fails (the provider behind it
        is down or not available to this account, or it times out), retry once on the fast lane and log it."""
        lane = self._lane(role)
        try:
            reply = self.llm.chat(system, user, model=lane, **kw)
            reply.lane = lane or (getattr(self.llm, "deep_model", None) if kw.get("deep") else getattr(self.llm, "model", None))
            return reply
        except LLMError as e:
            fast = getattr(self.llm, "model", None)
            used = lane or (getattr(self.llm, "deep_model", None) if kw.get("deep") else fast)
            if not fast or used == fast:
                raise
            self._t(role, "lane-fallback", failed_lane=used, retry_lane=fast, error=str(e)[:160])
            kw.pop("deep", None)
            reply = self.llm.chat(system, user, model=fast, **kw)
            reply.lane = fast
            return reply

    def _t(self, agent: str, action: str, **detail):
        entry = {"t": round(time.time(), 2), "agent": agent, "action": action, **detail}
        self.trace.append(entry)
        if self._log:
            self._log(entry)

    # -- planner
    def plan(self, task: str, result: dict, rules: dict) -> list[dict]:
        base = [dict(s) for s in (self.contract["plan"] if self.contract else DEFAULT_PLAN)]
        if not self.llm:
            self._t("planner", "default-plan", reason="no AI configured", source="scout contract" if self.contract else "default", steps=base)
            return base
        header = {"patient": result["patient"]["label"], "counts": result["counts"],
                  "finding_titles": [f"[{f['severity']}] {f['title']}" for f in result["findings"]],
                  "analyte_keys": list(result["trends"])}
        catalog = {k: v for k, v in TOOL_HELP.items() if not self.contract or k in self.contract["tools"]}
        prompt = f"Task: {task}\nPatient overview: {json.dumps(header)}\nTool catalog: {json.dumps(catalog)}"
        try:
            reply = self._ask("planner", PLANNER_SYSTEM, prompt, max_tokens=2000)
            steps = extract_json(reply.text)["steps"]
            valid = self._allowed([s for s in steps if isinstance(s, dict) and s.get("tool") in TOOL_HELP])
            dropped = len(steps) - len(valid)
            if not valid:
                raise ValueError("no valid steps")
            self._t("planner", "plan", lane=reply.lane, model=reply.model, seconds=reply.seconds, steps=valid,
                    dropped_invalid=dropped)
            return valid
        except (LLMError, ValueError, KeyError, TypeError) as e:
            self._t("planner", "plan-failed-using-default", error=str(e)[:200], steps=base)
            return base

    # -- executor
    def execute(self, plan: list[dict], rec: PatientRecord, result: dict, rules: dict) -> dict:
        bundle = {}
        for i, step in enumerate(plan):
            key = f"{i + 1}:{step['tool']}"
            try:
                bundle[key] = run_tool(step, rec, result, rules)
                self._t("executor", "tool", tool=step["tool"], args=step.get("args") or {}, ids=len(ids_in(bundle[key])))
            except ValueError as e:
                self._t("executor", "tool-error", tool=step["tool"], error=str(e))
        return bundle

    # -- writer
    def write(self, task: str, bundle: dict, result: dict, feedback: list[dict] | None) -> tuple[str, str]:
        if not self.llm:
            self._t("writer", "rule-based-draft", reason="no AI configured")
            return template_summary(result), "rules"
        msg = f"Task: {task}\nPatient: {result['patient']['label']}\nEvidence:\n{json.dumps(bundle, default=str)}"
        if feedback:
            msg += ("\n\nYour previous draft FAILED these checks. Fix every one; remove any sentence you cannot support:\n"
                    + json.dumps(feedback[:15]))
        reply = self._ask("writer", WRITER_SYSTEM, msg, deep=self.writer_deep, max_tokens=4000)
        reply.text = final_answer(reply.text, "#")
        self._t("writer", "draft", lane=reply.lane, model=reply.model, seconds=reply.seconds, chars=len(reply.text),
                revision=bool(feedback), text=reply.text)
        return reply.text, "ai"

    # -- the loop
    def run(self, task: str, rec: PatientRecord, result: dict, rules: dict, contract: dict | None = None,
            require_contract: bool = False) -> AgentResult:
        self._t("agent", "start", task=task, patient=result["patient"]["mrn"])
        if contract is not None or require_contract:
            ok, why = verify_contract(contract, result["patient"]["mrn"])
            self._t("scout", "contract-check", ok=ok, reason=why, contract_id=(contract or {}).get("contract_id"),
                    intent=(contract or {}).get("intent"), tools=(contract or {}).get("tools"), lanes=(contract or {}).get("lanes"))
            if not ok:
                return AgentResult("refused", f"Not run: {why}. Requests must pass Scout first.", {"reason": why}, [], 0, self.trace)
            self.contract = contract
        plan = self.plan(task, result, rules)
        feedback = None
        draft, kind, verdict = "", "rules", Verdict(False)
        for rnd in range(1, self.max_rounds + 1):
            bundle = self.execute(plan, rec, result, rules)
            retrieved = ids_in(bundle)
            try:
                draft, kind = self.write(task, bundle, result, feedback)
            except LLMError as e:
                self._t("writer", "ai-unavailable", error=str(e)[:200])
                break
            verdict = evaluate(draft, retrieved, rec, result)
            self._t("evaluator", "verdict", round=rnd, passed=verdict.passed, issues=verdict.issues[:20], stats=verdict.stats)
            if verdict.passed:
                status = "verified-ai" if kind == "ai" else "verified-rules"
                self._t("agent", "done", status=status, rounds=rnd)
                return AgentResult(status, draft, verdict.__dict__, plan, rnd, self.trace)
            if kind == "rules":
                break  # the deterministic writer cannot improve by retrying
            # Repair 1: a HIGH finding's evidence was never retrieved -> extend the plan
            missing = [i for i in verdict.issues if i["type"] == "missing-high-finding" and not (set(i["evidence"]) & retrieved)]
            if missing and not any(s["tool"] == "findings" for s in plan):
                plan = plan + [{"tool": "findings", "args": {}, "why": "evaluator: high finding evidence not retrieved"}]
                self._t("planner", "revise-plan", added="findings", because=[m["finding"] for m in missing])
            # Repair 2: redraft with the exact issues
            feedback = verdict.issues
        # Escalate: never show unverified AI text
        fallback = template_summary(result)
        fb_verdict = evaluate(fallback, ids_in(result), rec, result)
        reason = ("AI draft failed verification after "
                  f"{self.max_rounds} rounds" if kind == "ai" else "AI unavailable or rule-based draft failed checks")
        self._t("agent", "escalated", reason=reason, fallback_passed=fb_verdict.passed)
        return AgentResult("escalated" if kind == "ai" or not fb_verdict.passed else "verified-rules",
                           fallback, {"ai_verdict": verdict.__dict__, "fallback_verdict": fb_verdict.__dict__, "reason": reason},
                           plan, self.max_rounds, self.trace)
