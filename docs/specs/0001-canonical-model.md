# Spec 0001 - Canonical Model

Status: draft gate artifact
Date: 2026-05-31
Blocks: G1, Q1, Q20, Q24

Initial implementation:

- [`../../kyoko/storage.py`](../../kyoko/storage.py)
- [`../../kyoko/sdk.py`](../../kyoko/sdk.py)
- [`../../kyoko/web.py`](../../kyoko/web.py)
- [`../../kyoko/apply.py`](../../kyoko/apply.py)
- [`../../kyoko/skillbook.py`](../../kyoko/skillbook.py)
- [`../../kyoko/checks.py`](../../kyoko/checks.py)
- [`../../tests/test_storage.py`](../../tests/test_storage.py)
- [`../../tests/test_apply.py`](../../tests/test_apply.py)
- [`../../tests/test_skillbook.py`](../../tests/test_skillbook.py)
- [`../../tests/test_checks.py`](../../tests/test_checks.py)
- [`../../tests/test_cli.py`](../../tests/test_cli.py)

## Purpose

This spec defines Kyoko's canonical local data model before runtime code or
database migrations are written. Source adapters may ingest OTLP, Hermes rows,
OpenClaw sessions, SDK events, or operator-agent activity, but all product
features must reason over this normalized model.

OTLP and framework-native schemas are input formats. They are not Kyoko's
canonical state.

Initial runtime ingestion accepts canonical source-event JSON through
`kyoko ingest <path>` and `POST /api/ingest`. Framework-specific adapters should
normalize into this shape before persistence.

The Python SDK recorder emits the same canonical source-event shape. It is a
manual wrapper for frameworks that do not yet have a native Kyoko adapter.

`kyoko ingest-otlp`, `POST /api/ingest-otlp`, and `POST /v1/traces` accept
OTLP/GenAI-style JSON trace exports and normalize them into the canonical
source-event shape. This is intentionally a JSON export/HTTP normalizer, not a
full OTLP protobuf receiver.

## Design Rules

1. One `Profile` is the product boundary.
2. Multi-agent support lives inside one profile through `AgentIdentity`,
   `WorkflowNode`, `Task`, `Queue`, `Handoff`, and `TaskAttempt`.
3. Runs and spans explain what happened during execution.
4. Tasks, queues, and handoffs explain why work moved and who owned it.
5. Issues, proposals, checks, replay runs, and patch transactions explain what
   Kyoko learned and what it changed.
6. Large or sensitive payloads are stored by reference, not inline in every
   table.
7. Every learning or autonomy decision must cite stable evidence references.

## Identity And Time

All primary IDs are Kyoko-owned stable strings:

```text
profile_...
source_...
agent_...
node_...
run_...
span_...
queue_...
task_...
attempt_...
handoff_...
event_...
issue_...
proposal_...
check_...
checkrun_...
replay_...
patch_...
blob_...
```

Every persisted row should include:

- `created_at`
- `updated_at` when mutable
- `source_id` when imported or controlled by an integration
- `external_id` when the source has its own stable identifier
- `metadata_json` for source-specific attributes that are not query-critical

Times are UTC ISO-8601 strings at API/fixture boundaries. The database may store
them as text or integer timestamps, but public JSON uses ISO-8601.

## Core Entities

### Profile

The active local optimization boundary.

Required fields:

- `id`
- `name`
- `root_path`
- `status`: `active | archived`
- `created_at`
- `updated_at`

Notes:

- A Kyoko profile is not a Hermes profile.
- A Kyoko profile may contain many framework agents, Hermes profiles, OpenClaw
  agents, subagents, human actors, and operator agents.

### Source

An ingest or control origin.

Required fields:

- `id`
- `profile_id`
- `kind`: `otlp_http | kyoko_sdk | hermes_kanban | openclaw_sessions | ai_sdk | pydantic_ai | openai_agents | langgraph | crewai | operator_agent | manual | unknown`
- `display_name`
- `status`: `active | inactive | error`
- `adapter_version`
- `config_json`
- `capabilities_json`
- `last_seen_at`

Invariant:

- All imported rows must retain `source_id` and `adapter_version` either
  directly or through their source row.

### AgentIdentity

A stable actor identity inside a profile.

Required fields:

- `id`
- `profile_id`
- `source_id`
- `external_id`
- `name`
- `kind`: `agent | subagent | hermes_profile | openclaw_agent | framework_node | human | operator | unknown`
- `role`
- `model`
- `workspace_path`
- `metadata_json`

Invariant:

- Operator agents performing Kyoko analysis are represented here with
  `kind = operator`.

### WorkflowNode

A logical node in the user's workflow.

Required fields:

- `id`
- `profile_id`
- `source_id`
- `external_id`
- `agent_identity_id`
- `kind`: `workflow | agent | subagent | router | handoff | tool | retriever | evaluator | queue | unknown`
- `name`
- `metadata_json`

Use:

- A span can attach to a workflow node.
- A task can attach to a workflow node.
- An issue can target a workflow node even if evidence came from multiple runs.

### Run

An execution attempt.

Required fields:

- `id`
- `profile_id`
- `source_id`
- `external_id`
- `root_span_id`
- `agent_identity_id`
- `task_attempt_id`
- `status`: `running | succeeded | failed | cancelled | timed_out | unknown`
- `started_at`
- `ended_at`
- `input_ref`
- `output_ref`
- `summary`
- `metadata_json`

Invariant:

- A run may exist without a task attempt.
- A task attempt may link to one primary run, but replay and follow-up work may
  create additional runs linked through timeline events.

### Span

A normalized execution operation inside a run.

Required fields:

- `id`
- `run_id`
- `source_id`
- `external_id`
- `parent_span_id`
- `workflow_node_id`
- `agent_identity_id`
- `kind`: `workflow | agent | handoff | llm | tool | retrieval | check | system | unknown`
- `name`
- `status`: `running | succeeded | failed | cancelled | timed_out | unknown`
- `started_at`
- `ended_at`
- `input_ref`
- `output_ref`
- `usage_json`
- `attributes_json`
- `raw_ref`

Invariant:

- A handoff span should create or link to a `Handoff` row when the source
  provides enough information.

#### Span search index (`spans_fts`)

Added in schema version 24. `spans_fts` is a SQLite **FTS5** virtual table providing
fast full-text run-search (`search-run` / `/api/run-search` / the `kyoko_search_run`
MCP tool) instead of a linear Python scan. It indexes one document per span:

- `span_id` (UNINDEXED) — maps a match back to its `Span`.
- `run_id` (UNINDEXED) — restricts a search to a single run.
- `text` — span `name` + canonical JSON `attributes` + the input/output
  `payload_blobs.preview` text (the same redacted previews the linear scan saw).

It is kept in sync write-through during span ingest (`ingest_source_payload`), and is
backfilled from existing spans on first open of a pre-v24 database. The table is
additive (`CREATE VIRTUAL TABLE IF NOT EXISTS ... USING fts5(...)`) and best-effort: if
the local SQLite build lacks the FTS5 module, the index is skipped and `search-run`
transparently falls back to the original linear/regex scan. FTS5 is used only as a
*pre-filter* — every candidate span is re-verified with the precise (case/regex-aware)
matcher, and the pre-filter is bypassed for regex, case-sensitive, or mid-token
substring patterns, so search results are identical to the linear scan. The FTS shadow
tables are an implementation detail and are excluded from `status`/`STATUS_TABLES`
counts.

### Queue

A durable coordination container.

Required fields:

- `id`
- `profile_id`
- `source_id`
- `external_id`
- `name`
- `kind`: `hermes_board | openclaw_queue | generic | unknown`
- `metadata_json`

Invariant:

- Simple span-only frameworks do not need queue rows.

### Task

A durable work item.

Required fields:

- `id`
- `profile_id`
- `source_id`
- `queue_id`
- `external_id`
- `title`
- `body_ref`
- `status`: `triage | todo | ready | running | blocked | done | archived | unknown`
- `assignee_agent_identity_id`
- `created_by_agent_identity_id`
- `priority`
- `workspace_kind`: `repo | temp | external | unknown`
- `workspace_path`
- `created_at`
- `started_at`
- `completed_at`
- `metadata_json`

Invariant:

- Hermes-style support is not valid unless tasks, attempts, queues, and
  handoffs can be represented without losing ownership.

### TaskAttempt

One attempt by one worker or agent to perform a task.

