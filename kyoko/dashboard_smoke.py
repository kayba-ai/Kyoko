from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from typing import Any, Optional
from urllib.request import urlopen

from .demo import DemoError, run_demo_setup
from .storage import StorageError, initialize_database
from .web import make_handler


DEFAULT_DASHBOARD_SMOKE_VIEWPORTS = (
    ("desktop", 1440, 1000),
    ("mobile", 390, 844),
)


# The shipping dashboard is the React/Vite SPA, which mounts into ``#root`` and
# renders a left nav (Overview / Runs / ...). Readiness = the SPA has actually
# mounted content into ``#root`` and the nav contains the "Overview" item.
_SPA_MOUNTED_PREDICATE = (
    "() => { const root = document.querySelector('#root');"
    " return Boolean(root) && root.children.length > 0"
    " && /Overview/.test(document.body.innerText); }"
)


class DashboardSmokeError(Exception):
    """Raised when the dashboard browser smoke cannot complete."""


@dataclass(frozen=True)
class DashboardViewportSmokeResult:
    name: str
    width: int
    height: int
    # ``metric_count`` is retained for the frozen doctor/CLI JSON contract; for
    # the React SPA it counts the left-nav items that prove the app mounted.
    # ``metric_overflows`` is kept (always empty) for the same contract reason.
    metric_count: int
    metric_overflows: tuple[dict[str, Any], ...]
    screenshot_path: Optional[Path]

    @property
    def passed(self) -> bool:
        return self.metric_count > 0 and not self.metric_overflows

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "metric_count": self.metric_count,
            "metric_overflows": list(self.metric_overflows),
            "screenshot_path": str(self.screenshot_path) if self.screenshot_path else None,
            "passed": self.passed,
        }


@dataclass(frozen=True)
class DashboardSmokeReport:
    db_path: Path
    output_dir: Optional[Path]
    temporary: bool
    server_url: str
    seeded_demo: bool
    api_status: dict[str, Any]
    api_metric_cards_count: int
    console_errors: tuple[str, ...]
    page_errors: tuple[str, ...]
    request_failures: tuple[str, ...]
    viewports: tuple[DashboardViewportSmokeResult, ...]
    browser_backend: str

    @property
    def passed(self) -> bool:
        return (
            not self.console_errors
            and not self.page_errors
            and not self.request_failures
            and len(self.viewports) == len(DEFAULT_DASHBOARD_SMOKE_VIEWPORTS)
            and all(viewport.passed for viewport in self.viewports)
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "dashboard_browser_smoke",
            "db_path": str(self.db_path),
            "output_dir": str(self.output_dir) if self.output_dir else None,
            "temporary": self.temporary,
            "server_url": self.server_url,
            "seeded_demo": self.seeded_demo,
            "api_status": self.api_status,
            "api_metric_cards_count": self.api_metric_cards_count,
            "console_errors": list(self.console_errors),
            "page_errors": list(self.page_errors),
            "request_failures": list(self.request_failures),
            "viewports": [viewport.to_json() for viewport in self.viewports],
            "browser_backend": self.browser_backend,
            "passed": self.passed,
        }


