"""Minimal Zetaris Lightning REST client (read-only SQL).

Uses the same endpoint and headers verified by smoke_test.py:
    POST {ZETARIS_REST_URL}/sql-editor/sqls/run
Keys come from .env and are never printed.
"""
from __future__ import annotations

import os
import uuid
from typing import Any

import requests


class ZetarisError(RuntimeError):
    pass


class ZetarisClient:
    def __init__(self, rest_url: str, org_id: str, api_key: str, timeout: int = 120):
        self.url = rest_url.rstrip("/") + "/sql-editor/sqls/run"
        self.org_id = org_id
        self._key = api_key
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "ZetarisClient":
        from dotenv import load_dotenv

        load_dotenv()
        missing = [n for n in ("ZETARIS_REST_URL", "ZETARIS_ORG_ID", "ZETARIS_API_KEY")
                   if not os.environ.get(n) or os.environ[n].startswith(("create-", "copy-"))]
        if missing:
            raise ZetarisError("set these in .env: " + ", ".join(missing))
        return cls(os.environ["ZETARIS_REST_URL"], os.environ["ZETARIS_ORG_ID"], os.environ["ZETARIS_API_KEY"])

    def rows(self, sql: str, columns: list[str], limit: int = 100_000) -> list[dict[str, Any]]:
        """Run one SELECT and map each row to the column names you list.

        The SELECT must return exactly these columns, in this order. One
        statement only, no trailing semicolon (Zetaris SQL editor rule).
        """
        r = requests.post(
            self.url,
            headers={"Authorization": "Bearer " + self._key,
                     "X-Org-ID": self.org_id,
                     "X-Request-ID": str(uuid.uuid4())},
            json={"queryId": str(uuid.uuid4()), "sql": sql, "source": "SqlEditor", "limit": limit},
            timeout=self.timeout,
        )
        if r.status_code >= 400:
            raise ZetarisError(f"Zetaris HTTP {r.status_code}: {r.text[:300]}")
        data = r.json().get("data") or []
        out = []
        for row in data:
            if len(row) != len(columns):
                raise ZetarisError(f"expected {len(columns)} columns, got {len(row)}")
            out.append({c: ("" if v is None else str(v)) for c, v in zip(columns, row)})
        if len(out) >= limit:
            raise ZetarisError(f"result hit the row limit ({limit}); results may be truncated")
        return out