Required fields:

- `id`
- `task_id`
- `run_id`
- `agent_identity_id`
- `status`: `running | done | blocked | crashed | timed_out | failed | released | unknown`
- `outcome`
- `claim_token_hash`
- `worker_pid`
- `started_at`
- `ended_at`
- `last_heartbeat_at`
- `summary_ref`
- `metadata_json`
- `error_ref`

Invariant:

- Retries by different agents must be separate task attempts.

### Handoff

An explicit transfer of responsibility, context, or work.

Required fields:

- `id`
- `profile_id`
- `source_id`
- `from_agent_identity_id`
- `to_agent_identity_id`
- `from_workflow_node_id`
- `to_workflow_node_id`
- `from_task_id`
- `to_task_id`
- `run_id`
- `span_id`
- `kind`: `agent_handoff | task_created | task_assigned | queue_dependency | human_block | tool_delegation | unknown`
- `reason_ref`
- `payload_ref`
- `created_at`
- `metadata_json`

Invariant:

- A handoff can cite a span, a task transition, both, or neither when imported
  from a source that only exposes a coordination event.

### TimelineEvent

Append-only event for UI and audit trails.

Required fields:

- `id`
- `profile_id`
- `source_id`
- `entity_type`
- `entity_id`
- `kind`
- `at`
- `agent_identity_id`
- `payload_ref`
- `metadata_json`

Invariant:

- Proposal, check, replay, and patch state changes should create timeline
  events.

## Live & Observability Entities

These entities support live (push) observability and are pure evidence/read-side:
they never change agent behavior and sit outside the safety gate. Content is
redacted by default before persistence or serving, and live serving is loopback-only.
Added in schema version 20.

### LiveEvent

A fine-grained, real-time event emitted during agent execution (token deltas, tool
start/result, status, messages), the live analogue of post-hoc `Span` ingest.

Required fields:

- `id`
- `profile_id`
- `source_id` (nullable; live ingest may precede full source materialization)
- `run_id` (free reference; may arrive before the `Run` row exists)
- `span_id` (free reference)
- `seq`: monotonic per-run ordering hint
- `kind`: `token | tool_start | tool_result | status | message | error | other`
- `content_preview`: short redacted inline preview
- `content_ref`: optional `payload_blobs` id holding the full redacted body
- `at`
- `metadata_json`

Invariant:

- `run_id`/`span_id` are free references (like `timeline_events.entity_id`) so live
  events can be ingested before the batch `Run`/`Span` rows are materialized.

### McpLogEntry

A record of one JSON-RPC interaction on Kyoko's MCP server (the agent ↔ Kyoko
conversation): `initialize`, `tools/list`, `tools/call`, and their responses.

Required fields:

- `id`
- `profile_id` (nullable)
- `session_id`: stable id for one MCP client connection
- `seq`: monotonic per-session ordering
- `direction`: `request | response | notification`
- `method` (e.g. `tools/call`)
- `tool_name` (resolved for `tools/call`)
- `params_preview`, `params_ref`: redacted inline preview + optional full blob
- `result_preview`, `result_ref`: redacted inline preview + optional full blob
- `is_error`, `error_code`
- `duration_ms` (on the response record)
- `client_id`
- `at`
- `metadata_json`

Invariant:

- Logging is observability only; it never alters dispatch or bypasses the MCP tool
  safety boundary (no apply/harness-write tools are added by logging).

### Annotation

A lightweight, durable human/agent note attached to a run or span.

Required fields:

- `id`
- `profile_id`
- `run_id` (nullable)
- `span_id` (nullable)
- `kind`: `issue | good | note`
- `note`
- `source`: `user` or an MCP client id (e.g. `claude-code`, `codex`)
- `created_at`, `updated_at`
- `metadata_json`

Invariant:

- An annotation may *seed* a `LearningProposal` but never applies a change itself; it
  is evidence, not a behavior mutation.

## Learning Entities

### Issue

A first-class, operator-authored (or agent-proposed via MCP) record of a problem worth
tracking, **independent from any LearningProposal**. An Issue is pure evidence on the
read/propose side: it describes a category/severity of problem, links the affected
canonical entities, and may backlink to the proposals that address it. Creating, listing,
or resolving an Issue never changes agent behavior, so Issues sit entirely outside the
autonomy/safety gate. Added in schema version 23 (`issues` table). See
[0012-issue-model.md](0012-issue-model.md) for the full lifecycle and relationships.

