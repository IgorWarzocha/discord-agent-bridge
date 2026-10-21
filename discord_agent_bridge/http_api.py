"""Local HTTP server for callback posts. It does not log the token or the body."""

from __future__ import annotations

import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from discord_agent_bridge.replies import RAW_BODY_LIMIT, CallbackService, HttpResult, log_line

logger = logging.getLogger("discord_agent_bridge")


class CallbackHandler(BaseHTTPRequestHandler):
    server: CallbackHttpServer
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        length = self._content_length()
        if length is None:
            result = HttpResult(411, {"error": "length required"}, "unknown", "", "")
            self._send(result, 0)
            return
        if length > RAW_BODY_LIMIT:
            result = HttpResult(413, {"error": "body too large"}, _route_name(self.path), "", "")
            self._send(result, length)
            return
        raw = self.rfile.read(length)
        result = self.server.service.handle(self.path, raw)
        self._send(result, length)

    def do_GET(self) -> None:
        result = HttpResult(404, {"error": "not found"}, "unknown", "", "")
        self._send(result, 0)

    def log_message(self, format: str, *args: object) -> None:
        """BaseHTTPRequestHandler would write the request path, which holds the token."""
        return

    def _content_length(self) -> int | None:
        raw = self.headers.get("Content-Length")
        if raw is None or not raw.isdigit():
            return None
        return int(raw)

    def _send(self, result: HttpResult, byte_count: int) -> None:
        encoded = _json(result.body)
        self.send_response(result.status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
        logger.info("%s", log_line(result, byte_count))


class CallbackHttpServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], service: CallbackService) -> None:
        self.service = service
        super().__init__(address, CallbackHandler)


def serve_in_thread(host: str, port: int, service: CallbackService) -> CallbackHttpServer:
    server = CallbackHttpServer((host, port), service)
    thread = threading.Thread(target=server.serve_forever, name="callback-http", daemon=True)
    thread.start()
    return server


def stop_http(server: CallbackHttpServer) -> None:
    server.shutdown()
    server.server_close()


def _route_name(path: str) -> str:
    head = path.split("?", 1)[0].strip("/").split("/", 1)[0]
    if head in {"reply", "react"}:
        return head
    return "unknown"


def _json(body: dict[str, object]) -> bytes:
    import json

    return json.dumps(body).encode("utf-8")
