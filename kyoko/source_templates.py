from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from string import Template


SUPPORTED_SOURCE_FRAMEWORKS = {
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

TYPESCRIPT_SOURCE_FRAMEWORKS = {
    "generic-typescript",
    "ai-sdk-typescript",
}


class SourceTemplateError(Exception):
    """Raised when a source adapter template cannot be written."""


@dataclass(frozen=True)
class SourceTemplateReport:
    output_path: Path
    framework: str
    profile_name: str
    wrote: bool


def write_source_adapter_template(
    *,
    output_path: Path,
    framework: str = "generic-python",
    profile_name: str = "kyoko-agent",
    force: bool = False,
) -> SourceTemplateReport:
    if framework not in SUPPORTED_SOURCE_FRAMEWORKS:
        raise SourceTemplateError(f"unsupported_source_template_framework:{framework}")
    if output_path.exists() and not force:
        raise SourceTemplateError(f"source_template_exists:{output_path}")
    if not profile_name:
        raise SourceTemplateError("profile_name_required")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        _template_source(framework=framework, profile_name=profile_name),
        encoding="utf-8",
    )
    current_mode = output_path.stat().st_mode
    output_path.chmod(current_mode | 0o111)
    return SourceTemplateReport(
        output_path=output_path,
        framework=framework,
        profile_name=profile_name,
        wrote=True,
    )


def recommended_source_adapter_filename(framework: str) -> str:
    if framework in TYPESCRIPT_SOURCE_FRAMEWORKS:
        return "kyoko_source_adapter.mjs"
    return "kyoko_source_adapter.py"


def _template_source(*, framework: str, profile_name: str) -> str:
    template = NODE_SOURCE_TEMPLATE if framework in TYPESCRIPT_SOURCE_FRAMEWORKS else PYTHON_SOURCE_TEMPLATE
    return template.safe_substitute(
        framework=framework,
        framework_label=SUPPORTED_SOURCE_FRAMEWORKS[framework],
        profile_name=profile_name,
    )


