from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional


SCHEMA_VERSION = 32


class StorageError(Exception):
    """Raised when Kyoko storage operations fail."""


@dataclass(frozen=True)
class IngestReport:
    profile_id: str
    inserted_counts: dict[str, int]


@dataclass(frozen=True)
class DatabaseStatus:
    db_path: Path
    initialized: bool
    schema_version: Optional[int]
    counts: dict[str, int]
    migration_versions: tuple[int, ...] = ()


@dataclass(frozen=True)
class WalCheckpointReport:
    db_path: Path
    wal_path: Path
    mode: str
    busy: int
    log_frames: int
    checkpointed_frames: int
    wal_size_before: int
    wal_size_after: int

    def to_json(self) -> dict[str, Any]:
        return {
            "db_path": str(self.db_path),
            "wal_path": str(self.wal_path),
            "mode": self.mode,
            "busy": self.busy,
            "log_frames": self.log_frames,
            "checkpointed_frames": self.checkpointed_frames,
            "wal_size_before": self.wal_size_before,
            "wal_size_after": self.wal_size_after,
        }


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS profiles (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  root_path TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  display_name TEXT NOT NULL,
  status TEXT NOT NULL,
  adapter_version TEXT NOT NULL,
  config_json TEXT NOT NULL,
  capabilities_json TEXT NOT NULL,
  last_seen_at TEXT,
  FOREIGN KEY (profile_id) REFERENCES profiles(id)
);

CREATE TABLE IF NOT EXISTS agent_identities (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  external_id TEXT,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  role TEXT,
  model TEXT,
  workspace_path TEXT,
  metadata_json TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id),
  FOREIGN KEY (source_id) REFERENCES sources(id)
);

CREATE TABLE IF NOT EXISTS workflow_nodes (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  external_id TEXT,
  agent_identity_id TEXT,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id),
  FOREIGN KEY (source_id) REFERENCES sources(id),
  FOREIGN KEY (agent_identity_id) REFERENCES agent_identities(id)
);

CREATE TABLE IF NOT EXISTS queues (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  external_id TEXT,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id),
  FOREIGN KEY (source_id) REFERENCES sources(id)
);

CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  queue_id TEXT,
  external_id TEXT,
  title TEXT NOT NULL,
  body_ref TEXT,
  status TEXT NOT NULL,
  assignee_agent_identity_id TEXT,
  created_by_agent_identity_id TEXT,
  priority TEXT,
  workspace_kind TEXT,
  workspace_path TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  completed_at TEXT,
  metadata_json TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id),
  FOREIGN KEY (source_id) REFERENCES sources(id),
  FOREIGN KEY (queue_id) REFERENCES queues(id),
  FOREIGN KEY (assignee_agent_identity_id) REFERENCES agent_identities(id),
  FOREIGN KEY (created_by_agent_identity_id) REFERENCES agent_identities(id)
);

CREATE TABLE IF NOT EXISTS task_attempts (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  run_id TEXT,
  agent_identity_id TEXT NOT NULL,
  status TEXT NOT NULL,
  outcome TEXT,
  claim_token_hash TEXT,
  worker_pid INTEGER,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  last_heartbeat_at TEXT,
  summary_ref TEXT,
  metadata_json TEXT NOT NULL,
  error_ref TEXT,
  FOREIGN KEY (task_id) REFERENCES tasks(id),
  FOREIGN KEY (agent_identity_id) REFERENCES agent_identities(id)
);

CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  external_id TEXT,
  root_span_id TEXT,
  agent_identity_id TEXT,
  task_attempt_id TEXT,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  input_ref TEXT,
  output_ref TEXT,
  summary TEXT,
  metadata_json TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id),
  FOREIGN KEY (source_id) REFERENCES sources(id),
  FOREIGN KEY (agent_identity_id) REFERENCES agent_identities(id),
  FOREIGN KEY (task_attempt_id) REFERENCES task_attempts(id)
);

CREATE TABLE IF NOT EXISTS spans (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  external_id TEXT,
  parent_span_id TEXT,
  workflow_node_id TEXT,
  agent_identity_id TEXT,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  input_ref TEXT,
  output_ref TEXT,
  usage_json TEXT NOT NULL,
  attributes_json TEXT NOT NULL,
  raw_ref TEXT,
  FOREIGN KEY (run_id) REFERENCES runs(id),
  FOREIGN KEY (source_id) REFERENCES sources(id),
  FOREIGN KEY (parent_span_id) REFERENCES spans(id),
  FOREIGN KEY (workflow_node_id) REFERENCES workflow_nodes(id),
  FOREIGN KEY (agent_identity_id) REFERENCES agent_identities(id)
);

CREATE TABLE IF NOT EXISTS handoffs (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  from_agent_identity_id TEXT,
  to_agent_identity_id TEXT,
  from_workflow_node_id TEXT,
  to_workflow_node_id TEXT,
  from_task_id TEXT,
  to_task_id TEXT,
  run_id TEXT,
  span_id TEXT,
  kind TEXT NOT NULL,
  reason_ref TEXT,
  payload_ref TEXT,
  created_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id),
  FOREIGN KEY (source_id) REFERENCES sources(id),
  FOREIGN KEY (from_agent_identity_id) REFERENCES agent_identities(id),
  FOREIGN KEY (to_agent_identity_id) REFERENCES agent_identities(id),
  FOREIGN KEY (from_workflow_node_id) REFERENCES workflow_nodes(id),
  FOREIGN KEY (to_workflow_node_id) REFERENCES workflow_nodes(id),
  FOREIGN KEY (from_task_id) REFERENCES tasks(id),
  FOREIGN KEY (to_task_id) REFERENCES tasks(id),
  FOREIGN KEY (run_id) REFERENCES runs(id),
  FOREIGN KEY (span_id) REFERENCES spans(id)
);

CREATE TABLE IF NOT EXISTS timeline_events (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  at TEXT NOT NULL,
  agent_identity_id TEXT,
  payload_ref TEXT,
  metadata_json TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id),
  FOREIGN KEY (source_id) REFERENCES sources(id),
  FOREIGN KEY (agent_identity_id) REFERENCES agent_identities(id)
);

CREATE TABLE IF NOT EXISTS learning_proposals (
  id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  profile_id TEXT NOT NULL,
  producer_json TEXT NOT NULL,
  state TEXT NOT NULL,
  section TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  confidence REAL NOT NULL,
  evidence_refs_json TEXT NOT NULL,
  problem_json TEXT NOT NULL,
  insight TEXT NOT NULL,
  proposed_changes_json TEXT NOT NULL,
  gate_expectations_json TEXT NOT NULL,
  validation_errors_json TEXT NOT NULL,
  issue_id TEXT,                         -- v32: the skillbook entry (problem-phase) this proposal originates from
  created_at TEXT NOT NULL,
  updated_at TEXT,
  FOREIGN KEY (profile_id) REFERENCES profiles(id),
  FOREIGN KEY (issue_id) REFERENCES skills(id)
);

-- v32 (spec 0019): the skillbook entry is the single living unit, ACE-style. One row
-- holds the problem (`issue`/`body`), the evidence trail (`occurrences_json`), the
-- effectiveness feedback (helpful/harmful/neutral/used counts), and the learned fix
-- (`insight`) — and it evolves over runs (tag/mark_used/update in place). The separate
-- `issues` table is gone; its lifecycle folds onto these columns. The one divergence from
-- ACE: `active` stays 0 (never injected into a run) until the autonomy gate flips it on.
-- `status` is the lean lifecycle (surfaced | accepted | active | rolled_back | dismissed).
CREATE TABLE IF NOT EXISTS skills (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  proposal_id TEXT,                      -- proposal that authored the current insight
  section TEXT,                          -- context | harness (NULL until diagnosed)
  issue TEXT NOT NULL,                   -- the problem statement
  body TEXT,                             -- longer problem description (folded from issue.body)
  insight TEXT,                          -- the learned fix (NULL until proposed/applied)
  keywords_json TEXT NOT NULL DEFAULT '[]',
  occurrences_json TEXT NOT NULL DEFAULT '[]',
  helpful_count INTEGER NOT NULL DEFAULT 0,
  harmful_count INTEGER NOT NULL DEFAULT 0,
  neutral_count INTEGER NOT NULL DEFAULT 0,
  used_count INTEGER NOT NULL DEFAULT 0,        -- v32 (ACE): bumped when injected into a run
  active INTEGER NOT NULL DEFAULT 0,            -- injected only after the gate flips this on
  human_locked INTEGER NOT NULL DEFAULT 0,
  human_lock_reason TEXT,
  source_run_id TEXT,
  -- problem facet (folded from issues; `issue` above is the problem title/statement)
  status TEXT NOT NULL DEFAULT 'surfaced',
  category TEXT,
  severity TEXT,
  rank INTEGER,                          -- prioritization order (lower = more urgent)
  review_comment TEXT,                   -- free-text triage; never gated
  source TEXT,                           -- analysis | eval | llm_eval | manual
  root_cause TEXT,                       -- diagnosis narrative
  evidence_refs_json TEXT,
  affected_agent_identity_ids_json TEXT,
  affected_workflow_node_ids_json TEXT,
  affected_task_ids_json TEXT,
  affected_span_ids_json TEXT,
  proposal_ids_json TEXT,                -- all proposals over the entry's life (backlink)
  -- recurrence / deterministic dedup (a recurrence folds into THIS row)
  signature TEXT,
  recurrence_count INTEGER,
  -- gate + guard + regression (ride-along; no FK on evaluator/source-eval to avoid a cycle)
  accepted_at TEXT,                      -- gate-#1 acceptance watermark
  evaluator_id TEXT,                     -- the standing guard eval_definitions.id
  applied_at TEXT,                       -- gate-#2 apply watermark
  recurrence_count_at_apply INTEGER,     -- regression baseline
  auto_fix_attempts INTEGER,
  autonomy_blocked INTEGER,
  autonomy_blocked_reason TEXT,
  source_eval_definition_id TEXT,        -- v32: the eval/llm_eval metric that DETECTED this
  source_measure_run_id TEXT,            -- v32: the measurement run it was detected in
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id),
  FOREIGN KEY (proposal_id) REFERENCES learning_proposals(id),
  FOREIGN KEY (source_run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS skill_similarity_decisions (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  pair_key TEXT NOT NULL,                -- sorted "skill_id_a,skill_id_b"
  decision TEXT NOT NULL,               -- KEEP
  reasoning TEXT,
  similarity_at_decision REAL,
  decided_at TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id)
);

