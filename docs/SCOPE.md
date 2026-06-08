# Scope

Kyoko v0 is a local self-improvement loop for one developer working on
local AI agent workflows.

## In Scope

- Local CLI and Python package.
- Loopback dashboard and JSON API.
- SQLite database and local blob store.
- Python and TypeScript telemetry SDKs.
- Source adapters and importers for local agent traces.
- Replay adapters and generated replay-server scaffolds.
- Issue, proposal, check, replay, and gated apply workflows.
- Evidence-only eval and LLM-judge measurement of agent runs.
- Conservative context and harness autonomy.
- MCP server for local coding-agent workflows.
- Release artifacts as a Python wheel and source distribution.

## Out Of Scope

- Hosted observability.
- Team workspaces.
- Multi-tenant auth or RBAC.
- Cloud schedulers or remote workers.
- Billing or subscription management.
- Cross-user identity proof.
- Provider-backed automation by default.
- Unchecked autonomous repository writes.

## Product Boundary

Kyoko is not just a trace viewer. The trace is evidence for a repair
workflow. The product is complete only when an issue can move through proposal,
check, replay, and a reviewable or policy-approved apply decision.

Kyoko is also not a general agent orchestrator. It observes and improves
an existing workflow; it does not replace the user's agent framework.

## Safety Rules

- Behavior-changing writes must flow through proposals and gates.
- Replay must be bounded and side-effect mode must be explicit.
- Human locks block later writes to the same protected target.
- Harness patches require an explicit workspace root.
- External models, operator CLIs, and framework runtimes are opt-in.
- Local data stays local unless the user invokes an external command.

## Naming

The published distribution, primary CLI, Python import namespace, generated
helper filenames, and project data directory all use the `kyoko` name.