def run_dashboard_browser_smoke(
    *,
    db_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    seed_demo: bool = True,
    screenshot: bool = False,
    install_browser_deps: bool = False,
    timeout_seconds: int = 30,
) -> DashboardSmokeReport:
    """Run a real browser smoke against the local dashboard."""

    if timeout_seconds <= 0:
        raise DashboardSmokeError("timeout_seconds_must_be_positive")
    node = None
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        sync_playwright = None
        PlaywrightError = None
        PlaywrightTimeoutError = None
        node = shutil.which("node")
        if node is None:
            raise DashboardSmokeError(
                "playwright_missing: install Python Playwright or Node.js plus @playwright/test"
            ) from exc

    if output_dir is not None:
        selected_output_dir = output_dir.resolve()
        selected_output_dir.mkdir(parents=True, exist_ok=True)
        selected_db_path = (db_path or selected_output_dir / "dashboard-smoke.db").resolve()
        if db_path is None:
            _remove_sqlite_files(selected_db_path)
        if sync_playwright is None:
            return _run_dashboard_browser_smoke_with_node_paths(
                db_path=selected_db_path,
                output_dir=selected_output_dir,
                temporary=False,
                seed_demo=seed_demo,
                screenshot=screenshot,
                install_browser_deps=install_browser_deps,
                timeout_seconds=timeout_seconds,
            )
        return _run_dashboard_browser_smoke_with_paths(
            db_path=selected_db_path,
            output_dir=selected_output_dir,
            temporary=False,
            seed_demo=seed_demo,
            screenshot=screenshot,
            timeout_seconds=timeout_seconds,
            sync_playwright=sync_playwright,
            playwright_errors=(PlaywrightError, PlaywrightTimeoutError),
        )

    if db_path is not None:
        if sync_playwright is None:
            with TemporaryDirectory() as tmpdir:
                return _run_dashboard_browser_smoke_with_node_paths(
                    db_path=db_path.resolve(),
                    output_dir=Path(tmpdir),
                    temporary=False,
                    seed_demo=seed_demo,
                    screenshot=False,
                    install_browser_deps=install_browser_deps,
                    timeout_seconds=timeout_seconds,
                )
        return _run_dashboard_browser_smoke_with_paths(
            db_path=db_path.resolve(),
            output_dir=None,
            temporary=False,
            seed_demo=seed_demo,
            screenshot=screenshot,
            timeout_seconds=timeout_seconds,
            sync_playwright=sync_playwright,
            playwright_errors=(PlaywrightError, PlaywrightTimeoutError),
        )

    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        if sync_playwright is None:
            return _run_dashboard_browser_smoke_with_node_paths(
                db_path=root / "dashboard-smoke.db",
                output_dir=root,
                temporary=True,
                seed_demo=seed_demo,
                screenshot=False,
                install_browser_deps=install_browser_deps,
                timeout_seconds=timeout_seconds,
            )
        return _run_dashboard_browser_smoke_with_paths(
            db_path=root / "dashboard-smoke.db",
            output_dir=None,
            temporary=True,
            seed_demo=seed_demo,
            screenshot=False,
            timeout_seconds=timeout_seconds,
            sync_playwright=sync_playwright,
            playwright_errors=(PlaywrightError, PlaywrightTimeoutError),
        )


def _run_dashboard_browser_smoke_with_paths(
    *,
    db_path: Path,
    output_dir: Optional[Path],
    temporary: bool,
    seed_demo: bool,
    screenshot: bool,
    timeout_seconds: int,
    sync_playwright,
    playwright_errors: tuple[type[BaseException], ...],
) -> DashboardSmokeReport:
    try:
        if seed_demo:
            demo_output_dir = output_dir / "demo-replay" if output_dir else db_path.parent / "demo-replay"
            run_demo_setup(db_path=db_path, output_dir=demo_output_dir)
        else:
            initialize_database(db_path)
    except (DemoError, StorageError) as exc:
        raise DashboardSmokeError(f"dashboard_smoke_seed_failed:{exc}") from exc

    with _RunningDashboardServer(db_path) as server:
        status = _get_json(f"{server.base_url}/api/status")
        metrics = _get_json(f"{server.base_url}/api/dashboard-metrics")
        console_errors: list[str] = []
        page_errors: list[str] = []
        request_failures: list[str] = []
        viewport_results: list[DashboardViewportSmokeResult] = []
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    for name, width, height in DEFAULT_DASHBOARD_SMOKE_VIEWPORTS:
                        page = browser.new_page(viewport={"width": width, "height": height})
                        page.on(
                            "console",
                            lambda message: _record_console_error(console_errors, message),
                        )
                        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
                        page.on(
                            "requestfailed",
                            lambda request: request_failures.append(_request_failure_text(request)),
                        )
                        page.goto(server.base_url, wait_until="networkidle", timeout=timeout_seconds * 1000)
                        page.wait_for_function(
                            _SPA_MOUNTED_PREDICATE,
                            timeout=timeout_seconds * 1000,
                        )
                        screenshot_path = None
                        if screenshot and output_dir is not None:
                            screenshot_path = output_dir / f"dashboard-{name}.png"
                            page.screenshot(path=str(screenshot_path), full_page=True)
                        nav_item_count = int(page.locator("nav a").count())
                        viewport_results.append(
                            DashboardViewportSmokeResult(
                                name=name,
                                width=width,
                                height=height,
                                metric_count=nav_item_count,
                                metric_overflows=(),
                                screenshot_path=screenshot_path,
                            )
                        )
                        page.close()
                finally:
                    browser.close()
        except playwright_errors as exc:
            raise DashboardSmokeError(f"dashboard_browser_smoke_failed:{exc}") from exc

    return DashboardSmokeReport(
        db_path=db_path,
        output_dir=output_dir,
        temporary=temporary,
        server_url=server.base_url,
        seeded_demo=seed_demo,
        api_status=status,
        api_metric_cards_count=len(metrics.get("cards", [])) if isinstance(metrics, dict) else 0,
        console_errors=tuple(console_errors),
        page_errors=tuple(page_errors),
        request_failures=tuple(request_failures),
        viewports=tuple(viewport_results),
        browser_backend="python-playwright",
    )