CREATE TABLE IF NOT EXISTS context_delivery_rules (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  proposal_id TEXT,
  target_json TEXT NOT NULL,
  rule_json TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  human_locked INTEGER NOT NULL DEFAULT 0,
  human_lock_reason TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id),
  FOREIGN KEY (proposal_id) REFERENCES learning_proposals(id)
);

CREATE TABLE IF NOT EXISTS skill_revisions (
  id TEXT PRIMARY KEY,
  skill_id TEXT NOT NULL,
  profile_id TEXT NOT NULL,
  proposal_id TEXT,
  operation TEXT NOT NULL,
  before_json TEXT,
  after_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (skill_id) REFERENCES skills(id),
  FOREIGN KEY (profile_id) REFERENCES profiles(id),
  FOREIGN KEY (proposal_id) REFERENCES learning_proposals(id)
);

CREATE TABLE IF NOT EXISTS context_delivery_rule_revisions (
  id TEXT PRIMARY KEY,
  rule_id TEXT NOT NULL,
  profile_id TEXT NOT NULL,
  proposal_id TEXT,
  operation TEXT NOT NULL,
  before_json TEXT,
  after_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (rule_id) REFERENCES context_delivery_rules(id),
  FOREIGN KEY (profile_id) REFERENCES profiles(id),
  FOREIGN KEY (proposal_id) REFERENCES learning_proposals(id)
);

-- v31 (spec 0018): two-mode autonomy. The L0-L3 trust ladder, the three-way
-- off/propose/autonomous per-section modes, and the check-as-gate fields are gone.
-- One global `mode` (hitl | autonomous) decides *who approves* each gate; autonomous
-- gate #1 fires on production `recurrence_count >= recurrence_threshold`; gate #2 is
-- post-hoc (auto-apply, then the guard monitor rolls back on a confirmed regression).
-- `allow_repo_patch` + the path fence remain the one hard capability guard.
CREATE TABLE IF NOT EXISTS autonomy_policies (
  profile_id TEXT PRIMARY KEY,
  mode TEXT NOT NULL,                         -- hitl | autonomous
  recurrence_threshold INTEGER NOT NULL,      -- gate-#1 N for autonomous
  regression_threshold INTEGER NOT NULL,      -- post-apply recurrences that confirm a regression
  auto_rollback_on_regression INTEGER NOT NULL,
  max_auto_fix_attempts INTEGER NOT NULL,     -- K rollbacks before escalating an issue to HITL
  allow_repo_patch INTEGER NOT NULL,          -- the one hard capability guard (off by default)
  allowed_paths_json TEXT NOT NULL,           -- repo-patch fence (inert unless allow_repo_patch)
  protected_paths_json TEXT NOT NULL,
  dirty_worktree_policy TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id)
);

CREATE TABLE IF NOT EXISTS harness_target_locks (
  profile_id TEXT NOT NULL,
  target_path TEXT NOT NULL,
  human_locked INTEGER NOT NULL,
  reason TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (profile_id, target_path),
  FOREIGN KEY (profile_id) REFERENCES profiles(id)
);

CREATE TABLE IF NOT EXISTS payload_blobs (
  id TEXT PRIMARY KEY,
  profile_id TEXT,
  kind TEXT NOT NULL,
  media_type TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  path TEXT NOT NULL,
  preview TEXT,
  redaction_mode TEXT NOT NULL,
  retained_until TEXT,
  metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id)
);

CREATE TABLE IF NOT EXISTS check_specs (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  proposal_id TEXT,
  name TEXT NOT NULL,
  check_type TEXT NOT NULL,
  trust_level TEXT NOT NULL,
  side_effect_mode TEXT NOT NULL,
  target_json TEXT NOT NULL,
  definition_json TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id),
  FOREIGN KEY (proposal_id) REFERENCES learning_proposals(id)
);

CREATE TABLE IF NOT EXISTS check_locks (
  profile_id TEXT NOT NULL,
  check_spec_id TEXT NOT NULL,
  human_locked INTEGER NOT NULL,
  reason TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (profile_id, check_spec_id),
  FOREIGN KEY (profile_id) REFERENCES profiles(id),
  FOREIGN KEY (check_spec_id) REFERENCES check_specs(id)
);

CREATE TABLE IF NOT EXISTS replay_runs (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  proposal_id TEXT,
  check_spec_id TEXT,
  source_run_id TEXT,
  task_attempt_id TEXT,
  mode TEXT NOT NULL,
  side_effect_mode TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  input_ref TEXT,
  output_ref TEXT,
  result_json TEXT NOT NULL,
  artifact_refs_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id),
  FOREIGN KEY (proposal_id) REFERENCES learning_proposals(id),
  FOREIGN KEY (check_spec_id) REFERENCES check_specs(id),
  FOREIGN KEY (source_run_id) REFERENCES runs(id),
  FOREIGN KEY (task_attempt_id) REFERENCES task_attempts(id)
);

CREATE TABLE IF NOT EXISTS check_runs (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  check_spec_id TEXT NOT NULL,
  proposal_id TEXT,
  replay_run_id TEXT,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  result_json TEXT NOT NULL,
  artifact_refs_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id),
  FOREIGN KEY (check_spec_id) REFERENCES check_specs(id),
  FOREIGN KEY (proposal_id) REFERENCES learning_proposals(id),
  FOREIGN KEY (replay_run_id) REFERENCES replay_runs(id)
);

CREATE TABLE IF NOT EXISTS replay_adapters (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  name TEXT NOT NULL,
  command_json TEXT NOT NULL,
  output_dir TEXT,
  default_mode TEXT NOT NULL,
  default_side_effect_mode TEXT NOT NULL,
  timeout_seconds INTEGER NOT NULL,
  enabled INTEGER NOT NULL,
  metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id)
);

CREATE TABLE IF NOT EXISTS operator_adapters (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  name TEXT NOT NULL,
  operator_kind TEXT NOT NULL,
  command_json TEXT NOT NULL,
  output_dir TEXT,
  timeout_seconds INTEGER NOT NULL,
  enabled INTEGER NOT NULL,
  metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id)
);

CREATE TABLE IF NOT EXISTS operator_runs (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  adapter_id TEXT,
  operator_label TEXT NOT NULL,
  operator_kind TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  evidence_ref TEXT,
  prompt_ref TEXT,
  raw_output_ref TEXT,
  proposal_id TEXT,
  error TEXT,
  metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id),
  FOREIGN KEY (adapter_id) REFERENCES operator_adapters(id),
  FOREIGN KEY (proposal_id) REFERENCES learning_proposals(id)
);

CREATE TABLE IF NOT EXISTS patch_transactions (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  proposal_id TEXT NOT NULL,
  status TEXT NOT NULL,
  patch_kind TEXT NOT NULL,
  target_paths_json TEXT NOT NULL,
  diff_ref TEXT,
  command_plan_json TEXT NOT NULL,
  side_effect_mode TEXT NOT NULL,
  rollback_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id),
  FOREIGN KEY (proposal_id) REFERENCES learning_proposals(id)
);

