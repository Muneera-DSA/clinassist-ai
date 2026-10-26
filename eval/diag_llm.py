r"""Find out why Nightshift returns empty answers: tries the same question with different settings.

    .\.venv\Scripts\python.exe .\eval\diag_llm.py                      (5 settings, one call each)
    .\.venv\Scripts\python.exe .\eval\diag_llm.py --compare MODEL MODEL --n 10
    .\.venv\Scripts\python.exe .\eval\diag_llm.py --replay MODEL MODEL
        (sends the app's REAL boss and writer prompts, captured from a Kendrick run, with and without the thinking switch)
    .\.venv\Scripts\python.exe .\eval\diag_llm.py --fixtest
        (the real boss prompt 5 ways: which setting stops the empty replies)

Does not use or change clinassist/llm.py. Reads METERLESS_BASE_URL / METERLESS_RUNTIME_TOKEN / METERLESS_APP /
METERLESS_MODEL from .env; the token is never printed. Synthetic question only.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
BASE = os.environ["METERLESS_BASE_URL"].rstrip("/")
TOKEN = os.environ["METERLESS_RUNTIME_TOKEN"]
APP = os.environ.get("METERLESS_APP", "clinassist-ai")
ENV_MODEL = os.environ.get("METERLESS_MODEL", "meterless/fast")

SYSTEM = "You are a concise clinical documentation assistant. Never diagnose or prescribe."
USER = "In two bullet points, explain why a falling eGFR trend matters when reviewing a patient's medicines."

TRIALS = [
    ("A  .env model, no thinking switch, 400 tokens", ENV_MODEL, None, 400),
    ("B  .env model, thinking OFF,       400 tokens", ENV_MODEL, False, 400),
    ("C  .env model, no thinking switch, 2000 tokens", ENV_MODEL, None, 2000),
    ("D  meterless/fast lane, no switch, 400 tokens", "meterless/fast", None, 400),
    ("E  meterless/fast lane, thinking OFF, 400 tokens", "meterless/fast", False, 400),
]


def call(model: str, thinking: bool | None, max_tokens: int, system: str = SYSTEM, user: str = USER):
    body = {"model": model, "temperature": 0.2, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if thinking is not None:
        body["chat_template_kwargs"] = {"enable_thinking": thinking}
    t0 = time.time()
    try:
        r = requests.post(BASE + "/chat/completions", timeout=180, json=body,
                          headers={"Authorization": "Bearer " + TOKEN, "meterless-app": APP,
                                   "meterless-scope": "user", "Content-Type": "application/json"})
    except requests.RequestException as e:
        return f"NO CONNECTION ({type(e).__name__})", round(time.time() - t0, 1)
    secs = round(time.time() - t0, 1)
    if r.status_code >= 400:
        try:
            err = r.json().get("error", {})
            return f"HTTP {r.status_code}: {err.get('meterless_detail') or err.get('message')}", secs
        except ValueError:
            return f"HTTP {r.status_code}: {r.text[:150]}", secs
    j = r.json()
    msg = (j.get("choices") or [{}])[0].get("message", {})
    content = (msg.get("content") or "").strip()
    reasoning = (msg.get("reasoning_content") or msg.get("reasoning") or "").strip()
    served = j.get("model", "?")
    finish = (j.get("choices") or [{}])[0].get("finish_reason")
    out = f"OK, served by {served}, finish={finish}, answer {len(content)} chars, hidden reasoning {len(reasoning)} chars"
    if content:
        out += "\n      " + content[:300].replace("\n", "\n      ")
    return out, secs


def compare(models: list[str], n: int) -> None:
    import statistics
    print(f"Nightshift: {BASE}   {n} calls per model, same question, thinking switch not sent, 1500 tokens\n")
    for m in models:
        ok, secs, errors = 0, [], {}
        for _ in range(n):
            result, s_ = call(m, None, 1500)
            if result.startswith("OK"):
                ok += 1
                secs.append(s_)
            else:
                key = result.split(":", 1)[-1].strip()[:70]
                errors[key] = errors.get(key, 0) + 1
        med = statistics.median(secs) if secs else None
        print(f"{m}\n   answered {ok}/{n}   median {med}s   failures: {errors or 'none'}\n")


def replay(models: list[str]) -> None:
    import json
    prompts = json.loads((Path(__file__).resolve().parent / "replay_prompts.json").read_text(encoding="utf-8"))
    print(f"Nightshift: {BASE}   replaying the app's real prompts (synthetic Kendrick case)\n")
    for m in models:
        for role in ("boss", "writer"):
            p = prompts[role]
            for thinking, label in ((False, "thinking OFF (as llm.py sends)"), (None, "no thinking switch")):
                result, secs = call(m, thinking, p["max_tokens"], p["system"], p["user"])
                print(f"{m} | {role} | {label} | max_tokens {p['max_tokens']}  [{secs}s]\n   {result[:400]}\n")


def fixtest() -> None:
    """The app's real boss prompt on the .env model, 5 ways: which one stops the empty replies?"""
    import json
    p = json.loads((Path(__file__).resolve().parent / "replay_prompts.json").read_text(encoding="utf-8"))["boss"]
    sysmsg = p["system"]
    trials = [
        ("1 as the app sends it (thinking OFF switch, 1500 tokens)", sysmsg, False, 1500),
        ("2 thinking OFF switch, 8000 tokens", sysmsg, False, 8000),
        ("3 '/no_think' at the start of the system prompt, 1500 tokens", "/no_think\n" + sysmsg, False, 1500),
        ("4 'detailed thinking off' system line, 1500 tokens", "detailed thinking off\n" + sysmsg, False, 1500),
        ("5 no switch at all, 8000 tokens", sysmsg, None, 8000),
    ]
    print(f"Nightshift: {BASE}   model: {ENV_MODEL}   the app's real boss prompt (synthetic Kendrick case)\n")
    for label, system, thinking, mt in trials:
        result, secs = call(ENV_MODEL, thinking, mt, system, p["user"])
        print(f"{label}  [{secs}s]\n   {result[:300]}\n")


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare", nargs="+", help="model or lane names to compare")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--replay", nargs="+", help="model or lane names: send the app's real boss and writer prompts")
    ap.add_argument("--fixtest", action="store_true", help="real boss prompt, 5 ways to stop empty replies")
    a = ap.parse_args()
    if a.fixtest:
        return fixtest()
    if a.replay:
        return replay(a.replay)
    if a.compare:
        return compare(a.compare, a.n)
    print(f"Nightshift: {BASE}   model in .env: {ENV_MODEL}\n")
    for label, model, thinking, max_tokens in TRIALS:
        result, secs = call(model, thinking, max_tokens)
        print(f"{label}  [{secs}s]\n   {result}\n")


if __name__ == "__main__":
    main()
