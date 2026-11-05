from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .agent_loop import Agent
from .models import load_model_from_env
from .scheduling import RESOURCE_REGISTRY

ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web"


def configure_web_provider() -> None:
    web_provider = os.environ.get("AGENT_WEB_PROVIDER", "").strip()
    if web_provider:
        os.environ["AGENT_PROVIDER"] = web_provider


configure_web_provider()


def resource_status_payload() -> dict[str, Any]:
    RESOURCE_REGISTRY.refresh_stale()
    resources = [resource.to_dict() for resource in RESOURCE_REGISTRY.all()]
    counts: dict[str, int] = {}
    for resource in resources:
        status = str(resource["status"])
        counts[status] = counts.get(status, 0) + 1
    return {"resources": resources, "counts": counts, "total": len(resources)}


def configure_console_encoding() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


class AgentState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.agent = Agent(load_model_from_env())

    def reset(self) -> None:
        with self.lock:
            self.agent = Agent(load_model_from_env())

    def chat(self, message: str) -> dict[str, Any]:
        with self.lock:
            return self.agent.run_turn_with_trace(message)


STATE = AgentState()


class AgentWebHandler(BaseHTTPRequestHandler):
    server_version = "SelfTestAgent/0.1"

    def do_GET(self) -> None:
        if self.path == "/" or self.path.startswith("/index.html"):
            self._send_file(WEB_ROOT / "index.html")
            return
        if self.path.startswith("/static/"):
            relative = unquote(self.path.removeprefix("/static/"))
            self._send_file(WEB_ROOT / relative)
            return
        if self.path == "/api/health":
            self._send_json({"ok": True})
            return
        if self.path == "/api/resources":
            self._send_json(resource_status_payload())
            return
        self.send_error(404, "Not found")

    def do_POST(self) -> None:
        if self.path == "/api/chat":
            payload = self._read_json()
            message = str(payload.get("message", "")).strip()
            if not message:
                self._send_json({"error": "message is required"}, status=400)
                return
            try:
                result = STATE.chat(message)
            except Exception as exc:
                self._send_json({"error": f"{type(exc).__name__}: {exc}"}, status=500)
                return
            self._send_json(result)
            return

        if self.path == "/api/reset":
            STATE.reset()
            self._send_json({"ok": True})
            return

        self.send_error(404, "Not found")

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        return json.loads(raw or "{}")

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        resolved = path.resolve()
        try:
            resolved.relative_to(WEB_ROOT.resolve())
        except ValueError:
            self.send_error(403, "Forbidden")
            return
        if not resolved.exists() or not resolved.is_file():
            self.send_error(404, "Not found")
            return
        body = resolved.read_bytes()
        content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    configure_console_encoding()
    parser = argparse.ArgumentParser(description="Run the self-test agent web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), AgentWebHandler)
    print(f"self-test agent web UI: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