CREATE TABLE IF NOT EXISTS live_events (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  source_id TEXT,
  run_id TEXT,
  span_id TEXT,
  seq INTEGER NOT NULL,
  kind TEXT NOT NULL,
  content_preview TEXT,
  content_ref TEXT,
  at TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id)
);

CREATE TABLE IF NOT EXISTS mcp_log (
  id TEXT PRIMARY KEY,
  profile_id TEXT,
  session_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  direction TEXT NOT NULL,
  method TEXT,
  tool_name TEXT,
  params_preview TEXT,
  params_ref TEXT,
  result_preview TEXT,
  result_ref TEXT,
  is_error INTEGER NOT NULL DEFAULT 0,
  error_code INTEGER,
  duration_ms REAL,
  client_id TEXT,
  at TEXT NOT NULL,
  metadata_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS annotations (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  run_id TEXT,
  span_id TEXT,
  kind TEXT NOT NULL,
  note TEXT,
  source TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT,
  metadata_json TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id)
);

CREATE INDEX IF NOT EXISTS idx_sources_profile_id ON sources(profile_id);
CREATE INDEX IF NOT EXISTS idx_runs_profile_id ON runs(profile_id);
CREATE INDEX IF NOT EXISTS idx_spans_run_id ON spans(run_id);
CREATE INDEX IF NOT EXISTS idx_tasks_profile_id ON tasks(profile_id);
CREATE INDEX IF NOT EXISTS idx_task_attempts_task_id ON task_attempts(task_id);
CREATE INDEX IF NOT EXISTS idx_handoffs_profile_id ON handoffs(profile_id);
CREATE INDEX IF NOT EXISTS idx_timeline_events_profile_id ON timeline_events(profile_id);
CREATE INDEX IF NOT EXISTS idx_learning_proposals_profile_id ON learning_proposals(profile_id);
CREATE INDEX IF NOT EXISTS idx_skills_profile_id ON skills(profile_id);
CREATE INDEX IF NOT EXISTS idx_skill_similarity_decisions_profile_id ON skill_similarity_decisions(profile_id);
CREATE INDEX IF NOT EXISTS idx_context_delivery_rules_profile_id ON context_delivery_rules(profile_id);
CREATE INDEX IF NOT EXISTS idx_context_delivery_rules_proposal_id ON context_delivery_rules(proposal_id);
CREATE INDEX IF NOT EXISTS idx_skill_revisions_skill_id ON skill_revisions(skill_id);
CREATE INDEX IF NOT EXISTS idx_skill_revisions_proposal_id ON skill_revisions(proposal_id);
CREATE INDEX IF NOT EXISTS idx_context_delivery_rule_revisions_rule_id
  ON context_delivery_rule_revisions(rule_id);
CREATE INDEX IF NOT EXISTS idx_context_delivery_rule_revisions_proposal_id
  ON context_delivery_rule_revisions(proposal_id);
CREATE INDEX IF NOT EXISTS idx_payload_blobs_profile_id ON payload_blobs(profile_id);
CREATE INDEX IF NOT EXISTS idx_payload_blobs_sha256 ON payload_blobs(sha256);
CREATE INDEX IF NOT EXISTS idx_payload_blobs_retained_until ON payload_blobs(retained_until);
CREATE INDEX IF NOT EXISTS idx_harness_target_locks_profile_id ON harness_target_locks(profile_id);
CREATE INDEX IF NOT EXISTS idx_check_specs_profile_id ON check_specs(profile_id);
CREATE INDEX IF NOT EXISTS idx_check_locks_profile_id ON check_locks(profile_id);
CREATE INDEX IF NOT EXISTS idx_check_runs_check_spec_id ON check_runs(check_spec_id);
CREATE INDEX IF NOT EXISTS idx_replay_runs_check_spec_id ON replay_runs(check_spec_id);
CREATE INDEX IF NOT EXISTS idx_replay_adapters_profile_id ON replay_adapters(profile_id);
CREATE INDEX IF NOT EXISTS idx_operator_adapters_profile_id ON operator_adapters(profile_id);
CREATE INDEX IF NOT EXISTS idx_operator_runs_profile_id ON operator_runs(profile_id);
CREATE INDEX IF NOT EXISTS idx_operator_runs_adapter_id ON operator_runs(adapter_id);
CREATE INDEX IF NOT EXISTS idx_patch_transactions_profile_id ON patch_transactions(profile_id);
CREATE INDEX IF NOT EXISTS idx_patch_transactions_proposal_id ON patch_transactions(proposal_id);
CREATE INDEX IF NOT EXISTS idx_live_events_profile_id ON live_events(profile_id);
CREATE INDEX IF NOT EXISTS idx_live_events_run_id ON live_events(run_id);
CREATE INDEX IF NOT EXISTS idx_live_events_at ON live_events(at);
CREATE INDEX IF NOT EXISTS idx_mcp_log_session_id ON mcp_log(session_id);
CREATE INDEX IF NOT EXISTS idx_mcp_log_at ON mcp_log(at);
CREATE INDEX IF NOT EXISTS idx_mcp_log_profile_id ON mcp_log(profile_id);
CREATE INDEX IF NOT EXISTS idx_annotations_profile_id ON annotations(profile_id);
CREATE INDEX IF NOT EXISTS idx_annotations_run_id ON annotations(run_id);

-- v32 (spec 0019): the `issues` table is gone. Its lifecycle folded onto `skills`
-- (the unified living skillbook entry above). "Issues" are now just skill entries in a
-- problem-phase status (a lens), not a separate entity.

-- v26: measurement plane (evidence only). `eval` = deterministic Python
-- detector over a trace corpus; `llm_eval` = LLM-as-judge template. Neither
-- writes a check_run, mutates a skill, or edits a harness file. Discriminated
-- by `kind` (python | llm). See docs/specs/0014, 0015.
CREATE TABLE IF NOT EXISTS eval_definitions (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  kind TEXT NOT NULL,                   -- python | llm
  name TEXT NOT NULL,
  version INTEGER NOT NULL,
  partner TEXT,                         -- "ragas" for ported llm_evals, else NULL
  source TEXT NOT NULL,                 -- bundled | user
  unit_type TEXT NOT NULL,              -- event | llm_span | run
  output_type TEXT NOT NULL,            -- numeric | boolean
  direction TEXT NOT NULL,              -- lower_is_better | higher_is_better | true_is_notable | false_is_notable
  problem_statement TEXT,
  detector_ref TEXT,                    -- python: blob sha of detector .py (NULL for llm)
  prompt TEXT,                          -- llm only
  vars_json TEXT,                       -- llm only
  bindings_json TEXT,                   -- llm only
  output_json TEXT,                     -- llm only: {type, range}
  severity_bands_json TEXT,
  status TEXT NOT NULL,                 -- active | archived
  issue_id TEXT,                        -- v32: the skillbook entry this evaluator guards (NULL for library evals)
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id),
  FOREIGN KEY (issue_id) REFERENCES skills(id)
);

CREATE TABLE IF NOT EXISTS eval_measure_runs (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  eval_definition_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  definition_snapshot_json TEXT NOT NULL,   -- frozen def used this run
  corpus_json TEXT NOT NULL,                -- selector
  unit_type TEXT NOT NULL,
  status TEXT NOT NULL,                     -- pending | running | complete | failed
  unit_total INTEGER NOT NULL DEFAULT 0,
  unit_scored INTEGER NOT NULL DEFAULT 0,
  unit_skipped INTEGER NOT NULL DEFAULT 0,
  aggregate_json TEXT,                      -- {value, numerator, denominator, mean?, ...}
  baseline_run_id TEXT,                     -- compare lineage (optional)
  started_at TEXT,
  ended_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id),
  FOREIGN KEY (eval_definition_id) REFERENCES eval_definitions(id),
  FOREIGN KEY (baseline_run_id) REFERENCES eval_measure_runs(id)
);

CREATE TABLE IF NOT EXISTS eval_measure_results (
  id TEXT PRIMARY KEY,
  eval_run_id TEXT NOT NULL,
  profile_id TEXT NOT NULL,
  unit_type TEXT NOT NULL,
  unit_ref TEXT NOT NULL,               -- event_id | span_id | run_id
  status TEXT NOT NULL,                 -- scored | skipped | error
  score_numeric REAL,                   -- llm numeric
  score_bool INTEGER,                   -- python has_problem, or llm boolean
  reasoning TEXT,                       -- llm only, redacted one-liner
  degraded INTEGER NOT NULL DEFAULT 0,
  detail_json TEXT NOT NULL,            -- raw detector/judge output, skip/err reason
  created_at TEXT NOT NULL,
  FOREIGN KEY (eval_run_id) REFERENCES eval_measure_runs(id),
  FOREIGN KEY (profile_id) REFERENCES profiles(id)
);

