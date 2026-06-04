from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from string import Template


SUPPORTED_FRAMEWORKS = {
    "generic-python": "Generic Python agent",
    "langgraph-python": "LangGraph Python workflow",
    "pydantic-ai-python": "Pydantic AI Python agent",
    "openai-agents-python": "OpenAI Agents Python workflow",
    "crewai-python": "CrewAI Python workflow",
    "hermes-python": "Hermes agent workflow",
    "openclaw-python": "OpenClaw agent workflow",
    "generic-typescript": "Generic TypeScript/Node agent",
    "ai-sdk-typescript": "AI SDK TypeScript workflow",
}

TYPESCRIPT_REPLAY_FRAMEWORKS = {
    "generic-typescript",
    "ai-sdk-typescript",
}


class ReplayTemplateError(Exception):
    """Raised when a replay server template cannot be written."""


@dataclass(frozen=True)
class ReplayTemplateReport:
    output_path: Path
    framework: str
    profile_name: str
    wrote: bool


def write_replay_server_template(
    *,
    output_path: Path,
    framework: str = "generic-python",
    profile_name: str = "kyoko-agent",
    force: bool = False,
) -> ReplayTemplateReport:
    if framework not in SUPPORTED_FRAMEWORKS:
        raise ReplayTemplateError(f"unsupported_replay_template_framework:{framework}")
    if output_path.exists() and not force:
        raise ReplayTemplateError(f"replay_template_exists:{output_path}")
    if not profile_name:
        raise ReplayTemplateError("profile_name_required")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        _template_source(framework=framework, profile_name=profile_name),
        encoding="utf-8",
    )
    current_mode = output_path.stat().st_mode
    output_path.chmod(current_mode | 0o111)
    return ReplayTemplateReport(
        output_path=output_path,
        framework=framework,
        profile_name=profile_name,
        wrote=True,
    )


def _template_source(*, framework: str, profile_name: str) -> str:
    template = NODE_SERVER_TEMPLATE if framework in TYPESCRIPT_REPLAY_FRAMEWORKS else SERVER_TEMPLATE
    return template.safe_substitute(
        framework=framework,
        framework_label=SUPPORTED_FRAMEWORKS[framework],
        profile_name=profile_name,
    )


def recommended_replay_server_filename(framework: str) -> str:
    if framework in TYPESCRIPT_REPLAY_FRAMEWORKS:
        return "kyoko_replay_server.mjs"
    return "kyoko_replay_server.py"


