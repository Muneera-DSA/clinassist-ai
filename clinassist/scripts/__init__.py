"""Single-action scripts: the tools Nemotron (the boss) can choose to run.

Each script does exactly ONE thing - fetch, compute, sort or aggregate - and returns facts with evidence ids.
No script decides what matters or what to do next: Nemotron does, after reading the results.

Every script runs through the Meterless supervisor (meterless/supervisor), which checks it against the Scout
contract and records the request, the decision and the result in the World Model. The catalog below is loaded
into Meterless H-MEM, which retrieves the relevant scripts into Nemotron's prompt.
"""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable


@dataclass
class Script:
    name: str
    does: str                       # one sentence: the single action
    args: dict[str, str]            # argument -> description
    returns: str
    tags: list[str]
    needs_record: bool
    run: Callable[..., Any]
    kind: str = "compute"           # fetch | compute | sort | aggregate | verify


@dataclass
class Ctx:
    """What the scripts of one request share: the patient in scope and what has been fetched so far."""
    mrn: str
    as_of: date
    years: int
    source: Any                     # CsvSource or ZetarisSource (its queries go through the supervisor)
    world_dir: Path
    rules: dict
    rec: Any = None                 # PatientRecord, set by fetch_record
    cache: dict = field(default_factory=dict)    # computed inputs shared by scripts (trends, medicines)
    gathered: dict = field(default_factory=dict) # script results so far in this request (for aggregation)

    def need_record(self):
        if self.rec is None:
            raise ValueError("no patient record loaded yet: run fetch_record first")
        return self.rec

    def trends(self):
        from clinassist.analysis import trends
        if "trends" not in self.cache:
            self.cache["trends"] = trends(self.need_record(), self.rules)
        return self.cache["trends"]

    def meds(self):
        from clinassist.analysis import medications
        if "meds" not in self.cache:
            self.cache["meds"] = medications(self.need_record())
        return self.cache["meds"]

    def result(self):
        """The complete rule-based analysis. Used only by the enforced checker (verify_draft), never shown to the boss."""
        from clinassist.analysis import analyse
        if "result" not in self.cache:
            self.cache["result"] = analyse(self.need_record(), self.rules)
        return self.cache["result"]


REGISTRY: dict[str, Script] = {}


def script(name: str, does: str, returns: str, args: dict[str, str] | None = None, tags: list[str] | None = None,
           needs_record: bool = True, kind: str = "compute"):
    def wrap(fn):
        REGISTRY[name] = Script(name, does, args or {}, returns, tags or [], needs_record, fn, kind)
        return fn
    return wrap


def load_all() -> dict[str, Script]:
    for m in pkgutil.iter_modules([str(Path(__file__).parent)]):
        importlib.import_module(f"{__name__}.{m.name}")
    return REGISTRY


def catalog(names: list[str] | None = None) -> list[dict]:
    """Script descriptions for the H-MEM memory and Nemotron's prompt (enforced scripts excluded)."""
    load_all()
    return [{"name": s.name, "does": s.does, "args": s.args, "returns": s.returns, "tags": s.tags, "kind": s.kind}
            for s in REGISTRY.values() if s.kind != "verify" and (names is None or s.name in names)]


def run(name: str, ctx: Ctx, args: dict | None = None) -> Any:
    load_all()
    if name not in REGISTRY:
        raise ValueError(f"unknown script {name!r}")
    s = REGISTRY[name]
    args = {k: v for k, v in (args or {}).items() if k in s.args}
    if s.needs_record:
        ctx.need_record()
    out = s.run(ctx, **args)
    ctx.gathered[name + (f"({','.join(f'{k}={v}' for k, v in sorted(args.items()))})" if args else "")] = out
    return out