CREATE INDEX IF NOT EXISTS idx_eval_definitions_profile_id ON eval_definitions(profile_id);
CREATE INDEX IF NOT EXISTS idx_eval_definitions_issue_id ON eval_definitions(issue_id);
CREATE INDEX IF NOT EXISTS idx_eval_measure_runs_profile_id ON eval_measure_runs(profile_id);
CREATE INDEX IF NOT EXISTS idx_eval_measure_runs_definition_id ON eval_measure_runs(eval_definition_id);
CREATE INDEX IF NOT EXISTS eval_measure_results_run ON eval_measure_results(eval_run_id);

-- v28: recurring analysis schedules. A local single-user convenience (SCOPE: the
-- scheduler is a background thread inside `kyoko serve`; rows persist so they survive
-- restarts but only fire while the server runs). Each schedule re-imports new traces
-- from a connected source (openclaw/hermes) and runs that same operator over the new
-- runs, through the normal autonomy gate. `watermark` is the max run `started_at`
-- already analyzed; only newer runs are analyzed on the next fire.
CREATE TABLE IF NOT EXISTS analysis_schedules (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  analyzer_kind TEXT NOT NULL,          -- openclaw | hermes
  adapter_id TEXT,                      -- operator adapter that does the analysis
  source_kind TEXT,                     -- openclaw_sessions | hermes_kanban
  source_path TEXT,                     -- path re-imported on each fire (idempotent)
  refresh_import INTEGER NOT NULL DEFAULT 1,
  interval_hours INTEGER NOT NULL DEFAULT 24,
  at_time TEXT,                         -- 'HH:MM' local anchor, NULL = interval-only
  enabled INTEGER NOT NULL DEFAULT 1,
  run_autonomy INTEGER NOT NULL DEFAULT 1,
  watermark TEXT,                       -- last analyzed run cutoff (ISO)
  last_run_at TEXT,
  next_run_at TEXT,
  last_status TEXT,
  last_operator_run_id TEXT,
  last_error TEXT,
  metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id)
);
CREATE INDEX IF NOT EXISTS idx_analysis_schedules_profile_id ON analysis_schedules(profile_id);
CREATE INDEX IF NOT EXISTS idx_analysis_schedules_enabled ON analysis_schedules(enabled);
"""


# v24: per-span full-text search index (FTS5). Created separately from SCHEMA_SQL
# because `CREATE VIRTUAL TABLE ... USING fts5` raises on sqlite builds without the
# FTS5 module; we never want that to abort the whole schema script. ``span_id`` and
# ``run_id`` are UNINDEXED (stored, returned, but not tokenized) so search_run can
# filter by run and map matches back to spans. ``text`` carries the searchable body
# (span name + JSON attributes + payload-blob previews), one document per span.
SPANS_FTS_TABLE = "spans_fts"
SPANS_FTS_SQL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS spans_fts USING fts5("
    "span_id UNINDEXED, run_id UNINDEXED, text, "
    "tokenize='unicode61 remove_diacritics 2')"
)


TABLE_COLUMNS = {
    "profiles": ["id", "name", "root_path", "status", "created_at", "updated_at"],
    "sources": [
        "id",
        "profile_id",
        "kind",
        "display_name",
        "status",
        "adapter_version",
        "config_json",
        "capabilities_json",
        "last_seen_at",
    ],
    "agent_identities": [
        "id",
        "profile_id",
        "source_id",
        "external_id",
        "name",
        "kind",
        "role",
        "model",
        "workspace_path",
        "metadata_json",
    ],
    "workflow_nodes": [
        "id",
        "profile_id",
        "source_id",
        "external_id",
        "agent_identity_id",
        "kind",
        "name",
        "metadata_json",
    ],
    "queues": ["id", "profile_id", "source_id", "external_id", "name", "kind", "metadata_json"],
    "tasks": [
        "id",
        "profile_id",
        "source_id",
        "queue_id",
        "external_id",
        "title",
        "body_ref",
        "status",
        "assignee_agent_identity_id",
        "created_by_agent_identity_id",
        "priority",
        "workspace_kind",
        "workspace_path",
        "created_at",
        "started_at",
        "completed_at",
        "metadata_json",
    ],
    "task_attempts": [
        "id",
        "task_id",
        "run_id",
        "agent_identity_id",
        "status",
        "outcome",
        "claim_token_hash",
        "worker_pid",
        "started_at",
        "ended_at",
        "last_heartbeat_at",
        "summary_ref",
        "metadata_json",
        "error_ref",
    ],
    "runs": [
        "id",
        "profile_id",
        "source_id",
        "external_id",
        "root_span_id",
        "agent_identity_id",
        "task_attempt_id",
        "status",
        "started_at",
        "ended_at",
        "input_ref",
        "output_ref",
        "summary",
        "metadata_json",
    ],
    "spans": [
        "id",
        "run_id",
        "source_id",
        "external_id",
        "parent_span_id",
        "workflow_node_id",
        "agent_identity_id",
        "kind",
        "name",
        "status",
        "started_at",
        "ended_at",
        "input_ref",
        "output_ref",
        "usage_json",
        "attributes_json",
        "raw_ref",
    ],
    "handoffs": [
        "id",
        "profile_id",
        "source_id",
        "from_agent_identity_id",
        "to_agent_identity_id",
        "from_workflow_node_id",
        "to_workflow_node_id",
        "from_task_id",
        "to_task_id",
        "run_id",
        "span_id",
        "kind",
        "reason_ref",
        "payload_ref",
        "created_at",
        "metadata_json",
    ],
    "timeline_events": [
        "id",
        "profile_id",
        "source_id",
        "entity_type",
        "entity_id",
        "kind",
        "at",
        "agent_identity_id",
        "payload_ref",
        "metadata_json",
    ],
}


FIXTURE_COLLECTIONS = [
    ("sources", "sources"),
    ("agent_identities", "agent_identities"),
    ("workflow_nodes", "workflow_nodes"),
    ("queues", "queues"),
    ("tasks", "tasks"),
    ("task_attempts", "task_attempts"),
    ("runs", "runs"),
    ("spans", "spans"),
    ("handoffs", "handoffs"),
    ("timeline_events", "timeline_events"),
]

INLINE_PAYLOAD_FIELDS = {
    "tasks": {"body_ref": "body_payload"},
    "task_attempts": {
        "summary_ref": "summary_payload",
        "error_ref": "error_payload",
    },
    "runs": {
        "input_ref": "input_payload",
        "output_ref": "output_payload",
    },
    "spans": {
        "input_ref": "input_payload",
        "output_ref": "output_payload",
        "raw_ref": "raw_payload",
    },
    "handoffs": {
        "reason_ref": "reason_payload",
        "payload_ref": "payload",
    },
    "timeline_events": {"payload_ref": "payload"},
}
INLINE_PAYLOAD_WRAPPER_KEYS = {
    "content",
    "encoding",
    "kind",
    "media_type",
    "metadata",
    "redaction_mode",
    "retained_until",
    "retention_days",
}


STATUS_TABLES = [
    "profiles",
    "sources",
    "agent_identities",
    "workflow_nodes",
    "queues",
    "tasks",
    "task_attempts",
    "runs",
    "spans",
    "handoffs",
    "timeline_events",
    "learning_proposals",
    "skills",
    "context_delivery_rules",
    "skill_revisions",
    "context_delivery_rule_revisions",
    "autonomy_policies",
    "harness_target_locks",
    "payload_blobs",
    "check_specs",
    "check_locks",
    "check_runs",
    "replay_runs",
    "replay_adapters",
    "operator_adapters",
    "operator_runs",
    "patch_transactions",
    "skill_similarity_decisions",
    "analysis_schedules",
]


def default_db_path() -> Path:
    return Path.home() / ".kyoko" / "kyoko.db"


def connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def initialize_database(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as connection:
        existing_versions = _schema_migration_versions(connection)
        existing_user_version = _database_user_version(connection)
        existing_version = max((existing_user_version, *existing_versions))
        if existing_version > SCHEMA_VERSION:
            raise StorageError(f"database_schema_too_new:{existing_version}:supported:{SCHEMA_VERSION}")
        # v25: the apply-check `eval` concept is renamed to `check`. Rename the
        # tables/columns IN PLACE (preserving rows) BEFORE executescript, so the
        # `CREATE TABLE IF NOT EXISTS check_*` statements below become no-ops on a
        # migrated DB instead of creating empty check_* tables beside populated
        # eval_* ones. Fresh DBs have no eval_* tables, so every step is a no-op.
        _rename_table_if_needed(connection, "eval_specs", "check_specs")
        _rename_table_if_needed(connection, "eval_spec_locks", "check_locks")
        _rename_table_if_needed(connection, "eval_runs", "check_runs")
        _rename_column_if_needed(connection, "check_specs", "eval_type", "check_type")
        _rename_column_if_needed(connection, "check_locks", "eval_spec_id", "check_spec_id")
        _rename_column_if_needed(connection, "check_runs", "eval_spec_id", "check_spec_id")
        _rename_column_if_needed(connection, "replay_runs", "eval_spec_id", "check_spec_id")
        # v31 (spec 0018): two-mode autonomy. `autonomy_policies` is reshaped (mode +
        # recurrence/regression thresholds replace the per-section modes + trust-level
        # fields). Pre-prod: DROP and let executescript recreate the new shape, then
        # re-seed defaults for existing profiles below. Version-guarded so this destructive
        # step runs once on upgrade, NOT on every initialize_database (which would wipe the
        # operator's mode/threshold settings on every connect).
        if existing_version < 31:
            connection.execute("DROP TABLE IF EXISTS autonomy_policies")
        # v32 (spec 0019): the `issues` table folds into `skills` (the unified living
        # skillbook entry). Pre-prod, no data migration — DROP and let `skills` carry the
        # lifecycle. Drop the issue indexes too. Existing pre-v32 DBs should be recreated.
        if existing_version < 32:
            for _issue_index in (
                "idx_issues_profile_id",
                "idx_issues_status",
                "idx_issues_section",
                "idx_issues_evaluator_id",
                "idx_issues_signature",
            ):
                connection.execute(f"DROP INDEX IF EXISTS {_issue_index}")
            connection.execute("DROP TABLE IF EXISTS issues")
        for _old_index in (
            "idx_eval_specs_profile_id",
            "idx_eval_spec_locks_profile_id",
            "idx_eval_runs_eval_spec_id",
            "idx_replay_runs_eval_spec_id",
        ):
            connection.execute(f"DROP INDEX IF EXISTS {_old_index}")
        connection.executescript(SCHEMA_SQL)
        # v28: link operator_runs back to the schedule that triggered them (if any)
        # and record the "new traces" cutoff that scoped the analysis.
        _ensure_column(connection, "operator_runs", "schedule_id", "schedule_id TEXT")
        _ensure_column(connection, "operator_runs", "analyzed_since", "analyzed_since TEXT")
        _ensure_column(connection, "skills", "human_lock_reason", "human_lock_reason TEXT")
        _ensure_column(
            connection,
            "context_delivery_rules",
            "human_lock_reason",
            "human_lock_reason TEXT",
        )
        _ensure_column(connection, "eval_definitions", "issue_id", "issue_id TEXT")
        _ensure_column(connection, "learning_proposals", "issue_id", "issue_id TEXT")
        # v32 (spec 0019): the issue lifecycle folds onto `skills` (the unified living
        # skillbook entry). Additive/nullable columns carry the problem facet, the gate/guard
        # watermarks, the recurrence dedup, ACE's `used_count`, and the durable source-eval
        # link. The `active` default flipped to 0 (an entry is injected only after the gate);
        # `status`/`section`/`insight` relaxed to nullable for problem-phase entries.
        for _col, _ddl in (
            ("body", "body TEXT"),
            ("used_count", "used_count INTEGER NOT NULL DEFAULT 0"),
            ("status", "status TEXT NOT NULL DEFAULT 'surfaced'"),
            ("category", "category TEXT"),
            ("severity", "severity TEXT"),
            ("rank", "rank INTEGER"),
            ("review_comment", "review_comment TEXT"),
            ("source", "source TEXT"),
            ("root_cause", "root_cause TEXT"),
            ("evidence_refs_json", "evidence_refs_json TEXT"),
            ("affected_agent_identity_ids_json", "affected_agent_identity_ids_json TEXT"),
            ("affected_workflow_node_ids_json", "affected_workflow_node_ids_json TEXT"),
            ("affected_task_ids_json", "affected_task_ids_json TEXT"),
            ("affected_span_ids_json", "affected_span_ids_json TEXT"),
            ("proposal_ids_json", "proposal_ids_json TEXT"),
            ("signature", "signature TEXT"),
            ("recurrence_count", "recurrence_count INTEGER"),
            ("accepted_at", "accepted_at TEXT"),
            ("evaluator_id", "evaluator_id TEXT"),
            ("applied_at", "applied_at TEXT"),
            ("recurrence_count_at_apply", "recurrence_count_at_apply INTEGER"),
            ("auto_fix_attempts", "auto_fix_attempts INTEGER"),
            ("autonomy_blocked", "autonomy_blocked INTEGER"),
            ("autonomy_blocked_reason", "autonomy_blocked_reason TEXT"),
            ("source_eval_definition_id", "source_eval_definition_id TEXT"),
            ("source_measure_run_id", "source_measure_run_id TEXT"),
        ):
            _ensure_column(connection, "skills", _col, _ddl)
        # Indexes over v32-added skill columns — created here (not in SCHEMA_SQL) so they
        # bind AFTER the columns exist on a migrated legacy `skills` table.
        for _idx_sql in (
            "CREATE INDEX IF NOT EXISTS idx_skills_status ON skills(status)",
            "CREATE INDEX IF NOT EXISTS idx_skills_section ON skills(section)",
            "CREATE INDEX IF NOT EXISTS idx_skills_signature ON skills(signature)",
            "CREATE INDEX IF NOT EXISTS idx_skills_evaluator_id ON skills(evaluator_id)",
        ):
            connection.execute(_idx_sql)
        # v31: re-seed the reshaped autonomy_policies for any pre-existing profiles
        # (the DROP above removed their old-shape rows).
        if existing_version < 31:
            for _profile_row in connection.execute("SELECT id FROM profiles").fetchall():
                _ensure_default_autonomy_policy(connection, str(_profile_row["id"]))
        # v21 (SCOPE simplification): redaction collapses to a single global
        # "redact on export" default; the per-profile policy table and the audit
        # ledger are removed. Drop them for DBs created before v21.
        connection.execute("DROP TABLE IF EXISTS redaction_audit_events")
        connection.execute("DROP TABLE IF EXISTS redaction_policies")
        # v22 (SCOPE simplification): retention collapses to a manual
        # --older-than-days prune; the per-profile policy table is removed.
        connection.execute("DROP TABLE IF EXISTS retention_policies")
        # v24: per-span FTS5 search index. Additive and best-effort — if this sqlite
        # build lacks FTS5, search_run falls back to the linear scan and nothing here
        # raises. For pre-v24 DBs (index absent/empty), backfill from existing spans.
        if fts5_available(connection):
            connection.execute(SPANS_FTS_SQL)
            _backfill_spans_fts(connection)
        connection.executemany(
            "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
            [(version,) for version in range(1, SCHEMA_VERSION + 1)],
        )
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def ingest_source_fixture(db_path: Path, fixture_path: Path) -> IngestReport:
    return ingest_source_payload(
        db_path=db_path,
        fixture=_load_json(fixture_path),
        source_label=str(fixture_path),
    )


def ingest_source_json(db_path: Path, payload_path: Path) -> IngestReport:
    return ingest_source_payload(
        db_path=db_path,
        fixture=_load_json(payload_path),
        source_label=str(payload_path),
    )


def ingest_source_payload(
    *,
    db_path: Path,
    fixture: dict[str, Any],
    source_label: str,
) -> IngestReport:
    initialize_database(db_path)
    profile = fixture.get("profile")
    if not isinstance(profile, dict):
        raise StorageError(f"{source_label}: missing profile object")
    profile_id = profile.get("id")
    if not isinstance(profile_id, str):
        raise StorageError(f"{source_label}: profile id must be a string")

    with connect(db_path) as connection:
        _upsert_row(connection, "profiles", profile)
        _ensure_default_autonomy_policy(connection, str(profile["id"]))
        inserted_counts = {"profiles": 1}
        fixture, materialized_blob_count = _materialize_inline_payloads(
            connection=connection,
            db_path=db_path,
            fixture=fixture,
            profile_id=profile_id,
            source_label=source_label,
        )
        if materialized_blob_count:
            inserted_counts["payload_blobs"] = materialized_blob_count

        # Runs and task_attempts reference each other in the canonical model.
        # Insert task attempts with no run link first, insert runs, then update
        # the task attempts with their run ids.
        deferred_task_attempt_runs = {
            row["id"]: row.get("run_id")
            for row in fixture.get("task_attempts", [])
            if isinstance(row, dict)
        }

        for collection_name, table in FIXTURE_COLLECTIONS:
            rows = fixture.get(collection_name, [])
            if not isinstance(rows, list):
                raise StorageError(f"{source_label}: {collection_name} must be a list")
            if table == "task_attempts":
                rows = [{**row, "run_id": None} for row in rows if isinstance(row, dict)]
            for row in rows:
                if not isinstance(row, dict):
                    raise StorageError(f"{source_label}: {collection_name} contains non-object row")
                _upsert_row(connection, table, row)
                if table == "spans" and isinstance(row.get("id"), str):
                    # Write-through the per-span FTS index; payload-blob previews
                    # this span references were materialised earlier in this txn.
                    index_span_fts(connection, str(row["id"]))
            inserted_counts[table] = len(rows)

        for attempt_id, run_id in deferred_task_attempt_runs.items():
            if run_id is not None:
                connection.execute(
                    "UPDATE task_attempts SET run_id = ? WHERE id = ?",
                    (run_id, attempt_id),
                )
    return IngestReport(profile_id=profile_id, inserted_counts=inserted_counts)


def ensure_default_autonomy_policy(db_path: Path, profile_id: str) -> None:
    initialize_database(db_path)
    with connect(db_path) as connection:
        _ensure_default_autonomy_policy(connection, profile_id)


def get_database_status(db_path: Path) -> DatabaseStatus:
    if not db_path.exists():
        return DatabaseStatus(
            db_path=db_path,
            initialized=False,
            schema_version=None,
            counts={table: 0 for table in STATUS_TABLES},
            migration_versions=(),
        )

    with connect(db_path) as connection:
        try:
            version_row = connection.execute(
                "SELECT MAX(version) AS version FROM schema_migrations"
            ).fetchone()
        except sqlite3.OperationalError:
            return DatabaseStatus(
                db_path=db_path,
                initialized=False,
                schema_version=None,
                counts={table: 0 for table in STATUS_TABLES},
                migration_versions=(),
            )
        migration_versions = _schema_migration_versions(connection)

        counts = {}
        for table in STATUS_TABLES:
            counts[table] = _table_count(connection, table)

    version = version_row["version"] if version_row is not None else None
    return DatabaseStatus(
        db_path=db_path,
        initialized=version is not None,
        schema_version=version,
        counts=counts,
        migration_versions=migration_versions,
    )


def checkpoint_database(db_path: Path, *, mode: str = "PASSIVE") -> WalCheckpointReport:
    selected_mode = mode.upper()
    if selected_mode not in {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}:
        raise StorageError(f"unsupported_wal_checkpoint_mode:{mode}")
    initialize_database(db_path)
    wal_path = Path(f"{db_path}-wal")
    wal_size_before = _file_size(wal_path)
    with connect(db_path) as connection:
        row = connection.execute(f"PRAGMA wal_checkpoint({selected_mode})").fetchone()
    wal_size_after = _file_size(wal_path)
    busy = int(row[0]) if row is not None else 0
    log_frames = int(row[1]) if row is not None else 0
    checkpointed_frames = int(row[2]) if row is not None else 0
    return WalCheckpointReport(
        db_path=db_path,
        wal_path=wal_path,
        mode=selected_mode,
        busy=busy,
        log_frames=log_frames,
        checkpointed_frames=checkpointed_frames,
        wal_size_before=wal_size_before,
        wal_size_after=wal_size_after,
    )


def status_to_json(status: DatabaseStatus) -> dict[str, Any]:
    return {
        "db_path": str(status.db_path),
        "initialized": status.initialized,
        "schema_version": status.schema_version,
        "migration_versions": list(status.migration_versions),
        "counts": status.counts,
    }


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise StorageError(f"{path}: file not found") from exc
    except json.JSONDecodeError as exc:
        raise StorageError(f"{path}: invalid JSON: {exc}") from exc


def _materialize_inline_payloads(
    *,
    connection: sqlite3.Connection,
    db_path: Path,
    fixture: dict[str, Any],
    profile_id: str,
    source_label: str,
) -> tuple[dict[str, Any], int]:
    materialized_fixture = dict(fixture)
    materialized_count = 0
    for collection_name, ref_fields in INLINE_PAYLOAD_FIELDS.items():
        rows = fixture.get(collection_name, [])
        if not isinstance(rows, list):
            continue
        next_rows = []
        changed = False
        for row in rows:
            if not isinstance(row, dict):
                next_rows.append(row)
                continue
            next_row = dict(row)
            row_id = str(next_row.get("id") or "unknown")
            for ref_field, payload_field in ref_fields.items():
                if payload_field not in next_row or next_row.get(payload_field) is None:
                    continue
                if next_row.get(ref_field):
                    raise StorageError(
                        f"{source_label}: {collection_name}.{row_id}.{payload_field}_conflicts_with_{ref_field}"
                    )
                blob_id = _put_inline_payload_blob(
                    connection=connection,
                    db_path=db_path,
                    profile_id=profile_id,
                    collection_name=collection_name,
                    row_id=row_id,
                    ref_field=ref_field,
                    payload_field=payload_field,
                    payload=next_row[payload_field],
                    source_label=source_label,
                )
                next_row[ref_field] = blob_id
                changed = True
                materialized_count += 1
            next_rows.append(next_row)
        if changed:
            materialized_fixture[collection_name] = next_rows
    return materialized_fixture, materialized_count


def _put_inline_payload_blob(
    *,
    connection: sqlite3.Connection,
    db_path: Path,
    profile_id: str,
    collection_name: str,
    row_id: str,
    ref_field: str,
    payload_field: str,
    payload: Any,
    source_label: str,
) -> str:
    blob = _inline_payload_blob_input(
        payload,
        default_kind=f"source_{collection_name}_{ref_field.removesuffix('_ref')}",
    )
    sha256 = hashlib.sha256(blob["data"]).hexdigest()
    blob_id = f"blob_sha256_{sha256[:32]}"
    blob_path = db_path.parent / "blobs" / sha256[:2] / sha256
    blob_path.parent.mkdir(parents=True, exist_ok=True)
    if not blob_path.exists():
        blob_path.write_bytes(blob["data"])

    now = utc_now()
    occurrence = {
        "source_label": source_label,
        "collection": collection_name,
        "row_id": row_id,
        "ref_field": ref_field,
        "payload_field": payload_field,
    }
    existing_metadata = _existing_blob_metadata(connection, blob_id=blob_id)
    metadata = {
        **existing_metadata,
        **blob["metadata"],
        "inline_payload_occurrences": _inline_payload_occurrences(
            existing_metadata,
            occurrence=occurrence,
        ),
    }
    connection.execute(
        """
        INSERT INTO payload_blobs (
          id,
          profile_id,
          kind,
          media_type,
          sha256,
          size_bytes,
          path,
          preview,
          redaction_mode,
          retained_until,
          metadata_json,
          created_at,
          updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          profile_id = COALESCE(excluded.profile_id, payload_blobs.profile_id),
          kind = payload_blobs.kind,
          media_type = excluded.media_type,
          size_bytes = excluded.size_bytes,
          path = excluded.path,
          preview = excluded.preview,
          redaction_mode = excluded.redaction_mode,
          retained_until = COALESCE(excluded.retained_until, payload_blobs.retained_until),
          metadata_json = excluded.metadata_json,
          updated_at = excluded.updated_at
        """,
        (
            blob_id,
            profile_id,
            blob["kind"],
            blob["media_type"],
            sha256,
            len(blob["data"]),
            str(blob_path),
            _blob_preview(blob["data"], blob["media_type"]),
            blob["redaction_mode"],
            blob["retained_until"],
            _db_value(metadata),
            now,
            now,
        ),
    )
    return blob_id


def _existing_blob_metadata(connection: sqlite3.Connection, *, blob_id: str) -> dict[str, Any]:
    row = connection.execute(
        "SELECT metadata_json FROM payload_blobs WHERE id = ?",
        (blob_id,),
    ).fetchone()
    if row is None:
        return {}
    try:
        metadata = json.loads(str(row["metadata_json"] or "{}"))
    except json.JSONDecodeError:
        return {}
    return metadata if isinstance(metadata, dict) else {}


def _inline_payload_occurrences(
    metadata: dict[str, Any],
    *,
    occurrence: dict[str, str],
) -> list[dict[str, str]]:
    occurrences: list[dict[str, str]] = []
    existing = metadata.get("inline_payload_occurrences")
    if isinstance(existing, list):
        occurrences = [
            item
            for item in existing
            if isinstance(item, dict) and all(isinstance(key, str) for key in item.keys())
        ]
    if occurrence not in occurrences:
        occurrences.append(occurrence)
    return occurrences


def _inline_payload_blob_input(payload: Any, *, default_kind: str) -> dict[str, Any]:
    wrapper = _inline_payload_wrapper(payload)
    content = wrapper["content"]
    encoding = wrapper["encoding"]
    media_type = wrapper["media_type"] or _default_media_type(content, encoding)
    data = _inline_payload_bytes(content, encoding=encoding)
    return {
        "data": data,
        "kind": wrapper["kind"] or default_kind,
        "media_type": media_type,
        "redaction_mode": wrapper["redaction_mode"] or "redacted",
        "retained_until": wrapper["retained_until"],
        "metadata": wrapper["metadata"],
    }


def _inline_payload_wrapper(payload: Any) -> dict[str, Any]:
    wrapper_control_keys = INLINE_PAYLOAD_WRAPPER_KEYS - {"content"}
    if isinstance(payload, dict) and "content" in payload and wrapper_control_keys.intersection(payload):
        metadata = payload.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            raise StorageError("inline_payload_metadata_must_be_object")
        retained_until = payload.get("retained_until")
        retention_days = payload.get("retention_days")
        if retained_until is not None and not isinstance(retained_until, str):
            raise StorageError("inline_payload_retained_until_must_be_string")
        if retention_days is not None:
            if isinstance(retention_days, bool) or not isinstance(retention_days, int) or retention_days < 0:
                raise StorageError("inline_payload_retention_days_must_be_non_negative_integer")
            retained_until = _format_utc(datetime.now(timezone.utc) + timedelta(days=retention_days))
        return {
            "content": payload["content"],
            "encoding": _optional_payload_string(payload.get("encoding"), "encoding"),
            "kind": _optional_payload_string(payload.get("kind"), "kind"),
            "media_type": _optional_payload_string(payload.get("media_type"), "media_type"),
            "redaction_mode": _optional_payload_string(payload.get("redaction_mode"), "redaction_mode"),
            "retained_until": retained_until,
            "metadata": metadata or {},
        }
    return {
        "content": payload,
        "encoding": None,
        "kind": None,
        "media_type": None,
        "redaction_mode": None,
        "retained_until": None,
        "metadata": {},
    }


def _inline_payload_bytes(content: Any, *, encoding: Optional[str]) -> bytes:
    if encoding is None:
        if isinstance(content, str):
            return content.encode("utf-8")
        return json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
    normalized = encoding.strip().lower()
    if normalized == "text":
        if not isinstance(content, str):
            raise StorageError("inline_payload_text_content_must_be_string")
        return content.encode("utf-8")
    if normalized == "json":
        return json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if normalized == "base64":
        if not isinstance(content, str):
            raise StorageError("inline_payload_base64_content_must_be_string")
        try:
            return base64.b64decode(content.encode("ascii"), validate=True)
        except Exception as exc:
            raise StorageError("inline_payload_base64_invalid") from exc
    raise StorageError(f"inline_payload_encoding_unsupported:{encoding}")


def _default_media_type(content: Any, encoding: Optional[str]) -> str:
    if encoding is not None and encoding.strip().lower() == "base64":
        return "application/octet-stream"
    if isinstance(content, str):
        return "text/plain"
    return "application/json"


def _optional_payload_string(value: Any, field_name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise StorageError(f"inline_payload_{field_name}_must_be_string")
    return value


def _blob_preview(data: bytes, media_type: str) -> str:
    if media_type.startswith("text/") or media_type == "application/json":
        return data.decode("utf-8", errors="replace")[:500]
    return ""


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _upsert_row(connection: sqlite3.Connection, table: str, row: dict[str, Any]) -> None:
    columns = TABLE_COLUMNS[table]
    missing = [column for column in columns if column not in row]
    if missing:
        raise StorageError(f"{table}: row {row.get('id')} missing columns {missing}")

    placeholders = ", ".join("?" for _ in columns)
    column_list = ", ".join(columns)
    update_list = ", ".join(f"{column} = excluded.{column}" for column in columns if column != "id")
    values = [_db_value(row[column]) for column in columns]

    connection.execute(
        f"""
        INSERT INTO {table} ({column_list})
        VALUES ({placeholders})
        ON CONFLICT(id) DO UPDATE SET {update_list}
        """,
        values,
    )


def _db_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return value


def _table_count(connection: sqlite3.Connection, table: str) -> int:
    try:
        row = connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row["count"])


def _schema_migration_versions(connection: sqlite3.Connection) -> tuple[int, ...]:
    try:
        rows = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version ASC"
        ).fetchall()
    except sqlite3.OperationalError:
        return ()
    return tuple(int(row["version"]) for row in rows)


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {
        str(row["name"])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _rename_table_if_needed(connection: sqlite3.Connection, old: str, new: str) -> None:
    """Rename old->new only when old exists and new does not (idempotent)."""
    if _table_exists(connection, old) and not _table_exists(connection, new):
        connection.execute(f"ALTER TABLE {old} RENAME TO {new}")


def _rename_column_if_needed(
    connection: sqlite3.Connection, table: str, old: str, new: str
) -> None:
    """Rename a column old->new when the table exists with old and not new."""
    if not _table_exists(connection, table):
        return
    columns = {
        str(row["name"])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if old in columns and new not in columns:
        connection.execute(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")


def _database_user_version(connection: sqlite3.Connection) -> int:
    try:
        row = connection.execute("PRAGMA user_version").fetchone()
    except sqlite3.OperationalError:
        return 0
    if row is None:
        return 0
    return int(row[0])


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def _ensure_default_autonomy_policy(connection: sqlite3.Connection, profile_id: str) -> None:
    now = utc_now()
    connection.execute(
        """
        INSERT OR IGNORE INTO autonomy_policies (
          profile_id,
          mode,
          recurrence_threshold,
          regression_threshold,
          auto_rollback_on_regression,
          max_auto_fix_attempts,
          allow_repo_patch,
          allowed_paths_json,
          protected_paths_json,
          dirty_worktree_policy,
          updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            profile_id,
            "hitl",
            3,
            2,
            1,
            1,
            0,
            json.dumps(["agents/**", "prompts/**", "checks/**", "tests/**", ".kyoko/**"]),
            json.dumps(
                [
                    ".env",
                    ".env.*",
                    "secrets/**",
                    "**/secrets/**",
                    "node_modules/**",
                    ".git/**",
                    "*.pem",
                    "*.key",
                    "*.p12",
                ]
            ),
            "block",
            now,
        ),
    )


