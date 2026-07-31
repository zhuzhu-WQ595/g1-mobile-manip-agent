from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol
from urllib.parse import urlparse

from contracts.execution import ExecutionError, ExecutionRequest, ExecutionStatus


class ExecutionService(Protocol):
    def execute(self, request: ExecutionRequest) -> dict[str, Any]: ...


class DemoService:
    """Small external process used only to verify the HTTP execution boundary."""

    def execute(self, request: ExecutionRequest) -> dict[str, Any]:
        operation = str(request.arguments.get("operation", "")).strip()
        payload = request.arguments.get("payload", {})
        if not isinstance(payload, dict):
            return request.event(
                ExecutionStatus.FAILED,
                error=ExecutionError("invalid_payload", "payload must be an object"),
            ).to_dict()
        if operation == "inspect":
            result = {
                "service": "self-test-demo",
                "operations": ["inspect", "echo"],
                "received_execution_id": request.execution_id,
            }
        elif operation == "echo":
            result = {"echo": payload}
        else:
            return request.event(
                ExecutionStatus.FAILED,
                error=ExecutionError(
                    "unsupported_operation",
                    f"unsupported demo operation: {operation}",
                ),
            ).to_dict()
        return request.event(ExecutionStatus.SUCCEEDED, result=result).to_dict()


class ExecutionServiceHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        service: ExecutionService,
        service_name: str,
    ) -> None:
        self.service = service
        self.service_name = service_name
        super().__init__(server_address, DemoServiceHandler)


class DemoServiceHTTPServer(ExecutionServiceHTTPServer):
    def __init__(self, server_address: tuple[str, int], service: DemoService | None = None) -> None:
        super().__init__(server_address, service or DemoService(), "self-test-demo")


class DemoServiceHandler(BaseHTTPRequestHandler):
    server: ExecutionServiceHTTPServer

    def do_GET(self) -> None:
        if urlparse(self.path).path == "/health":
            self._send(200, {"status": "ok", "service": self.server.service_name})
            return
        self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/executions":
            self._send(404, {"error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1024 * 1024:
                raise ValueError("request body must be between 1 byte and 1 MiB")
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("request body must be a JSON object")
            request = ExecutionRequest.from_dict(data)
            if request.execution_target != "remote_service":
                raise ValueError("demo service only accepts remote_service requests")
            self._send(200, self.server.service.execute(request))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._send(400, {"error": type(exc).__name__, "message": str(exc)})

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the self-test remote service demo")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9020)
    args = parser.parse_args()
    server = DemoServiceHTTPServer((args.host, args.port))
    print(f"Demo remote service listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