SERVER_TEMPLATE = Template(
    '''#!/usr/bin/env python3
"""
Kyoko replay server template.

Framework: $framework_label

Run:
    python3 kyoko_replay_server.py --port 61200

Register:
    python3 -m kyoko replay-adapter-register \\
      --db /tmp/kyoko.db \\
      $profile_name-replay \\
      --name "$profile_name replay" \\
      --command "python3 kyoko_replay_server.py --port 61200" \\
      --server-url http://127.0.0.1:61200 \\
      --json

This file is intentionally stdlib-only. Wire `run_agent_replay` to your agent,
emit replay telemetry back into Kyoko, then return the output run id and target
map. Keep side effects mocked or sandboxed until the eval gate is trustworthy.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


PROFILE_NAME = "$profile_name"
FRAMEWORK = "$framework"
SUPPORTED_SIDE_EFFECT_MODES = {"none", "filesystem_read", "sandboxed_filesystem", "network_mocked"}
FRAMEWORK_HINTS = {
    "generic-python": "Call your Python agent with the replay input and return source_events plus output_run_id.",
    "langgraph-python": "Invoke your compiled graph with the replay input and return traced source_events plus output_run_id.",
    "pydantic-ai-python": "Run your Pydantic AI agent with mocked/sandboxed tools and return source_events plus output_run_id.",
    "openai-agents-python": "Run your OpenAI Agents SDK workflow with mocked tools/handoffs and return source_events plus output_run_id.",
    "crewai-python": "Run your CrewAI crew/task with mocked tools and return source_events plus output_run_id.",
    "hermes-python": "Dispatch the Hermes profile/task replay through your local Hermes command or API and return source_events plus output_run_id.",
    "openclaw-python": "Run the OpenClaw agent/session replay in its workspace and return source_events plus output_run_id.",
}


def run_agent_replay(request_payload: dict[str, Any]) -> dict[str, Any]:
    """Run the target agent and return Kyoko replay completion metadata.

    Easiest hook return shape:
        {
            "status": "passed",
            "output_run_id": "run_replay_...",
            "actual_side_effect_mode": "network_mocked",
            "target_map": {"source_span_id": "replay_span_id"},
            "note": "what happened",
            "source_events": { ... Kyoko canonical source-event JSON ... }
        }

    If your agent already emitted telemetry to Kyoko, omit source_events and
    return only output_run_id/run_id plus status metadata. You can also return
    a full kyoko.replay_result.v1 object with a top-level "replay" key.

    Configure without editing this file:
        KYOKO_REPLAY_HOOK=/absolute/path/to/hooks.py:replay
        KYOKO_REPLAY_HOOK=my_package.replay:replay
    """
    hook = load_replay_hook()
    if hook is None:
        hint = FRAMEWORK_HINTS.get(FRAMEWORK, FRAMEWORK_HINTS["generic-python"])
        raise NotImplementedError(
            "set KYOKO_REPLAY_HOOK=module_or_path:function; " + hint
        )
    return hook(request_payload)


def load_replay_hook() -> Any:
    hook_spec = os.environ.get("KYOKO_REPLAY_HOOK", "").strip()
    if not hook_spec:
        return None
    module_ref, separator, function_name = hook_spec.rpartition(":")
    if not separator or not module_ref or not function_name:
        raise ValueError("KYOKO_REPLAY_HOOK must be module_or_path:function")
    if module_ref.endswith(".py") or "/" in module_ref or "\\\\" in module_ref:
        module_path = Path(module_ref).expanduser().resolve()
        spec = importlib.util.spec_from_file_location("kyoko_replay_hook", module_path)
        if spec is None or spec.loader is None:
            raise ValueError(f"cannot load replay hook module: {module_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    else:
        module = importlib.import_module(module_ref)
    hook = getattr(module, function_name, None)
    if not callable(hook):
        raise ValueError(f"replay hook is not callable: {hook_spec}")
    return hook


def build_replay_response(request_payload: dict[str, Any], hook_result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(hook_result, dict):
        raise ValueError("run_agent_replay must return a JSON object")

    if isinstance(hook_result.get("replay"), dict):
        response = dict(hook_result)
        replay = dict(response["replay"])
        replay["replay_run_id"] = request_payload["replay_run_id"]
        replay.setdefault("actual_side_effect_mode", _actual_side_effect_mode(request_payload, hook_result))
        response["replay"] = replay
        response.setdefault("fixture_version", "kyoko.replay_result.v1")
        return response

    output_run_id = hook_result.get("output_run_id") or hook_result.get("run_id")
    if not isinstance(output_run_id, str) or not output_run_id:
        raise ValueError("run_agent_replay must return output_run_id or run_id")

    status = str(hook_result.get("status") or "passed")
    actual_side_effect_mode = _actual_side_effect_mode(request_payload, hook_result)
    target_map = hook_result.get("target_map", {})
    if not isinstance(target_map, dict):
        raise ValueError("target_map must be an object")

    source_events = hook_result.get("source_events") or hook_result.get("fixture")
    if source_events is None:
        return {
            "status": status,
            "replay_run_id": request_payload["replay_run_id"],
            "idempotency_key": request_payload.get("idempotency_key") or request_payload["replay_run_id"],
            "run_id": output_run_id,
            "output_run_id": output_run_id,
            "executed_agent": bool(hook_result.get("executed_agent", True)),
            "actual_side_effect_mode": actual_side_effect_mode,
            "target_map": target_map,
            "note": hook_result.get("note", "replay hook completed"),
        }
    if not isinstance(source_events, dict):
        raise ValueError("source_events must be an object")

    response = dict(source_events)
    response["fixture_version"] = "kyoko.replay_result.v1"
    response["replay"] = {
        "replay_run_id": request_payload["replay_run_id"],
        "output_run_id": output_run_id,
        "status": status,
        "executed_agent": bool(hook_result.get("executed_agent", True)),
        "actual_side_effect_mode": actual_side_effect_mode,
        "target_map": target_map,
        "note": hook_result.get("note", "replay hook completed"),
    }
    return response


def _actual_side_effect_mode(request_payload: dict[str, Any], hook_result: dict[str, Any]) -> str:
    mode = (
        hook_result.get("actual_side_effect_mode")
        or hook_result.get("side_effect_mode")
        or request_payload.get("side_effect_mode")
        or "unknown"
    )
    if mode not in SUPPORTED_SIDE_EFFECT_MODES:
        raise ValueError(f"unsupported actual_side_effect_mode: {mode}")
    return str(mode)


class ReplayHandler(BaseHTTPRequestHandler):
    server_version = "KyokoReplayTemplate/0.1"

    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return
        self._send_json(
            {
                "ok": True,
                "profile": PROFILE_NAME,
                "framework": FRAMEWORK,
                "side_effect_modes": sorted(SUPPORTED_SIDE_EFFECT_MODES),
                "capabilities": ["trace", "replay"],
            }
        )

    def do_POST(self) -> None:
        if self.path != "/replay":
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return
        try:
            payload = self._read_json()
            self._validate_replay_request(payload)
            result = build_replay_response(payload, run_agent_replay(payload))
        except NotImplementedError as exc:
            self._send_json(
                {
                    "status": "errored",
                    "error": "replay_not_implemented",
                    "detail": str(exc),
                },
                status=HTTPStatus.NOT_IMPLEMENTED,
            )
            return
        except ValueError as exc:
            self._send_json(
                {"status": "errored", "error": "invalid_replay_request", "detail": str(exc)},
                status=HTTPStatus.BAD_REQUEST,
            )
            return
        self._send_json(result)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _validate_replay_request(self, payload: dict[str, Any]) -> None:
        replay_run_id = payload.get("replay_run_id")
        if not isinstance(replay_run_id, str) or not replay_run_id:
            raise ValueError("replay_run_id required")
        side_effect_mode = payload.get("side_effect_mode")
        if side_effect_mode not in SUPPORTED_SIDE_EFFECT_MODES:
            raise ValueError(f"unsupported side_effect_mode: {side_effect_mode}")

    def _send_json(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


class FastThreadingHTTPServer(ThreadingHTTPServer):
    def server_bind(self) -> None:
        self.socket.bind(self.server_address)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


def main() -> int:
    parser = argparse.ArgumentParser(description="Kyoko replay server template")
    parser.add_argument("--host", default=os.environ.get("KYOKO_REPLAY_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("KYOKO_REPLAY_PORT", "61200")))
    args = parser.parse_args()

    server = FastThreadingHTTPServer((args.host, args.port), ReplayHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
)


NODE_SERVER_TEMPLATE = Template(
    '''#!/usr/bin/env node
/*
Kyoko replay server template.

Framework: $framework_label

Run:
    node kyoko_replay_server.mjs --port 61200

Register:
    python3 -m kyoko replay-adapter-register \\
      --db /tmp/kyoko.db \\
      $profile_name-replay \\
      --name "$profile_name replay" \\
      --command "node kyoko_replay_server.mjs --port 61200" \\
      --server-url http://127.0.0.1:61200 \\
      --json

This file is dependency-free ESM. Wire KYOKO_REPLAY_HOOK to your Node agent,
emit replay telemetry back into Kyoko, then return the output run id and target
map. Keep side effects mocked or sandboxed until the eval gate is trustworthy.
*/

import http from "node:http";
import path from "node:path";
import { pathToFileURL } from "node:url";

const PROFILE_NAME = "$profile_name";
const FRAMEWORK = "$framework";
const SUPPORTED_SIDE_EFFECT_MODES = new Set(["none", "filesystem_read", "sandboxed_filesystem", "network_mocked"]);
const FRAMEWORK_HINTS = {
  "generic-typescript": "Call your Node agent with the replay input and return source_events plus output_run_id.",
  "ai-sdk-typescript": "Run your AI SDK workflow with mocked tools and return source_events plus output_run_id."
};

async function runAgentReplay(requestPayload) {
  const hook = await loadReplayHook();
  if (!hook) {
    const hint = FRAMEWORK_HINTS[FRAMEWORK] || FRAMEWORK_HINTS["generic-typescript"];
    const error = new Error("set KYOKO_REPLAY_HOOK=module_or_path:function; " + hint);
    error.code = "replay_not_implemented";
    throw error;
  }
  return await hook(requestPayload);
}

async function loadReplayHook() {
  const hookSpec = (process.env.KYOKO_REPLAY_HOOK || "").trim();
  if (!hookSpec) {
    return null;
  }
  const separatorIndex = hookSpec.lastIndexOf(":");
  if (separatorIndex <= 0 || separatorIndex === hookSpec.length - 1) {
    throw new Error("KYOKO_REPLAY_HOOK must be module_or_path:function");
  }
  const moduleRef = hookSpec.slice(0, separatorIndex);
  const functionName = hookSpec.slice(separatorIndex + 1);
  let module;
  if (isPathLikeModule(moduleRef)) {
    const modulePath = path.resolve(expandHome(moduleRef));
    module = await import(pathToFileURL(modulePath).href);
  } else {
    module = await import(moduleRef);
  }
  const hook = module[functionName] || (module.default && module.default[functionName]);
  if (typeof hook !== "function") {
    throw new Error("replay hook is not callable: " + hookSpec);
  }
  return hook;
}

function buildReplayResponse(requestPayload, hookResult) {
  if (!hookResult || typeof hookResult !== "object" || Array.isArray(hookResult)) {
    throw new Error("runAgentReplay must return a JSON object");
  }

  if (hookResult.replay && typeof hookResult.replay === "object" && !Array.isArray(hookResult.replay)) {
    const response = { ...hookResult };
    const replay = { ...response.replay };
    replay.replay_run_id = requestPayload.replay_run_id;
    replay.actual_side_effect_mode = replay.actual_side_effect_mode || actualSideEffectMode(requestPayload, hookResult);
    response.replay = replay;
    response.fixture_version = response.fixture_version || "kyoko.replay_result.v1";
    return response;
  }

  const outputRunId = hookResult.output_run_id || hookResult.run_id;
  if (typeof outputRunId !== "string" || !outputRunId) {
    throw new Error("runAgentReplay must return output_run_id or run_id");
  }

  const status = String(hookResult.status || "passed");
  const actualMode = actualSideEffectMode(requestPayload, hookResult);
  const targetMap = hookResult.target_map || {};
  if (!targetMap || typeof targetMap !== "object" || Array.isArray(targetMap)) {
    throw new Error("target_map must be an object");
  }

  const sourceEvents = hookResult.source_events || hookResult.fixture;
  if (sourceEvents === undefined || sourceEvents === null) {
    return {
      status,
      replay_run_id: requestPayload.replay_run_id,
      idempotency_key: requestPayload.idempotency_key || requestPayload.replay_run_id,
      run_id: outputRunId,
      output_run_id: outputRunId,
      executed_agent: hookResult.executed_agent !== false,
      actual_side_effect_mode: actualMode,
      target_map: targetMap,
      note: hookResult.note || "replay hook completed"
    };
  }
  if (!sourceEvents || typeof sourceEvents !== "object" || Array.isArray(sourceEvents)) {
    throw new Error("source_events must be an object");
  }

  const response = { ...sourceEvents };
  response.fixture_version = "kyoko.replay_result.v1";
  response.replay = {
    replay_run_id: requestPayload.replay_run_id,
    output_run_id: outputRunId,
    status,
    executed_agent: hookResult.executed_agent !== false,
    actual_side_effect_mode: actualMode,
    target_map: targetMap,
    note: hookResult.note || "replay hook completed"
  };
  return response;
}

function actualSideEffectMode(requestPayload, hookResult) {
  const mode = hookResult.actual_side_effect_mode || hookResult.side_effect_mode || requestPayload.side_effect_mode || "unknown";
  if (!SUPPORTED_SIDE_EFFECT_MODES.has(mode)) {
    throw new Error("unsupported actual_side_effect_mode: " + mode);
  }
  return String(mode);
}

function validateReplayRequest(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("request body must be a JSON object");
  }
  if (typeof payload.replay_run_id !== "string" || !payload.replay_run_id) {
    throw new Error("replay_run_id required");
  }
  if (!SUPPORTED_SIDE_EFFECT_MODES.has(payload.side_effect_mode)) {
    throw new Error("unsupported side_effect_mode: " + payload.side_effect_mode);
  }
}

