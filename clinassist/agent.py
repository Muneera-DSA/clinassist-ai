"""ClinAssist agent: Nemotron is the boss; Meterless supervises every step.

    Boss      Nemotron (planner lane) reads the script catalog that Meterless H-MEM retrieves for the question, chooses
              which single-action scripts to run, reads a short summary of each result, and decides the next scripts
              or that it has enough. Scripts only fetch, compute, sort or aggregate; Nemotron makes the decisions.
    Writer    Nemotron (writer lane) writes the answer from the script results: summary, how the findings connect,
              questions for the clinician. Every bullet cites evidence ids.
    Checks    enforced by Meterless on every draft, never chosen by the boss:
              1. verify_draft  - deterministic fact-check of every sentence against the source records
              2. judge         - Nemotron on the judge lane reviews meaning (misleading but technically cited wording)
    Repair    a failed check goes back with the exact problems: a missed HIGH finding goes back to the boss (which
              check to run), other problems go to the writer. After the allowed rounds the AI text is NOT shown: the
              verified rule-based summary is shown instead and the case is flagged for a person.
    Meterless every script run, data fetch (Zetaris), Nightshift call and memory lookup passes the supervisor:
              approved against the signed Scout contract and recorded (request, decision, result) in the World Model.

Without AI the agent runs the contract's default plan of scripts and the deterministic writer.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from meterless.scout import verify_contract
from meterless.supervisor import ActionDenied, MemoryRecorder, Supervisor, SupervisedLLM, SupervisedSource

from . import scripts as S
from .llm import LLMError, extract_json, final_answer
from .patient_record import load_identity
from .verifier import Verdict, evaluate, ids_in, template_summary  # noqa: F401  (re-exported for callers)

# HIGH rules and the check script that finds them: the checker requires a HIGH finding to be covered only when its
# check is allowed for this request, and tells the boss which check it missed.
HIGH_RULE_SCRIPT = {"ckd-accelerated": "check_egfr_decline", "renal-alendronate": "check_renal_dosing",
                    "renal-metformin": "check_renal_dosing", "allergy-match": "check_allergy_conflicts",
                    "rx-opioid-benzo": "check_risky_combinations", "rx-raas-dual": "check_risky_combinations"}

TRANSIENT = re.compile(r"empty_response|provider request failed|provider_error|HTTP 50[234]|timed out|Timeout|unreachable", re.I)
PERMANENT = re.compile(r"Function not found|not found|unauthori[sz]ed|forbidden|invalid api key|switched off|HTTP 400", re.I)  # no point retrying
RETRIES = 1          # extra attempt on the role's own lane after a transient provider failure
RETRY_WAIT = 2
# Nemotron's own text switch for short, direct answers. Measured 26 Oct on the app's real boss prompt: with it the boss
# started the investigation correctly (fetch_record) in 14 s; with only the API thinking switch it answered without
# running any script. Set AGENT_NO_THINK=0 in .env to turn it off.
# Reply budget for every Nemotron call. Measured 26 Oct: Lightning sometimes reasons at length even with thinking
# switched off; the reasoning is not returned but counts against max_tokens, so with 1500-2000 the reply came back
# empty (failures took 15-27 s, i.e. the time to fill the budget). With 8000 the same prompt answered 4/4.
WRITER_LENGTH = "Keep the whole answer short: at most about 250 words, only what this request needs."
TOKENS = int(os.environ.get("AGENT_MAX_TOKENS", "8000"))
NO_THINK = "/no_think\n" if os.environ.get("AGENT_NO_THINK", "1") != "0" else ""
PLAN_NOT_ANSWER = ("\n\nIMPORTANT: your previous reply described steps to take or tools to call. The scripts have ALREADY run and "
                   "their results are above. Do not describe a plan. Write the final answer now, in the required sections, and end "
                   "every bullet with the evidence IDs (E-...) of the script results it uses.")


BOSS_SYSTEM = """You are the lead clinical reviewer of ONE patient's record. You do not compute anything yourself: you have
single-action scripts that fetch, compute, sort or aggregate, and you decide which to run, in which order, and when you
have enough. You see a short summary of every result before deciding the next step.
Reply with JSON only:
{"calls": [{"script": "<name>", "args": {...}}], "why": "<one sentence: what you saw and why these scripts>", "done": false}
or, when the evidence covers the request:
{"calls": [], "why": "<one sentence>", "done": true}
Rules: only scripts from the catalog; at most 8 calls per step; never repeat a call; nothing works before fetch_record
(except get_identity_links); follow up on what you see (a criterion met -> the data behind it; a medicine finding ->
the medicine list); run rank_findings last if you ran several checks."""

WRITER_SYSTEM = """You are the clinical reasoning and writing step of a pre-visit review. Use ONLY the script results provided.
Write exactly these sections, as markdown, and nothing before the first heading:

# Pre-visit summary
5-8 bullet sentences, most important first: what the evidence shows.

