# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What Kyoko is

Kyoko is a local, self-hosted optimization loop for agentic workflows: a single-player
tool that takes agent telemetry → issues/insights → eval specs → replay → context/harness
updates, all on one machine. Its Python core is stdlib-first *today* (only runtime
dependency is `jsonschema`), SQLite-backed, and deliberately conservative about autonomy —
nothing mutates a skillbook or repo without passing an eval/replay gate and the profile's
autonomy policy.

> **Read `docs/SCOPE.md` first — it is the constitution and overrides every other doc.**
> Kyoko is a **single-player, single-machine, local** tool for **one** agentic workflow.
> No multi-tenancy, no teams, no auth, no cloud. Most "enterprise" machinery you might
> reach for (auth, policy tables, audit ledgers, approval state machines) is out of scope;
> `SCOPE.md` has the anti-slop smell test. Three standing decisions baked there: **(1)
> single workflow profile, never surfaced as a picker; (2) loopback-only dashboard with no
> auth; (3) context autonomy gates on an L1 eval with no replay, harness autonomy needs L2
> + replay.**
>
> **Dependency philosophy has also shifted — read "Frontend & dependency direction" below.**
> "stdlib-only, no build step" is no longer a hard, project-wide rule. The owner has
> decided we *should* use third-party packages and build tooling where they save real time,
> especially for the dashboard. Don't refuse to add a dependency on principle.

The README is unusually complete and is the canonical reference for every CLI command and
its flags. When a task touches a command, read the relevant README section first.

## Frontend & dependency direction

**Decided 2026-06-03 by the project owner. This supersedes the older "stdlib-only, no
build step" guidance wherever they conflict.**

- **Dependencies are allowed.** The strict "core is stdlib-only except `jsonschema`, don't
  add runtime dependencies, no build step" stance is relaxed. Prefer well-maintained
  packages and build tooling when they save meaningful time. Still be reasonable: keep the
  embeddable `sdk.py` recorder/client dependency-free, don't pull in a dependency to avoid
  ten lines of stdlib, and keep the safety boundary intact. But "it would add a dependency"
  is **not** by itself a reason to say no.