def _run_dashboard_browser_smoke_with_node_paths(
    *,
    db_path: Path,
    output_dir: Path,
    temporary: bool,
    seed_demo: bool,
    screenshot: bool,
    install_browser_deps: bool,
    timeout_seconds: int,
) -> DashboardSmokeReport:
    playwright_bin = _node_playwright_bin(
        output_dir=output_dir,
        install_browser_deps=install_browser_deps,
    )
    try:
        if seed_demo:
            run_demo_setup(db_path=db_path, output_dir=output_dir / "demo-replay")
        else:
            initialize_database(db_path)
    except (DemoError, StorageError) as exc:
        raise DashboardSmokeError(f"dashboard_smoke_seed_failed:{exc}") from exc

    spec_path = output_dir / "dashboard-smoke.spec.cjs"
    result_path = output_dir / "dashboard-smoke-result.json"
    screenshot_dir = output_dir / "screenshots" if screenshot else None
    if screenshot_dir is not None:
        screenshot_dir.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(_node_playwright_spec(), encoding="utf-8")

    with _RunningDashboardServer(db_path) as server:
        status = _get_json(f"{server.base_url}/api/status")
        metrics = _get_json(f"{server.base_url}/api/dashboard-metrics")
        env = os.environ.copy()
        env.update(
            {
                "KYOKO_DASHBOARD_SMOKE_URL": server.base_url,
                "KYOKO_DASHBOARD_SMOKE_RESULT_PATH": str(result_path),
                "KYOKO_DASHBOARD_SMOKE_TIMEOUT_MS": str(timeout_seconds * 1000),
                "KYOKO_DASHBOARD_SMOKE_VIEWPORTS": json.dumps(
                    [
                        {"name": name, "width": width, "height": height}
                        for name, width, height in DEFAULT_DASHBOARD_SMOKE_VIEWPORTS
                    ],
                    sort_keys=True,
                ),
            }
        )
        if screenshot_dir is not None:
            env["KYOKO_DASHBOARD_SMOKE_SCREENSHOT_DIR"] = str(screenshot_dir)
        completed = subprocess.run(
            [
                str(playwright_bin),
                "test",
                str(spec_path),
                "--reporter=line",
                "--workers=1",
            ],
            cwd=output_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=max(timeout_seconds * 4, timeout_seconds + 30),
            check=False,
        )
        if completed.returncode != 0:
            output = (completed.stdout + completed.stderr)[-4000:]
            raise DashboardSmokeError(f"dashboard_browser_smoke_failed:npx:{output}")
        result = _load_node_result(result_path)

    return DashboardSmokeReport(
        db_path=db_path,
        output_dir=None if temporary else output_dir,
        temporary=temporary,
        server_url=server.base_url,
        seeded_demo=seed_demo,
        api_status=status,
        api_metric_cards_count=len(metrics.get("cards", [])) if isinstance(metrics, dict) else 0,
        console_errors=tuple(result.get("console_errors", [])),
        page_errors=tuple(result.get("page_errors", [])),
        request_failures=tuple(result.get("request_failures", [])),
        viewports=tuple(_node_viewport_results(result.get("viewports", []))),
        browser_backend="npx-playwright",
    )


class _RunningDashboardServer:
    def __init__(self, db_path: Path) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(db_path))
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self.base_url = f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self) -> "_RunningDashboardServer":
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def _get_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def _remove_sqlite_files(db_path: Path) -> None:
    for path in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _record_console_error(console_errors: list[str], message) -> None:
    if message.type == "error":
        console_errors.append(message.text)


def _request_failure_text(request) -> str:
    failure = request.failure
    error_text = failure.get("errorText") if isinstance(failure, dict) else str(failure)
    return f"{request.method} {request.url} {error_text}"