## How the findings connect
2-4 bullet sentences. Each one links two or more DIFFERENT findings that bear on each other and says why they matter
together (for example, a falling kidney function and a medicine whose safety depends on kidney function; low blood
pressure and several blood-pressure medicines). Each sentence must cite evidence from at least two different findings.
Omit this section if there are fewer than two findings.

## Questions for the clinician
2-4 bullet questions a clinician may want to check, for example whether a result has been confirmed or a calculation done.
Ask about checking and confirming; never about starting, stopping or changing a treatment.

If the request is about which records are linked to the patient, add a section '## Identity links' listing the record ids
from get_identity_links (linked, and waiting for a person); bullets in that section need no citations but may only name
record ids that the script returned.

Rules for every bullet (a separate checker enforces each one; failing drafts are discarded):
- End with citations in square brackets, e.g. [E-lab_result-R123, E-prescription-RXN9]. Use only ids that appear in the results.
- Every number and date must appear in the evidence you cite for that bullet. Do not calculate new numbers.
- Cover every finding whose rule_level is "high" in the summary section.
- Do not diagnose and do not tell anyone to start, stop, increase, decrease or switch a treatment.
- Plain clinical English."""

JUDGE_SYSTEM = """You are an independent clinical reviewer. A separate program has already confirmed that every sentence of
the draft cites real records and that its numbers and dates appear in them. Your job is meaning: find sentences that are
misleading, overstate what the evidence shows, link findings that do not actually bear on each other, or could be read
as advice to change treatment. Reply with JSON only:
{"ok": true|false, "concerns": [{"sentence": "<quote the sentence>", "issue": "<one short sentence>"}]}
Raise a concern only when a clinician could be misled; otherwise reply {"ok": true, "concerns": []}."""


def compact(value: Any, keep_first: int = 2, keep_last: int = 6) -> Any:
    """Shorten long result lists for the writer and judge: keep the first and the most recent rows (with their evidence
    ids) and say how many were left out. Measured 26 Oct: the full eGFR series was 6,000 of the writer's 8,400 input
    characters, and writer calls hit the provider's time limit (about 46 s). The fact-check still uses everything."""
    if isinstance(value, list):
        if len(value) > keep_first + keep_last and all(isinstance(x, dict) for x in value):
            return ([compact(x) for x in value[:keep_first]]
                    + [{"omitted": f"{len(value) - keep_first - keep_last} rows not shown"}]
                    + [compact(x) for x in value[-keep_last:]])
        return [compact(x) for x in value]
    if isinstance(value, dict):
        return {k: compact(v) for k, v in value.items()}
    return value


def observe(name: str, out: Any, limit: int = 1200) -> str:
    """A short, readable summary of a script result for the boss's next decision."""
    try:
        if isinstance(out, dict) and "criterion_met" in out:
            txt = ("criterion met: " + "; ".join(f"[{f['rule_level']}] {f['title']}" for f in out["findings"])) if out["criterion_met"] \
                else "criterion not met"
        elif name == "fetch_record":
            txt = f"loaded {out['counts']}; linked {len(out['linked_records'])}, pending identity review {len(out['pending_review'])}"
        elif name == "compute_trend":
            txt = (f"{out['label']}: {out['direction']}, {out['first']['value']:g} ({out['first']['date']}) -> {out['latest']['value']:g} "
                   f"({out['latest']['date']}) {out['unit']}, slope {out['slope_per_year']}/yr, n={out['n']}") if out.get("available") \
                else f"no results for {out.get('analyte')}"
        elif name == "list_lab_results":
            r = out["results"]
            txt = f"{out['n']} {out['label']} results" + (f", first {r[0]['value']:g} ({r[0]['date']}), last {r[-1]['value']:g} ({r[-1]['date']})" if r else "")
        elif name == "kidney_stage_history":
            txt = f"{out['n']} eGFR results; category changes: " + "; ".join(f"{c['date']} {c['from']}->{c['to']}" for c in out["category_changes"][:12])
        elif name == "list_medications":
            txt = f"{out['n']} medicines: " + "; ".join(f"{m['medication']} ({m['status']}, last {m['last_prescribed']})" for m in out["medications"][:15])
        elif name == "list_problems":
            txt = f"{out['n']} active problems: " + "; ".join(p["display"] for p in out["problems"][:15])
        elif name == "build_timeline":
            txt = "; ".join(f"{e['date']} {e['type']}: {e['text']}" for e in out["events"][:12])
        elif name == "list_emergency_visits":
            txt = f"{out['n']} emergency/inpatient visits: " + "; ".join(f"{e['date']} {e['type']}" for e in out["encounters"][-5:])
        elif name == "get_identity_links":
            txt = f"{len(out['linked_records'])} linked records, {len(out['pending_review'])} waiting for identity review"
        elif name == "rank_findings":
            txt = f"{out['n']} findings ranked: " + "; ".join(f"[{f['rule_level']}] {f['title']}" for f in out["findings"][:12])
        else:
            txt = json.dumps(out, default=str)
    except (KeyError, TypeError, ValueError, IndexError):
        txt = json.dumps(out, default=str)
    return txt[:limit]