Fields (`issues` table):

- `id` — `issue_{uuid hex[:12]}`
- `profile_id` — the single implicit profile (resolved when omitted)
- `title` (required)
- `body` (nullable)
- `section`: `context | harness` (nullable; validated in the module, not the DB)
- `category` (nullable, free-text)
- `severity`: `low | medium | high` (nullable)
- `status`: `open | resolved | dismissed` (default `open`)
- `evidence_refs_json` — evidence refs (resolved/redacted on export via the standard path)
- `affected_agent_identity_ids_json`
- `affected_workflow_node_ids_json`
- `affected_task_ids_json`
- `affected_span_ids_json`
- `proposal_ids_json` — backlinks to the LearningProposals that address this issue
- `created_at`
- `updated_at` (nullable; set on status transitions)

Indices: `profile_id`, `status`, `section`.

### Skill

ACE-compatible skillbook entry plus Kyoko metadata.

Required fields:

- `id`
- `profile_id`
- `section`: `context | harness`
- `issue`
- `insight`
- `keywords_json`
- `occurrences_json`
- `helpful_count`
- `harmful_count`
- `neutral_count`
- `active`
- `human_locked`
- `human_lock_reason`
- `source_run_id`
- `created_at`
- `updated_at`

Invariant:

- ACE-compatible fields must remain exportable to ACE Skillbook v2.
- Kyoko-specific targeting metadata lives outside the ACE-compatible shape.

### SkillRevision

Audit record for every canonical skillbook write.

Required fields:

- `id`
- `skill_id`
- `profile_id`
- `proposal_id`
- `operation`: `create | update | deactivate | link_occurrence | rollback`
- `before_json`
- `after_json`
- `created_at`

Invariant:

- `before_json` is null only for `create`.
- Update, deactivate, and link-occurrence writes must preserve the previous row
  in `before_json` before mutating the canonical skill.
- Rollback is only allowed for the latest revision for a skill. Create rollback
  deactivates the created skill while preserving the row and audit history.

### ContextDeliveryRule

Kyoko-owned delivery policy for accepted context.

Required fields:

- `id`
- `profile_id`
- `proposal_id`
- `target_json`
- `rule_json`
- `active`
- `human_locked`
- `human_lock_reason`
- `created_at`
- `updated_at`

Invariant:

- Delivery rules are context autonomy state, not ACE Skillbook state.
- A locked rule still participates in context delivery, but later proposals
  cannot update or deactivate the same rule id.
- v0 target-scoped rendering supports `include_skill_ids`,
  `exclude_skill_ids`, `include_keywords`, `exclude_keywords`, and
  `max_skills`.

### ContextDeliveryRuleRevision

Audit record for every context delivery rule write.

Required fields:

- `id`
- `rule_id`
- `profile_id`
- `proposal_id`
- `operation`: `create | update | deactivate | rollback`
- `before_json`
- `after_json`
- `created_at`

Invariant:

- `before_json` is null only for `create`.
- Update and deactivate writes must preserve the previous rule row in
  `before_json` before mutating the canonical rule.
- Rollback is only allowed for the latest revision for a rule. Create rollback
  deactivates the created rule while preserving the row and audit history.
- Human-locked rules cannot be rolled back automatically or manually until the
  lock is removed.

### HarnessTargetLock

Human-owned write block for a normalized harness target path.

Fields:

- `profile_id`
- `target_path`
- `human_locked`
- `reason`
- `created_at`
- `updated_at`

Invariant:

- A locked harness target path blocks both harness proposal preparation and
  prepared patch transaction apply for the same profile/path.
- Autonomous harness apply reports
  `human_locked_harness_target:<target_path>` as a blocked decision before any
  repository write.

### LearningProposal

A proposed learning transaction. See
[`../schemas/learning-proposal.schema.json`](../schemas/learning-proposal.schema.json).

Required fields:

- `id`
- `schema_version`
- `profile_id`
- `producer`
- `state`
- `section`
- `title`
- `summary`
- `evidence_refs_json`
- `proposed_changes_json`
- `gate_expectations_json`
- `validation_errors_json`
- `created_at`
- `updated_at`

