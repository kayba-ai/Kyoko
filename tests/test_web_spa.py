"""Static-file serving for the built React/Vite dashboard bundle (Phase F).

`kyoko serve` serves the compiled SPA at `/` and its hashed assets under `/assets/*`,
with a client-side-routing fallback (unknown non-API GET paths return index.html) and
the existing JSON API untouched. When no bundle is present it falls back to the inline
HTML dashboard. These tests patch the bundle directory to a fixture so they do not
depend on `npm run build` having run.
"""

from __future__ import annotations

import json
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from unittest import mock

from kyoko import web
from kyoko.web import make_handler


class _Server:
    def __init__(self, db_path: Path) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(db_path))
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self) -> "_Server":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def get(self, path: str):
        with urlopen(Request(f"{self.base_url}{path}"), timeout=5) as response:
            return response.status, dict(response.headers), response.read()


def _write_bundle(root: Path) -> None:
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text(
        '<!doctype html><html><head><title>Kyoko</title>'
        '<script type="module" src="/assets/app-abc123.js"></script></head>'
        '<body><div id="root"></div></body></html>',
        encoding="utf-8",
    )
    (root / "assets" / "app-abc123.js").write_text("export const x = 1;\n", encoding="utf-8")
    (root / "assets" / "style-def456.css").write_text("body{color:#fff}\n", encoding="utf-8")


class SpaServingTests(unittest.TestCase):
    def test_serves_bundle_index_assets_and_spa_fallback(self) -> None:
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            db_path = tmpdir / "kyoko.db"
            bundle = tmpdir / "web"
            _write_bundle(bundle)

            with mock.patch.object(web, "SPA_BUNDLE_DIR", bundle):
                self.assertTrue(web.spa_bundle_available())
                with _Server(db_path) as server:
                    # `/` serves the SPA shell.
                    status, headers, body = server.get("/")
                    self.assertEqual(status, 200)
                    self.assertIn("text/html", headers["Content-Type"])
                    self.assertIn(b'<div id="root">', body)

                    # Hashed JS asset: correct content-type + immutable caching.
                    status, headers, body = server.get("/assets/app-abc123.js")
                    self.assertEqual(status, 200)
                    self.assertIn("javascript", headers["Content-Type"])
                    self.assertIn("immutable", headers.get("Cache-Control", ""))
                    self.assertIn(b"export const x", body)

                    # CSS asset content-type.
                    status, headers, _ = server.get("/assets/style-def456.css")
                    self.assertEqual(status, 200)
                    self.assertIn("text/css", headers["Content-Type"])

                    # Client-side route falls back to index.html (not a 404).
                    status, headers, body = server.get("/runs/run_123/span/span_9")
                    self.assertEqual(status, 200)
                    self.assertIn("text/html", headers["Content-Type"])
                    self.assertIn(b'<div id="root">', body)

                    # The JSON API is unaffected.
                    status, _, body = server.get("/api/status")
                    self.assertEqual(status, 200)
                    self.assertIn("counts", json.loads(body))

    def test_path_traversal_cannot_escape_bundle_dir(self) -> None:
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            bundle = tmpdir / "web"
            _write_bundle(bundle)
            secret = tmpdir / "secret.txt"
            secret.write_text("TOP SECRET", encoding="utf-8")

            with mock.patch.object(web, "SPA_BUNDLE_DIR", bundle):
                with _Server(tmpdir / "kyoko.db") as server:
                    # Encoded traversal stays inside the bundle dir: it resolves to no
                    # file and falls back to the SPA shell — never the sibling secret.
                    status, headers, body = server.get("/assets/%2e%2e/secret.txt")
                    self.assertEqual(status, 200)
                    self.assertIn("text/html", headers["Content-Type"])
                    self.assertNotIn(b"TOP SECRET", body)

    def test_api_404_preserved_for_unknown_api_paths(self) -> None:
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            bundle = tmpdir / "web"
            _write_bundle(bundle)
            with mock.patch.object(web, "SPA_BUNDLE_DIR", bundle):
                with _Server(tmpdir / "kyoko.db") as server:
                    with self.assertRaises(HTTPError) as ctx:
                        server.get("/api/does-not-exist")
                    self.assertEqual(ctx.exception.code, 404)

    def test_falls_back_to_inline_dashboard_when_bundle_absent(self) -> None:
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            missing = tmpdir / "no-bundle-here"
            with mock.patch.object(web, "SPA_BUNDLE_DIR", missing):
                self.assertFalse(web.spa_bundle_available())
                with _Server(tmpdir / "kyoko.db") as server:
                    status, headers, body = server.get("/")
                    self.assertEqual(status, 200)
                    self.assertIn("text/html", headers["Content-Type"])
                    # The inline dashboard ships an embedded script; the SPA shell does not.
                    self.assertIn(b"Kyoko", body)
                    self.assertIn(b"<script", body)


if __name__ == "__main__":
    unittest.main()
