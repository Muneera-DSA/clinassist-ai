r"""ClinAssist AI backend: a small JSON API over the ClinAssist modules, plus the built Angular app.

Standard library only (no web framework to install). Listens on 127.0.0.1 only.
Needs the Meterless gateway running (npx.cmd tsx meterless/gateway/server.ts): every request is supervised by it.

    .\.venv\Scripts\python.exe -m server              # http://127.0.0.1:8000
    .\.venv\Scripts\python.exe -m server --port 8001

During development the Angular dev server (npm start in web\) forwards /api here. After `npm run build`
this server also serves the built app, so http://127.0.0.1:8000 is the whole product.

API (all JSON; POST bodies are JSON):
    GET  /api/status                      Zetaris, Nightshift, World Model, Scout, data path
    POST /api/settings                    {"mode": "zetaris" | "csv"}
    GET  /api/sources[?fresh=1]           per-table rows through Zetaris vs the source files
    POST /api/query                       {"sql": "SELECT ..."}  read-only federated query
    GET  /api/patients                    all patients from the World Model identity view
    GET  /api/patients/<mrn>[?fresh=1]    evidence-linked 3-year review (findings, trends, timeline, evidence)
    GET  /api/patients/<mrn>/evidence/<eid>  one source row
    GET  /api/patients/<mrn>/systems      the same person as each system stores them
    GET  /api/patients/<mrn>/provenance   World Model events about this patient
    GET  /api/identity                    matching report, review queue, decisions
    POST /api/identity/review             {"system","record_id","action":"approve|reject","by","note"}
    POST /api/identity/rematch            {"by"}  supervised batch job: re-run matching, rebuild the World Model view
    GET  /api/meterless/runs[/<id>]       World Model record of every supervised run (request, decision, actions)
    POST /api/scout                       {"prompt","mrn","role","user"}
    POST /api/agent/run                   {"prompt","mrn","role","user","ai","history"}  -> Server-Sent Events, step by step
    POST /api/feedback                    {"run_id","rating":"up|down","comment","user","role"}  -> lesson in Meterless H-MEM
    GET  /api/feedback                    what ClinAssist has learned from people
    GET  /api/patients/<mrn>/prescriptions   medicine review: full history, safety flags, saved FDA label sections
    GET  /api/scripts                     the single-action scripts Nemotron can choose from, and what each is for
    GET  /api/runs  /api/runs/<id>        saved agent runs (audit trail)
    GET  /api/evaluation                  saved evaluation results
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import queue
import re
import sys
import threading
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from meterless.supervisor import ActionDenied, MeterlessUnavailable  # noqa: E402
from server.services import Services, _clean  # noqa: E402

WEB_DIST = ROOT / "web" / "dist" / "clinassist-web" / "browser"
ROLES = {"clinician", "coordinator", "records_staff"}
SVC: Services | None = None


class Handler(BaseHTTPRequestHandler):
    server_version = "ClinAssist/1.0"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------ plumbing
    def log_message(self, fmt, *args):  # quieter console: one line per API call
        if self.path.startswith("/api/"):
            sys.stderr.write(f"  {self.command} {self.path.split('?')[0]} -> {args[1] if len(args) > 1 else ''}\n")

    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def json(self, data, status: int = 200):
        self._send(status, json.dumps(data, default=str).encode("utf-8"), "application/json; charset=utf-8")

    def error(self, status: int, message: str):
        self.json({"error": message}, status)

    def body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 1_000_000:
            raise ValueError("request too large")
        raw = self.rfile.read(n) if n else b"{}"
        data = json.loads(raw or b"{}")
        if not isinstance(data, dict):
            raise ValueError("JSON object expected")
        return data

    def _route(self, method: str):
        u = urlparse(self.path)
        q = {k: v[-1] for k, v in parse_qs(u.query).items()}
        path = u.path.rstrip("/") or "/"
        try:
            if path.startswith("/api/"):
                return self.api(method, path, q)
            if method == "GET":
                return self.static(path)
            return self.error(405, "method not allowed")
        except (ValueError, KeyError) as e:
            return self.error(400 if isinstance(e, ValueError) else 404, _clean(str(e).strip("'\"")))
        except MeterlessUnavailable as e:
            return self.error(503, _clean(f"{e}. Nothing runs without Meterless supervising it."))
        except ActionDenied as e:
            return self.error(403, _clean(f"Meterless refused this action: {e}"))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return self.error(502, _clean(f"{type(e).__name__}: {e}"))

    def do_GET(self):  # noqa: N802
        self._route("GET")

    def do_POST(self):  # noqa: N802
        self._route("POST")

    # ------------------------------------------------------------ API
    def api(self, method: str, path: str, q: dict):
        s = SVC
        fresh = q.get("fresh") in ("1", "true")
        if method == "GET":
            if path == "/api/status":
                return self.json(s.status(fresh))
            if path == "/api/sources":
                return self.json(s.source_counts(fresh))
            if path == "/api/patients":
                return self.json(s.patients())
            m = re.fullmatch(r"/api/patients/([A-Za-z0-9_.-]+)/evidence/([A-Za-z0-9_.:-]+)", path)
            if m:
                return self.json(s.evidence(m.group(1), m.group(2)))
            m = re.fullmatch(r"/api/patients/([A-Za-z0-9_.-]+)(/systems|/provenance)?", path)
            if m:
                mrn, sub = m.group(1), m.group(2)
                if sub == "/systems":
                    return self.json(s.patient_in_systems(mrn))
                if sub == "/provenance":
                    return self.json(s.provenance(mrn))
                return self.json(s.patient(mrn, fresh))
            if path == "/api/identity":
                return self.json(s.identity())
            if path == "/api/runs":
                return self.json(s.runs())
            m = re.fullmatch(r"/api/runs/([A-Za-z0-9_.-]+)", path)
            if m:
                return self.json(s.run(m.group(1)))
            if path == "/api/feedback":
                return self.json(s.feedback_list())
            m = re.fullmatch(r"/api/patients/([A-Za-z0-9]+)/prescriptions", path)
            if m:
                return self.json(s.prescriptions(m.group(1), fresh))
            if path == "/api/scripts":
                return self.json(s.scripts())
            if path == "/api/evaluation":
                return self.json(s.evaluation())
            if path == "/api/meterless/runs":
                return self.json(s.meterless_runs())
            m = re.fullmatch(r"/api/meterless/runs/([A-Za-z0-9_.-]+)", path)
            if m:
                return self.json(s.meterless_run(m.group(1)))
            return self.error(404, "unknown endpoint")
        b = self.body()
        if path == "/api/settings":
            return self.json(s.set_mode(str(b.get("mode", ""))))
        if path == "/api/query":
            return self.json(s.run_query(str(b.get("sql", ""))))
        if path == "/api/identity/review":
            return self.json(s.review(str(b.get("system", "")), str(b.get("record_id", "")), str(b.get("action", "")),
                                      str(b.get("by", "")), str(b.get("note", ""))))
        if path == "/api/identity/rematch":
            return self.json(s.rematch(str(b.get("by", ""))))
        if path == "/api/scout":
            prompt, mrn, user = self._ask(b)
            return self.json(s.scout_decide(prompt, mrn, user, bool(b.get("ai", True))))
        if path == "/api/agent/run":
            prompt, mrn, user = self._ask(b)
            history = b.get("history") if isinstance(b.get("history"), list) else []
            return self.stream_agent(prompt, mrn, user, bool(b.get("ai", True)), history[-3:])
        if path == "/api/feedback":
            role = str(b.get("role", "clinician"))
            if role not in ROLES:
                raise ValueError(f"role must be one of {sorted(ROLES)}")
            user = {"id": re.sub(r"[^A-Za-z0-9 ._-]", "", str(b.get("user", "demo-user")))[:40] or "demo-user", "role": role}
            return self.json(s.feedback(str(b.get("run_id", "")), str(b.get("rating", "")), str(b.get("comment", "")), user))
        return self.error(404, "unknown endpoint")

    @staticmethod
    def _ask(b: dict) -> tuple[str, str, dict]:
        prompt = str(b.get("prompt", "")).strip()[:1000]
        mrn = str(b.get("mrn", "")).strip()
        role = str(b.get("role", "clinician"))
        if not prompt or not mrn:
            raise ValueError("prompt and mrn are required")
        if role not in ROLES:
            raise ValueError(f"role must be one of {sorted(ROLES)}")
        user = {"id": re.sub(r"[^A-Za-z0-9 ._-]", "", str(b.get("user", "demo-user")))[:40] or "demo-user", "role": role}
        return prompt, mrn, user

    def stream_agent(self, prompt: str, mrn: str, user: dict, use_ai: bool, history: list | None = None):
        """Server-Sent Events: the UI sees each step (Scout, data load, plan, tools, drafts, checks) as it happens."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        events: queue.Queue = queue.Queue()

        def work():
            try:
                SVC.run_agent(prompt, mrn, user, use_ai, events.put, history)
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                events.put({"type": "result", "result": {"status": "error", "summary": _clean(f"{type(e).__name__}: {e}"),
                                                         "verdict": {}, "plan": [], "rounds": 0}})
            finally:
                events.put(None)

        threading.Thread(target=work, daemon=True).start()
        while True:
            try:
                ev = events.get(timeout=15)
            except queue.Empty:
                ev = {"type": "ping"}  # keeps the connection alive during long model calls
            if ev is None:
                break
            try:
                self.wfile.write(f"data: {json.dumps(ev, default=str)}\n\n".encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                break

    # ------------------------------------------------------------ static (built Angular app)
    def static(self, path: str):
        if not WEB_DIST.exists():
            return self._send(200, (b"<h3>ClinAssist API is running.</h3><p>Build the web app (cd web; npm run build) "
                                    b"or run it in development with npm start and open http://localhost:4200</p>"),
                              "text/html; charset=utf-8")
        f = (WEB_DIST / path.lstrip("/")).resolve()
        if not str(f).startswith(str(WEB_DIST.resolve())) or not f.is_file():
            f = WEB_DIST / "index.html"  # client-side routes
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        self._send(200, f.read_bytes(), ctype)


def main() -> None:
    global SVC
    ap = argparse.ArgumentParser(description="ClinAssist AI backend")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--source", choices=["zetaris", "csv"], help="data path (default: CLINASSIST_SOURCE or zetaris)")
    a = ap.parse_args()
    SVC = Services()
    if a.source:
        SVC.set_mode(a.source)
    httpd = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    httpd.daemon_threads = True
    print(f"ClinAssist backend on http://127.0.0.1:{a.port}   data path: {SVC.mode}   review date: {SVC.as_of}")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
