r"""ClinAssist AI — connection smoke test (Data: Zetaris, Power: Meterless Nightshift).

Run from the project folder:
    .\.venv\Scripts\python.exe .\smoke_test.py

Read-only: it runs SELECT 1 on Zetaris, lists Nightshift's models and sends one
short chat request. It never prints keys or tokens.
"""
from __future__ import annotations

import os
import uuid

import requests
from dotenv import load_dotenv

load_dotenv()
results: list[tuple[str, str, str]] = []


def check(name, fn):
    try:
        detail = fn() or ""
        results.append(("PASS", name, str(detail)))
    except Exception as error:  # report, don't crash
        results.append(("FAIL", name, str(error)[:200]))


def need(*names):
    missing = [n for n in names if not os.environ.get(n) or os.environ[n].startswith(("create-", "copy-"))]
    assert not missing, f"set these in .env: {', '.join(missing)}"


# ---------- DATA: Zetaris ----------
def zetaris_web():
    url = os.environ.get("ZETARIS_BASE_URL", "http://localhost:3000")
    requests.get(url, timeout=10).raise_for_status()
    return url


def zetaris_sql():
    need("ZETARIS_REST_URL", "ZETARIS_ORG_ID", "ZETARIS_API_KEY")
    r = requests.post(
        os.environ["ZETARIS_REST_URL"].rstrip("/") + "/sql-editor/sqls/run",
        headers={
            "Authorization": "Bearer " + os.environ["ZETARIS_API_KEY"],
            "X-Org-ID": os.environ["ZETARIS_ORG_ID"],
            "X-Request-ID": str(uuid.uuid4()),
        },
        json={"queryId": str(uuid.uuid4()), "sql": "SELECT 1", "source": "SqlEditor", "limit": 1},
        timeout=60,
    )
    r.raise_for_status()
    data = r.json().get("data")
    assert data and str(data[0][0]) == "1", "unexpected reply: " + r.text[:100]
    return "SELECT 1 returned 1"


# ---------- POWER: Meterless Nightshift ----------
def _ms_headers():
    need("METERLESS_BASE_URL", "METERLESS_RUNTIME_TOKEN")
    return {
        "Authorization": "Bearer " + os.environ["METERLESS_RUNTIME_TOKEN"],
        "meterless-app": os.environ.get("METERLESS_APP", "clinassist-ai"),
        "meterless-scope": "user",
        "Content-Type": "application/json",
    }


def nightshift_models():
    r = requests.get(os.environ["METERLESS_BASE_URL"].rstrip("/") + "/models", headers=_ms_headers(), timeout=30)
    if r.status_code in (401, 403):
        raise AssertionError(f"unauthorized ({r.status_code}): copy the token again from Nightshift > Console")
    r.raise_for_status()
    ids = [m.get("id", "") for m in r.json().get("data", [])]
    print(f"\nNightshift exposes {len(ids)} model id(s):")
    for i in ids:
        print("   ", i)
    nemo = [i for i in ids if "nemotron" in i.lower()]
    want = os.environ.get("METERLESS_MODEL", "")
    if want and want not in ids:
        print(f"   NOTE: METERLESS_MODEL={want} is not in this list; pick one of the ids above.")
    assert ids, "Runtime returned no models"
    return f"{len(ids)} id(s), {len(nemo)} named Nemotron"


def nightshift_chat():
    model = os.environ.get("METERLESS_MODEL", "")
    assert model, "set METERLESS_MODEL in .env"
    r = requests.post(
        os.environ["METERLESS_BASE_URL"].rstrip("/") + "/chat/completions",
        headers=_ms_headers(),
        json={"model": model, "messages": [{"role": "user", "content": "Reply with the single word: ready"}], "max_tokens": 20,
              "chat_template_kwargs": {"enable_thinking": False}},
        timeout=180,
    )
    if r.status_code >= 400:
        raise AssertionError(f"HTTP {r.status_code} from Nightshift: {r.text[:300]}")
    body = r.json()
    text = (body["choices"][0]["message"].get("content") or "").strip()
    assert text, "empty reply"
    return f"requested={model} served_by={body.get('model', '?')} reply={text[:40]!r}  (confirm Nemotron in Nightshift run details)"


check("Data: Zetaris web interface", zetaris_web)
check("Data: Zetaris runs SQL over REST", zetaris_sql)
check("Power: Nightshift lists models", nightshift_models)
check("Power: Nemotron replies via Nightshift", nightshift_chat)

print()
for status, name, detail in results:
    print(f"{status}  {name}  {detail}")
