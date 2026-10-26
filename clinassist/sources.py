"""Where each source system lives and what Zetaris calls its tables (config/sources.json)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "config" / "sources.json"


@lru_cache(maxsize=1)
def load() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def zt(name: str) -> str:
    """Our table name (e.g. 'hospital_ehr.patients') -> the name to use in Zetaris SQL."""
    return load()["tables"].get(name, name)


def systems() -> dict:
    return load()["systems"]
