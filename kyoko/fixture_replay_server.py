from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .bundled_assets import load_bundled_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the bundled Kyoko replay fixture over HTTP.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), make_handler())
    print(f"kyoko fixture replay server listening on {args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


def make_handler() -> type[BaseHTTPRequestHandler]:
    class ReplayHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/health":
                self.send_error(404)
                return
            self._send_json(
                {
                    "ok": True,
                    "profile": "news-research-agent",
                    "framework": "fixture",
                    "side_effect_modes": ["network_mocked", "none"],
                    "capabilities": ["trace", "replay"],
                }
            )

        def do_POST(self) -> None:
            if self.path != "/replay":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            fixture = load_bundled_json("replay-results/researcher-fetch-timeout-success.json")
            fixture["replay"]["replay_run_id"] = payload["replay_run_id"]
            fixture["replay"]["idempotency_key"] = payload.get("idempotency_key") or payload["replay_run_id"]
            self._send_json(fixture)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_json(self, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ReplayHandler


if __name__ == "__main__":
    raise SystemExit(main())