def template_from_results(ctx: S.Ctx) -> str:
    """Deterministic writer: a cited summary built only from the script results gathered in this request."""
    L = [f"# Pre-visit summary: {ctx.rec.label if ctx.rec else ctx.mrn}"]
    seen_titles = set()
    for key, out in ctx.gathered.items():
        if isinstance(out, dict) and "findings" in out and not key.startswith("rank_findings"):
            for f in out["findings"]:
                if f["rule_level"] in ("high", "review") and f["evidence"] and f["title"] not in seen_titles:
                    seen_titles.add(f["title"])
                    L.append(f"- {f['title']} [{', '.join(f['evidence'][:4])}].")
    for key, out in ctx.gathered.items():
        if key == "get_patient_details" and isinstance(out, dict):
            L.append("## Patient details (identity)")
            L.append(f"- {out['name']}, MRN {out['mrn']}: born {out['birth_date']}, age {out['age']} on {out['age_on']}, sex {out['sex']}."
                     + (f" Deceased {out['deceased']}." if out.get("deceased") else ""))
            L += [f"- Linked {r['system']} record {r['record_id']} ({r['status']})." for r in out["linked_records"]]
            L += [f"- {r['system'].capitalize()} record {r['record_id']} is waiting for a person's identity decision." for r in out["pending_review"]]
        if key == "list_visits" and isinstance(out, dict) and out.get("visits"):
            kinds = ", ".join(f"{v} {k}" for k, v in out["counts"].items())
            L.append(f"## Hospital visits in the review period: {out['n']} ({kinds})")
            for v in out["visits"][:25]:
                L.append(f"- {v['date']}: {v['kind']}, {v['type']}" + (f" at {v['organisation']}" if v["organisation"] else "") + f" [{v['eid']}].")
        if key == "list_lab_visits" and isinstance(out, dict) and out.get("lab_visits"):
            L.append(f"## Laboratory visits in the review period: {out['n']}")
            for v in out["lab_visits"][:25]:
                L.append(f"- {v['date']}: {v['n']} test(s) collected, accession {v['accessions']} [{v['eid']}].")
    for key, out in ctx.gathered.items():
        if key == "list_lab_results" and isinstance(out, dict) and out.get("tests"):
            L.append("## Laboratory tests in the review period")
            for t in out["tests"][:25]:
                L.append(f"- {t['test']}: {t['n']} result(s), latest {t['latest_value']} {t['unit'] or ''} on {t['latest_date']} [{t['eid']}].".replace(" on", " on", 1))
            break
    if not seen_titles:  # nothing flagged: say which medicines were checked, each with its record
        for key, out in ctx.gathered.items():
            if key.startswith("list_medications") and isinstance(out, dict) and out.get("medications"):
                L.append("## Medicines checked: no safety flag raised")
                for m in out["medications"][:12]:
                    if m.get("evidence"):
                        L.append(f"- {m['medication']}: {m['status']}, last prescribed {m['last_prescribed']} [{m['evidence'][0]}].")
                break
    for key, out in ctx.gathered.items():
        if key.startswith("compute_trend") and isinstance(out, dict) and out.get("available") and out["direction"] != "too few results":
            L.append(f"- {out['label']} is {out['direction']}: {out['first']['value']:g} on {out['first']['date']} and "
                     f"{out['latest']['value']:g} on {out['latest']['date']} [{out['first']['eid']}, {out['latest']['eid']}].")
        if key.startswith("build_timeline") and isinstance(out, dict):
            for e in out["events"]:
                if e["type"] == "emergency":
                    L.append(f"- Emergency visit on {e['date']}: {e['text']} [{', '.join(e['evidence'])}].")
        if key.startswith("get_identity_links") and isinstance(out, dict):
            L.append("## Identity links")
            L += [f"- Linked {r['system']} record {r['record_id']} ({r['status']})." for r in out["linked_records"]]
            L += [f"- {r['system'].capitalize()} record {r['record_id']} is waiting for a person's identity decision and is not used."
                  for r in out["pending_review"]]
            if not out["linked_records"] and not out["pending_review"]:
                L.append("- No laboratory or pharmacy records are linked to this patient.")
    return "\n".join(L)


@dataclass
class AgentResult:
    status: str               # "verified-ai" | "verified-rules" | "escalated" | "refused" (no valid Scout contract)
    summary: str
    verdict: dict
    plan: list[dict]
    rounds: int
    trace: list[dict]


