r"""Quick check of the Nightshift -> Nemotron client (clinassist/llm.py), as it is on disk now.

    .\.venv\Scripts\python.exe .\eval\try_llm.py

Sends one short request on the fast lane and one on the deep lane, and prints for each: which model answered,
how long it took, whether the reply still contained "thinking aloud" before the answer, and the answer itself.
Reads the Nightshift settings from .env; the token is never printed. Synthetic question only, no patient data.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clinassist.llm import LLMError, NightshiftLLM, final_answer  # noqa: E402

SYSTEM = "You are a concise clinical documentation assistant. Never diagnose or prescribe. Answer as a markdown list."
USER = "In two bullet points, explain why a falling eGFR trend matters when reviewing a patient's medicines."


def main() -> None:
    llm = NightshiftLLM.from_env()
    print(f"Nightshift lanes: fast={llm.model}  deep={llm.deep_model}\n")
    for deep in (False, True):
        lane = llm.deep_model if deep else llm.model
        print(f"--- {lane} ---")
        try:
            r = llm.chat(SYSTEM, USER, deep=deep, max_tokens=400)
        except LLMError as e:
            print(f"FAILED: {e}\n")
            continue
        answer = final_answer(r.text)
        thinking = len(r.text.strip()) - len(answer.strip())
        print(f"answered by {r.model} in {r.seconds}s; reply {len(r.text)} chars, "
              f"{'no thinking text before the answer' if thinking <= 5 else f'{thinking} chars of thinking text removed'}")
        print(answer, "\n")


if __name__ == "__main__":
    main()
