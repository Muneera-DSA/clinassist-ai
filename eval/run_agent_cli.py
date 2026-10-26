r"""Run one ClinAssist request from the terminal, exactly as the app does, but without the backend or web app.

    .\.venv\Scripts\python.exe .\eval\run_agent_cli.py
    .\.venv\Scripts\python.exe .\eval\run_agent_cli.py --source zetaris --prompt "Prepare a pre-visit summary"

Scout signs the contract, Nemotron (via Nightshift) is the boss and writer, every action is supervised (recorded in
memory here, not in the World Model). Prints every Nemotron call as it happens: role, lane, seconds, ok or the error.
Used to tell apart "the agent's call pattern fails" from "the backend environment fails". Synthetic data only.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clinassist import scripts as S  # noqa: E402
from clinassist.agent import Agent  # noqa: E402
from clinassist.analysis import load_rules  # noqa: E402
from clinassist.llm import NightshiftLLM  # noqa: E402
from clinassist.patient_record import CsvSource, ZetarisSource  # noqa: E402
from meterless.scout import Scout, load_patients  # noqa: E402
from meterless.supervisor import MemoryRecorder, Supervisor, SupervisedLLM  # noqa: E402

DATA = ROOT / "data" / "derived"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mrn", default="MRN91862E3E")
    ap.add_argument("--prompt", default="Why is his eGFR flagged?")
    ap.add_argument("--source", choices=["csv", "zetaris"], default="csv")
    a = ap.parse_args()

    t0 = time.time()

    def log(entry: dict) -> None:
        t = f"{time.time() - t0:6.1f}s"
        act, agent = entry.get("action"), entry.get("agent")
        if agent == "meterless" and entry.get("kind") == "nightshift.chat":
            if act == "approved-and-done":
                print(f"{t}  NEMOTRON OK    {entry.get('actor')}  {entry.get('target')}  {entry.get('seconds')}s  {entry.get('summary', '')[:60]}")
            elif act == "failed":
                print(f"{t}  NEMOTRON FAIL  {entry.get('actor')}  {entry.get('target')}  {str(entry.get('error', ''))[:110]}")
        elif act == "verdict":
            issues = [f"{i.get('type')}: {str(i.get('sentence') or i.get('finding') or '')[:60]}" for i in entry.get("issues", [])[:4]]
            print(f"{t}  fact-check  {'PASSED' if entry.get('passed') else 'FAILED'}  {issues}")
        elif act in ("boss-step", "provider-retry", "lane-fallback", "not-an-answer", "boss-step-failed", "ai-unavailable",
                     "review", "escalated", "verified", "draft", "required-checks-added", "back-to-boss", "done"):
            extra = entry.get("calls") or entry.get("scripts") or entry.get("retry_lane") or entry.get("error") or entry.get("status") or ""
            print(f"{t}  {agent:<9} {act:<16} {str(extra)[:110]}")

    llm = NightshiftLLM.from_env()
    sup = Supervisor(MemoryRecorder(), log=log)
    user = {"id": "cli-test", "role": "clinician"}
    sup.open(a.prompt, a.mrn, user, True, a.source)
    scout = Scout(patients=load_patients(DATA / "world"), llm=SupervisedLLM(llm, sup, "interpreter"))
    d = scout.decide(a.prompt, a.mrn, user)
    print(f"Scout: {d.status}  intent={d.intent.get('primary')}  lanes={d.contract and d.contract['lanes']}")
    if d.status != "approved":
        sys.exit(d.message)
    sup.decided(d.to_dict(), {a.mrn} | _linked(a.mrn))
    if a.source == "zetaris":
        from clinassist.zetaris_client import ZetarisClient
        src = ZetarisSource(ZetarisClient.from_env())
    else:
        src = CsvSource(DATA)
    from meterless.supervisor import SupervisedSource
    ctx = S.Ctx(a.mrn, date(2026, 10, 24), 3, SupervisedSource(src, sup, a.source), DATA / "world", load_rules())
    r = Agent(llm, supervisor=sup, log=log).run(a.prompt, ctx, contract=d.contract)
    calls = [x for x in sup.actions if x["kind"] == "nightshift.chat"]
    print(f"\nRESULT: {r.status} after {r.rounds} round(s), {time.time() - t0:.0f}s; Nemotron calls: {len(calls)}")
    print(r.summary[:1500])


def _linked(mrn: str) -> set[str]:
    import json
    world = json.loads((DATA / "world" / "patient_identity.json").read_text(encoding="utf-8"))
    p = next((x for x in world.get("patients", []) if x.get("mrn") == mrn), {})
    return {x["record_id"] for x in p.get("linked_records", [])}


if __name__ == "__main__":
    main()
