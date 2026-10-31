"""Configurable in-thread A2A stub agent for gateway/security tests (stdlib http.server)."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class StubAgent:
    def __init__(self, reply: Callable[[dict[str, Any]], Any], card_override: dict[str, Any] | None = None):
        self.reply = reply
        self.card_override = card_override or {}
        stub = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:
                pass

            def _send(self, obj: Any) -> None:
                body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                card = {"name": "stub", "description": "", "url": stub.url + "/", "version": "1",
                        "defaultInputModes": ["application/json"], "defaultOutputModes": ["application/json"],
                        "skills": [{"id": "wifi-rf-telemetry", "name": "rf"}]}
                card.update(stub.card_override)
                self._send(card)

            def do_POST(self) -> None:  # noqa: N802
                n = int(self.headers.get("Content-Length", 0))
                rpc = json.loads(self.rfile.read(n))
                env = rpc["params"]["message"]["parts"][0]["data"]
                data = stub.reply(env)
                if isinstance(data, bytes):
                    return self._send(data)
                self._send({"jsonrpc": "2.0", "id": rpc["id"],
                            "result": {"kind": "message", "role": "agent", "messageId": "m",
                                       "parts": [{"kind": "data", "data": data}]}})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> StubAgent:
        self.thread.start()
        return self

    def __exit__(self, *a: Any) -> None:
        self.server.shutdown()
        self.server.server_close()


def v09(env: dict[str, Any], obs: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
    q = "evidence" if env.get("message_type") == "evidence_request" else "task"
    return {"ver": "0.9", "inc": env["incident_id"], "from": "stub", "re": env["message_id"], "q": q, "obs": obs, **kw}
