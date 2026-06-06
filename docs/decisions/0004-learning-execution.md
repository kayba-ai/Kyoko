# 0004 - Learning Execution Strategy

Status: accepted for planning
Date: 2026-05-30

## Decision

Kyoko will support two learning executors:

1. **Operator-agent executor** for the default no-separate-API-key path.
2. **Native ACE executor** for users who configure model/provider access.

The operator-agent executor is the default product path when no Kyoko/ACE model
provider is configured. Codex, Claude Code CLI, Hermes, OpenClaw, or another
installed operator agent performs the analysis by reading Kyoko evidence and
returning strict JSON proposals.

Native ACE is optional. Kyoko may use the `ace-framework` package for
`Skillbook`, `TraceAnalyser`, pipeline composition, `ReflectorOutput`,
`SkillManagerOutput`, `UpdateOperation`, and `UpdateBatch`, but native ACE must
run against cloned skillbook state. Kyoko converts the resulting delta into a
`LearningProposal`.

No executor may directly mutate canonical Kyoko state.

## Rationale

ACE's built-in learning roles use PydanticAI/LiteLLM-backed model access. ACE
does not currently provide a turnkey local mode where Codex, Claude Code CLI,
Hermes, or OpenClaw acts as the Reflector and SkillManager without provider
access.

ACE does provide the right extension point: `ReflectorLike` and
`SkillManagerLike` are structural protocols. Kyoko can supply compatible
objects that call operator agents instead of direct model providers.

This preserves the main product promise:

- users can run Kyoko locally,
- they do not need a separate Kyoko/ACE API key if they already use a coding
  agent subscription or target-agent runtime,
- ACE compatibility remains available,
- Kyoko owns validation, evals, autonomy policy, human locks, and writes.

## Operator-Agent Executor

Flow:

```text
Kyoko evidence bundle
  -> Kyoko MCP/CLI read tools
  -> operator agent analysis
  -> strict JSON proposal
  -> Kyoko validation
  -> eval/replay gates
  -> apply only if policy allows
```

Operator agents may:

- inspect profile, run, span, task, handoff, payload, issue, eval, and replay
  evidence,
- propose issues,
- propose ACE-compatible skill operations,
- propose eval specs,
- propose harness patches.

Operator agents may not by default:

- apply proposals,
- mutate canonical skillbook entries,
- patch repo files directly,
- bypass eval/replay gates,
- override human-locked wording,
- change autonomy policy.

Required adapters:

- `KyokoOperatorReflector`: converts operator-agent analysis into
  `ReflectorOutput` or directly into the reflection portion of a
  `LearningProposal`.
- `KyokoProposalSkillManager`: converts operator-agent proposal JSON into
  validated `UpdateOperation[]`, `SkillManagerOutput`, and a Kyoko
  `LearningProposal`.

The adapter may run through ACE's `TraceAnalyser.from_roles(...)` with these
custom role objects, or bypass ACE pipeline execution and use only ACE data
types. The canonical output is still `LearningProposal`.

For coding-agent use, `kyoko improve` is the high-level orchestration command.
It can start from an existing proposal or invoke an operator adapter, then
generate eval specs, run a registered replay adapter, execute evals, and call
the normal autonomy runner. This keeps the easy path and the safe path the same
path.

## Native ACE Executor

Flow:

```text
Kyoko evidence bundle
  -> clone canonical skillbook into temporary ACE Skillbook
  -> ACE TraceAnalyser
  -> diff temporary skillbook against canonical snapshot
  -> LearningProposal
  -> Kyoko validation
  -> eval/replay gates
  -> apply only if policy allows
```

Native ACE requires configured model/provider access. It is not the no-key path.

Implemented bridge:

- `kyoko ace-compat` verifies that Kyoko's exported ACE Skillbook v2 JSON can
  be loaded by ACE's public `Skillbook.from_dict(...)` API.
- `kyoko ace-diff-proposals` converts a before/after ACE Skillbook clone into
  `native_ace` LearningProposals with generic replay/eval gates.
- See [`0006 - Native ACE Bridge`](0006-native-ace-bridge.md).

## Canonical Transaction

All learning paths converge on `LearningProposal`.

Minimum fields:

- producer: `operator_agent | native_ace | human`
- producer identity
- issue title/body/severity/evidence
- section: `context | harness`
- ACE-compatible skill operations
- eval proposals
- patch proposal reference when relevant
- confidence and rationale reference
- validation status

Kyoko stores ACE-compatible skill operations for portability, but the Kyoko
transaction and audit trail are canonical.

## Operator Adapter Registry

The first runtime slice stores named local operator commands as
`operator_adapters`. An adapter id such as `codex`, `claude`, `hermes`, or
`openclaw` is a stable alias for an installed local command. Kyoko writes an
`evidence-bundle.json` and `operator-instructions.md`, sets
`KYOKO_EVIDENCE_PATH` and `KYOKO_OPERATOR_PROMPT_PATH`, passes the prompt on
stdin, and requires exactly one delimited `LearningProposal` JSON block.

