"""Scout: ClinAssist's front-door decision layer, implementing the Meterless Scout Intent spec.

Before the agent runs, every request passes five stages:

    1. Sense      score the request against the intent registry (multi-label, with confidence)
    2. Interpret  bind the patient in scope and any lab values the request mentions
    3. Guard      block prompt injection, clinical decisions (diagnose / prescribe / dose),
                  requests about another patient, population-wide data requests, and
                  intents the user's role may not run
    4. Route      build the tool plan for the intent(s) and assign a Nightshift lane per AI role
    5. Recommend  issue an execution contract signed with HMAC-SHA256

The agent refuses to act without a valid contract (see Agent.run(contract=...)), so every action
can be traced back to an approved, signed decision. Deterministic and local: no AI call, no network.

Configuration: config/scout_intents.json.  Signing key: SCOUT_SIGNING_KEY in .env (if it is missing,
a random key is generated for this process only and the decision says so).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REGISTRY_FILE = Path(__file__).resolve().parents[1] / "config" / "scout_intents.json"
MRN = re.compile(r"\bMRN[0-9A-F]{8}\b", re.I)


def load_registry(path: Path = REGISTRY_FILE) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _key() -> tuple[bytes, bool]:
    try:  # read .env so the key is found even when nothing else has loaded it yet
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    k = os.environ.get("SCOUT_SIGNING_KEY", "")
    if k and not k.startswith("change-me"):
        return k.encode(), True
    global _EPHEMERAL
    if "_EPHEMERAL" not in globals():
        _EPHEMERAL = secrets.token_bytes(32)
    return _EPHEMERAL, False


def _canonical(contract: dict) -> bytes:
    body = {k: v for k, v in contract.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()


def sign(contract: dict) -> dict:
    key, _ = _key()
    contract["signature"] = hmac.new(key, _canonical(contract), hashlib.sha256).hexdigest()
    return contract


def verify_contract(contract: dict | None, mrn: str | None = None, now: datetime | None = None) -> tuple[bool, str]:
    """True if the contract is signed with our key, not expired and (if given) for this patient."""
    if not contract or "signature" not in contract:
        return False, "no contract"
    key, _ = _key()
    expected = hmac.new(key, _canonical(contract), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, str(contract["signature"])):
        return False, "signature does not match (contract altered or signed elsewhere)"
    now = now or datetime.now(timezone.utc)
    if datetime.fromisoformat(contract["expires_at"]) < now:
        return False, "contract expired"
    if mrn and contract.get("patient") != mrn:
        return False, f"contract is for {contract.get('patient')}, not {mrn}"
    return True, "ok"


@dataclass
class Decision:
    status: str                      # "approved" | "clarify" | "blocked"
    message: str
    intent: dict = field(default_factory=dict)       # {primary, confidence, secondary}
    risk: dict = field(default_factory=dict)         # {level, flags, matched}
    plan: list[dict] = field(default_factory=list)
    lanes: dict = field(default_factory=dict)
    contract: dict | None = None
    telemetry: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class Scout:
    def __init__(self, registry: dict | None = None, patients: list[dict] | None = None):
        """patients: [{"mrn", "label"}] from data/derived/world/patient_identity.json (for the patient-scope guard)."""
        self.reg = registry or load_registry()
        self.patients = patients or []
        flags = re.I
        self._intents = {k: [(re.compile(p, flags), float(w)) for p, w in v["patterns"]] for k, v in self.reg["intents"].items()}
        g = self.reg["guards"]
        self._guards = {name: [re.compile(p, flags) for p in g[name]] for name in ("injection", "clinical_decision", "bulk_data")}
        self._other = [re.compile(p, flags) for p in g["other_patient_words"]]

    # 1. sense
    def sense(self, prompt: str) -> dict[str, float]:
        return {k: round(sum(w for rx, w in pats if rx.search(prompt)), 2) for k, pats in self._intents.items()}

    # 2. interpret
    def interpret(self, prompt: str) -> dict:
        low = prompt.lower()
        analytes = sorted({key for key, words in self.reg["analyte_words"].items()
                           if any(re.search(r"\b" + re.escape(w) + r"\b", low) for w in words)})
        return {"mrns_mentioned": sorted({m.upper() for m in MRN.findall(prompt)}), "analytes": analytes}

    # 3. guard
    def guard(self, prompt: str, mrn: str, details: dict) -> tuple[list[str], list[str]]:
        flags, matched = [], []
        names = {"injection": "injection", "clinical_decision": "clinical-decision", "bulk_data": "bulk-data"}
        for gname, flag in names.items():
            hits = [rx.pattern for rx in self._guards[gname] if rx.search(prompt)]
            if hits:
                flags.append(flag)
                matched += hits[:2]
        other = [m for m in details["mrns_mentioned"] if m != mrn.upper()]
        own_label = next((p["label"] for p in self.patients if p["mrn"] == mrn), "")
        own_words = set(re.findall(r"[A-Z][A-Za-z'-]+", own_label))
        other_names = []
        for p in self.patients:
            if p["mrn"] == mrn:
                continue
            surname = p["label"].split(",")[0].strip().title()
            if surname and surname not in own_words and re.search(r"\b" + re.escape(surname) + r"\b", prompt):
                other_names.append(surname)
        if other or other_names or any(rx.search(prompt) for rx in self._other):
            flags.append("wrong-patient")
            matched += other + sorted(set(other_names))[:3]
        return flags, matched

    # 4 + 5. route and recommend
    def decide(self, prompt: str, mrn: str, user: dict | None = None) -> Decision:
        t0 = time.perf_counter()
        user = user or {"id": "unknown", "role": "clinician"}
        role = user.get("role", "clinician")
        cfg = self.reg["scoring"]
        scores = self.sense(prompt)
        details = self.interpret(prompt)
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        (top, top_s), (second, second_s) = ranked[0], ranked[1]
        confidence = round(top_s / (top_s + second_s), 2) if top_s else 0.0
        secondary = [k for k, s in ranked[1:] if top_s and s >= cfg["min_score"] and s >= cfg["secondary_ratio"] * top_s]
        intent = {"primary": top if top_s >= cfg["min_score"] else None, "confidence": confidence, "secondary": secondary}
        telemetry = {"scores": scores, "interpreted": details, "registry_version": self.reg["version"]}

        flags, matched = self.guard(prompt, mrn, details)
        if not flags and intent["primary"]:
            allowed = all(role in self.reg["intents"][k]["roles"] for k in [top] + secondary)
            if not allowed:
                flags.append("role-not-permitted")
                matched.append(f"role={role}")
        msgs = self.reg["messages"]
        telemetry["seconds"] = round(time.perf_counter() - t0, 4)
        if flags:
            return Decision("blocked", msgs[flags[0]], intent, {"level": "high", "flags": flags, "matched": matched},
                            telemetry=telemetry)
        if not intent["primary"]:
            return Decision("clarify", msgs["clarify"], intent, {"level": "none", "flags": [], "matched": []},
                            telemetry=telemetry)

        plan, seen = [], set()
        for k in [top] + secondary:
            for step in self.reg["intents"][k]["tools"]:
                step = json.loads(json.dumps(step))
                if step["tool"] == "trends" and details["analytes"]:
                    step["args"] = {"analytes": sorted(set(step["args"].get("analytes", [])) | set(details["analytes"]))}
                if step["tool"] in seen:
                    continue
                seen.add(step["tool"])
                plan.append(step)
        if top in ("trend.review", "finding.explain") and len(details["analytes"]) == 1 and "lab_series" not in seen:
            plan.append({"tool": "lab_series", "args": {"analyte": details["analytes"][0]}})
        lanes = dict(self.reg["lanes"])
        now = datetime.now(timezone.utc)
        _, persistent = _key()
        contract = sign({
            "version": "scout/1", "contract_id": str(uuid.uuid4()),
            "issued_at": now.isoformat(), "expires_at": (now + timedelta(minutes=cfg["contract_ttl_minutes"])).isoformat(),
            "user": {"id": user.get("id", "unknown"), "role": role}, "patient": mrn, "request": prompt[:500],
            "intent": intent, "risk": {"level": "low", "flags": []},
            "tools": [s["tool"] for s in plan], "plan": plan, "lanes": lanes,
            "registry_version": self.reg["version"], "key": "persistent" if persistent else "ephemeral",
        })
        msg = f"Approved: {top}" + (f" + {', '.join(secondary)}" if secondary else "")
        if not persistent:
            msg += " (signed with a temporary key: set SCOUT_SIGNING_KEY in .env to verify contracts across processes)"
        return Decision("approved", msg, intent, {"level": "low", "flags": [], "matched": []}, plan, lanes, contract, telemetry)


def load_patients(world_dir: Path) -> list[dict]:
    f = Path(world_dir) / "patient_identity.json"
    return [{"mrn": p["mrn"], "label": p["label"]} for p in json.loads(f.read_text(encoding="utf-8"))["patients"]] if f.exists() else []
