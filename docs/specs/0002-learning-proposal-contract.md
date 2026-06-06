# Spec 0002 - LearningProposal Contract

Status: draft gate artifact — updated by [0016-issue-centric-loop.md](0016-issue-centric-loop.md)
Date: 2026-05-31
Blocks: G2, G3, Q2, Q3, Q4, Q15, Q16

> **Updated by 0016.** Every `LearningProposal` now **originates from an Issue** (the central
> spine). The contract gains one optional field, `issue_id` (schema-optional so legacy static
> fixtures still validate, but referentially checked when present and stamped by every
> production producer via `originate_issue_for_proposal`). See
> [0016](0016-issue-centric-loop.md).

Initial implementation:

- [`../../kyoko/proposals.py`](../../kyoko/proposals.py)
- [`../../kyoko/analyze.py`](../../kyoko/analyze.py)
- [`../../kyoko/evidence.py`](../../kyoko/evidence.py)
- [`../../kyoko/checks.py`](../../kyoko/checks.py)
- [`../../kyoko/apply.py`](../../kyoko/apply.py)
- [`../../kyoko/skillbook.py`](../../kyoko/skillbook.py)
- [`../../tests/test_analyze.py`](../../tests/test_analyze.py)
- [`../../tests/test_evidence.py`](../../tests/test_evidence.py)
- [`../../tests/test_checks.py`](../../tests/test_checks.py)
- [`../../tests/test_proposals.py`](../../tests/test_proposals.py)
- [`../../tests/test_apply.py`](../../tests/test_apply.py)
- [`../../tests/test_skillbook.py`](../../tests/test_skillbook.py)
- [`../../tests/test_cli.py`](../../tests/test_cli.py)

## Purpose

`LearningProposal` is the one transaction shape used by every learning path:

- operator-agent mode
- native ACE clone/diff mode
- human review mode
- future automated schedulers

No producer may mutate canonical skillbook, check, replay, patch, or autonomy
state directly. Producers submit proposals; Kyoko validates and applies them.

Machine-readable schema:

- [`../schemas/learning-proposal.schema.json`](../schemas/learning-proposal.schema.json)

Fixtures:

- [`../fixtures/learning-proposals/valid-context-proposal.json`](../fixtures/learning-proposals/valid-context-proposal.json)
- [`../fixtures/learning-proposals/invalid-hallucinated-span.json`](../fixtures/learning-proposals/invalid-hallucinated-span.json)

## Producer Modes

### Operator Agent

Codex, Claude Code CLI, Hermes, OpenClaw, or another installed operator reads
Kyoko evidence through CLI/MCP and returns strict JSON matching the schema.

The operator may propose:

- skillbook updates
- check specs
- replay requests
- harness patches
- context delivery rule updates

The operator may not:

- apply a proposal
- write canonical skillbook state
- patch the user's repo directly through Kyoko
- override a human lock
- change autonomy policy
- invent evidence IDs

### Native ACE

Native ACE may run when provider configuration exists. It must run against a
cloned skillbook snapshot. Kyoko diffs the clone against canonical state and
converts the delta into this proposal shape.

Native ACE may not directly mutate Kyoko canonical state.

### Human

Human edits should still use this proposal path when practical, so the UI,
audit trail, check gates, rollback, and apply engine stay consistent.

## Required Validation Layers

### 1. JSON Schema Validation

Checks:

- required fields exist
- enums are valid
- proposed change types are shaped correctly
- confidence values are bounded
- unknown top-level fields are rejected

This catches malformed operator output, but it does not prove the proposal is
safe or true.

The proposal `confidence` field is producer-reported confidence. Kyoko keeps it
for audit but computes a separate `kyoko_confidence` assessment at read time
from evidence coverage, target resolution, check/replay verification, duplicate
history, and validation state. UI and API surfaces should display the Kyoko
score as the product confidence and label the raw field as operator confidence.

### 2. Semantic Validation

Checks:

- every evidence reference exists in the same profile
- referenced spans/tasks/handoffs belong to cited runs or tasks when applicable
- target references exist or are explicitly new
- section matches proposed change type
- patch paths are normalized and relative
- check trust levels are not self-promoted without evidence
- duplicate proposals are detected
- locked skill entries are not overwritten

### 3. Policy Validation

Checks:

- context mode and harness mode allow the requested action
- autonomous actions meet the required check trust level
- replay side-effect mode is allowed
- protected paths are blocked
- dirty worktree policy is satisfied
- patch byte/file limits are satisfied
- rollback metadata exists for harness changes

For `harness_patch.patch_kind = unified_diff`, `diff_ref` must point at a
registered `payload_blobs` row containing UTF-8 unified diff text. Apply is
strict: target paths must exactly match the patch file paths, every hunk must
match the current workspace content without fuzzy offset search, additions are
secret-scanned, and rollback restores captured preimages.

### 4. Apply Transaction

Application must be transactional:

1. Load proposal and current policy.
2. Re-run semantic validation against current state.
3. Re-run policy validation against current state.
4. Create timeline event.
5. Apply skill, check, context, replay, or patch changes.
6. Record post-apply state.
7. Emit final timeline event.