def _load_node_result(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DashboardSmokeError(f"dashboard_browser_smoke_result_missing:{path}") from exc
    if not isinstance(payload, dict):
        raise DashboardSmokeError("dashboard_browser_smoke_result_not_object")
    return payload


def _node_viewport_results(payloads: Any) -> list[DashboardViewportSmokeResult]:
    if not isinstance(payloads, list):
        return []
    results: list[DashboardViewportSmokeResult] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        screenshot_path = payload.get("screenshot_path")
        results.append(
            DashboardViewportSmokeResult(
                name=str(payload.get("name") or "viewport"),
                width=int(payload.get("width") or 0),
                height=int(payload.get("height") or 0),
                metric_count=int(payload.get("metric_count") or 0),
                metric_overflows=tuple(
                    item for item in payload.get("metric_overflows", []) if isinstance(item, dict)
                ),
                screenshot_path=Path(screenshot_path) if isinstance(screenshot_path, str) else None,
            )
        )
    return results


def _node_playwright_bin(*, output_dir: Path, install_browser_deps: bool) -> Path:
    package_json = output_dir / "node_modules" / "@playwright" / "test" / "package.json"
    playwright_bin = output_dir / "node_modules" / ".bin" / "playwright"
    if not package_json.exists():
        if not install_browser_deps:
            raise DashboardSmokeError(
                "playwright_missing: Python Playwright is unavailable; rerun with "
                "--output-dir and --install-browser-deps to install @playwright/test locally"
            )
        npm = shutil.which("npm")
        if npm is None:
            raise DashboardSmokeError("playwright_missing:npm_not_found")
        completed = subprocess.run(
            [
                npm,
                "install",
                "--prefix",
                str(output_dir),
                "--no-save",
                "@playwright/test",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=240,
            check=False,
        )
        if completed.returncode != 0:
            output = (completed.stdout + completed.stderr)[-4000:]
            raise DashboardSmokeError(f"playwright_install_failed:{output}")
    if not playwright_bin.exists():
        raise DashboardSmokeError(f"playwright_binary_missing:{playwright_bin}")
    if install_browser_deps:
        completed = subprocess.run(
            [str(playwright_bin), "install", "chromium"],
            cwd=output_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=240,
            check=False,
        )
        if completed.returncode != 0:
            output = (completed.stdout + completed.stderr)[-4000:]
            raise DashboardSmokeError(f"playwright_browser_install_failed:{output}")
    return playwright_bin


def _node_playwright_spec() -> str:
    return r"""
const fs = require("fs");
const { test } = require("@playwright/test");

const baseUrl = process.env.KYOKO_DASHBOARD_SMOKE_URL;
const resultPath = process.env.KYOKO_DASHBOARD_SMOKE_RESULT_PATH;
const timeoutMs = Number(process.env.KYOKO_DASHBOARD_SMOKE_TIMEOUT_MS || "30000");
const screenshotDir = process.env.KYOKO_DASHBOARD_SMOKE_SCREENSHOT_DIR || "";
const viewports = JSON.parse(process.env.KYOKO_DASHBOARD_SMOKE_VIEWPORTS || "[]");
const result = {
  console_errors: [],
  page_errors: [],
  request_failures: [],
  viewports: []
};

test("kyoko dashboard browser smoke", async ({ browser }) => {
  for (const viewport of viewports) {
    const context = await browser.newContext({
      viewport: { width: viewport.width, height: viewport.height }
    });
    const page = await context.newPage();
    page.on("console", (message) => {
      if (message.type() === "error") {
        result.console_errors.push(message.text());
      }
    });
    page.on("pageerror", (error) => result.page_errors.push(String(error)));
    page.on("requestfailed", (request) => {
      const failure = request.failure();
      result.request_failures.push(`${request.method()} ${request.url()} ${failure ? failure.errorText : ""}`);
    });
    await page.goto(baseUrl, { waitUntil: "networkidle", timeout: timeoutMs });
    await page.waitForFunction(
      () => {
        const root = document.querySelector("#root");
        return Boolean(root) && root.children.length > 0 && /Overview/.test(document.body.innerText);
      },
      null,
      { timeout: timeoutMs }
    );
    const navItemCount = await page.locator("nav a").count();
    let screenshotPath = null;
    if (screenshotDir) {
      screenshotPath = `${screenshotDir}/dashboard-${viewport.name}.png`;
      await page.screenshot({ path: screenshotPath, fullPage: true });
    }
    result.viewports.push({
      name: viewport.name,
      width: viewport.width,
      height: viewport.height,
      metric_count: navItemCount,
      metric_overflows: [],
      screenshot_path: screenshotPath
    });
    await context.close();
  }
});

test.afterAll(async () => {
  fs.writeFileSync(resultPath, JSON.stringify(result, null, 2) + "\n");
});
"""