Invariant:

- Operator-agent, native ACE, and human-generated learning paths all converge
  here.
- A proposal is not a canonical mutation until Kyoko validates and applies it.

### CheckSpec

A test or evaluation definition owned by Kyoko.

Required fields:

- `id`
- `profile_id`
- `proposal_id`
- `name`
- `type`: `deterministic_assertion | judge | regression_replay | smoke_run`
- `trust_level`: `L0_generated | L1_repeated | L2_regression | L3_human_approved`
- `side_effect_mode`: `none | filesystem_read | sandboxed_filesystem | network_mocked | live_network | unknown`
- `target_json`
- `definition_json`
- `status`: `active | inactive | superseded`
- `created_at`
- `updated_at`

### CheckSpecLock

Human-owned write block for a Kyoko check spec.

Required fields:

- `profile_id`
- `check_spec_id`
- `human_locked`
- `reason`
- `created_at`
- `updated_at`

Invariant:

- A locked check spec may still be executed.
- Kyoko-owned check-spec mutation, including automatic trust-level promotion,
  must not rewrite a locked check spec.
- Lock state is exposed as an overlay in check list/detail payloads.

### CheckRun

One execution of an check spec.

Required fields:

- `id`
- `profile_id`
- `check_spec_id`
- `proposal_id`
- `replay_run_id`
- `status`: `queued | running | passed | failed | errored | cancelled`
- `started_at`
- `ended_at`
- `result_json`
- `artifact_refs_json`
- `created_at`
- `updated_at`

### ReplayRun

One replay attempt.

Required fields:

- `id`
- `profile_id`
- `proposal_id`
- `check_spec_id`
- `source_run_id`
- `task_attempt_id`
- `mode`: `dry_run | sandbox | live`
- `side_effect_mode`: `none | filesystem_read | sandboxed_filesystem | network_mocked | live_network | unknown`
- `status`: `queued | running | passed | failed | errored | cancelled`
- `started_at`
- `ended_at`
- `input_ref`
- `output_ref`
- `result_json`
- `artifact_refs_json`
- `created_at`
- `updated_at`

### ReplayAdapter

A named local replay executor for one profile.

Required fields:

- `id`
- `profile_id`
- `name`
- `command_json`
- `output_dir`
- `default_mode`: `dry_run | sandbox | live`
- `default_side_effect_mode`: `none | filesystem_read | sandboxed_filesystem | network_mocked | live_network | unknown`
- `timeout_seconds`
- `enabled`
- `metadata_json`
- `created_at`
- `updated_at`

Invariant:

- v0 rejects `live` mode and unsafe side-effect modes at registration and run
  time.
- Adapter commands receive a `kyoko.replay_request.v1` artifact path and must
  return strict `kyoko.replay_result.v1` JSON through the replay-result stdout
  block.

### OperatorAdapter

A named local operator-agent command for one profile.

Required fields:

- `id`
- `profile_id`
- `name`
- `operator_kind`: `generic | codex | claude | hermes | openclaw`
- `command_json`
- `output_dir`
- `timeout_seconds`
- `enabled`
- `metadata_json`
- `created_at`
- `updated_at`

Invariant:

- Adapter commands do not get direct write access to Kyoko canonical state.
  They receive evidence and a prompt, then return a strict LearningProposal
  block that Kyoko validates before storage or apply.

### OperatorRun

One invocation of a mock, command, or registered operator adapter.

Required fields:

- `id`
- `profile_id`
- `adapter_id`
- `operator_label`
- `operator_kind`
- `status`: `running | succeeded | failed | cancelled | timed_out`
- `started_at`
- `ended_at`
- `evidence_ref`
- `prompt_ref`
- `raw_output_ref`
- `proposal_id`
- `error`
- `metadata_json`
- `created_at`
- `updated_at`

Invariant:

- Operator failures are persisted as run records. A failed operator run may
  have evidence, prompt, and raw-output refs even when no proposal was accepted.

### PatchTransaction

A proposed, prepared, applied, or rolled-back repository/harness write.

Required fields:

- `id`
- `profile_id`
- `proposal_id`
- `status`: `draft | ready | applied | rolled_back | failed | rejected`
- `patch_kind`: `unified_diff | generated_file | command_plan`
- `target_paths_json`
- `diff_ref`
- `command_plan_json`
- `side_effect_mode`
- `rollback_json`
- `created_at`
- `updated_at`

Invariant:

- Harness autonomy cannot apply a patch without a patch transaction.
- The runtime prepares `ready` patch transactions for all patch kinds, but
  applies only `generated_file` and strict `unified_diff` transactions with an
  explicit workspace root. Apply captures file preimages in `rollback_json`;
  rollback restores or removes files from those preimages. `command_plan`
  remains review-only.
- When `rollback_on_regression` is enabled, the autonomy runner may roll back
  applied harness patch transactions if the latest proposal-linked check run
  fails after apply.

### AutonomyPolicy

Per-profile write boundaries.

Required fields:

- `profile_id`
- `context_mode`: `off | propose | autonomous`
- `harness_mode`: `off | propose | autonomous`
- `allow_skillbook_write`
- `allow_check_write`
- `allow_profile_config_write`
- `allow_repo_patch`
- `allow_replay_server_patch`
- `allowed_paths_json`
- `protected_paths_json`
- `dirty_worktree_policy`: `block | allow_touched_only | allow`
- `required_check_level_context`
- `required_check_level_harness`
- `rollback_on_regression`
- `updated_at`

### Redaction (global default, no table)

Kyoko is single-user/local, so redaction is a single global "redact on export"
default rather than a per-profile policy table. There is no `redaction_policies`
table and no `redaction_audit_events` ledger (both dropped in schema version 22).

The default policy is fixed in code (`kyoko.redaction.DEFAULT_REDACTION_POLICY`):

- `payload_access`: `redacted`
- `redact_sensitive_values`: `true`
- `redacted_placeholder`: `[REDACTED]`
- `sensitive_key_patterns`: the 14 built-in secret-key fragments (api_key,
  apikey, authorization, client_secret, access_key, refresh_token, secret,
  password, passwd, pwd, token, credential, private_key, cookie)

Invariant:

- Operator evidence, prompt artifacts, and MCP/API evidence are redacted with
  this global default before leaving Kyoko's canonical store.
- `redacted` hides payload/artifact refs and sensitive values.
- Each redacted bundle still carries a `redaction` summary (policy, redacted
  count/paths, and consumer label such as `cli:evidence`,
  `operator_prompt:codex`, `mcp:kyoko_get_evidence`, or `api:evidence-summary`).
- There is no persisted audit ledger and no acknowledgement workflow.

### Retention (manual prune, no table)

Retention is a manual `--older-than-days` prune rather than a per-profile policy
table. There is no `retention_policies` table (dropped in schema version 22).

The prune path takes explicit `trace_older_than_days`, `replay_older_than_days`,
and `operator_older_than_days` inputs.

Invariant:

- A blank/omitted day value means that row family is not pruned.
- Retention pruning is dry-run by default and only deletes rows when apply is
  explicitly requested.
- Trace pruning must skip runs referenced by applied skills, active replay
  rows, check specs, learning proposals, or skill occurrences.
- Payload blobs remain governed by `payload_blobs.retained_until` and the
  separate blob prune path.

## Measurement Entities (`eval` / `llm_eval`)

Added in schema version 26. The **measurement plane** scores a trace corpus to
surface the prevalence/severity of a problem, in two flavors discriminated by
`kind`: `python` (a deterministic detector → numerator/denominator prevalence)
and `llm` (an LLM-as-judge template → 0–1 / boolean). Measurements are
**evidence only** — they never write a `CheckRun`, mutate a skill, or edit a
harness file, and never satisfy the autonomy gate. They may raise an `Issue`
(opt-in, threshold-gated). See specs 0014/0015. Module: `kyoko/evals_measure.py`.

### EvalDefinition (`eval_definitions` table)

A registered measurement. Bundled `llm_eval` templates upsert from assets; user
detectors register their own. Key fields: `kind` (`python`|`llm`), `name`,
`version`, `partner` (`"ragas"` for ported templates, else NULL), `source`
(`bundled`|`user`), `unit_type` (`event`|`llm_span`|`run`), `output_type`
(`numeric`|`boolean`), `direction` (`lower_is_better`|`higher_is_better`|
`true_is_notable`|`false_is_notable`), `problem_statement`, `detector_ref`
(python: blob sha of the detector `.py`), `prompt`/`vars_json`/`bindings_json`/
`output_json` (llm only), `severity_bands_json`, `status` (`active`|`archived`).

