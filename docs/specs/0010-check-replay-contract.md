# 0010 - Checks And Replay Contract

Status: implemented for deterministic v0 gates, regression replay gates, recorded judge checks, and smoke-run checks
Date: 2026-06-01

## Purpose

Kyoko's learning loop is only credible if a proposed change can be checked
against evidence. Checks and replay are therefore canonical Kyoko state, not
operator prose.

The v0 contract supports storing multiple check types. Deterministic assertion
and regression-replay checks are executable and gateable in the local runtime
when backed by the required replay evidence. Judge and smoke-run checks are
executable as informational checks over recorded verdicts or already-recorded
runs, but they do not gate autonomous writes.

## Check Types

The `LearningProposal` schema allows these check spec types:

| Check type | V0 storage | V0 execution | Gates autonomy |
|---|---:|---:|---:|
| `deterministic_assertion` | yes | yes | yes, when trust and replay gates pass |
| `judge` | yes | yes, recorded verdict only; explicit command capture can populate the recorded verdict | no |
| `regression_replay` | yes | yes, completed bounded replay only | yes, when trust and replay gates pass |
| `smoke_run` | yes | yes, stored-run/replay-output checks only | no |

Judge check specs execute only as recorded verdict checks in v0. Kyoko does not
invoke an LLM judge or external model provider from `run-check`. A judge
definition must include `verdict`, `judgment`, `result`, or boolean `passed`
directly or inside `judgment`/`recorded_judgment`. Missing or ambiguous verdicts
return `errored` with `judge_verdict_required`. Recorded judge results include
the rubric, judge label, score, reasoning, evidence refs, assertion-like verdict
details, and `gateable = false`. `judge-command` is the explicit live/provider
handoff: it writes a profile-redacted `kyoko.judge_request.v1`, invokes a user
command, requires exactly one delimited `kyoko.judge_result.v1` block, persists
that result as `recorded_judgment`, then runs the same non-gateable judge check.
The same explicit handoff is exposed through CLI, `POST /api/judge-command`,
dashboard judge controls, and `kyoko_run_judge_command` MCP.

Regression-replay checks require an explicit completed replay run. Running one
without replay evidence returns `errored` with `replay_required`. Running one
with completed bounded replay evidence delegates to the deterministic assertion
engine, requires a `target_status_not_failed` before/after assertion, and only
passes as gateable proof when the cited baseline target failed, the replay
target passed, the replay run passed, and the declared side-effect mode is
safe.

## Deterministic Assertions

Supported v0 deterministic assertions:

- `target_status_not_failed`
- `replay_target_field_equals`
- `replay_entity_field_equals`
- `replay_run_status_equals`
- `replay_no_failed_spans`
- `replay_span_count_at_least`
- `replay_handoff_count_at_least`

Generated fallback checks for operator context and harness proposals start with
`target_status_not_failed` against the cited failed evidence.

## Assertion Presets

Operator proposals may provide `assertion_preset` or `assertion_presets` inside
an check `definition`. Kyoko expands supported presets into concrete assertion
objects before execution, so check detail surfaces still show exact pass/fail
checks.

Supported v0 presets:

- `replay_success_shape`: expands to `replay_run_status_equals`,
  `replay_no_failed_spans`, and `replay_span_count_at_least`. It accepts
  optional `expected_run_status`/`replay_run_status` and
  `min_spans`/`minimum_spans` overrides.
- `replay_handoff_present`: expands to `replay_handoff_count_at_least`. It
  accepts optional `min_handoffs`/`minimum_handoffs` overrides.

Unsupported presets fail as an assertion with
`unsupported_assertion_preset:<name>` and include the supported preset names in
the check result and check detail.

The full check capability contract is discoverable through `kyoko
check-capabilities --json`, `GET /api/check-capabilities`, and the
`kyoko_get_check_capabilities` MCP tool. The dashboard Checks panel renders the
same capability summary. Operator evidence bundles and generated operator
prompts include the same capability summary so proposal authors can choose
supported check types, assertions, and presets from the evidence handoff itself.
Proposal detail payloads include compact `check_guidance` with gateable check
types, informational check types, safe replay side-effect modes, assertion
presets, and recorded-judge-only status.
Supported presets are also available through the narrower `kyoko
check-assertion-presets --json`, `GET
/api/check-assertion-presets`, and `kyoko_list_check_assertion_presets` MCP tool.

## Recorded Judge Checks

Supported v0 `judge` execution is deliberately non-invoking. It records and
normalizes a verdict already supplied by an operator, human review step, or
fixture. Accepted pass verdicts are `pass`, `passed`, `accept`, `accepted`, and
`meets_rubric`; accepted fail verdicts are `fail`, `failed`, `reject`,
`rejected`, and `does_not_meet_rubric`.