PYTHON_SOURCE_TEMPLATE = Template(
    '''#!/usr/bin/env python3
"""
Kyoko source adapter template.

Framework: $framework_label

Run:
    KYOKO_SOURCE_HOOK=/absolute/path/to/hooks.py:collect \\
      python3 kyoko_source_adapter.py --output source-events.json

Ingest:
    python3 -m kyoko ingest --db /tmp/kyoko.db source-events.json --json

Or post directly to a running local Kyoko app:
    python3 -m kyoko serve --db /tmp/kyoko.db
    KYOKO_SOURCE_HOOK=/absolute/path/to/hooks.py:collect \\
      python3 kyoko_source_adapter.py --post-url http://127.0.0.1:8765/api/ingest

The hook should return Kyoko canonical source-event JSON or
{"source_events": <canonical JSON>}. Keep raw prompts, tool outputs, and
secrets out of refs unless you have reviewed your privacy boundary.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROFILE_NAME = "$profile_name"
FRAMEWORK = "$framework"
FRAMEWORK_LABEL = "$framework_label"
FRAMEWORK_HINTS = {
    "generic-python": "Wrap the agent invocation and return canonical Kyoko source events.",
    "langgraph-python": "Collect graph invocation spans, node names, tool spans, and final status.",
    "pydantic-ai-python": "Collect Pydantic AI agent run/tool events or a Logfire/OTel export converted to Kyoko source events.",
    "openai-agents-python": "Collect OpenAI Agents SDK tracing output and map agents, tools, and handoffs to Kyoko source events.",
    "crewai-python": "Collect CrewAI task/agent/tool execution events and map them to Kyoko runs and spans.",
    "hermes-python": "Collect Hermes profile/task/queue/handoff data and map it into one Kyoko workflow profile.",
    "openclaw-python": "Collect OpenClaw agent/session/workspace events and map them into one Kyoko workflow profile.",
}


def collect_source_events(args: argparse.Namespace) -> dict[str, Any]:
    hook = load_source_hook()
    if hook is None:
        hint = FRAMEWORK_HINTS.get(FRAMEWORK, FRAMEWORK_HINTS["generic-python"])
        raise NotImplementedError(
            "set KYOKO_SOURCE_HOOK=module_or_path:function; " + hint
        )

    result = hook(
        {
            "framework": FRAMEWORK,
            "profile_id": args.profile_id,
            "profile_name": args.profile_name,
            "root_path": args.root_path,
            "source_id": args.source_id,
            "agent_id": args.agent_id,
            "agent_name": args.agent_name,
        }
    )
    return normalize_hook_result(result, args)


def normalize_hook_result(result: Any, args: argparse.Namespace) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise ValueError("KYOKO_SOURCE_HOOK must return a JSON object")
    if isinstance(result.get("source_events"), dict):
        payload = result["source_events"]
    else:
        payload = result
    if not isinstance(payload, dict):
        raise ValueError("source_events must be a JSON object")
    if "profile" in payload and "runs" in payload and "spans" in payload:
        return payload
    if isinstance(payload.get("runs"), list) or isinstance(payload.get("spans"), list):
        return canonical_from_partial(payload, args)
    raise ValueError("hook result must be canonical source events or contain runs/spans")


def canonical_from_partial(partial: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    now = utc_now()
    profile_id = args.profile_id
    source_id = args.source_id
    agent_id = args.agent_id
    node_id = "node_" + slug(args.agent_name)
    runs = partial.get("runs") if isinstance(partial.get("runs"), list) else []
    spans = partial.get("spans") if isinstance(partial.get("spans"), list) else []
    return {
        "fixture_version": "kyoko.source_events.v1",
        "profile": {
            "id": profile_id,
            "name": args.profile_name,
            "root_path": args.root_path,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
        "sources": [
            {
                "id": source_id,
                "profile_id": profile_id,
                "kind": FRAMEWORK,
                "display_name": FRAMEWORK_LABEL,
                "status": "active",
                "adapter_version": "kyoko.source_adapter_template.v0",
                "config_json": {"template": True},
                "capabilities_json": ["trace"],
                "last_seen_at": now,
            }
        ],
        "agent_identities": [
            {
                "id": agent_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": args.agent_name,
                "name": args.agent_name,
                "kind": "agent",
                "role": None,
                "model": None,
                "workspace_path": args.root_path,
                "metadata_json": {"framework": FRAMEWORK},
            }
        ],
        "workflow_nodes": [
            {
                "id": node_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": args.agent_name,
                "agent_identity_id": agent_id,
                "kind": "agent",
                "name": args.agent_name,
                "metadata_json": {"framework": FRAMEWORK},
            }
        ],
        "queues": partial.get("queues", []),
        "tasks": partial.get("tasks", []),
        "task_attempts": partial.get("task_attempts", []),
        "runs": runs,
        "spans": spans,
        "handoffs": partial.get("handoffs", []),
        "timeline_events": partial.get("timeline_events", []),
    }


def load_source_hook() -> Any:
    hook_spec = os.environ.get("KYOKO_SOURCE_HOOK", "").strip()
    if not hook_spec:
        return None
    module_ref, separator, function_name = hook_spec.rpartition(":")
    if not separator or not module_ref or not function_name:
        raise ValueError("KYOKO_SOURCE_HOOK must be module_or_path:function")
    if module_ref.endswith(".py") or "/" in module_ref or "\\\\" in module_ref:
        module_path = Path(module_ref).expanduser().resolve()
        spec = importlib.util.spec_from_file_location("kyoko_source_hook", module_path)
        if spec is None or spec.loader is None:
            raise ValueError(f"cannot load source hook module: {module_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    else:
        module = importlib.import_module(module_ref)
    hook = getattr(module, function_name, None)
    if not callable(hook):
        raise ValueError(f"source hook is not callable: {hook_spec}")
    return hook


def write_or_post(payload: dict[str, Any], args: argparse.Namespace) -> None:
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\\n")
        print(json.dumps({"output": str(output_path), "profile_id": payload["profile"]["id"]}, sort_keys=True))
        return
    if args.post_url:
        request = urllib.request.Request(
            args.post_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=args.timeout) as response:
                print(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"post failed: {exc}") from exc
        return
    print(json.dumps(payload, indent=2, sort_keys=True))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")
    return cleaned or "agent"


def short_id() -> str:
    return uuid.uuid4().hex[:8]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kyoko source adapter template")
    parser.add_argument("--output", help="Write canonical source events JSON to this file.")
    parser.add_argument("--post-url", help="POST canonical source events to a Kyoko /api/ingest endpoint.")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP post timeout in seconds.")
    parser.add_argument("--profile-id", default="profile_" + slug(PROFILE_NAME))
    parser.add_argument("--profile-name", default=PROFILE_NAME)
    parser.add_argument("--root-path", default=".")
    parser.add_argument("--source-id", default="source_" + slug(FRAMEWORK) + "_" + short_id())
    parser.add_argument("--agent-id", default="agent_" + slug(PROFILE_NAME) + "_" + short_id())
    parser.add_argument("--agent-name", default=PROFILE_NAME)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        payload = collect_source_events(args)
        write_or_post(payload, args)
    except Exception as exc:
        print(f"kyoko_source_adapter_failed:{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
)


NODE_SOURCE_TEMPLATE = Template(
    '''#!/usr/bin/env node
/*
Kyoko source adapter template.

Framework: $framework_label

Run:
    KYOKO_SOURCE_HOOK=/absolute/path/to/hooks.mjs:collect \\
      node kyoko_source_adapter.mjs --output source-events.json

Ingest:
    python3 -m kyoko ingest --db /tmp/kyoko.db source-events.json --json

Or post directly to a running local Kyoko app:
    python3 -m kyoko serve --db /tmp/kyoko.db
    KYOKO_SOURCE_HOOK=/absolute/path/to/hooks.mjs:collect \\
      node kyoko_source_adapter.mjs --post-url http://127.0.0.1:8765/api/ingest

The hook should return Kyoko canonical source-event JSON or
{"source_events": <canonical JSON>}. For AI SDK projects, the simplest path is
to convert the telemetry/trace data you already collect into Kyoko runs and
spans here, then let Kyoko own evals, replay, and autonomy.
*/

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const PROFILE_NAME = "$profile_name";
const FRAMEWORK = "$framework";
const FRAMEWORK_LABEL = "$framework_label";
const FRAMEWORK_HINTS = {
  "generic-typescript": "Wrap the Node agent invocation and return canonical Kyoko source events.",
  "ai-sdk-typescript": "Collect AI SDK request/tool telemetry or OTLP JSON converted to Kyoko source events."
};

async function collectSourceEvents(args) {
  const hook = await loadSourceHook();
  if (!hook) {
    const hint = FRAMEWORK_HINTS[FRAMEWORK] || FRAMEWORK_HINTS["generic-typescript"];
    throw new Error("set KYOKO_SOURCE_HOOK=module_or_path:function; " + hint);
  }
  const result = await hook({
    framework: FRAMEWORK,
    profile_id: args.profileId,
    profile_name: args.profileName,
    root_path: args.rootPath,
    source_id: args.sourceId,
    agent_id: args.agentId,
    agent_name: args.agentName
  });
  return normalizeHookResult(result, args);
}

function normalizeHookResult(result, args) {
  if (!result || typeof result !== "object" || Array.isArray(result)) {
    throw new Error("KYOKO_SOURCE_HOOK must return a JSON object");
  }
  const payload = result.source_events && typeof result.source_events === "object"
    ? result.source_events
    : result;
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("source_events must be a JSON object");
  }
  if (payload.profile && Array.isArray(payload.runs) && Array.isArray(payload.spans)) {
    return payload;
  }
  if (Array.isArray(payload.runs) || Array.isArray(payload.spans)) {
    return canonicalFromPartial(payload, args);
  }
  throw new Error("hook result must be canonical source events or contain runs/spans");
}