### EvalMeasureRun (`eval_measure_runs` table)

One execution of a definition over a corpus. Carries a frozen
`definition_snapshot_json`, the `corpus_json` selector, `status`
(`pending`|`running`|`complete`|`failed`), `unit_total`/`unit_scored`/
`unit_skipped` counters, the `aggregate_json` (`{value, numerator, denominator}`
for prevalence or `{value(mean), scored, skipped, histogram}` for numeric), and
an optional `baseline_run_id` for before/after compare lineage.

### EvalMeasureResult (`eval_measure_results` table)

One per-unit result: `unit_ref` (event_id|span_id|run_id), `status`
(`scored`|`skipped`|`error`), `score_numeric` / `score_bool`, a redacted
`reasoning` one-liner (llm only), a `degraded` flag, and `detail_json` (raw
detector/judge output or skip/error reason). Indexed by `eval_run_id`.

## Evidence References

Evidence references are stable pointers used by issues, proposals, checks, and
patch transactions.

```json
{
  "entity_type": "span",
  "entity_id": "span_001",
  "role": "failure",
  "quote_ref": "blob_quote_001",
  "note": "Tool call timed out after the handoff."
}
```

Allowed `entity_type` values:

- `run`
- `span`
- `task`
- `task_attempt`
- `handoff`
- `timeline_event`
- `issue`
- `check_run`
- `replay_run`
- `patch_transaction`
- `blob`

Semantic validation must confirm that each referenced entity exists in the
same profile unless the reference explicitly points to an imported external
artifact.

## Source Adapter Contract

Each source adapter must emit:

- normalized rows matching this spec
- raw payload references for audit/debugging
- adapter version
- source kind
- source external IDs when available
- a fixture file that demonstrates the mapping

Runs, spans, tasks, handoffs, and timeline events retain source lineage through
`source_id`; run detail resolves that source row and exposes its
`adapter_version`. Fixture-level compatibility coverage ingests two adapter
payload revisions for one profile and verifies each run still resolves to its
own source adapter version.

Adapter output must not create issues, insights, or proposals directly. It may
create timeline events and evidence rows that the learning engine uses later.

Adapters may provide inline payload siblings for canonical reference fields
when they have raw data but have not pre-registered a blob. During source-event
ingest, Kyoko materializes:

- `input_payload` -> `input_ref`
- `output_payload` -> `output_ref`
- `raw_payload` -> `raw_ref`
- `body_payload` -> `body_ref`
- `summary_payload` -> `summary_ref`
- `error_payload` -> `error_ref`
- `reason_payload` -> `reason_ref`
- handoff/timeline `payload` -> `payload_ref`

Inline payloads may be plain strings, JSON values, or wrapper objects with
`content`, `encoding`, `media_type`, `kind`, `retention_days`,
`retained_until`, and `metadata`. Kyoko rejects a row that provides both an
existing ref and the matching inline payload field, because that would make
provenance ambiguous.

## First Required Fixtures

The first gate fixtures are:

- [`../fixtures/source-events/hermes-news-research-minimal.json`](../fixtures/source-events/hermes-news-research-minimal.json)
- [`../fixtures/learning-proposals/valid-context-proposal.json`](../fixtures/learning-proposals/valid-context-proposal.json)
- [`../fixtures/learning-proposals/invalid-hallucinated-span.json`](../fixtures/learning-proposals/invalid-hallucinated-span.json)

## Open Decisions

- Exact SQL migration format.
- Whether IDs are generated by SQLite triggers, application code, or a shared ID
  utility.
- Blob storage path/hash format is implemented in
  [`../../kyoko/blobs.py`](../../kyoko/blobs.py): `<db-parent>/blobs/<sha-prefix>/<sha256>`
  with `blob_sha256_<sha-prefix>` registry ids.
- Whether check specs are first-class rows before they are linked to proposals.
- Whether `Issue` is created before `LearningProposal` or derived from it for
  operator-agent proposals.