function isPathLikeModule(moduleRef) {
  return (
    moduleRef.endsWith(".js") ||
    moduleRef.endsWith(".mjs") ||
    moduleRef.endsWith(".cjs") ||
    moduleRef.endsWith(".ts") ||
    moduleRef.includes("/") ||
    moduleRef.includes("\\\\")
  );
}

function expandHome(value) {
  if (value === "~") {
    return process.env.HOME || value;
  }
  if (value.startsWith("~/")) {
    return path.join(process.env.HOME || "~", value.slice(2));
  }
  return value;
}

async function readJsonRequest(request) {
  const chunks = [];
  for await (const chunk of request) {
    chunks.push(chunk);
  }
  const raw = Buffer.concat(chunks).toString("utf8");
  const payload = raw ? JSON.parse(raw) : {};
  validateReplayRequest(payload);
  return payload;
}

function sendJson(response, statusCode, payload) {
  const body = Buffer.from(JSON.stringify(payload, null, 2) + "\\n", "utf8");
  response.writeHead(statusCode, {
    "Content-Type": "application/json",
    "Content-Length": String(body.length),
    "Cache-Control": "no-store"
  });
  response.end(body);
}

function buildArgs(argv) {
  const args = {
    host: process.env.KYOKO_REPLAY_HOST || "127.0.0.1",
    port: Number(process.env.KYOKO_REPLAY_PORT || "61200")
  };
  for (let index = 0; index < argv.length; index += 1) {
    const item = argv[index];
    if (item === "--host") {
      args.host = argv[++index];
    } else if (item === "--port") {
      args.port = Number(argv[++index]);
    } else {
      throw new Error("unknown argument: " + item);
    }
  }
  if (!Number.isInteger(args.port) || args.port < 1 || args.port > 65535) {
    throw new Error("--port must be between 1 and 65535");
  }
  return args;
}