function canonicalFromPartial(partial, args) {
  const now = utcNow();
  const nodeId = "node_" + slug(args.agentName);
  return {
    fixture_version: "kyoko.source_events.v1",
    profile: {
      id: args.profileId,
      name: args.profileName,
      root_path: args.rootPath,
      status: "active",
      created_at: now,
      updated_at: now
    },
    sources: [
      {
        id: args.sourceId,
        profile_id: args.profileId,
        kind: FRAMEWORK,
        display_name: FRAMEWORK_LABEL,
        status: "active",
        adapter_version: "kyoko.source_adapter_template.node.v0",
        config_json: { template: true },
        capabilities_json: { trace: true },
        last_seen_at: now
      }
    ],
    agent_identities: [
      {
        id: args.agentId,
        profile_id: args.profileId,
        source_id: args.sourceId,
        external_id: args.agentName,
        name: args.agentName,
        kind: "agent",
        role: null,
        model: null,
        workspace_path: args.rootPath,
        metadata_json: { framework: FRAMEWORK }
      }
    ],
    workflow_nodes: [
      {
        id: nodeId,
        profile_id: args.profileId,
        source_id: args.sourceId,
        external_id: args.agentName,
        agent_identity_id: args.agentId,
        kind: "agent",
        name: args.agentName,
        metadata_json: { framework: FRAMEWORK }
      }
    ],
    queues: Array.isArray(partial.queues) ? partial.queues : [],
    tasks: Array.isArray(partial.tasks) ? partial.tasks : [],
    task_attempts: Array.isArray(partial.task_attempts) ? partial.task_attempts : [],
    runs: Array.isArray(partial.runs) ? partial.runs : [],
    spans: Array.isArray(partial.spans) ? partial.spans : [],
    handoffs: Array.isArray(partial.handoffs) ? partial.handoffs : [],
    timeline_events: Array.isArray(partial.timeline_events) ? partial.timeline_events : []
  };
}