Each operator invocation is recorded as an `operator_runs` row with status,
prompt/evidence/raw-output artifact refs, the selected adapter id when
available, proposal id on success, and a structured error on failure. This
keeps malformed JSON, timeout, and nonzero-exit failures visible to the UI,
CLI, API, and evidence bundle.

This does not grant the operator direct write access. Adapter output still
passes through normal proposal schema validation, semantic evidence checks, and
policy-gated apply/eval/replay paths.

## MCP Surface

The first MCP slice follows the official MCP lifecycle and tools model:
clients initialize the server, list available tools through `tools/list`, and
call individual tools through `tools/call`.

References:

- [MCP lifecycle, 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)
- [MCP tools, 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)

Default operator-agent MCP access is read/propose/eval-request plus readiness
and dry-run inspection oriented:

- read profile/run/span/task/handoff/eval/replay evidence,
- inspect storage and retention dry-run impact,
- run first-run readiness checks and no-live-model smokes,
- search evidence,
- create learning proposals,
- create eval proposals,
- create patch proposals,
- request gated eval/replay runs.

Direct apply, destructive prune, and rollback tools are privileged. If exposed
at all, they must enforce the same autonomy policy, eval gates, write
boundaries, human locks, retention safeguards, and patch transaction rules as
the UI and CLI.

`kyoko_run_improve` is allowed on the default MCP surface as orchestration, not
as an apply tool. It may import an explicitly selected discovered source,
invoke an operator proposal, generate evals, and optionally run registered
replay/eval gates, but the MCP handler forces `run_autonomy_after=False` and
returns `mcp_autonomy_disabled=true`.

`kyoko_mcp_safety_contract` reports the active default MCP safety posture.
Server startup also enforces that the default tool surface does not include
direct apply, run-autonomy, or harness file-write tools. Rollback tools remain
visible on the default surface only with MCP destructive annotations, and any
future direct apply or harness write tool must deliberately change this
contract.

Implemented stdio tools:

- `kyoko_status`
- `kyoko_mcp_safety_contract`
- `kyoko_list_profiles`
- `kyoko_get_dashboard_metrics`
- `kyoko_run_doctor`
- `kyoko_discover_sources`
- `kyoko_get_storage_report`
- `kyoko_list_payload_blobs`
- `kyoko_prune_payload_blobs_dry_run`
- `kyoko_get_evidence`
- `kyoko_list_runs`
- `kyoko_get_run_detail`
- `kyoko_get_policy`
- `kyoko_get_retention_policy`
- `kyoko_prune_retention_dry_run`
- `kyoko_list_proposals`
- `kyoko_get_proposal_detail`
- `kyoko_submit_proposal`
- `kyoko_get_context`
- `kyoko_list_skills`
- `kyoko_list_skill_revisions`
- `kyoko_rollback_skill_revision`
- `kyoko_list_context_rules`
- `kyoko_list_context_rule_revisions`
- `kyoko_rollback_context_rule_revision`
- `kyoko_list_evals`
- `kyoko_get_eval_capabilities`
- `kyoko_list_eval_assertion_presets`
- `kyoko_list_eval_spec_locks`
- `kyoko_get_eval_detail`
- `kyoko_get_replay_detail`
- `kyoko_generate_evals`
- `kyoko_run_eval`
- `kyoko_list_replay_adapters`
- `kyoko_run_replay_adapter`
- `kyoko_run_improve`
- `kyoko_prepare_operator_smoke_matrix`
- `kyoko_list_operator_adapters`
- `kyoko_list_operator_runs`
- `kyoko_list_harness_patches`
- `kyoko_list_harness_target_locks`

## Failure Handling

Operator-agent outputs must be validated before storage or execution.

Required failure cases:

- malformed JSON,
- schema-valid but unsupported operation,
- missing evidence references,
- confidence below policy threshold,
- timeout,
- cancelled job,
- partial output,
- duplicate proposal,
- proposal conflicts with a human lock,
- proposal attempts protected path writes,
- replay/eval gate unavailable.

Failures become visible proposal/job records, not silent retries.

## Consequences

Positive:

- Kyoko can deliver the no-separate-API-key path without pretending ACE itself
  has no model dependency.
- ACE remains useful as a package dependency and compatibility layer.
- Operator agents can use the subscriptions/runtimes users already have.
- Kyoko keeps safety-critical writes centralized.

Costs:

- Kyoko must build and test operator-agent spawning, prompts, JSON validation,
  cancellation, and retries.
- Operator outputs may be less deterministic than native ACE.
- The MVP needs strong fixture tests before enabling autonomy.

## Required Spikes

1. Codex or Claude Code reads one Kyoko evidence fixture and returns strict
   `LearningProposal` JSON.
2. Hermes does the same if non-interactive execution is viable.
3. `KyokoOperatorReflector` converts operator output into `ReflectorOutput`.
4. `KyokoProposalSkillManager` validates `UpdateOperation[]`.
5. Native ACE clone/diff produces the same proposal envelope.
6. Malformed and partial operator outputs produce clear errors.