async function handleRequest(request, response) {
  if (request.method === "GET" && request.url === "/health") {
    sendJson(response, 200, {
      ok: true,
      profile: PROFILE_NAME,
      framework: FRAMEWORK,
      side_effect_modes: Array.from(SUPPORTED_SIDE_EFFECT_MODES).sort(),
      capabilities: ["trace", "replay"]
    });
    return;
  }
  if (request.method !== "POST" || request.url !== "/replay") {
    sendJson(response, 404, { status: "errored", error: "not_found" });
    return;
  }

  try {
    const payload = await readJsonRequest(request);
    const result = buildReplayResponse(payload, await runAgentReplay(payload));
    sendJson(response, 200, result);
  } catch (error) {
    if (error && error.code === "replay_not_implemented") {
      sendJson(response, 501, {
        status: "errored",
        error: "replay_not_implemented",
        detail: error.message
      });
      return;
    }
    sendJson(response, 400, {
      status: "errored",
      error: "invalid_replay_request",
      detail: error && error.message ? error.message : String(error)
    });
  }
}

async function main() {
  const args = buildArgs(process.argv.slice(2));
  const server = http.createServer((request, response) => {
    handleRequest(request, response).catch((error) => {
      sendJson(response, 500, {
        status: "errored",
        error: "internal_error",
        detail: error && error.message ? error.message : String(error)
      });
    });
  });
  server.listen(args.port, args.host);
}

main().catch((error) => {
  console.error("kyoko_replay_server_failed:" + (error && error.message ? error.message : String(error)));
  process.exit(1);
});
'''
)