class Agent:
    def __init__(self, llm=None, supervisor: Supervisor | None = None, max_rounds: int = 3,
                 log: Callable[[dict], None] | None = None, writer_deep: bool = True, max_steps: int = 5,
                 max_calls: int = 24, judge: bool = True, memory: Callable[[str], dict] | None = None):
        """llm: Nightshift client (or None for the deterministic path). supervisor: the Meterless supervisor of this
        request (a recorder in memory is used if none is given). memory: H-MEM lookup (query -> {"scripts", "lessons"})."""
        self.raw_llm = llm
        self.sup = supervisor
        self.max_rounds, self.writer_deep = max_rounds, writer_deep
        self.max_steps, self.max_calls, self.use_judge = max_steps, max_calls, judge
        self.memory = memory
        self.trace: list[dict] = []
        self._log = log
        self.contract: dict | None = None
        self.calls: list[dict] = []

    # ------------------------------------------------------------ plumbing
    def _t(self, agent: str, action: str, **detail):
        entry = {"t": round(time.time(), 2), "agent": agent, "action": action, **detail}
        self.trace.append(entry)
        if self._log:
            self._log(entry)

    def _lane(self, role: str) -> str | None:
        return (self.contract or {}).get("lanes", {}).get(role)

    def _ask(self, role: str, system: str, user: str, **kw):
        """One Nemotron call for a role, through the Meterless supervisor.

        Tries the contract's lane for this role (twice on a transient provider failure), then each other Nemotron model
        named in the contract, then the fast lane: one attempt each. Every attempt is approved and recorded by Meterless;
        every switch is logged. Measured 26 Oct: the provider intermittently returns empty replies, and a failure can
        take 20-45 s, so retries on the same model are kept to one."""
        llm = self.llm.for_role(role)
        system = NO_THINK + system
        first = self._lane(role) or (llm.deep_model if kw.get("deep") else llm.model)
        others = [v for v in (self.contract or {}).get("lanes", {}).values() if v]
        candidates = list(dict.fromkeys([first] + others + [llm.model]))
        candidates = [c for c in candidates if c]
        last: LLMError | None = None
        for i, lane in enumerate(candidates):
            tries = 1 + (RETRIES if i == 0 else 0)
            for attempt in range(1, tries + 1):
                try:
                    reply = llm.chat(system, user, model=lane, **{k: v for k, v in kw.items() if k != "deep"})
                    reply.lane = lane
                    return reply
                except LLMError as e:
                    last = e
                    retry_same = attempt < tries and TRANSIENT.search(str(e)) and not PERMANENT.search(str(e))
                    if retry_same:
                        self._t(role, "provider-retry", lane=lane, attempt=attempt, error=str(e)[:160], wait_s=RETRY_WAIT)
                        time.sleep(RETRY_WAIT)
                        continue
                    break
            if i + 1 < len(candidates):
                self._t(role, "lane-fallback", failed_lane=lane, retry_lane=candidates[i + 1], error=str(last)[:160])
        raise last if last else LLMError("no Nightshift lane available")

    def _script(self, name: str, args: dict, actor: str) -> Any:
        """Run one script through the Meterless supervisor."""
        out = self.sup.act("script", name, args, lambda: S.run(name, self.ctx, args), actor=actor, executor="python-script",
                           summarize=lambda o: observe(name, o, 200))
        self.calls.append({"tool": name, "args": args})
        self._t("executor", "script", tool=name, args=args, ids=len(ids_in(out)), by=actor)
        return out

    def _catalog(self, query: str) -> list[dict]:
        """The scripts the boss may use, ranked for this question by Meterless H-MEM (or the local registry offline)."""
        allowed = set(self.contract["tools"]) if self.contract else None
        local = {c["name"]: c for c in S.catalog()}
        ranked, lessons = list(local), []
        if self.memory:
            try:
                mem = self.sup.act("hmem.query", "script-catalog", {"query": query[:300]}, lambda: self.memory(query),
                                   actor="agent", executor="meterless-hmem",
                                   summarize=lambda m: f"{len(m.get('scripts', []))} scripts, {len(m.get('lessons', []))} lessons")
                ranked = [t.split(":", 1)[1] for m in mem.get("scripts", []) for t in m["tags"] if t.startswith("script:")]
                ranked += [n for n in local if n not in ranked]
                lessons = [m["content"] for m in mem.get("lessons", [])]
            except Exception as e:  # noqa: BLE001 - memory is advisory; the registry still bounds what can run
                self._t("meterless", "hmem-unavailable", error=str(e)[:160])
        self._lessons = lessons
        return [local[n] for n in ranked if n in local and (allowed is None or n in allowed)]

    # ------------------------------------------------------------ the boss
    def boss(self, task: str, note: str | None = None, steps: int | None = None) -> None:
        """Nemotron decides which scripts to run, step by step, after reading each result."""
        if note:  # a repair step may go past the normal budget, but only by a little
            self.max_calls = max(self.max_calls, len(self.calls) + 4)
        catalog = self._catalog(task + (" " + note if note else ""))
        cat_text = json.dumps([{k: c[k] for k in ("name", "does", "args", "returns")} for c in catalog])
        self._t("planner", "catalog", scripts=[c["name"] for c in catalog][:40], lessons=len(self._lessons), source="meterless H-MEM" if self.memory else "registry")
        seen: list[str] = [f"{c['tool']} {json.dumps(c['args'])}: {observe(c['tool'], self.ctx.gathered.get(self._key(c)), 600)}"
                           for c in self.calls if self._key(c) in self.ctx.gathered]
        for step in range(1, (steps or self.max_steps) + 1):
            prompt = (f"Request: {task}\nPatient: {self.ctx.mrn}\n"
                      + (f"Checker feedback: {note}\n" if note else "")
                      + (f"Lessons from earlier runs (Meterless memory): {json.dumps(self._lessons)}\n" if self._lessons else "")
                      + f"Script catalog (from Meterless H-MEM, most relevant first): {cat_text}\n"
                      f"Calls made so far: {json.dumps(self.calls)}\n"
                      "Results so far:\n" + ("\n".join(seen) if seen else "(nothing yet)"))
            try:
                reply = self._ask("planner", BOSS_SYSTEM, prompt, max_tokens=TOKENS)
                out = extract_json(reply.text)
                calls = [c for c in (out.get("calls") or []) if isinstance(c, dict) and (c.get("script") or c.get("tool"))]
            except (LLMError, ActionDenied, ValueError, KeyError, TypeError, AttributeError) as e:
                self._t("planner", "boss-step-failed", step=step, error=str(e)[:200])
                break
            done_keys = {self._key(c) for c in self.calls}
            chosen, refused = [], []
            for c in calls:
                c = {"tool": c.get("script") or c.get("tool"), "args": c.get("args") or {}}
                if self._key(c) in done_keys:
                    continue
                if self.contract and c["tool"] not in self.contract["tools"]:
                    refused.append(c["tool"])
                    continue
                chosen.append(c)
            room = max(0, min(8, self.max_calls - len(self.calls)))
            truncated = len(chosen) > room
            chosen = chosen[:room]
            self._t("planner", "boss-step", step=step, lane=reply.lane, model=reply.model, seconds=reply.seconds,
                    calls=chosen, why=str(out.get("why", ""))[:300], done=bool(out.get("done")) or not chosen, outside_contract=refused)
            if refused:
                self._t("meterless", "scripts-outside-contract-refused", scripts=refused)
            for c in chosen:
                try:
                    res = self._script(c["tool"], c["args"], actor="nemotron")
                    seen.append(f"{c['tool']} {json.dumps(c['args'])}: {observe(c['tool'], res)}")
                except Exception as e:  # noqa: BLE001 - recorded by Meterless; the boss sees the error
                    self._t("executor", "script-error", tool=c["tool"], error=str(e)[:200])
                    seen.append(f"{c['tool']} {json.dumps(c['args'])}: ERROR {str(e)[:200]}")
            if (out.get("done") and not truncated) or not chosen or len(self.calls) >= self.max_calls:
                break

    @staticmethod
    def _key(c: dict) -> str:
        args = c.get("args") or {}
        return c["tool"] + (f"({','.join(f'{k}={v}' for k, v in sorted(args.items()))})" if args else "")

    def ensure_required_checks(self) -> None:
        """Meterless-enforced minimum evidence: the checks for the HIGH rules this request must cover run before the
        writer starts, even if the boss stopped early. The boss still chooses everything else. Measured 26 Oct: the
        boss sometimes stopped after loading the record; the fact-check then sent the case back for a whole extra
        round, and the longer redraft hit the provider's time limit."""
        if self.ctx.rec is None and not any(c["tool"] == "fetch_record" for c in self.calls):
            return
        needed = sorted({HIGH_RULE_SCRIPT[r] for r in self.required_rules()})
        missing = [n for n in needed if self._key({"tool": n, "args": {}}) not in self.ctx.gathered]
        if not missing:
            return
        self._t("meterless", "required-checks-added", scripts=missing)
        for name in missing:
            try:
                self._script(name, {}, actor="meterless-enforced")
            except Exception as e:  # noqa: BLE001 - recorded by Meterless; the fact-check will report the gap
                self._t("executor", "script-error", tool=name, error=str(e)[:200])

    def default_plan(self) -> None:
        for step in (self.contract["plan"] if self.contract else []):
            try:
                self._script(step["tool"], step.get("args") or {}, actor="contract-plan")
            except Exception as e:  # noqa: BLE001 - recorded by Meterless; the run reports it below
                self._t("executor", "script-error", tool=step["tool"], error=str(e)[:200])

    # ------------------------------------------------------------ writer, checks
    def write(self, task: str, feedback: list[dict] | None) -> tuple[str, str]:
        if not self.llm:
            self._t("writer", "rule-based-draft", reason="no AI configured")
            return template_from_results(self.ctx), "rules"
        bundle = {k: v for k, v in self.ctx.gathered.items() if not k.startswith("verify_draft")}
        msg = (f"Request: {task}\nPatient: {self.ctx.rec.label if self.ctx.rec else self.ctx.mrn}\n"
               f"Script results:\n{json.dumps(compact(bundle), default=str)}\n\n{WRITER_LENGTH}")
        if getattr(self, "_nodata", None):
            msg += ("\n\nNot found in the records (ClinAssist reports these itself; do not write about missing data): "
                    + " ".join(self._nodata))
        learned = [x for x in (self._lessons or []) if x.startswith("Clinician feedback")]
        if learned:
            msg += ("\n\nLessons from clinician feedback on earlier answers (Meterless memory). Use them for focus and style "
                    "only; every fact must still come from the script results above:\n- " + "\n- ".join(learned[:5]))
            self._t("writer", "lessons-applied", count=len(learned[:5]))
        if feedback:
            msg += ("\n\nYour previous draft FAILED these checks. Fix every one; remove any sentence you cannot support:\n"
                    + json.dumps(feedback[:15]))
        reply = self._ask("writer", WRITER_SYSTEM, msg, deep=self.writer_deep, max_tokens=TOKENS)
        reply.text = final_answer(reply.text, "#")
        if ids_in(bundle) and not ids_in(reply.text):
            # No evidence IDs at all: the model wrote a plan or a refusal, not the cited summary. Correct it once.
            self._t("writer", "not-an-answer", model=reply.model, chars=len(reply.text), text=reply.text[:400])
            reply = self._ask("writer", WRITER_SYSTEM, msg + PLAN_NOT_ANSWER, deep=self.writer_deep, max_tokens=TOKENS)
            reply.text = final_answer(reply.text, "#")
        self._t("writer", "draft", lane=reply.lane, model=reply.model, seconds=reply.seconds, chars=len(reply.text),
                revision=bool(feedback), text=reply.text)
        return reply.text, "ai"

    def required_rules(self) -> set[str]:
        """HIGH rules this request must cover: those found by a check in the intent's core plan."""
        core = {s["tool"] for s in self.contract["plan"]} if self.contract else set(HIGH_RULE_SCRIPT.values())
        return {r for r, s in HIGH_RULE_SCRIPT.items() if s in core}

    def identity_ids(self) -> set[str]:
        out = {self.ctx.mrn}
        for k, v in self.ctx.gathered.items():
            if k.startswith(("get_identity_links", "fetch_record")) and isinstance(v, dict):
                out |= {r["record_id"] for r in v.get("linked_records", []) + v.get("pending_review", [])}
        return out

    def verify(self, draft: str) -> Verdict:
        retrieved = sorted(ids_in({k: v for k, v in self.ctx.gathered.items() if not k.startswith("verify_draft")}))
        out = self.sup.act("script", "verify_draft", {"retrieved": len(retrieved)},
                           lambda: S.run("verify_draft", self.ctx, {"draft": draft, "retrieved": retrieved,
                                                                    "required_rules": sorted(self.required_rules()),
                                                                    "identity_ids": sorted(self.identity_ids())}),
                           actor="meterless-enforced", executor="python-script",
                           summarize=lambda v: f"passed={v['passed']} issues={len(v['issues'])}")
        return Verdict(out["passed"], out["issues"], out["stats"])

    def judge(self, draft: str) -> list[dict]:
        bundle = {k: v for k, v in self.ctx.gathered.items() if not k.startswith("verify_draft")}
        try:
            reply = self._ask("judge", JUDGE_SYSTEM, f"Draft:\n{draft}\n\nEvidence (script results):\n{json.dumps(compact(bundle), default=str)[:60000]}",
                              max_tokens=TOKENS, temperature=0.0)
            out = extract_json(reply.text)
            concerns = [c for c in (out.get("concerns") or []) if isinstance(c, dict) and c.get("issue")]
            self._t("judge", "review", lane=reply.lane, model=reply.model, seconds=reply.seconds, ok=not concerns, concerns=concerns[:8])
            return [{"type": "judge-concern", "sentence": str(c.get("sentence", ""))[:300], "issue": str(c["issue"])[:200]} for c in concerns[:8]]
        except (LLMError, ActionDenied, ValueError, KeyError, TypeError, AttributeError) as e:
            self._t("judge", "review-unavailable", error=str(e)[:200])
            return []

    # ------------------------------------------------------------ the loop
    def run(self, task: str, ctx: S.Ctx, contract: dict | None = None, require_contract: bool = True) -> AgentResult:
        self._nodata: list[str] = []
        self._task = task
        r = self._run(task, ctx, contract, require_contract)
        heading = self.HEADINGS.get(((contract or {}).get("intent") or {}).get("primary") or "")
        if heading and r.summary.startswith("# Pre-visit summary"):
            r.summary = "# " + heading + r.summary[len("# Pre-visit summary"):]
        if self._nodata and r.status in ("verified-ai", "verified-rules", "escalated"):
            # Absences come straight from the scripts' empty results (deterministic), so they are added after the fact-check.
            r.summary = r.summary.rstrip() + "\n\n## Not found in the records\n" + "\n".join(f"- {n}" for n in self._nodata)
        return r

    HEADINGS = {"admin.details": "Patient details and visits", "medication.review": "Medicine safety review", "finding.explain": "Flagged findings", "trend.review": "Lab results and trends",
                "gaps.review": "Missing or overdue tests", "identity.review": "Linked records"}

    # ------------------------------------------------------------ "no data" answers
    FOCUS = ("list_lab_results", "compute_trend", "find_medication", "list_medications", "list_emergency_visits", "list_problems",
             "list_visits", "list_lab_visits")

    def no_data(self) -> tuple[list[str], int]:
        """Plain sentences for what was asked about but is not in the records, and how many focused results exist."""
        rec = self.ctx.rec
        who = rec.label if rec is not None else self.ctx.mrn
        win = next((v.get("window") for k, v in self.ctx.gathered.items() if k.startswith("fetch_record") and isinstance(v, dict)), None) or {}
        span = f"between {win['from']} and {win['to']}" if win.get("from") else "in the review period"
        notes, focused = [], 0
        for k, v in self.ctx.gathered.items():
            name = k.split("(")[0]
            if name not in self.FOCUS or not isinstance(v, dict):
                continue
            focused += 1
            empty = v.get("available") is False or v.get("n") == 0
            if not empty:
                continue
            if name in ("list_lab_results", "compute_trend"):
                label = v.get("label") or str(v.get("analyte", "")).upper()
                intent = ((self.contract or {}).get("intent") or {}).get("primary")
                asked = str(v.get("analyte", "")).lower() in getattr(self, "_task", "").lower() or label.lower() in getattr(self, "_task", "").lower()
                if v.get("analyte") == "all":
                    notes.append(f"No laboratory results are recorded for {who} {span}.")
                    continue
                if intent in ("medication.review", "gaps.review", "summary.previsit", "trend.review") and not asked:
                    continue  # background context for this kind of request, not what was asked about
                notes.append(f"No {label} results are recorded for {who} {span}.")
            elif name == "find_medication":
                notes.append(f"No prescription for {v.get('name')} is recorded for {who} in the hospital or pharmacy records.")
            elif name == "list_medications":
                notes.append(f"No medicines are recorded for {who} in the pharmacy records.")
            elif name == "list_visits":
                notes.append(f"No hospital visits or admissions are recorded for {who} {span}.")
            elif name == "list_lab_visits":
                notes.append(f"No laboratory visits are recorded for {who} {span}.")
            elif name == "list_emergency_visits":
                notes.append(f"No emergency visits are recorded for {who} {span}.")
            elif name == "list_problems":
                notes.append(f"No diagnoses are recorded for {who}.")
        uniq: dict[str, str] = {}
        for n in notes:  # the same absence can come from two scripts (e.g. 'EGFR' and 'eGFR'): say it once
            uniq.setdefault(n.lower(), n)
        return list(uniq.values()), focused

    def _run(self, task: str, ctx: S.Ctx, contract: dict | None = None, require_contract: bool = True) -> AgentResult:
        self.ctx, self.calls, self._lessons = ctx, [], []
        self._t("agent", "start", task=task, patient=ctx.mrn)
        ok, why = verify_contract(contract, ctx.mrn) if (contract is not None or require_contract) else (True, "no contract required")
        self._t("scout", "contract-check", ok=ok, reason=why, contract_id=(contract or {}).get("contract_id"),
                intent=(contract or {}).get("intent"), tools=(contract or {}).get("tools"), lanes=(contract or {}).get("lanes"))
        if not ok:
            return AgentResult("refused", f"Not run: {why}. Requests must pass Scout first.", {"reason": why}, [], 0, self.trace)
        self.contract = contract
        if self.sup is None:  # offline use: supervise in memory
            self.sup = Supervisor(MemoryRecorder(), log=self._log)
            ident = load_identity(ctx.world_dir, ctx.mrn)
            self.sup.mrn = ctx.mrn
            self.sup.decided({"status": "approved", "contract": contract, "intent": (contract or {}).get("intent")},
                             {ctx.mrn} | {r["record_id"] for r in ident["linked_records"]})
        if not isinstance(ctx.source, SupervisedSource):
            ctx.source = SupervisedSource(ctx.source, self.sup, "data")
        self.llm = SupervisedLLM(self.raw_llm, self.sup, "planner") if self.raw_llm else None

        if self.llm:
            self.boss(task)
            if not self.calls:
                self._t("planner", "boss-gave-no-plan-using-contract-plan")
                self.default_plan()
        else:
            self._t("planner", "default-plan", reason="no AI configured", steps=(contract or {}).get("plan"))
            self.default_plan()

        self.ensure_required_checks()

        load_errors = [t for t in self.trace if t["action"] == "script-error" and t["tool"] == "fetch_record"]
        if self.ctx.rec is None and load_errors:
            return AgentResult("error", f"Could not load the patient record: {load_errors[-1]['error']}", {}, self.calls, 0, self.trace)

        notes, focused = self.no_data()
        LABS = ("list_lab_results", "compute_trend")
        empty_lab = any(k.split("(")[0] in LABS and isinstance(v, dict) and (v.get("available") is False or v.get("n") == 0)
                        for k, v in self.ctx.gathered.items())
        if focused and empty_lab and self.contract:
            # Before saying "not in the records", run the contract's own look-ups the boss skipped (e.g. the list of all
            # lab tests for "what blood tests has she had?"). Found 27 Oct: the boss only asked for eGFR and creatinine,
            # both empty, and the answer wrongly said there were no results while 11 other lab results existed.
            skipped = [st for st in self.contract.get("plan", []) if st["tool"] in LABS and self._key(st) not in self.ctx.gathered]
            if skipped:
                self._t("meterless", "lookups-before-no-data", scripts=[self._key(st) for st in skipped])
                for st in skipped:
                    try:
                        self._script(st["tool"], st.get("args") or {}, actor="meterless-enforced")
                    except Exception as e:  # noqa: BLE001 - recorded by Meterless
                        self._t("executor", "script-error", tool=st["tool"], error=str(e)[:200])
                notes, focused = self.no_data()
        empty_focused = sum(1 for k, v in self.ctx.gathered.items() if k.split("(")[0] in self.FOCUS and isinstance(v, dict)
                            and (v.get("available") is False or v.get("n") == 0))
        # Only a pure look-up question ("Is he on metformin?") ends here: if any other check or list ran (a medicine
        # review, a summary), its results are the answer and the missing items are added as a note at the end.
        def has_content(v) -> bool:
            if not isinstance(v, dict):
                return False
            if v.get("criterion_met") is True or (isinstance(v.get("n"), int) and v["n"] > 0):
                return True
            return any(isinstance(v.get(f), list) and v[f] for f in ("medications", "items", "results", "findings", "problems", "visits"))
        enforced = {n for t in self.trace if t.get("action") == "required-checks-added" for n in t.get("scripts", [])}
        other = [k for k, v in self.ctx.gathered.items()
                 if k.split("(")[0] not in self.FOCUS + ("fetch_record", "rank_findings", "build_timeline")
                 and k not in enforced and has_content(v)]
        if focused and empty_focused == focused and not other:
            # Everything the question was about is absent: say so plainly. Nothing to write or fact-check.
            text = "\n".join(f"- {n}" for n in notes)
            self._t("agent", "no-data", notes=notes)
            return AgentResult("no-data", text, {"passed": True, "issues": [], "stats": {}, "reason": "nothing recorded for what was asked"},
                               self.calls, 0, self.trace)
        self._nodata = notes

        feedback, draft, kind, verdict = None, "", "rules", Verdict(False)
        judge_notes: list[dict] = []
        for rnd in range(1, self.max_rounds + 1):
            try:
                draft, kind = self.write(task, feedback)
            except (LLMError, ActionDenied) as e:
                self._t("writer", "ai-unavailable", error=str(e)[:200])
                break
            verdict = self.verify(draft)
            self._t("evaluator", "verdict", round=rnd, passed=verdict.passed, issues=verdict.issues[:20], stats=verdict.stats)
            if verdict.passed and kind == "ai" and self.use_judge:
                judge_notes = self.judge(draft)
                if judge_notes and rnd < self.max_rounds:
                    feedback = judge_notes
                    continue
            if verdict.passed:
                status = "verified-ai" if kind == "ai" else "verified-rules"
                self._t("agent", "done", status=status, rounds=rnd, judge_notes=len(judge_notes))
                return AgentResult(status, draft, {**verdict.__dict__, "judge_notes": judge_notes}, self.calls, rnd, self.trace)
            if kind == "rules":
                break
            missed = [i for i in verdict.issues if i["type"] == "missing-high-finding"]
            if missed:  # the boss decides how to get the evidence for what it missed
                note = "; ".join(f"HIGH finding not covered: {i['finding']} (found by {HIGH_RULE_SCRIPT.get(i.get('rule'), 'a check')})"
                                 for i in missed)
                self._t("planner", "back-to-boss", because=note)
                self.boss(task, note=note, steps=2)
            feedback = verdict.issues
        # Fallback: Meterless makes sure the intent's core HIGH checks have run, then the deterministic writer is used.
        for script in sorted({HIGH_RULE_SCRIPT[r] for r in self.required_rules()} - {c["tool"] for c in self.calls}):
            try:
                self._script(script, {}, actor="meterless-enforced")
            except (ActionDenied, ValueError) as e:
                self._t("executor", "script-error", tool=script, error=str(e)[:200])
        fallback = template_from_results(self.ctx)
        fb = self.verify(fallback)
        reason = (f"AI draft failed verification after {self.max_rounds} rounds" if kind == "ai"
                  else "AI unavailable or rule-based draft failed checks")
        self._t("agent", "escalated", reason=reason, fallback_passed=fb.passed)
        return AgentResult("escalated" if kind == "ai" or not fb.passed else "verified-rules", fallback,
                           {"ai_verdict": verdict.__dict__, "fallback_verdict": fb.__dict__, "reason": reason},
                           self.calls, self.max_rounds, self.trace)
