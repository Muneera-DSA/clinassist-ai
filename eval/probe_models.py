r"""Probe: does Nightshift honour the model we ask for?

For each candidate model id, send one tiny request and record which model actually served it
(the "model" field of the reply), how long it took, and whether it answered. Read-only; never
prints keys or tokens. Used to decide which model each agent role (planner, writer, judge) gets.

    .\.venv\Scripts\python.exe .\eval\probe_models.py

Writes data\derived\eval\model_probe.json
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

CANDIDATES = [
    "meterless/fast", "meterless/deep", "meterless/judge",
    "nvidia/nemotron-3-nano-30b-a3b",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "nvidia/llama-3.3-nemotron-super-49b-v1.5",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/llama-3.1-nemotron-ultra-253b-v1",
    "nvidia/nemotron-3-ultra-550b-a55b",
]
PROMPT = "Reply with exactly one word: OK"


def main() -> None:
    load_dotenv()
    base, token = os.environ.get("METERLESS_BASE_URL", ""), os.environ.get("METERLESS_RUNTIME_TOKEN", "")
    if not base or not token or token.startswith("copy-"):
        sys.exit("Set METERLESS_BASE_URL and METERLESS_RUNTIME_TOKEN in .env first.")
    headers = {"Authorization": "Bearer " + token, "meterless-app": os.environ.get("METERLESS_APP", "clinassist-ai"),
               "meterless-scope": "user", "Content-Type": "application/json"}
    rows = []
    print(f"{'requested':45s} {'served by':45s} {'secs':>6s}  result")
    for model in CANDIDATES:
        t0 = time.time()
        try:
            r = requests.post(base.rstrip("/") + "/chat/completions", headers=headers, timeout=180, json={
                "model": model, "temperature": 0, "max_tokens": 300,
                "messages": [{"role": "user", "content": PROMPT}]})
            secs = round(time.time() - t0, 1)
            if r.status_code >= 400:
                row = {"requested": model, "served": None, "seconds": secs, "ok": False, "error": f"HTTP {r.status_code}: {r.text[:150]}"}
            else:
                body = r.json()
                text = re.sub(r"<think>.*?</think>", "", (body["choices"][0]["message"].get("content") or ""), flags=re.S).strip()
                row = {"requested": model, "served": body.get("model"), "seconds": secs, "ok": bool(text), "reply": text[:40]}
        except requests.RequestException as e:
            row = {"requested": model, "served": None, "seconds": round(time.time() - t0, 1), "ok": False, "error": str(e)[:150]}
        rows.append(row)
        print(f"{model:45s} {str(row['served']):45s} {row['seconds']:6.1f}  "
              f"{'OK ' + repr(row.get('reply', '')) if row['ok'] else 'FAIL ' + row.get('error', 'empty reply')}", flush=True)
    explicit = [r for r in rows if r["requested"].startswith("nvidia/") and r["ok"]]
    honoured = [r for r in explicit if r["served"] == r["requested"]]
    distinct = sorted({r["served"] for r in rows if r["served"]})
    print(f"\nExplicit Nemotron ids honoured: {len(honoured)} of {len(explicit)} that answered")
    print(f"Distinct models that actually served: {len(distinct)} -> {distinct}")
    out = Path("data/derived/eval")
    out.mkdir(parents=True, exist_ok=True)
    (out / "model_probe.json").write_text(json.dumps({"rows": rows, "distinct_served": distinct}, indent=2), encoding="utf-8")
    print("Saved data\\derived\\eval\\model_probe.json")


if __name__ == "__main__":
    main()
