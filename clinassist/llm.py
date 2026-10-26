"""Chat client for the AI layer: Meterless Nightshift (OpenAI-compatible), serving NVIDIA Nemotron.

Configured from .env:
    METERLESS_BASE_URL, METERLESS_RUNTIME_TOKEN, METERLESS_APP, METERLESS_MODEL, METERLESS_MODEL_DEEP

The token is never printed. Each call returns the text and the model that actually
served it, so the trace shows which model answered.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass

import requests


class LLMError(RuntimeError):
    pass


@dataclass
class Reply:
    text: str
    model: str
    seconds: float
    lane: str | None = None  # the Nightshift lane that actually answered (set by the agent)


class NightshiftLLM:
    def __init__(self, base_url: str, token: str, app: str, model: str, deep_model: str, timeout: int = 180):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self._token = token
        self.app = app
        self.model = model
        self.deep_model = deep_model
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "NightshiftLLM":
        from dotenv import load_dotenv

        load_dotenv()
        need = ["METERLESS_BASE_URL", "METERLESS_RUNTIME_TOKEN"]
        missing = [n for n in need if not os.environ.get(n) or os.environ[n].startswith(("copy-", "create-"))]
        if missing:
            raise LLMError("set these in .env: " + ", ".join(missing))
        return cls(os.environ["METERLESS_BASE_URL"], os.environ["METERLESS_RUNTIME_TOKEN"],
                   os.environ.get("METERLESS_APP", "clinassist-ai"),
                   os.environ.get("METERLESS_MODEL", "meterless/fast"),
                   os.environ.get("METERLESS_MODEL_DEEP", "meterless/deep"),
                   int(os.environ.get("METERLESS_TIMEOUT", "180")))

    def chat(self, system: str, user: str, deep: bool = False, max_tokens: int = 1500, temperature: float = 0.2,
             model: str | None = None) -> Reply:
        """model: an explicit Nightshift lane (e.g. from a Scout contract); otherwise fast, or deep if deep=True."""
        model = model or (self.deep_model if deep else self.model)
        t0 = time.time()
        try:
            r = requests.post(self.url, timeout=self.timeout, headers={
                "Authorization": "Bearer " + self._token, "meterless-app": self.app,
                "meterless-scope": "user", "Content-Type": "application/json"},
                json={"model": model, "temperature": temperature, "max_tokens": max_tokens,
                      "chat_template_kwargs": {"enable_thinking": False},
                      "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        except requests.RequestException as e:  # timeouts, refused connections: report as an AI failure, not a crash
            raise LLMError(f"Nightshift unreachable on {model}: {type(e).__name__}") from e
        if r.status_code >= 400:
            raise LLMError(f"Nightshift HTTP {r.status_code} on {model}: {r.text[:300]}")
        body = r.json()
        msg = body["choices"][0]["message"]
        text = (msg.get("content") or "").strip()
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()  # reasoning models may emit thinking
        return Reply(text, body.get("model", model), round(time.time() - t0, 1))


def extract_json(text: str):
    """Pull the JSON object out of a model reply. Reasoning models may think aloud first (possibly with braces),
    so try every '{' and keep the LAST object that parses."""
    m = re.search(r"```(?:json)?\s*(.+?)```", text, flags=re.S)
    candidate = m.group(1) if m else text
    dec, found, i = json.JSONDecoder(), None, 0
    while i < len(candidate):
        if candidate[i] in "{[":
            try:
                obj, end = dec.raw_decode(candidate[i:])
                found, i = obj, i + end  # skip past this object so its inner objects are not taken separately
                continue
            except ValueError:
                pass
        i += 1
    if found is None:
        raise ValueError("no JSON in reply")
    return found


BULLET = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s+")


def final_answer(text: str, marker: str = "#") -> str:
    """Keep only the answer when a reasoning model thinks aloud before it.

    1. If there is a top-level heading line ('# ...'), keep from the LAST one: thinking may mention the
       heading, but the answer starts at the final top-level heading (its '## ...' sub-sections are kept).
    2. Otherwise keep the trailing block of bullet lines (the answer is the bulleted list at the end) and
       add the heading. 3. Otherwise return the text unchanged (the checker will judge it).
    """
    lines = text.strip().splitlines()
    # top-level headings only ('# x', not '## x'): the answer can have sub-sections under its main heading
    heads = [i for i, l in enumerate(lines) if l.lstrip().startswith(marker) and not l.lstrip().startswith(marker * 2)]
    if heads:
        return "\n".join(lines[heads[-1]:]).strip()
    start, style = None, None
    for i in range(len(lines) - 1, -1, -1):
        if not lines[i].strip():
            continue
        m = BULLET.match(lines[i])
        kind = ("num" if m.group(0).strip()[0].isdigit() else "dash") if m else None
        if m and style in (None, kind):  # the answer's bullets share one style; notes above it may use another
            start, style = i, kind
            continue
        break
    if start is not None and sum(1 for l in lines[start:] if BULLET.match(l)) >= 2:
        return "# Pre-visit summary\n" + "\n".join(lines[start:]).strip()
    return text.strip()
