"""Meterless supervisor: nothing in ClinAssist happens without Meterless approving and recording it.

Every request is recorded in the Meterless World Model with Scout's decision (and the signed contract). After that,
every action - a script run, a data fetch through Zetaris, a call to Nightshift/Nemotron, an H-MEM lookup - goes
through Supervisor.act(), which:

    1. records the action as requested            (World Model: action entity, part_of the request)
    2. checks it against the signed Scout contract (valid signature and expiry, right patient, allowed script,
                                                    data keys inside the patient's linked records, allowed lane)
    3. records the decision                        (World Model fact: authorization)
    4. only if approved, runs it                   (the executor: a script, the Zetaris client, the Nightshift client)
    5. records the result                          (World Model fact: result - status, seconds, short summary)

If the Meterless gateway (World Model) cannot be reached, nothing runs: the supervisor fails closed.

The recorder is pluggable: GatewayRecorder writes to the Meterless gateway (meterless/gateway/server.ts, which runs
the vendored World Model); MemoryRecorder keeps events in memory for offline tests.
"""
from __future__ import annotations

import itertools
import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

import requests

from meterless.scout import verify_contract

ENFORCED_SCRIPTS = {"verify_draft"}          # Meterless runs these itself; the boss cannot choose or skip them
ROLE_ACTIONS = {                              # supervised actions that are not part of a clinical request
    "admin.query": {"admin"},                 # read-only federated SQL console (synthetic data, demo)
    "identity.decision": {"records_staff", "clinician"},
    "batch.matching": {"records_staff", "admin"},
    "feedback.record": {"clinician", "coordinator", "records_staff", "admin"},  # a person rates an answer
}
AI_ROLES = {"planner", "writer", "judge", "interpreter"}


class MeterlessUnavailable(RuntimeError):
    pass


class ActionDenied(RuntimeError):
    pass


# ------------------------------------------------------------------ recorders
class MemoryRecorder:
    """Keeps the record in memory (tests and offline checks)."""

    def __init__(self):
        self.events: list[dict] = []

    def post(self, path: str, body: dict) -> dict:
        self.events.append({"path": path, **body})
        return {"ok": True}


class GatewayRecorder:
    """Writes to the Meterless gateway, which stores everything in the World Model."""

    def __init__(self, base: str | None = None, timeout: float = 5.0):
        self.base = (base or os.environ.get("METERLESS_GATEWAY_URL", "http://127.0.0.1:8090")).rstrip("/")
        self.timeout = timeout

    def post(self, path: str, body: dict) -> dict:
        try:
            r = requests.post(self.base + path, json=body, timeout=self.timeout)
        except requests.RequestException as e:
            raise MeterlessUnavailable("the Meterless gateway is not running (start it with: npx.cmd tsx meterless/gateway/server.ts)") from e
        if r.status_code >= 400:
            raise MeterlessUnavailable(f"Meterless gateway refused the record: {r.text[:200]}")
        return r.json()

    def get(self, path: str) -> dict:
        try:
            r = requests.get(self.base + path, timeout=self.timeout)
        except requests.RequestException as e:
            raise MeterlessUnavailable("the Meterless gateway is not running") from e
        if r.status_code >= 400:
            raise MeterlessUnavailable(r.text[:200])
        return r.json()


# ------------------------------------------------------------------ supervisor
def _digest(x: Any, limit: int = 300) -> str:
    try:
        s = json.dumps(x, default=str)
    except (TypeError, ValueError):
        s = str(x)
    return s if len(s) <= limit else s[:limit] + "..."