## Proposal State Machine

Kyoko is a local, single-user tool, so the proposal lifecycle is intentionally collapsed
to **three user-facing states plus one internal state**. There is no separate draft,
review, approval, gating, or transient-applying state: a proposal is either waiting to be
acted on (`pending`), or it has reached one of three terminal outcomes.

```text
pending
-> applied
-> rolled_back
-> failed
```

States:

- `pending` is the only working state. Every newly submitted proposal starts here and stays
  here while validation, check/replay gates, and harness preparation run. A failing gate is
  recorded as evidence (autonomy events) but does **not** change the state — the proposal
  remains `pending` and is re-evaluated on the next autonomy run until it is applied, rolled
  back, or fails.
- `applied` (terminal) means the proposal's changes were applied to canonical state
  (skillbook/context rules or harness patch transactions).
- `rolled_back` (terminal) means a previously applied harness change was reverted, or a
  proposal was superseded by a newer one.
- `failed` (terminal, **internal**) means schema/semantic validation failed, the proposal
  was rejected by policy, or applying it regressed an check. Detail is preserved in the
  proposal's reason/error/validation-error fields rather than in distinct states.

### Legacy state mapping

Older producers and fixtures may still emit any of the previous ten states. On submission
they are normalized through this mapping (`kyoko.proposals.normalize_proposal_state`):

| legacy state(s)                                          | collapsed state |
| -------------------------------------------------------- | --------------- |
| `draft`, `proposed`, `gated`, `approved`, `applying`     | `pending`       |
| `applied`                                                | `applied`       |
| `superseded`                                             | `rolled_back`   |
| `failed`, `invalid`, `rejected`                          | `failed`        |

## Change Types

### `skillbook_update`

Creates or updates an ACE-compatible issue/insight entry.

Allowed operations:

- `create`
- `update`
- `deactivate`
- `link_occurrence`

Current apply behavior:

- `create` inserts a new active skill and records a `skill_revisions` row with
  null `before`.
- `update` rewrites issue, insight, keywords, occurrences, section, source run,
  and active state, after recording the previous row.
- `deactivate` marks the existing skill inactive without rewriting wording.
- `link_occurrence` appends new occurrence refs without duplicating existing
  refs.
- Human-locked skills reject later writes with `human_locked_skill:<id>`.
- `kyoko skill-rollback` and `POST /api/skill-revisions/rollback` can restore
  the latest revision. Non-create revisions restore their stored `before_json`
  preimage; create revisions roll back by deactivating the created skill.

Context autonomy may apply this if:

- policy context mode is `autonomous`
- evidence references exist
- no human lock conflict exists
- required context check gate is met

### `check_spec`

Creates an check owned by Kyoko.

Generated checks should start at `L0_generated` unless a higher level is proven
outside the operator's own assertion.

Initial implementation:

- `kyoko generate-checks <proposal_id>` persists `check_spec` changes from a
  validated proposal.
- `kyoko run-autonomy` can generate missing check specs for eligible context and
  harness proposals before evaluating the autonomous apply gate.
- `kyoko proposal-detail <proposal_id> --json` exposes proposal-linked check
  specs, check runs, replay runs, evidence refs, timeline events, and a read-only
  autonomy gate inspection for operator agents and the dashboard.
- `kyoko check-lock`, `POST /api/check-specs/lock`, and dashboard controls
  can human-lock an check spec. Locked check specs may still run, but Kyoko does
  not mutate their trust level through automatic promotion.
- deterministic assertions are tied to existing evidence, currently the failure
  evidence span when available, and can also verify replay target fields or
  replay entities such as handoffs.
- `kyoko run-check <check_spec_id>` records an `CheckRun` and fails the baseline
  fixture because the source span is still failed.
- repeated stable deterministic results can promote an check from
  `L0_generated` to `L1_repeated`; this is trust promotion, not proof that a
  fix passed.

Allowed check types:

- `deterministic_assertion`
- `judge`
- `regression_replay`
- `smoke_run`

### `replay_request`

Requests replay of an existing run or task attempt.

Replay must declare:

- mode
- side-effect mode
- source run or task attempt
- tool/network/filesystem boundaries

Initial implementation:

- `kyoko replay <check_spec_id>` records a bounded dry-run replay linked to the
  source run inferred from check evidence.
- `kyoko complete-replay <replay_run_id> <fixture>` ingests a controlled replay
  result fixture, links the replay run to a new output run, and stores a
  target map from original failed evidence to replay evidence.
- `kyoko replay-command <check_spec_id> --command "..." --output-dir ...` writes
  a replay request file, runs an external replay command, extracts exactly one
  delimited replay-result JSON block, ingests it, and can run the check
  immediately.
- `kyoko replay-adapter-register` stores a named replay command and default
  side-effect boundary.
- `kyoko replay-adapter-run <adapter_id> <check_spec_id>` executes the registered
  adapter through the same strict replay-result contract.