_FTS5_SUPPORTED: Optional[bool] = None


def fts5_available(connection: sqlite3.Connection) -> bool:
    """Return True if this sqlite build can create FTS5 virtual tables.

    Cached process-wide: FTS5 is a compile-time module, so availability never
    changes across connections in one interpreter. When unavailable, callers fall
    back to the linear scan and never create ``spans_fts``.
    """

    global _FTS5_SUPPORTED
    if _FTS5_SUPPORTED is None:
        try:
            connection.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS temp._kyoko_fts5_probe USING fts5(x)"
            )
            connection.execute("DROP TABLE IF EXISTS temp._kyoko_fts5_probe")
            _FTS5_SUPPORTED = True
        except sqlite3.OperationalError:
            _FTS5_SUPPORTED = False
    return bool(_FTS5_SUPPORTED)


def spans_fts_ready(connection: sqlite3.Connection) -> bool:
    """True when the ``spans_fts`` index exists and is usable for this connection."""

    if not fts5_available(connection):
        return False
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (SPANS_FTS_TABLE,),
    ).fetchone()
    return row is not None


def _span_fts_text(connection: sqlite3.Connection, span_row: Any) -> str:
    """Build the searchable document for one span: name + attributes + previews.

    Sections are newline-joined so substring/snippet behaviour downstream stays
    natural and tokenisation never merges adjacent fields.
    """

    parts: list[str] = []
    name = span_row["name"]
    if name:
        parts.append(str(name))
    attributes_json = span_row["attributes_json"]
    if attributes_json:
        # Re-serialise canonically (sorted keys, no separators stripping) so the FTS
        # document matches what search_run's attribute scope would render.
        try:
            attributes = json.loads(attributes_json)
        except (json.JSONDecodeError, TypeError):
            attributes = None
        if attributes:
            parts.append(json.dumps(attributes, ensure_ascii=False, sort_keys=True))
    for ref_field in ("input_ref", "output_ref"):
        ref = span_row[ref_field]
        if not ref:
            continue
        blob = connection.execute(
            "SELECT preview FROM payload_blobs WHERE id = ?", (ref,)
        ).fetchone()
        if blob is not None and blob["preview"]:
            parts.append(str(blob["preview"]))
    return "\n".join(parts)