Recorded judge checks do not auto-promote trust level, and autonomy rejects them
with `unsupported_gate_check_type:judge` even if a human later approves the check
spec to `L3_human_approved`. Provider-backed or live LLM judge execution must
enter through `judge-command`; the resulting check remains informational unless a
separate deterministic or replay gate proves the change.
Judge output is useful review evidence for subjective quality, rubric scoring,
and cases where deterministic assertions cannot yet express the concern. In v0,
it must not be used as the sole proof for context or harness autonomy.

## Smoke Runs

Supported v0 `smoke_run` execution is deliberately conservative. It never
invokes an agent or live replay by itself. It evaluates an already-recorded run:
the completed replay output run when a replay run is supplied, an explicit
`definition.run_id`, or the source run resolved from the check target.

Supported smoke checks:

- run status is not in the configured failure statuses, or is in
  `allowed_run_statuses` when that list is provided
- replay run status is `passed` when evaluating replay output
- no failed spans, unless `no_failed_spans` is set to `false`
- span count is at least `min_spans` or `minimum_spans`, default `1`
- handoff count is at least `min_handoffs` or `minimum_handoffs`, default `0`

Smoke-run results include assertion-like check details and
`gateable = false`. They do not auto-promote check trust level, and the autonomy
gate rejects them with `unsupported_gate_check_type:smoke_run` even if a human
later approves the check spec to `L3_human_approved`.

## Trust Promotion

Check trust levels:

- `L0_generated`: generated or operator-proposed check; not enough alone for
  autonomous apply.
- `L1_repeated`: two stable deterministic results at the same status.
- `L2_regression`: deterministic or regression-replay fail-before/pass-after
  evidence with a completed replay and a safe replay side-effect mode.
- `L3_human_approved`: explicit human approval through
  `kyoko check-approve`, `POST /api/check-specs/approve`, or the dashboard
  `Approve L3` control. Kyoko does not auto-promote to this level.

Human-locked check specs can still run, but automatic trust promotion leaves
their canonical `trust_level` unchanged. Human locks also block explicit L3
approval until the check spec is unlocked.

## Replay Boundary

Safe replay side-effect modes:

- `none`
- `filesystem_read`
- `sandboxed_filesystem`
- `network_mocked`

Unsafe v0 replay modes:

- `live_network`
- `unknown`
- any unrecognized side-effect mode
- `mode = live`

`kyoko replay` records a bounded dry-run request and does not invoke the target
agent. Replay commands and HTTP replay servers must return a replay result that
declares the actual side-effect mode. Kyoko rejects unsafe modes before
canonical completion. Kyoko also rejects actual side-effect modes that exceed
the requested replay boundary: a completion may report `none`, the requested
safe mode, or `filesystem_read` for a `sandboxed_filesystem` request. HTTP
replay server URLs are loopback-only by default; non-loopback URLs require
explicit remote opt-in on direct server commands or on the registered replay
adapter. When HTTP replay-server `/health` advertises `capabilities`, Kyoko
requires it to include `replay`; when it advertises `side_effect_modes`, Kyoko
verifies the requested mode is present before posting replay context. If those
fields are absent, completion-time validation remains the backstop. Replay
requests handed to external replay commands or HTTP replay servers are redacted
with the profile evidence policy before leaving Kyoko. The default policy hides
payload refs and common secret-looking values while keeping replay ids, check ids,
entity ids, status fields, and trace shape available to the replay adapter.
When that redaction changes the request, Kyoko records a redaction audit event
for the replay consumer. Full `kyoko.replay_result.v1` fixture
responses are ingested as source events for the output run. Compact HTTP
replay-server responses that reference an already-ingested output run are
retained as content-addressed `replay_server_response` payload blobs; the
replay run result stores the side-effect mode, output run id, target map, note,
response key list, and blob ref instead of embedding the whole server response
in SQLite. The response blob defaults to redacted preview metadata, so blob
list/API/MCP surfaces expose a placeholder preview rather than server-returned
payload text. HTTP replay-server completion requires the response to echo
either `replay_run_id` or `idempotency_key` matching Kyoko's created replay run
id before the response can be accepted.

## Evidence

Implementation:

- `kyoko/checks.py`
- `kyoko/replay_adapters.py`
- `kyoko/replay_servers.py`
- `docs/decisions/0005-checks-and-replay.md`

Fixtures:

- `docs/fixtures/learning-proposals/valid-context-proposal.json`
- `docs/fixtures/replay-results/researcher-fetch-timeout-success.json`

Tests:

- `tests/test_checks.py`
- `tests/test_replay_adapters.py`
- `tests/test_replay_servers.py`
- `tests/test_details.py`
- `tests/test_web.py`

## Remaining Evidence

Retained live model/backend judge smoke evidence exists under
`.kyoko/smoke/judge-provider-live`. Before claiming arbitrary live replay
safety, Kyoko still needs deeper tool/network/filesystem policy enforcement,
broader secrets-policy evidence, and real framework replay smokes.
