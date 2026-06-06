# 0005 - Eval And Replay Boundary

Status: accepted for first implementation slice
Date: 2026-05-31

## Decision

Kyoko will treat evals and replay as canonical runtime state, not as ad hoc
operator notes.

The first implementation slice stores:

- `eval_specs`
- `eval_runs`
- `replay_runs`

Generated eval specs are created from validated `LearningProposal` changes.
Replay runs are recorded with explicit side-effect modes. Eval runs are
separate records linked to eval specs and optionally to replay runs.

The second implementation slice adds controlled replay result ingestion:

- a replay result fixture is normal source-event data plus a top-level
  `replay` object,
- `complete-replay` ingests the new run, spans, handoffs, and events,
- the replay run is updated with `output_ref = <new run id>`,
- the replay result stores a `target_map` from original failed evidence to
  replay evidence.

## Initial Runtime Contract

CLI:

```text
kyoko generate-evals <proposal_id> --json
kyoko replay <eval_spec_id> --json
kyoko complete-replay <replay_run_id> <fixture> --json
kyoko replay-command <eval_spec_id> --command "..." --output-dir ... --run-eval --json
kyoko replay-server-health <server_url> --json
kyoko replay-server-run <server_url> <eval_spec_id> --run-eval --json
kyoko replay-adapter-register <adapter_id> --command "..." --json
kyoko replay-adapter-register <adapter_id> --server-url http://127.0.0.1:61200 --json
kyoko replay-adapter-register <adapter_id> --command "..." --server-url http://127.0.0.1:61200 --json
kyoko replay-adapter-register <adapter_id> --server-url https://replay.example.test --allow-remote-server --json
kyoko replay-adapter-run <adapter_id> <eval_spec_id> --run-eval --json
kyoko run-eval <eval_spec_id> --json
kyoko evals --json
kyoko demo --json
```

API:

```text
GET  /api/evals
POST /api/evals/generate
POST /api/replay
POST /api/replay/complete
POST /api/evals/run
```

Evidence bundles now include eval specs, eval runs, and replay runs so operator
agents can see prior gates and avoid repeating stale recommendations.

Deterministic eval specs can include an `assertions` list. Supported v0
assertions:

- `target_status_not_failed`: baseline failure must map to a replay target that
  no longer has a failure status.
- `replay_target_field_equals`: the replay target row must have a matching
  decoded field, such as `attributes.retry_count == 1`.
- `replay_entity_field_equals`: a replay run entity such as a handoff must
  match selector fields and expose the expected decoded value, such as
  `metadata.source_status == "complete"`.
- `replay_run_status_equals`: the replay output run must have the expected
  status, usually `succeeded`.
- `replay_no_failed_spans`: the replay output run must have no failed spans.
- `replay_span_count_at_least`: the replay output run must contain at least
  the configured number of spans.
- `replay_handoff_count_at_least`: the replay output run must contain at least
  the configured number of handoffs.

Replay command contract:

```text
BEGIN_KYOKO_REPLAY_RESULT_JSON
{ ...kyoko.replay_result.v1 JSON... }
END_KYOKO_REPLAY_RESULT_JSON
```

Kyoko writes `replay-request.json`, sets `KYOKO_REPLAY_REQUEST_PATH`,
captures raw stdout/stderr, extracts exactly one replay result block, ingests
the replay result, and can run the eval immediately when `--run-eval` is set.
If the command fails, times out, or returns malformed output, Kyoko marks the
replay run `errored` with the failure reason.

Replay adapters persist that command boundary for normal use:

- adapter id and profile id,
- adapter kind: local command, already-running HTTP replay server, or managed
  HTTP replay-server command,
- command argv, HTTP server URL, or both for managed servers,
- default mode and side-effect mode,
- default artifact output directory,
- timeout,
- enabled flag.

Running a command adapter is equivalent to `replay-command`. Running an HTTP
adapter checks `GET /health`, posts a `kyoko.replay_server_request.v1` payload
to `POST /replay`, then completes the replay from either a full
`kyoko.replay_result.v1` response or a server response that points at an
already-ingested output run. HTTP replay server URLs are loopback-only by
default; direct server commands and registered adapters require explicit
`--allow-remote-server` opt-in before Kyoko will send replay/eval context to a
non-loopback endpoint. Running a managed HTTP adapter starts the server command,
polls health, captures stdout/stderr, executes the replay, and stops the server
process. Users and operator agents can refer to a stable adapter id instead of
repeating command or URL details.