def index_span_fts(connection: sqlite3.Connection, span_id: str) -> None:
    """(Re)index a single span in ``spans_fts``. No-op if FTS5 is unavailable.

    Write-through: deletes any prior rows for the span then inserts the current
    document, so re-ingest/upsert keeps the index consistent.
    """

    if not spans_fts_ready(connection):
        return
    span_row = connection.execute(
        "SELECT id, run_id, name, attributes_json, input_ref, output_ref "
        "FROM spans WHERE id = ?",
        (span_id,),
    ).fetchone()
    if span_row is None:
        return
    connection.execute("DELETE FROM spans_fts WHERE span_id = ?", (span_id,))
    text = _span_fts_text(connection, span_row)
    connection.execute(
        "INSERT INTO spans_fts (span_id, run_id, text) VALUES (?, ?, ?)",
        (str(span_row["id"]), str(span_row["run_id"]), text),
    )


def _backfill_spans_fts(connection: sqlite3.Connection) -> None:
    """Populate ``spans_fts`` from existing spans for DBs created before v24.

    Runs only when the index is empty but spans exist, so re-initialising an
    already-indexed DB is cheap.
    """

    if not spans_fts_ready(connection):
        return
    indexed = connection.execute("SELECT COUNT(*) FROM spans_fts").fetchone()[0]
    span_count = connection.execute("SELECT COUNT(*) FROM spans").fetchone()[0]
    if indexed or not span_count:
        return
    for row in connection.execute("SELECT id FROM spans").fetchall():
        index_span_fts(connection, str(row["id"]))


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Analysis schedules (v28). Recurring openclaw/hermes analysis runs. These are a
# local single-user convenience; the scheduler thread in `kyoko serve` reads these
# rows. No autonomy shortcut lives here — a fired schedule runs the normal gate.
# ---------------------------------------------------------------------------