- v0 dry-run replay does not itself re-invoke tools or call the network; a
  controlled fixture can represent replay output under an explicit side-effect
  mode such as `network_mocked`.
- `live_network` and `unknown` side-effect modes are rejected by the runtime.

### `harness_patch`

Proposes a file or harness change.

Initial implementation:

- `kyoko prepare-harness <proposal_id>` validates a harness proposal and
  creates a `patch_transactions` row in `ready` state.
- `kyoko harness-patches --json` lists prepared patch transactions.
- `kyoko apply-harness <patch_transaction_id> --workspace-root <path>` applies
  `generated_file` patch transactions only, captures file preimages, and marks
  the transaction `applied`.
- `kyoko rollback-harness <patch_transaction_id> --workspace-root <path>`
  restores captured preimages and marks the transaction `rolled_back`.
- `POST /api/harness/prepare`, `POST /api/harness/apply`, `POST
  /api/harness/rollback`, and `GET /api/harness-patches` expose the same
  review path in the self-hosted API.
- The prepare step enforces allowed paths, protected paths, safe side-effect
  modes, and `rollback_required: true`.
- `command_plan` remains review-only. `generated_file` and `unified_diff`
  support manual apply/rollback against an explicit workspace root. Autonomous
  harness apply uses the same patch transaction path after the harness check gate
  passes.
- Human-locked harness target paths reject prepare/apply with
  `human_locked_harness_target:<path>`.

Harness autonomy may apply this only if:

- policy harness mode is `autonomous`
- repository patch writes are enabled
- patch paths are allowed
- protected paths are untouched
- dirty worktree policy is satisfied
- required harness check gate is met
- rollback metadata can be captured

If a later active proposal-linked check run fails and `rollback_on_regression`
is enabled, Kyoko may roll back applied harness patch transactions and move the
proposal from `applied` to `failed`.

### `context_delivery_rule`

Changes how accepted skillbook/context is delivered to target agents or
workflow nodes.

This is context autonomy, not harness autonomy, unless it writes repo files
outside Kyoko-owned config.

Current apply behavior:

- `create` inserts a canonical `context_delivery_rules` row.
- `update` rewrites the target/rule body and reactivates the row.
- `deactivate` marks the row inactive without deleting audit history.
- Every write records a `context_delivery_rule_revisions` row with before/after
  snapshots. `create` stores a null `before`; update/deactivate store the
  previous canonical rule row before mutation.
- `rule.id` is used as the stable rule id when present; otherwise Kyoko derives
  `context_rule_<proposal_id>_<change_index>`.
- Human-locked rules reject later writes with
  `human_locked_context_delivery_rule:<id>`.
- `kyoko context-rule-rollback` and
  `POST /api/context-rule-revisions/rollback` can restore the latest rule
  revision. Non-create revisions restore their stored `before_json` preimage;
  create revisions roll back by deactivating the created rule.
- Target-scoped context rendering can use `include_skill_ids`,
  `exclude_skill_ids`, `include_keywords`, `exclude_keywords`, and
  `max_skills`.

## Operator Output Contract

Operator CLI/MCP integrations should be prompted to return:

```text
BEGIN_KYOKO_LEARNING_PROPOSAL_JSON
{ ...schema-valid JSON... }
END_KYOKO_LEARNING_PROPOSAL_JSON
```

Initial command adapter:

- `kyoko operator-prompt --target codex --output-dir ...`
- `kyoko analyze --operator command --command "..." --output-dir ...`
- `kyoko operator-adapter-register <adapter_id> --command "..."`
- `kyoko analyze --operator <adapter_id> --output-dir ...`
- `kyoko operator-adapter-run <adapter_id>`
- `kyoko operator-runs --json`
- `kyoko mcp serve`
- `kyoko mcp config`
- `kyoko mcp install-plan`
- `kyoko mcp install --output <path>`
- Kyoko writes `evidence-bundle.json` and sets `KYOKO_EVIDENCE_PATH`.
- Kyoko writes `operator-instructions.md`, sets
  `KYOKO_OPERATOR_PROMPT_PATH`, and passes the prompt on stdin for command
  adapters that can read stdin.
- Kyoko records every command invocation in `operator_runs`, including
  nonzero exits, parse failures, and rejected proposals.
- The operator process may print arbitrary prose outside the delimited block.
- Kyoko rejects output unless exactly one proposal block exists.
- Kyoko persists the extracted proposal only after normal schema and semantic
  validation pass.

Kyoko should reject:

- multiple conflicting proposal blocks
- markdown-only summaries
- JSON with unknown top-level fields
- proposals without evidence refs
- proposals that cite missing or inaccessible evidence
- proposals that require direct apply

## Minimum Acceptance Fixtures

Before runtime implementation locks this contract, Kyoko needs fixtures for:

1. Valid context proposal.
2. Valid harness proposal.
3. Malformed JSON.
4. JSON schema violation.
5. Hallucinated evidence ID.
6. Locked skill conflict.
7. Protected path patch.
8. Context-only autonomy trying to apply harness change.
9. Native ACE clone/diff producing the same shape.
10. Duplicate proposal detection.