The bundled first-run demo uses `python -m kyoko.fixture_replay` as its
package-local replay adapter. `scripts/kyoko_fixture_replay.py` remains a
source-checkout wrapper for direct fixture debugging. Both execute the same
contract as any other replay command, but keep side effects mocked so the whole
telemetry to proposal to replay/eval to context-apply path can run with one
command.

## Safety Boundary

The first replay implementation is deliberately conservative.

`kyoko replay` in v0 records a bounded dry-run replay request and verifies that
the source evidence can be resolved. It does not re-invoke the target agent,
call tools, write files, or use live network access.

Recorded replay result:

```json
{
  "executed_agent": false,
  "actual_side_effect_mode": "none"
}
```

`live_network` and `unknown` side-effect modes are rejected. Live network
replay must wait for side-effect review, tool/network/filesystem policy
enforcement, secrets policy, and eval gate wiring even though the bounded HTTP
replay-server path exists.

Controlled replay fixtures may represent a completed replay under a bounded
side-effect mode such as `network_mocked`. This lets Kyoko test the before/after
verification path without allowing arbitrary live tool execution.

External replay commands are held to the same boundary: they must declare the
actual side-effect mode in the replay-result JSON, and Kyoko rejects unsafe
modes before canonical completion.

External replay handoff is also a disclosure boundary. Replay-command request
files and HTTP replay-server POST bodies are redacted with the profile evidence
policy before they leave Kyoko. The default policy hides payload refs and
secret-shaped values while preserving replay ids, eval ids, entity ids, status
fields, and trace shape. Kyoko records a redaction audit event when the replay
request is changed by redaction.

## Eval Trust

Generated eval specs start as `L0_generated`.

The deterministic runner can promote a generated eval to `L1_repeated` only
after two stable deterministic results. This promotion means the eval is
repeatable and tied to evidence. It does not mean the proposed fix passed.

For the current Hermes/news-research fixture, the generated deterministic eval
fails against the original failed span. After the controlled replay success
fixture is completed, the same eval compares:

```text
span_fetch_timeout_001 -> failed
span_fetch_retry_success_001 -> succeeded
```

That result is promoted to `L2_regression` because Kyoko has fail-before and
pass-after evidence with bounded side effects.

Kyoko never auto-promotes to `L3_human_approved`. That level is set only by an
explicit human approval action through `kyoko eval-spec-approve`,
`POST /api/eval-specs/approve`, or the dashboard `Approve L3` control. The
approval writes an `eval_spec_human_approved` timeline event and is rejected
while the eval spec is human-locked.

## Consequences

Positive:

- eval/replay state exists in the canonical database and UI,
- operator agents can reason over previous gate attempts,
- unsafe replay modes are blocked early and completed replay results must stay
  within the requested side-effect boundary,
- HTTP replay servers that advertise `side_effect_modes` are checked for the
  requested mode before Kyoko posts replay context,
- replay-command and HTTP replay-server requests share the same default
  evidence-redaction boundary as operator handoffs,
- the product loop moves from advice toward measurable verification.

Costs:

- this is not yet live replay,
- current evals can prove baseline failure and controlled fixture before/after
  success, but not arbitrary real-world re-execution,
- autonomous context and harness gates must still wait for real replay and
  pass-after-fix evidence.

## Next Required Work

1. Live/source-native replay evidence for Hermes and OpenClaw.
   Dependency-free LangGraph, Pydantic AI, OpenAI Agents, CrewAI, Hermes,
   OpenClaw, and AI SDK examples now exercise the generic
   `KYOKO_REPLAY_HOOK` contract through generated replay servers and a linked
   Kyoko replay result.
2. Deeper framework-specific assertion libraries and provider-backed judge
   evals. Generic replay-shape presets now cover replay success, no failed
   spans, minimum span count, and minimum handoff count.
3. Richer UI for gate-decision history. Proposal detail now exposes persisted
   autonomy gate history in CLI, API, dashboard, and MCP. Eval detail exposes
   assertion-level evidence; replay detail exposes Kyoko-owned artifact
   previews for replay-command output and managed replay-server logs.