class Supervisor:
    def __init__(self, recorder=None, run_id: str | None = None, log: Callable[[dict], None] | None = None):
        self.recorder = recorder or GatewayRecorder()
        self.run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
        self.contract: dict | None = None
        self.mrn: str | None = None
        self.scope: set[str] = set()      # patient keys any data action may touch: MRN + linked lab/pharmacy ids
        self._seq = itertools.count(1)
        self._log = log
        self.actions: list[dict] = []

    def _emit(self, entry: dict):
        entry = {"t": round(time.time(), 2), "agent": "meterless", **entry}
        if self._log:
            self._log(entry)

    # -- the request and Scout's decision
    def open(self, prompt: str, mrn: str, user: dict, ai: bool, data_path: str) -> None:
        self.mrn = mrn
        self.role = user.get("role")
        self.recorder.post(f"/world/runs/{self.run_id}/request",
                           {"prompt": prompt[:500], "user": user.get("id"), "role": user.get("role"), "patient": mrn, "ai": ai,
                            "data_path": data_path})
        self._emit({"action": "request-recorded", "run_id": self.run_id})

    def decided(self, decision: dict, scope: set[str]) -> None:
        self.contract = decision.get("contract")
        self.scope = set(scope)
        c = self.contract or {}
        self.recorder.post(f"/world/runs/{self.run_id}/decision",
                           {"status": decision.get("status"), "intent": (decision.get("intent") or {}).get("primary"),
                            "source": (decision.get("intent") or {}).get("source"), "flags": (decision.get("risk") or {}).get("flags"),
                            "contract_id": c.get("contract_id"), "tools": c.get("tools"), "lanes": c.get("lanes")})
        self._emit({"action": "decision-recorded", "status": decision.get("status"), "contract_id": c.get("contract_id")})

    def close(self, status: str, rounds: int = 0) -> None:
        self.recorder.post(f"/world/runs/{self.run_id}/close", {"status": status, "rounds": rounds})
        self._emit({"action": "run-closed", "status": status, "actions": len(self.actions)})

    # -- policy
    def authorize(self, kind: str, target: str, args: dict) -> tuple[bool, str]:
        if kind == "nightshift.chat" and args.get("role") == "interpreter" and self.contract is None:
            return True, "Scout may ask Nemotron to interpret a safe request before issuing a contract"
        # Actions outside a clinical request: allowed by role, still recorded
        if kind in ROLE_ACTIONS:
            roles = ROLE_ACTIONS[kind]
            return (getattr(self, "role", None) in roles,
                    f"{kind} is allowed for {', '.join(sorted(roles))}" if getattr(self, "role", None) in roles
                    else f"{kind} needs one of the roles {sorted(roles)}, not {getattr(self, 'role', None)}")
        ok, why = verify_contract(self.contract, self.mrn)
        if not ok:
            return False, f"no valid Scout contract: {why}"
        if kind == "script":
            if target in ENFORCED_SCRIPTS:
                return True, "enforced by Meterless"
            if target not in self.contract["tools"]:
                return False, f"script {target} is not in the contract for intent {self.contract['intent'].get('primary')}"
            return True, "script allowed by the contract"
        if kind == "data.fetch":
            keys = set(args.get("keys") or [])
            outside = keys - self.scope
            if outside:
                return False, f"keys outside this patient's linked records: {sorted(outside)[:3]}"
            return True, "keys inside the patient's linked records"
        if kind == "nightshift.chat":
            role, lane = args.get("role"), target
            lanes = set((self.contract.get("lanes") or {}).values())
            fallback = os.environ.get("METERLESS_MODEL", "meterless/fast")
            if role not in AI_ROLES:
                return False, f"unknown AI role {role}"
            if lane not in lanes | {fallback}:
                return False, f"lane {lane} is not in the contract"
            return True, f"lane {lane} allowed for {role}"
        if kind == "hmem.query":
            return True, "memory lookup"
        if kind == "view":
            return True, "patient view allowed by the contract"
        return False, f"unknown action kind {kind}"

    # -- the gate
    def act(self, kind: str, target: str, args: dict, fn: Callable[[], Any], actor: str = "agent",
            summarize: Callable[[Any], str] | None = None, executor: str | None = None) -> Any:
        aid = f"a{next(self._seq)}"
        safe_args = {k: v for k, v in args.items() if k not in ("prompt", "system", "text")}
        self.recorder.post(f"/world/runs/{self.run_id}/actions",
                           {"id": aid, "kind": kind, "target": target, "args": json.loads(json.dumps(safe_args, default=str)),
                            "actor": actor, "seq": int(aid[1:])})
        ok, reason = self.authorize(kind, target, args)
        self.recorder.post(f"/world/runs/{self.run_id}/actions/{aid}/decision", {"allowed": ok, "reason": reason})
        entry = {"id": aid, "kind": kind, "target": target, "actor": actor, "allowed": ok, "reason": reason}
        self.actions.append(entry)
        if not ok:
            self._emit({"action": "denied", **entry})
            raise ActionDenied(reason)
        t0 = time.time()
        try:
            out = fn()
        except Exception as e:
            self.recorder.post(f"/world/runs/{self.run_id}/actions/{aid}/result",
                               {"status": "error", "seconds": round(time.time() - t0, 2), "error": str(e)[:300], "executor": executor or kind})
            self._emit({"action": "failed", **entry, "error": str(e)[:200]})
            raise
        secs = round(time.time() - t0, 2)
        summary = summarize(out) if summarize else _digest(out, 200)
        self.recorder.post(f"/world/runs/{self.run_id}/actions/{aid}/result",
                           {"status": "ok", "seconds": secs, "summary": summary, "executor": executor or kind})
        entry.update(seconds=secs, summary=summary)
        self._emit({"action": "approved-and-done", **entry})
        return out


class SupervisedSource:
    """A data source (Zetaris or the offline copy) whose every fetch is approved and recorded by Meterless."""

    def __init__(self, source, supervisor: Supervisor, name: str):
        self.source, self.sup, self.name = source, supervisor, name

    def fetch(self, kind: str, keys: list[str], since: str | None):
        from clinassist.patient_record import TABLES
        table = TABLES[kind][0]
        return self.sup.act("data.fetch", f"{self.name}:{table}", {"keys": list(keys), "since": since},
                            lambda: self.source.fetch(kind, keys, since), actor="script:fetch_record",
                            summarize=lambda rows: f"{len(rows)} row(s)", executor=self.name)


class SupervisedLLM:
    """The Nightshift client, with every call approved and recorded by Meterless."""

    def __init__(self, llm, supervisor: Supervisor, role: str):
        self.llm, self.sup, self.role = llm, supervisor, role
        self.model = getattr(llm, "model", None)
        self.deep_model = getattr(llm, "deep_model", None)

    def for_role(self, role: str) -> "SupervisedLLM":
        return SupervisedLLM(self.llm, self.sup, role)

    def chat(self, system: str, user: str, deep: bool = False, max_tokens: int = 1500, temperature: float = 0.2,
             model: str | None = None):
        lane = model or (self.deep_model if deep else self.model)
        return self.sup.act("nightshift.chat", lane or "default", {"role": self.role, "chars": len(system) + len(user)},
                            lambda: self.llm.chat(system, user, deep=deep, max_tokens=max_tokens, temperature=temperature, model=model),
                            actor=f"nemotron:{self.role}", executor="nightshift",
                            summarize=lambda r: f"{getattr(r, 'model', '?')} answered in {getattr(r, 'seconds', '?')}s, "
                                                f"{len(getattr(r, 'text', '') or '')} chars")