- **The dashboard is React (Phase F — built).** The React/Vite/TypeScript SPA lives in
  `frontend/` and is the shipping dashboard. It was built reusing Raindrop's Workshop app
  (reference at `/Users/filip/Desktop/external_code/workshop/`) for its look and component
  ideas (dark theme, span tree, flame timeline, live streaming, annotations), wired to
  Kyoko's existing `/api/*` endpoints + the SSE channel (`GET /api/events/stream`).
  - **Build:** `cd frontend && npm install && npm run build`. Vite emits the bundle into
    `kyoko/assets/web/` (`outDir` in `frontend/vite.config.ts`); `kyoko serve` serves it as
    static files (`web.py` `SPA_BUNDLE_DIR`, `_serve_spa_index`/`_serve_static_file`, with a
    client-side-routing fallback to `index.html` for non-`/api`/`/v1` GETs). When the bundle
    is absent (fresh checkout, no `npm run build`), `serve` falls back to the inline
    `_dashboard_html()`.
  - **Dev:** `cd frontend && npm run dev` runs Vite on its own port and proxies `/api` +
    `/v1` to a running `kyoko serve` (default `:8765`; override with `KYOKO_SERVE_URL`).
  - **Transport:** push is **SSE, not WebSocket** (the threaded server's natural fit);
    `src/hooks/useLiveBus.ts` wraps a single `EventSource` over the `run_upsert` /
    `live_event` / `mcp_log` / `annotation` events. Client→server actions are plain POSTs.
  - **Pages:** Overview, Runs (list + span-tree/flame/live-tail/payload/annotations detail),
    Agent ↔ Kyoko (live MCP log), Proposals, Autonomy, Evals & Replay, Settings.
  - **SCOPE:** loopback-only, no auth/login, **no profile selector** (single invisible
    profile). The inline-dashboard tests now assert against `_dashboard_html()` directly
    (the fallback), since `GET /` serves the compiled SPA.
- **What stays true regardless:** the safety boundary (every behavior-changing path is
  gated), loopback-only serving, and `--json` as the machine-readable contract. A nicer
  frontend does not get to bypass any of those.

## Commands

```bash
# Install for local development/smoke testing
python3 -m pip install .

# Run the full test suite (stdlib unittest, no pytest)
python3 -m unittest discover -s tests

# Run a single test module / class / method
python3 -m unittest tests.test_cli
python3 -m unittest tests.test_cli.SomeTestCase
python3 -m unittest tests.test_cli.SomeTestCase.test_something

# Validate gate artifacts (specs, schemas, fixtures) — fast correctness gate
python3 scripts/validate_gate_artifacts.py
python3 -m kyoko validate-gates

# First-run readiness check (does not mutate the default user DB)
python3 -m kyoko doctor --json
python3 -m kyoko doctor --safe-smokes --json   # runs every no-live-model smoke

# End-to-end bundled demo loop against a throwaway DB
python3 -m kyoko demo --db /tmp/kyoko-demo.db --json
```

There is no separate lint/format config checked in; match surrounding style.

## Architecture

Everything is the `kyoko` package, invoked as `python3 -m kyoko <command>` (console
script `kyoko`, entry point `kyoko.cli:main`).

- **`cli.py`** (~7k lines) is the single argparse front door. `main()` builds all
  subparsers, then dispatches with a long `if args.command == "...":` chain, each branch
  delegating to a feature module. To add a command: add an `add_parser(...)` block and a
  matching dispatch branch, then wire it to the feature module's function.
- **`storage.py`** owns the SQLite schema (`SCHEMA_VERSION`, currently 24), `connect()`,
  and `initialize_database()`. Kyoko **refuses to open a DB whose `user_version` is newer
  than the installed `SCHEMA_VERSION`**. Schema changes mean bumping `SCHEMA_VERSION` and
  adding a migration (additive `CREATE TABLE IF NOT EXISTS` + `_ensure_column`, or a
  `DROP TABLE IF EXISTS` in `initialize_database` for SCOPE removals). The canonical data
  model (profiles → sources → runs → spans → handoffs → timeline_events; plus
  learning_proposals, issues, skills, eval_specs, replay_runs, patch_transactions,
  payload_blobs, autonomy_policies, live_events, mcp_log, annotations, and a per-span FTS5
  search index) is specified in `docs/specs/0001-canonical-model.md`. **SCOPE
  simplifications applied:** the per-profile `redaction_policies`/`retention_policies`
  tables and the `redaction_audit_events` ledger were removed (redaction is a single global
  "redact on export" default; retention is a manual `prune-retention --older-than-days`);
  the human-lock event ledger was dropped (a lock is a boolean + reason with enforcement);
  the profile is a single invisible row (no picker / `--all-profiles`); proposal `state`
  collapsed to `pending → applied → rolled_back` (+ internal `failed`).
- **`web.py`** (~7k lines) is the self-hosted dashboard + JSON API (`kyoko serve`). API
  endpoints generally mirror CLI commands one-to-one (`POST /api/improve`, `/api/demo`,
  etc.). Keep CLI and API behavior in sync when changing a feature.
- **Feature modules** map closely to command groups: `proposals.py`, `apply.py`,
  `evals.py`, `replay_adapters.py`/`replay_servers.py`, `autonomy_runner.py`, `harness.py`,
  `improve.py`, `analyze.py`, `operator_adapters.py`, `profiles.py`/`profile_next.py`,
  `retention.py` (manual age-cutoff prune), `redaction.py` (a single global redact-on-export
  default — `DEFAULT_REDACTION_POLICY` + `redact_evidence_bundle`), `issues.py` (first-class
  Issue evidence entity — create/list/get/status, outside the gate), `event_envelope.py`
  (the documented normalized ingest envelope + `validate_envelope`), `ace_bridge.py` (ACE Skillbook compat/import),
  `hermes_import.py`/`openclaw_import.py` (offline source importers), `otlp.py` (OTLP/GenAI
  JSON normalizer), `mcp.py` (stdio MCP server + native install plans), `sdk.py`
  (dependency-free `KyokoClient`/`KyokoRecorder`), `live.py` (live-event ingest +
  `LiveBus` SSE fan-out for push observability), `mcp_log.py` (records the agent↔Kyoko
  MCP JSON-RPC traffic, redacted), `inspection.py` (read-only run outline / search /
  span-context / redacted span-payload + current-run), `annotations.py` (durable
  issue/good/note markers on runs/spans — evidence only, outside the gate),
  `otlp_protobuf.py` (dependency-free stdlib OTLP `ExportTraceServiceRequest`
  decoder/encoder), `span_normalize.py` (SDK span → canonical llm/tool/other view),
  `subagents.py` (infers sub-agent groupings from span-tree shape).
- **`mcp.py`** exposes a read/propose/eval-request MCP surface. It deliberately does **not**
  expose direct apply/harness-write tools, and cleanup tools are dry-run only. Preserve
  this boundary.

### The safety boundary (most important invariant)

Every path that could change agent behavior is gated. Operator/ACE/import output becomes a
validated `LearningProposal`; evals and replay produce evidence; the profile autonomy policy
(`context_mode`, `harness_mode`, `repo_patch`, independent of each other, repo patches **off
by default**) decides whether anything is written. `improve`, `profile-next --run`, the MCP
`kyoko_run_improve` tool, and the dashboard all funnel through this same gate — do not add a
shortcut that applies changes without it. Human locks (skills, context rules, eval specs,
harness target paths) block later writes to the same id/path. Evidence is **redacted by
default** before being written to disk, embedded in prompts, or served via MCP/API.

### Contract-driven testing (do not break goldens silently)

Many CLI commands have a frozen JSON contract: a golden file under
`docs/fixtures/cli-json/*.contract.golden.json` (or `*.golden.json`) checked by
`tests/test_cli_json_contracts.py`. If you change a command's `--json` output shape, you
must update both the golden and the corresponding spec in `docs/specs/0005-cli-json-contracts.md`.
Gate artifacts (specs in `docs/specs/`, schemas in `docs/schemas/`, fixtures in
`docs/fixtures/`) are validated by `scripts/validate_gate_artifacts.py` and
`kyoko validate-gates`; keep them consistent when changing the model or proposal schema
(`docs/schemas/learning-proposal.schema.json`).

### Integration smokes vs. live calls

Tests and `doctor --safe-smokes` never invoke live model CLIs or providers. Smokes that
touch real frameworks/providers (`integration-smoke framework-*`, `--opentelemetry-smoke`,
`--ace-native-smoke`, live operator/judge smokes) are explicitly separate, opt-in, and
marked mutating because they shell out to installed packages or model backends. Keep new
provider-dependent work behind the same explicit, no-live-by-default convention. Replay
server URLs are loopback-only unless `--allow-remote-server` is passed.

## Conventions

- Python ≥3.12 (baseline; CI/release matrix targets 3.12 and 3.13). The Python core is
  currently stdlib-only except `jsonschema`, and that's a fine default to preserve — but
  adding dependencies is now allowed where they earn their keep (see **Frontend & dependency
  direction**). Optional integrations go under `[options.extras_require]` — e.g.
  `pip install .[ace]` pulls `ace-framework>=0.12.0` (which itself requires Python ≥3.12).
  ACE is never imported at module top level; every `import ace` is lazy/optional so core
  Kyoko runs without it. The same lazy/optional pattern is the preferred way to add a new
  backend dependency to the Python core. The dashboard/frontend is exempt from the
  stdlib-only expectation and is expected to grow a Node/Vite/React build.
- Bundled assets ship under `kyoko/assets/**` (schemas, demo source-events, proposal
  fixtures) and are exported by `kyoko bundled-assets`. The authoring copies live under
  `docs/`.
- The default user database is `~/.kyoko/kyoko.db` with a sibling `~/.kyoko/blobs`
  content-addressed payload blob store; large payloads belong in blobs, not hot SQLite rows.
- `--json` is the machine-readable contract for nearly every command; human text output is
  secondary. Operator agents are expected to drive Kyoko via `--json` and `suggested_commands`.
