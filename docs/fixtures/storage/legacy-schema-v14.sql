PRAGMA user_version = 14;

CREATE TABLE schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO schema_migrations(version) VALUES
  (1), (2), (3), (4), (5), (6), (7),
  (8), (9), (10), (11), (12), (13), (14);

CREATE TABLE profiles (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  root_path TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

INSERT INTO profiles (
  id, name, root_path, status, created_at, updated_at
) VALUES (
  'profile_legacy_migration_001',
  'Legacy migration fixture',
  '/tmp/kyoko-legacy',
  'active',
  '2026-01-01T00:00:00Z',
  '2026-01-01T00:00:00Z'
);

CREATE TABLE skills (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  proposal_id TEXT,
  section TEXT NOT NULL,
  issue TEXT NOT NULL,
  insight TEXT NOT NULL,
  keywords_json TEXT NOT NULL,
  occurrences_json TEXT NOT NULL,
  helpful_count INTEGER NOT NULL DEFAULT 0,
  harmful_count INTEGER NOT NULL DEFAULT 0,
  neutral_count INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  human_locked INTEGER NOT NULL DEFAULT 0,
  source_run_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

INSERT INTO skills (
  id, profile_id, proposal_id, section, issue, insight, keywords_json,
  occurrences_json, helpful_count, harmful_count, neutral_count, active,
  human_locked, source_run_id, created_at, updated_at
) VALUES (
  'skill_legacy_migration_001',
  'profile_legacy_migration_001',
  NULL,
  'context',
  'legacy issue',
  'legacy insight',
  '["legacy"]',
  '[]',
  0,
  0,
  0,
  1,
  1,
  NULL,
  '2026-01-01T00:00:00Z',
  '2026-01-01T00:00:00Z'
);

CREATE TABLE context_delivery_rules (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  proposal_id TEXT,
  target_json TEXT NOT NULL,
  rule_json TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  human_locked INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

INSERT INTO context_delivery_rules (
  id, profile_id, proposal_id, target_json, rule_json, active, human_locked,
  created_at, updated_at
) VALUES (
  'context_rule_legacy_migration_001',
  'profile_legacy_migration_001',
  NULL,
  '{"entity_type":"workflow_node","entity_id":"node_legacy"}',
  '{"mode":"include","max_skills":3}',
  1,
  1,
  '2026-01-01T00:00:00Z',
  '2026-01-01T00:00:00Z'
);

CREATE TABLE retention_policies (
  profile_id TEXT PRIMARY KEY,
  trace_retention_days INTEGER,
  replay_retention_days INTEGER,
  operator_retention_days INTEGER,
  updated_at TEXT NOT NULL
);

INSERT INTO retention_policies (
  profile_id, trace_retention_days, replay_retention_days,
  operator_retention_days, updated_at
) VALUES (
  'profile_legacy_migration_001',
  30,
  14,
  30,
  '2026-01-01T00:00:00Z'
);

CREATE TABLE redaction_audit_events (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  run_id TEXT,
  consumer TEXT NOT NULL,
  payload_access TEXT NOT NULL,
  redact_sensitive_values INTEGER NOT NULL,
  redacted INTEGER NOT NULL,
  redacted_count INTEGER NOT NULL,
  redacted_paths_json TEXT NOT NULL,
  redacted_paths_truncated INTEGER NOT NULL,
  policy_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

INSERT INTO redaction_audit_events (
  id, profile_id, run_id, consumer, payload_access, redact_sensitive_values,
  redacted, redacted_count, redacted_paths_json, redacted_paths_truncated,
  policy_json, created_at
) VALUES (
  'redaction_audit_legacy_migration_001',
  'profile_legacy_migration_001',
  NULL,
  'operator_prompt',
  'refs_only',
  1,
  1,
  1,
  '["payload.api_key"]',
  0,
  '{"payload_access":"refs_only"}',
  '2026-01-01T00:00:00Z'
);
