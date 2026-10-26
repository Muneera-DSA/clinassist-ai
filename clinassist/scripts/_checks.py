"""Helpers shared by the check scripts (not a script itself)."""
from dataclasses import asdict


def findings_out(findings) -> dict:
    """A check reports whether its criterion is met and the findings (facts with evidence and guideline source)."""
    out = [asdict(f) for f in findings]
    for f in out:
        f["rule_level"] = f.pop("severity")  # the level the rule definition assigns; the agent decides priority
    return {"criterion_met": bool(out), "findings": out}