ANALYSIS_SCHEDULE_ANALYZER_KINDS = ("openclaw", "hermes", "llm_judge")
_ANALYZER_SOURCE_KIND = {
    "openclaw": "openclaw_sessions",
    "hermes": "hermes_kanban",
}


def _resolve_schedule_profile_id(connection: sqlite3.Connection, profile_id: Optional[str]) -> str:
    if profile_id:
        if connection.execute("SELECT 1 FROM profiles WHERE id = ?", (profile_id,)).fetchone() is None:
            raise StorageError(f"profile_not_found:{profile_id}")
        return profile_id
    row = connection.execute("SELECT id FROM profiles ORDER BY created_at, id LIMIT 1").fetchone()
    if row is None:
        raise StorageError("no_profiles_found")
    return str(row["id"])


def create_analysis_schedule(
    *,
    db_path: Path,
    analyzer_kind: str,
    adapter_id: Optional[str] = None,
    source_path: Optional[str] = None,
    refresh_import: bool = True,
    interval_hours: int = 24,
    at_time: Optional[str] = None,
    enabled: bool = True,
    run_autonomy: bool = True,
    next_run_at: Optional[str] = None,
    profile_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if analyzer_kind not in ANALYSIS_SCHEDULE_ANALYZER_KINDS:
        raise StorageError(f"unsupported_schedule_analyzer:{analyzer_kind}")
    if analyzer_kind == "llm_judge" and not adapter_id:
        # The judge runs through an operator adapter (the backend CLI); there is no
        # source to import from, so the adapter is what makes the schedule runnable.
        raise StorageError("llm_judge_schedule_requires_adapter_id")
    if int(interval_hours) <= 0:
        raise StorageError("interval_hours_must_be_positive")
    if at_time is not None and not _valid_hhmm(at_time):
        raise StorageError(f"invalid_at_time:{at_time}")
    initialize_database(db_path)
    now = utc_now()
    schedule_id = f"sched_{uuid.uuid4().hex[:12]}"
    with connect(db_path) as connection:
        resolved_profile_id = _resolve_schedule_profile_id(connection, profile_id)
        connection.execute(
            """
            INSERT INTO analysis_schedules (
              id, profile_id, analyzer_kind, adapter_id, source_kind, source_path,
              refresh_import, interval_hours, at_time, enabled, run_autonomy,
              watermark, last_run_at, next_run_at, last_status, last_operator_run_id,
              last_error, metadata_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, NULL, NULL, NULL, ?, ?, ?)
            """,
            (
                schedule_id,
                resolved_profile_id,
                analyzer_kind,
                adapter_id or analyzer_kind,
                _ANALYZER_SOURCE_KIND.get(analyzer_kind),
                source_path,
                1 if refresh_import else 0,
                int(interval_hours),
                at_time,
                1 if enabled else 0,
                1 if run_autonomy else 0,
                next_run_at,
                json.dumps(metadata or {}, sort_keys=True, separators=(",", ":")),
                now,
                now,
            ),
        )
    return get_analysis_schedule(db_path=db_path, schedule_id=schedule_id)  # type: ignore[return-value]


def update_analysis_schedule(
    *,
    db_path: Path,
    schedule_id: str,
    **fields: Any,
) -> dict[str, Any]:
    allowed = {
        "adapter_id",
        "source_path",
        "refresh_import",
        "interval_hours",
        "at_time",
        "enabled",
        "run_autonomy",
        "next_run_at",
        "watermark",
    }
    initialize_database(db_path)
    sets: list[str] = []
    params: list[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            raise StorageError(f"unsupported_schedule_field:{key}")
        if key == "at_time" and value is not None and not _valid_hhmm(str(value)):
            raise StorageError(f"invalid_at_time:{value}")
        if key in {"refresh_import", "enabled", "run_autonomy"}:
            value = 1 if value else 0
        if key == "interval_hours":
            value = int(value)
            if value <= 0:
                raise StorageError("interval_hours_must_be_positive")
        sets.append(f"{key} = ?")
        params.append(value)
    if not sets:
        existing = get_analysis_schedule(db_path=db_path, schedule_id=schedule_id)
        if existing is None:
            raise StorageError(f"analysis_schedule_not_found:{schedule_id}")
        return existing
    sets.append("updated_at = ?")
    params.append(utc_now())
    params.append(schedule_id)
    with connect(db_path) as connection:
        cursor = connection.execute(
            f"UPDATE analysis_schedules SET {', '.join(sets)} WHERE id = ?",
            tuple(params),
        )
        if cursor.rowcount == 0:
            raise StorageError(f"analysis_schedule_not_found:{schedule_id}")
    return get_analysis_schedule(db_path=db_path, schedule_id=schedule_id)  # type: ignore[return-value]


def record_schedule_result(
    *,
    db_path: Path,
    schedule_id: str,
    last_run_at: str,
    last_status: str,
    last_operator_run_id: Optional[str] = None,
    last_error: Optional[str] = None,
    watermark: Optional[str] = None,
) -> None:
    """Record the outcome of a fired schedule. Does NOT touch ``next_run_at`` — the
    scheduler owns that and sets it when it picks the schedule up."""

    with connect(db_path) as connection:
        connection.execute(
            """
            UPDATE analysis_schedules
            SET last_run_at = ?,
                last_status = ?,
                last_operator_run_id = ?,
                last_error = ?,
                watermark = COALESCE(?, watermark),
                updated_at = ?
            WHERE id = ?
            """,
            (
                last_run_at,
                last_status,
                last_operator_run_id,
                last_error,
                watermark,
                utc_now(),
                schedule_id,
            ),
        )


def list_analysis_schedules(db_path: Path, *, enabled_only: bool = False) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    initialize_database(db_path)
    where = " WHERE enabled = 1" if enabled_only else ""
    with connect(db_path) as connection:
        try:
            rows = connection.execute(
                f"SELECT * FROM analysis_schedules{where} ORDER BY created_at, id"
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [_decode_analysis_schedule(row) for row in rows]


def get_analysis_schedule(*, db_path: Path, schedule_id: str) -> Optional[dict[str, Any]]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM analysis_schedules WHERE id = ?", (schedule_id,)
        ).fetchone()
    return _decode_analysis_schedule(row) if row is not None else None


def delete_analysis_schedule(*, db_path: Path, schedule_id: str) -> bool:
    initialize_database(db_path)
    with connect(db_path) as connection:
        cursor = connection.execute(
            "DELETE FROM analysis_schedules WHERE id = ?", (schedule_id,)
        )
    return cursor.rowcount > 0


def runs_newer_than(
    db_path: Path,
    *,
    profile_id: str,
    since: Optional[str],
) -> tuple[int, Optional[str]]:
    """Return ``(count, max_started_at)`` for runs newer than ``since`` (None = all)."""

    with connect(db_path) as connection:
        if since:
            row = connection.execute(
                """
                SELECT COUNT(*) AS n, MAX(started_at) AS max_started
                FROM runs
                WHERE profile_id = ? AND started_at > ?
                """,
                (profile_id, since),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT COUNT(*) AS n, MAX(started_at) AS max_started
                FROM runs
                WHERE profile_id = ?
                """,
                (profile_id,),
            ).fetchone()
    count = int(row["n"]) if row is not None and row["n"] is not None else 0
    max_started = row["max_started"] if row is not None else None
    return count, (str(max_started) if max_started is not None else None)


def _valid_hhmm(value: str) -> bool:
    parts = value.split(":")
    if len(parts) != 2:
        return False
    hh, mm = parts
    if not (hh.isdigit() and mm.isdigit()):
        return False
    return 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59


def _decode_analysis_schedule(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    payload["refresh_import"] = bool(payload.get("refresh_import"))
    payload["enabled"] = bool(payload.get("enabled"))
    payload["run_autonomy"] = bool(payload.get("run_autonomy"))
    metadata_json = payload.pop("metadata_json", None)
    if isinstance(metadata_json, str):
        try:
            payload["metadata"] = json.loads(metadata_json)
        except json.JSONDecodeError:
            payload["metadata"] = {}
    else:
        payload["metadata"] = {}
    return payload