async function loadSourceHook() {
  const hookSpec = (process.env.KYOKO_SOURCE_HOOK || "").trim();
  if (!hookSpec) {
    return null;
  }
  const separatorIndex = hookSpec.lastIndexOf(":");
  if (separatorIndex <= 0 || separatorIndex === hookSpec.length - 1) {
    throw new Error("KYOKO_SOURCE_HOOK must be module_or_path:function");
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
    throw new Error("source hook is not callable: " + hookSpec);
  }
  return hook;
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

async function writeOrPost(payload, args) {
  if (args.output) {
    const outputPath = path.resolve(args.output);
    fs.mkdirSync(path.dirname(outputPath), { recursive: true });
    fs.writeFileSync(outputPath, JSON.stringify(payload, null, 2) + "\\n", "utf8");
    console.log(JSON.stringify({ output: outputPath, profile_id: payload.profile.id }));
    return;
  }
  if (args.postUrl) {
    if (typeof fetch !== "function") {
      throw new Error("posting requires Node 18+ global fetch");
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), args.timeout * 1000);
    try {
      const response = await fetch(args.postUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal
      });
      const text = await response.text();
      if (!response.ok) {
        throw new Error("post failed: " + response.status + " " + text);
      }
      console.log(text);
    } finally {
      clearTimeout(timeout);
    }
    return;
  }
  console.log(JSON.stringify(payload, null, 2));
}

function buildArgs(argv) {
  const args = {
    output: null,
    postUrl: null,
    timeout: 20,
    profileId: "profile_" + slug(PROFILE_NAME),
    profileName: PROFILE_NAME,
    rootPath: ".",
    sourceId: "source_" + slug(FRAMEWORK) + "_" + shortId(),
    agentId: "agent_" + slug(PROFILE_NAME) + "_" + shortId(),
    agentName: PROFILE_NAME
  };
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    const value = argv[index + 1];
    if (flag === "--output") {
      args.output = requireValue(flag, value);
      index += 1;
    } else if (flag === "--post-url") {
      args.postUrl = requireValue(flag, value);
      index += 1;
    } else if (flag === "--timeout") {
      args.timeout = Number.parseInt(requireValue(flag, value), 10);
      index += 1;
    } else if (flag === "--profile-id") {
      args.profileId = requireValue(flag, value);
      index += 1;
    } else if (flag === "--profile-name") {
      args.profileName = requireValue(flag, value);
      index += 1;
    } else if (flag === "--root-path") {
      args.rootPath = requireValue(flag, value);
      index += 1;
    } else if (flag === "--source-id") {
      args.sourceId = requireValue(flag, value);
      index += 1;
    } else if (flag === "--agent-id") {
      args.agentId = requireValue(flag, value);
      index += 1;
    } else if (flag === "--agent-name") {
      args.agentName = requireValue(flag, value);
      index += 1;
    } else if (flag === "--help" || flag === "-h") {
      printHelp();
      process.exit(0);
    } else {
      throw new Error("unknown argument: " + flag);
    }
  }
  if (!Number.isFinite(args.timeout) || args.timeout <= 0) {
    throw new Error("--timeout must be a positive integer");
  }
  return args;
}

function requireValue(flag, value) {
  if (!value || value.startsWith("--")) {
    throw new Error(flag + " requires a value");
  }
  return value;
}

function printHelp() {
  console.log("Usage: node kyoko_source_adapter.mjs [--output path | --post-url url] [options]");
  console.log("");
  console.log("Options:");
  console.log("  --profile-id ID");
  console.log("  --profile-name NAME");
  console.log("  --root-path PATH");
  console.log("  --source-id ID");
  console.log("  --agent-id ID");
  console.log("  --agent-name NAME");
  console.log("  --timeout SECONDS");
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

function utcNow() {
  return new Date().toISOString();
}

function slug(value) {
  const cleaned = String(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$$/g, "");
  return cleaned || "agent";
}

function shortId() {
  return crypto.randomBytes(4).toString("hex");
}

async function main() {
  try {
    const args = buildArgs(process.argv.slice(2));
    const payload = await collectSourceEvents(args);
    await writeOrPost(payload, args);
  } catch (error) {
    const message = error && error.message ? error.message : String(error);
    console.error("kyoko_source_adapter_failed:" + message);
    return 1;
  }
  return 0;
}

process.exitCode = await main();
'''
)
