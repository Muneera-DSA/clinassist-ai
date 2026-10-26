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
                    "renal-metformin": "check_renal_dosing", "allergy-match": "check_allergy_conflicts"}

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
        """One Nemotron call for a role on the contract's lane, through the supervisor. If that lane fails, retry once
        on the fast lane (also supervised) and log it."""
        llm = self.llm.for_role(role)
        lane = self._lane(role)
        try:
            reply = llm.chat(system, user, model=lane, **kw)
            reply.lane = lane or (llm.deep_model if kw.get("deep") else llm.model)
            return reply
        except LLMError as e:
            fast = llm.model
            used = lane or (llm.deep_model if kw.get("deep") else fast)
            if not fast or used == fast:
                raise
            self._t(role, "lane-fallback", failed_lane=used, retry_lane=fast, error=str(e)[:160])
            kw.pop("deep", None)
            reply = llm.chat(system, user, model=fast, **kw)
            reply.lane = fast
            return reply

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
                reply = self._ask("planner", BOSS_SYSTEM, prompt, max_tokens=1500)
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
        msg = f"Request: {task}\nPatient: {self.ctx.rec.label if self.ctx.rec else self.ctx.mrn}\nScript results:\n{json.dumps(bundle, default=str)}"
        if feedback:
            msg += ("\n\nYour previous draft FAILED these checks. Fix every one; remove any sentence you cannot support:\n"
                    + json.dumps(feedback[:15]))
        reply = self._ask("writer", WRITER_SYSTEM, msg, deep=self.writer_deep, max_tokens=4000)
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
            reply = self._ask("judge", JUDGE_SYSTEM, f"Draft:\n{draft}\n\nEvidence (script results):\n{json.dumps(bundle, default=str)[:60000]}",
                              max_tokens=1500, temperature=0.0)
            out = extract_json(reply.text)
            concerns = [c for c in (out.get("concerns") or []) if isinstance(c, dict) and c.get("issue")]
            self._t("judge", "review", lane=reply.lane, model=reply.model, seconds=reply.seconds, ok=not concerns, concerns=concerns[:8])
            return [{"type": "judge-concern", "sentence": str(c.get("sentence", ""))[:300], "issue": str(c["issue"])[:200]} for c in concerns[:8]]
        except (LLMError, ActionDenied, ValueError, KeyError, TypeError, AttributeError) as e:
            self._t("judge", "review-unavailable", error=str(e)[:200])
            return []

    # ------------------------------------------------------------ the loop
    def run(self, task: str, ctx: S.Ctx, contract: dict | None = None, require_contract: bool = True) -> AgentResult:
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

        load_errors = [t for t in self.trace if t["action"] == "script-error" and t["tool"] == "fetch_record"]
        if self.ctx.rec is None and load_errors:
            return AgentResult("error", f"Could not load the patient record: {load_errors[-1]['error']}", {}, self.calls, 0, self.trace)

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
