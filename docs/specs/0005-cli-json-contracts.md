# 0005 - CLI JSON Contracts

Status: implemented
Date: 2026-06-02

## Purpose

Kyoko CLI commands are used by coding agents and scripts. JSON output must be
stable enough to parse without scraping human text.

This contract covers fixture-backed golden outputs for commands whose payloads
are used by coding agents and scripts to bootstrap and inspect the local
optimization loop.

## Golden Fixtures

- `docs/fixtures/cli-json/import-hermes-kanban.golden.json`
- `docs/fixtures/cli-json/import-openclaw-sessions.golden.json`
- `docs/fixtures/cli-json/bundled-assets.contract.golden.json`
- `docs/fixtures/cli-json/bundled-assets-export.contract.golden.json`
- `docs/fixtures/cli-json/demo.contract.golden.json`
- `docs/fixtures/cli-json/status.contract.golden.json`
- `docs/fixtures/cli-json/ingest.contract.golden.json`
- `docs/fixtures/cli-json/ingest-otlp.contract.golden.json`
- `docs/fixtures/cli-json/wal-checkpoint.contract.golden.json`
- `docs/fixtures/cli-json/load-smoke.contract.golden.json`
- `docs/fixtures/cli-json/ace-compat.contract.golden.json`
- `docs/fixtures/cli-json/ace-diff-proposals.contract.golden.json`
- `docs/fixtures/cli-json/ace-native-run.contract.golden.json`
- `docs/fixtures/cli-json/ace-native-run-prepare.contract.golden.json`
- `docs/fixtures/cli-json/blob-put.contract.golden.json`
- `docs/fixtures/cli-json/blobs.contract.golden.json`
- `docs/fixtures/cli-json/storage-report.contract.golden.json`
- `docs/fixtures/cli-json/prune.contract.golden.json`
- `docs/fixtures/cli-json/prune-retention.contract.golden.json`
- `docs/fixtures/cli-json/dashboard-metrics.contract.golden.json`
- `docs/fixtures/cli-json/dashboard-smoke.contract.golden.json`
- `docs/fixtures/cli-json/runs.contract.golden.json`
- `docs/fixtures/cli-json/run-detail.contract.golden.json`
- `docs/fixtures/cli-json/policy.contract.golden.json`
- `docs/fixtures/cli-json/policy-set.contract.golden.json`
- `docs/fixtures/cli-json/prepare-harness.contract.golden.json`
- `docs/fixtures/cli-json/harness-patches.contract.golden.json`
- `docs/fixtures/cli-json/harness-target-locks.contract.golden.json`
- `docs/fixtures/cli-json/harness-target-lock.contract.golden.json`
- `docs/fixtures/cli-json/harness-target-unlock.contract.golden.json`
- `docs/fixtures/cli-json/apply-harness.contract.golden.json`
- `docs/fixtures/cli-json/rollback-harness.contract.golden.json`
- `docs/fixtures/cli-json/skills.contract.golden.json`
- `docs/fixtures/cli-json/skill-revisions.contract.golden.json`
- `docs/fixtures/cli-json/skill-lock.contract.golden.json`
- `docs/fixtures/cli-json/skill-unlock.contract.golden.json`
- `docs/fixtures/cli-json/skill-rollback.contract.golden.json`
- `docs/fixtures/cli-json/context-rules.contract.golden.json`
- `docs/fixtures/cli-json/context-rule-revisions.contract.golden.json`
- `docs/fixtures/cli-json/context-rule-lock.contract.golden.json`
- `docs/fixtures/cli-json/context-rule-unlock.contract.golden.json`
- `docs/fixtures/cli-json/context-rule-rollback.contract.golden.json`
- `docs/fixtures/cli-json/run-autonomy.contract.golden.json`
- `docs/fixtures/cli-json/operator-prompt.contract.golden.json`
- `docs/fixtures/cli-json/analyze-mock.contract.golden.json`
- `docs/fixtures/cli-json/mcp-install-plan.contract.golden.json`
- `docs/fixtures/cli-json/mcp-install.contract.golden.json`
- `docs/fixtures/cli-json/operator-presets.contract.golden.json`
- `docs/fixtures/cli-json/operator-adapter-bootstrap.contract.golden.json`
- `docs/fixtures/cli-json/operator-adapters.contract.golden.json`
- `docs/fixtures/cli-json/operator-adapter-register.contract.golden.json`
- `docs/fixtures/cli-json/operator-adapter-run.contract.golden.json`
- `docs/fixtures/cli-json/operator-runs.contract.golden.json`
- `docs/fixtures/cli-json/replay-adapter-register.contract.golden.json`
- `docs/fixtures/cli-json/replay-adapters.contract.golden.json`
- `docs/fixtures/cli-json/replay-adapter-run.contract.golden.json`
- `docs/fixtures/cli-json/replay.contract.golden.json`
- `docs/fixtures/cli-json/complete-replay.contract.golden.json`
- `docs/fixtures/cli-json/replay-command.contract.golden.json`
- `docs/fixtures/cli-json/replay-server-template.contract.golden.json`
- `docs/fixtures/cli-json/replay-server-health.contract.golden.json`
- `docs/fixtures/cli-json/replay-server-run.contract.golden.json`
- `docs/fixtures/cli-json/replay-server-start.contract.golden.json`
- `docs/fixtures/cli-json/replay-server-status.contract.golden.json`
- `docs/fixtures/cli-json/replay-server-logs.contract.golden.json`
- `docs/fixtures/cli-json/replay-server-stop.contract.golden.json`
- `docs/fixtures/cli-json/source-adapter-template.contract.golden.json`
- `docs/fixtures/cli-json/integration-smoke-source.contract.golden.json`
- `docs/fixtures/cli-json/integration-smoke-framework-source.contract.golden.json`
- `docs/fixtures/cli-json/integration-smoke-framework-replay.contract.golden.json`
- `docs/fixtures/cli-json/integration-smoke-framework-improve.contract.golden.json`
- `docs/fixtures/cli-json/integration-smoke-opentelemetry-python.contract.golden.json`
- `docs/fixtures/cli-json/integration-smoke-replay-server.contract.golden.json`
- `docs/fixtures/cli-json/integration-smoke-improve.contract.golden.json`
- `docs/fixtures/cli-json/discover-sources.contract.golden.json`
- `docs/fixtures/cli-json/import-discovered-source.contract.golden.json`
- `docs/fixtures/cli-json/proposals-context.golden.json`
- `docs/fixtures/cli-json/proposal-detail-context.contract.golden.json`
- `docs/fixtures/cli-json/issues.contract.golden.json`
- `docs/fixtures/cli-json/issue-detail.contract.golden.json`
- `docs/fixtures/cli-json/profile-next-context.contract.golden.json`
- `docs/fixtures/cli-json/improve-existing-proposal.contract.golden.json`
- `docs/fixtures/cli-json/consolidate-skillbook.contract.golden.json`
- `docs/fixtures/cli-json/autonomy-events.contract.golden.json`
- `docs/fixtures/cli-json/check-capabilities.contract.golden.json`
- `docs/fixtures/cli-json/generate-checks.contract.golden.json`
- `docs/fixtures/cli-json/checks.contract.golden.json`
- `docs/fixtures/cli-json/check-assertion-presets.contract.golden.json`
- `docs/fixtures/cli-json/run-check.contract.golden.json`
- `docs/fixtures/cli-json/judge-command.contract.golden.json`
- `docs/fixtures/cli-json/judge-smoke.contract.golden.json`
- `docs/fixtures/cli-json/check-detail.contract.golden.json`
- `docs/fixtures/cli-json/check-lock.contract.golden.json`
- `docs/fixtures/cli-json/check-locks.contract.golden.json`
- `docs/fixtures/cli-json/check-unlock.contract.golden.json`
- `docs/fixtures/cli-json/check-approve.contract.golden.json`
- `docs/fixtures/cli-json/evals.contract.golden.json` (measurement plane: `eval` detectors)
- `docs/fixtures/cli-json/eval-detail.contract.golden.json` (measurement plane)
- `docs/fixtures/cli-json/run-eval.contract.golden.json` (measurement plane)
- `docs/fixtures/cli-json/eval-runs.contract.golden.json` (measurement plane)
- `docs/fixtures/cli-json/eval-run-detail.contract.golden.json` (measurement plane)
- `docs/fixtures/cli-json/llm-evals.contract.golden.json` (measurement plane: `llm_eval` judges)
- `docs/fixtures/cli-json/llm-eval-detail.contract.golden.json` (measurement plane)
- `docs/fixtures/cli-json/run-llm-eval.contract.golden.json` (measurement plane)
- `docs/fixtures/cli-json/llm-eval-runs.contract.golden.json` (measurement plane)
- `docs/fixtures/cli-json/llm-eval-run-detail.contract.golden.json` (measurement plane)
- `docs/fixtures/cli-json/replay-detail.contract.golden.json`
- `docs/fixtures/cli-json/doctor-readiness.contract.golden.json`
- `docs/fixtures/cli-json/operator-smoke-prepare-matrix.contract.golden.json`
- `docs/fixtures/cli-json/operator-smoke-command.contract.golden.json`
- `docs/fixtures/cli-json/operator-smoke-failure-command.contract.golden.json`
- `docs/fixtures/cli-json/release-smoke.contract.golden.json`
- `docs/fixtures/cli-json/release-smoke-matrix.contract.golden.json`
- `docs/fixtures/cli-json/mcp-install-smoke-matrix.contract.golden.json`
- `docs/fixtures/cli-json/project-bootstrap.contract.golden.json`

The tests run the real CLI commands against local fixture stores. Import
command tests replace only volatile absolute path fields with placeholders and
compare the remaining JSON exactly. Proposal list output is compared exactly.
Proposal detail and profile-next output are intentionally broad, so their
golden fixtures compare stable contract projections containing the fields
operator agents should branch on.
`improve --json` also compares a stable contract projection because replay
artifact paths and policy timestamps are intentionally local and volatile.
`autonomy-events --json` compares a stable contract projection because timeline
event timestamps and generated event ids are intentionally volatile.
`check-capabilities --json` is compared exactly because it is static runtime
metadata for operator agents and contains no local paths or timestamps.
`generate-checks --json`, `checks --json`, `run-check --json`, and
`check-detail --json` compare stable lifecycle projections because generated check
rows, check runs, replay runs, and timeline events contain local timestamps and
generated event ids, while check ids, target refs, replay target mapping,
assertion outcomes, gate summaries, and trust promotion are contract fields.
`check-assertion-presets --json` is compared exactly because built-in preset
metadata is static runtime metadata and contains no local paths or timestamps.
`judge-command --json` compares a stable projection because request/result/raw
output paths are local, while the external-judge backend marker, verdict,
non-gateable check result, artifact creation, and stdout result markers are
contract fields.
`judge-smoke --json` compares a stable projection because the smoke database and
artifacts are local, while the command handoff, provider-backed flags,
non-gateable check result, and stdout result markers are contract fields.
`check-lock --json`, `check-unlock --json`, and
`check-approve --json` are compared exactly because their direct reports
contain deterministic governance decisions and no local timestamps or paths.
`check-locks --json` compares a stable projection because lock rows include
timestamps, while lock state, reason, actor-safe profile/check ids, and active
lock filtering are contract fields. `replay-detail --json` compares a stable
projection because replay command artifact paths, previews, run timestamps, and
timeline event ids are local, while artifact presence, preview markers,
source/output run links, check outcome, replay result, span counts, target map,
and timeline metadata are contract fields.
`demo --json` compares a stable projection because database and replay artifact
paths are local, while seeded profile/proposal/check/replay ids, promoted trust
level, applied skill ids, and final database counts are contract fields.
`doctor --json` compares a stable readiness projection because local
interpreter paths, installed optional CLIs, and temporary database paths are
machine-specific, while check ids/statuses, bundled asset names, release-target
readiness fields, and suggested command intents/mutation flags are contract
fields.
`operator-smoke --all-presets --prepare-only --json` compares a stable matrix
projection because output directories and artifact paths are local, while
target statuses, command shapes, environment keys, artifact-relative placement,
and live-invocation flags are contract fields for capturing external operator
evidence.
`operator-smoke --operator command --json` compares a stable live report
projection because operator-run ids and artifact paths are local, while
proposal persistence, artifact creation, proposal-output markers,
`live_operator_invoked`, and the proposal file summary are contract fields.
`operator-smoke --operator command --expect-failure --json` compares a stable
expected-failure report projection because operator-run ids and artifact paths
are local, while captured failure kind, last attempt status, proposal
non-persistence, prompt override markers, and raw-output presence are contract
fields.
`release-smoke --json` compares a stable single-interpreter projection because
artifact directories, virtualenv/run paths, command durations, and command
output tails are local, while artifact type, build command names, installed
version, doctor result, dependency/demo flags, Python executable, and temporary
output status are contract fields.
`release-smoke --python-matrix --json` compares a stable matrix projection
because output paths, command durations, and command output tails are local,
while target status/reason, summary counts, artifact types, nested report
presence, command names, and doctor summaries are contract fields.
`mcp install-smoke --all-targets --json` compares a stable matrix projection
because isolated homes, config paths, command output tails, and durations are
local, while target status/reason, list verification, command shape, config
existence, summary counts, and temporary-output metadata are contract fields.
`project-bootstrap --json` compares a stable bootstrap projection because
project paths and the Python executable are local, while generated artifact
presence, framework choices, MCP config shape, registered operator ids, and
copyable command-map entries are contract fields.
`source-adapter-template --json`, `integration-smoke source --json`,
`integration-smoke framework-source --json`, `integration-smoke
framework-replay --json`, `integration-smoke framework-improve --json`,
`integration-smoke opentelemetry-python --json`, `integration-smoke
replay-server --json`, and `integration-smoke improve --json` compare stable
projections because generated adapter paths, smoke databases, hook paths,
selected Python executables, loopback ports, process ids, and log paths are
local, while template capabilities, artifact creation, ingest counts, database
status counts, installed-framework/OpenTelemetry markers, health metadata,
replay request/response,
replay/check/apply results, and lifecycle booleans are contract fields.
`status --json`, `blob-put --json`, `blobs --json`, `storage-report --json`,
`prune --json`, and `prune-retention --json` compare stable projections because
database paths, blob roots, content-addressed file names, payload hashes, and
prune cutoffs are local or time-derived, while schema status, table counts,
blob registration, storage health, dry-run behavior, and prunable row
identities are contract fields. `prune-retention` is a manual
`--older-than-days` prune (no retention policy table); a blank day value skips
that row family.
`ingest --json`, `ingest-otlp --json`, and `wal-checkpoint --json` compare
stable projections because normalized output paths, generated OTLP ids, and
database/WAL paths are local, while inserted counts, profile ids, checkpoint
mode, and WAL/checkpoint nonnegative metrics are contract fields.
`load-smoke --json` compares a stable projection because timings, database/blob
paths, WAL sizes, and content-addressed blob names are local, while seed
parameters, generated counts, read-operation coverage, retained dry-run rows,
checkpoint mode, and pass/fail behavior are contract fields.
`ace-compat --json`, `ace-diff-proposals --json`, `ace-native-run --json`,
`ace-native-run --prepare-only --json`, and `ace-native-smoke --json` compare
stable projections because Python/import paths, output proposal paths, command
artifact paths, and generated timestamps are local, while ACE availability,
detected API family, roundtrip counts, command execution status, proposal ids,
persisted state, evidence refs, proposed
changes, check-gate expectations, and unsupported change reporting are contract
fields.
`dashboard-metrics --json`, `dashboard-smoke --json`, `runs --json`, and
`run-detail --json` compare stable projections because run/task/span
timestamps, fixture workspace paths, local server ports, browser artifact
paths, and screenshot paths are local context, while dashboard card ordering,
product-loop counts, browser-smoke error/overflow fields, run summaries, span
tree shape, handoff metadata, timeline event metadata, and proposal evidence
links are contract fields.
`policy --json` and `policy-set --json` compare stable projections because policy
timestamps are local or generated, while the autonomy `mode`, recurrence and
regression thresholds, auto-rollback / max-auto-fix settings, `allow_repo_patch`,
path globs, and `dirty_worktree_policy` are contract fields. Redaction is a fixed global "redact on export"
default with no per-profile policy command and no audit ledger; evidence bundles
still carry a `redaction` summary.
`prepare-harness --json`, `harness-patches --json`,
`harness-target-locks --json`, `harness-target-lock --json`,
`harness-target-unlock --json`, `apply-harness --json`, and
`rollback-harness --json` compare stable projections because patch row
timestamps and workspace roots are local, while patch ids, target paths, patch
kinds, rollback availability, lock state, actor attribution, and apply/rollback
side-effect status are contract fields.
`skills --json`, `skill-revisions --json`, `skill-lock --json`,
`skill-unlock --json`, `skill-rollback --json`, `context-rules --json`,
`context-rule-revisions --json`, `context-rule-lock --json`,
`context-rule-unlock --json`, and `context-rule-rollback --json` compare
stable projections because revision ids and timestamps are generated, while
learned skill/rule content, active state, lock state, actor attribution, and
rollback status are contract fields.
`run-autonomy --json` compares a stable projection because policy timestamps
are local, while per-proposal decisions (action, reason, before/after state,
applied skill/context-rule ids, patch ids) and the policy snapshot
(mode/thresholds/`allow_repo_patch`) are contract fields.
`operator-prompt --json` and `analyze --operator mock --json` compare stable
projections because artifact paths, redaction audit ids, and operator-run ids
are generated or local, while artifact creation, proposal block markers,
profile/operator ids, persistence, attempts, and proposal ids are contract
fields.
`mcp install-plan --json` and `mcp install --json` compare stable projections
because Python executable paths, temp database paths, home config paths, and
repo paths are local, while target/server names, command shape, MCP config
structure, config output creation, install notes, and manual-config flags are
contract fields.
`bundled-assets --json` is compared exactly for list-only output because bundled
asset paths are package-relative and deterministic. `bundled-assets
--output-dir --json` compares a stable export projection because output paths
are local, while asset ordering, relative paths, exported asset names, and file
creation are contract fields for installed-package first-run flows.
`operator-adapter-bootstrap --list-presets --json` is compared exactly because
the built-in preset names, command vectors, operator kinds, and notes are static
runtime metadata for no-key local operator setup. `operator-adapter-bootstrap
--json` and `operator-adapters --json` compare stable projections because output
directories and adapter timestamps are local, while registered/skipped adapter
ids, command vectors, enabled state, profile binding, timeout, and preset
metadata are contract fields.
`operator-adapter-register --json`, `operator-adapter-run --json`, and
`operator-runs --json` compare stable projections because Python executable
paths, artifact directories, operator run ids, timestamps, and path-length-based
stdout counts are local, while command shape, artifact creation, proposal
persistence, attempt status, audit refs, and retry metadata are contract fields.
`replay-adapter-register --json`, `replay-adapters --json`, and
`replay-adapter-run --json` compare stable projections because Python executable
paths, adapter artifact directories, and copied replay artifact paths are local,
while command shape, adapter safety boundary, replay/check ids, replay result,
check status, trust promotion, assertion details, and artifact creation are
contract fields.
`replay --json` and `complete-replay --json` compare deterministic local fixture
contracts because they contain no paths or timestamps. `replay-command --json`
compares a stable projection because request/result/raw-output artifact paths
are local, while replay ids, status, result, check outcome, artifact creation, and
required replay-result stdout markers are contract fields.
`replay-server-template --json`, `replay-server-health --json`,
`replay-server-run --json`, and managed replay-server lifecycle commands compare
stable projections because template paths, process ids, loopback server ports,
and process output directories are local, while generated template capabilities,
health metadata, replay status, replay result, check outcome, trust promotion,
managed command shape, lifecycle booleans, and bounded log markers are contract
fields.
`discover-sources --json` and `import-discovered-source --json` compare stable
contract projections because discovered homes, candidate paths, and generated
import command paths are local, while candidate ids/statuses, source kinds,
metadata counts, command vectors, import counts, and normalized artifact
creation are contract fields.

## Stable Fields

Kyoko runs a single implicit workflow profile ([docs/SCOPE.md](../SCOPE.md)
Decision 1): the product never displays, selects, or implies "which profile",
so there is no user-facing `profiles` listing command or `/api/profiles` route.
The `profiles` table remains an internal storage detail and commands that accept
an optional `--profile-id`/`?profile_id=` default to the single implicit
profile.

Routing states are compact local next-step guidance:
`setup_sources`, `needs_analysis`, `needs_check_generation`,
`needs_replay_or_check`, `ready_for_autonomy`, `loop_complete`, or `monitor`.
Suggested commands are argument vectors rather than shell strings so coding
agents can execute them without reparsing quoted paths.
For `ready_for_autonomy` harness proposals, routing also reports
`harness_repo_patch_allowed`, `harness_workspace_root`,
`harness_workspace_root_status`, and `harness_workspace_root_required`. When
the profile root is an existing directory, the suggested `run_autonomy` command
includes `--harness-workspace-root`; otherwise its `requires` list names the
missing prerequisite.

`profile-next --json` must keep these fields stable:

- `profile_id`, `run_requested`, `action`, `status`, and `reason`
- `routing_before` and `routing_after`
- top-level `suggested_commands`, mirroring the current post-step routing
  command guidance for the profile
- `result`, when a local step executes
- `notes`, when the next step is blocked or needs prerequisites

`profile-next` operates on the single implicit profile (its optional
`--profile-id` resolves to that profile). There is no `--all-profiles` batch
mode — multi-profile orchestration is out of scope per
[docs/SCOPE.md](../SCOPE.md) Decision 1.

Without `--run`, `profile-next` is a dry-run planner and reports
`status = planned`. With `--run`, it may execute Kyoko-owned local steps such
as running a registered operator adapter, preparing redacted operator
evidence/prompt artifacts, check generation, registered replay/check execution,
or autonomy. It reports `status = blocked` instead of importing sources
implicitly or replacing human review. Supplying `--operator-target` keeps the
analysis step prompt-only; otherwise a selected or latest enabled
`--operator-adapter` can run through the audited operator-adapter path.
Autonomous harness steps also block before apply when repo patch permission or a
usable workspace root is missing.

`doctor --json` returns a readiness payload with:

- `ok`
- `checks`, each with `id`, `status`, `message`, and `detail`
- `summary.passed`, `summary.warnings`, and `summary.failed`
- `readiness.local_runtime_ready`, `readiness.local_v0_ready`,
  `readiness.safe_smokes_complete`, `readiness.pending_safe_smoke_checks`,
  `readiness.blocking_checks`, `readiness.warning_checks`,
  `readiness.external_evidence_warnings`, and
  `readiness.satisfied_external_evidence_commands`, and
  `readiness.pending_external_evidence_commands`
- top-level `suggested_commands`, using the same argument-vector command shape
  as profile routing
- top-level `retained_external_evidence`, when complete retained smoke
  artifacts prove a live follow-up has already run

Suggested doctor commands cover the one-command `doctor --safe-smokes` shortcut,
safe optional local smokes that were not already requested, optional installed
OpenTelemetry SDK, ACE native, and dashboard browser smokes, plus release, MCP,
live-operator, and live judge evidence follow-ups when readiness checks surface
warning-only external prerequisites. By default, doctor scans `.kyoko/smoke`
for retained live operator proposal smoke, live operator expected-failure smoke,
provider-backed judge smoke evidence, and provider-backed native ACE run
evidence with a durable `ace-native-run-report.json`; `--smoke-evidence-dir`
can point the scan at a different artifact root or a non-existent directory for
deterministic contract projections. Satisfied retained evidence is reported in
`readiness.satisfied_external_evidence_commands` and suppresses the matching
suggested follow-up command without suppressing unrelated external checks.
Safe doctor smokes include bundled demo, operator
prepare-only, judge-command prepare-only handoff, native ACE prepare-only
handoff, generated integration, generated improve, and isolated MCP client
install checks; they do not invoke live model CLIs. The installed OpenTelemetry
SDK, ACE native, and dashboard browser smokes are separate from safe smokes
because they depend on installed third-party packages or browser test tooling,
even though the built-in ACE smoke uses `DummyLLMClient` and does not invoke a
live provider. The
readiness object separates blocking local runtime failures from pending safe
smoke coverage and external evidence follow-ups: `local_runtime_ready` is true
when no check failed, while `local_v0_ready` additionally requires the safe
doctor smoke checks to be present. Warning-only release, MCP, and live operator
evidence remains visible through warning and pending evidence lists without
changing `ok` to false. The live operator proposal-output and provider-backed
judge follow-ups must be marked `mutating = true` and must name installed or
user-supplied provider prerequisites, live model/subscription invocation, and
retained artifact prerequisites in `requires`.
The `release_python_targets` check detail must separate `missing_targets`,
`ready_targets`, `bootstrap_required_targets`, and `unready_targets`, preserve
raw `build_backend_reasons`, and expose `ready_matrix_command` when at least one
named release target can run. Existing interpreters that lack
`setuptools.build_meta` or `wheel.bdist_wheel` are listed in
`bootstrap_required_targets`; release smoke must bootstrap `setuptools>=58` and
`wheel>=0.37` in an isolated build venv instead of requiring a global
interpreter mutation.
When the release check is not fully ready, `suggested_commands` also includes
the generic full-matrix command. If any named targets are ready, it includes a
non-mutating `release_smoke_ready_targets` command whose prerequisites explain
that build backends may be bootstrapped in isolated venvs.
When `--smoke-output-dir` is supplied, optional smoke checks must mark
`artifacts_retained = true` and return inspectable artifact paths instead of
paths inside deleted temporary directories.
Human `doctor` output mirrors the same suggested commands as shell-quoted
commands so the non-JSON first-run path exposes the next safe action.

`demo --json` returns a first-run loop payload with:

- database path, output directory, profile id, proposal id, and replay adapter
  id
- check spec ids, replay/check run ids, check status, promoted trust level, and
  applied skill ids
- final database status counts after source ingest, proposal persistence,
  check/replay execution, and context apply

The demo contract must prove the replay output directory exists and the local
loop reaches `L2_regression` without live model or network side effects.

`operator-smoke --all-presets --prepare-only --json` returns:

- `operators`, `prepare_only`, `passed`, `summary`, and `used_demo_database`
- `targets`, each with `operator`, `status`, `reason`, optional `plan`, and
  optional `report`
- prepare-only `plan` payloads with command vectors, expanded command vectors,
  shell-rendered command text, environment contract, artifact paths, and
  `live_operator_invoked = false`

The prepare-only matrix must write evidence and prompt artifacts per operator,
skip missing preset executables by default, and never invoke live operator CLIs.
The live `operator-smoke --json` report must mark `live_operator_invoked = true`
for non-mock operators, surface at least one validated Issue (analysis is
diagnosis-only — no proposal), retain evidence, prompt, and raw-output
artifacts, and report the operator run id used for audit lookup. The live `operator-smoke --all-presets --json` evidence command
uses the same target summary shape but may include `report` payloads instead of
plans.
With `--expect-failure`, `operator-smoke` appends a negative-path prompt
override, runs the same operator boundary, and exits successfully only when the
operator run records a captured failure matching `--expected-failure-kind`
(`invalid_output` by default). Expected-failure reports must retain evidence,
prompt, and raw-output artifacts, expose the operator run id, report
`persisted = false`, and skip missing preset executables by default in
`--all-presets` mode.

`release-smoke --json` returns:

- project root, output directory, artifact directory, selected Python
  executable, install-dependency flag, demo flag, dashboard-smoke flag,
  pass/fail result, and temporary-output flag
- build command reports with command vector, cwd, command name, return code,
  and bounded stdout tail
- artifact install reports with artifact type/path, installed version, doctor
  result/summary, optional dashboard-smoke result/summary, install strategy,
  modern install return code, legacy fallback usage, venv path, run cwd, and
  post-install command names

The single-interpreter release smoke contract is fixture-backed with a mocked
release runner so JSON shape stays protected without rebuilding packages in the
CLI JSON contract suite.
For sdist artifact installs, command reports may include
`install_sdist_build_backend` before `install_sdist` when the clean install venv
cannot import `setuptools.build_meta` or `wheel.bdist_wheel`; this command
installs `setuptools>=58` and `wheel>=0.37` into the install venv and is
distinct from the top-level build-target preflight.
When an offline sdist install falls back from modern pip/PEP 517 installation
to legacy `setup.py install`, the artifact report must expose
`install_strategy = legacy_setup_py`, `legacy_fallback_used = true`, and the
original `modern_install_returncode` instead of hiding the fallback behind an
overall passing doctor check.

`release-smoke --python-matrix --json` returns:

- `python_targets`, `artifact_types`, `install_dependencies`, `run_demo`,
  `dashboard_smoke`, `passed`, `summary`, `temporary`, `project_root`, and
  `output_dir`
- `targets`, each with `target`, `python_executable`, `status`, `reason`, and
  optional nested `report`
- nested `report` payloads for passed targets with build command reports,
  artifact install reports, installed version, doctor status/summary, and
  artifact/venv/run paths

Missing Python targets must be reported as `skipped` rather than fatal.
Existing targets that lack `setuptools.build_meta` or `wheel.bdist_wheel` must
run through an isolated build venv bootstrap; only bootstrap or release-smoke failures should be
reported as `failed`, while passing targets keep their nested install-smoke
report.

`mcp install-smoke --all-targets --json` returns:

- `targets`, `server`, `output_dir`, `passed`, `summary`, `temporary`, and
  `results`
- `results`, each with `target`, `status`, `reason`, and optional nested
  `report`
- nested `report` payloads with native install command shape, isolated `home`,
  isolated `cwd`, config path hint/existence, install return code, post-install
  `mcp list` command/return code, `list_verified`, and notes

Missing native MCP clients must be reported as `skipped` by default in matrix
mode. Known MCP targets without verified native install commands must also be
reported as skipped with `mcp_install_smoke_no_native_command` rather than being
silently omitted. Passed targets must prove both the native install command and
post-install registry/list verification for the requested server name.

`project-bootstrap --json` returns:

- generated artifact paths for the project directory, SQLite database, source
  adapter, replay server, MCP config, and `.kyoko/NEXT_STEPS.md`
- `source_adapter` and `replay_server` framework/profile metadata
- `mcp_config` for the selected target
- `operator_bootstrap` registration/skipped metadata
- `commands`, the machine-readable command map embedded in `NEXT_STEPS.md`

The bootstrap command map must include first-run doctor checks, safe no-live
smokes with retained artifacts, profile routing, source discovery/import,
generated source-adapter ingest, dashboard start, replay-server smoke with
`--run-replay`, replay-adapter registration, and Hermes/OpenClaw import
commands. Bootstrap itself must not invoke live operator models, replay,
autonomy, or apply.

`discover-sources --json` returns:

- `db_path` and `home`
- `candidates`, each with `id`, `kind`, `label`, `path`, `exists`, `status`,
  `metadata`, and an import-ready command

The stable projection converts each shell import command to `import_command_args`
so coding agents can validate command shape without depending on shell quoting.
The fixture covers a missing Hermes default, a ready Hermes board, and ready
OpenClaw sessions with session/transcript counts.

`import-discovered-source --json` returns:

- `db_path`
- `candidate`, mirroring the selected `discover-sources` candidate
- `import`, using the underlying Hermes/OpenClaw import report shape

The stable projection proves the Kyoko database and normalized source-event JSON
were created, while preserving normalized source counts and storage
`ingested_counts`.

`ingest --json` must keep these fields available:

- `profile_id`
- `ingested_counts`, including inserted run, span, handoff, proposal, check, and
  replay rows

`ingest-otlp --json` must keep these fields available:

- `profile_id`
- normalized source-event run/span ids and run status
- `ingested_counts`
- `normalized_path` when the command writes normalized source events

`wal-checkpoint --json` must keep these fields available:

- `db_path`, `wal_path`, `mode`, `busy`, `log_frames`, `checkpointed_frames`,
  `wal_size_before`, and `wal_size_after`

WAL metrics must be nonnegative integers. Golden projections normalize local
database paths and generated OTLP ids but keep profile ids and inserted row
counts exact.

`load-smoke --json` must keep these fields available:

- database path, profile id, seeded flag, temporary flag, pass/fail status,
  errors, parameters, and total read operations
- status and storage summaries after seeding
- latency summaries for the overall run and each UI-style read operation
- retention dry-run pruned blob rows and WAL checkpoint metrics

Load-smoke golden projections normalize local database/blob paths and check
latency metric shape/ranges instead of storing machine-specific durations.

`ace-compat --json` must keep these fields available:

- ACE availability, exported schema version, exported skill count, ACE path,
  package/source version fields, and Python version
- detected API family, expected API, base `ace` importability/path/stdout/stderr,
  Skillbook import path/error, compatibility import path/stdout/stderr/error,
  roundtrip schema version, roundtrip skill count, and optional ACE stats

`ace-diff-proposals --json` must keep these fields available:

- profile id, proposal ids, output proposal paths, persisted flag, unsupported
  changes, and generated proposals
- proposal producer, evidence refs, gate expectations, native skillbook update
  change, generated check spec change, and created timestamp presence

`ace-native-run --json` must keep these fields available:

- profile id, database path, output directory, before/after Skillbook paths,
  proposal output directory, handoff artifact path, original and expanded
  command argv, shell command, Kyoko ACE environment keys/values, return code,
  stdout/stderr artifact paths and tails, durable run report path, timeout, and
  temporary-output flag
- prepare-only, prepared, external-command, provider-backed,
  external-model-invoked, live-operator, canonical-mutation, and pass/fail flags
- nested `ace-diff-proposals` report for the generated native ACE proposals

`ace-native-run --prepare-only --json` must use the same path/command/environment
contract, set `external_command_invoked = false`, preserve the caller-supplied
`provider_backed` metadata, set `external_model_invoked = false`,
`canonical_mutation = false`, and `diff = null`, and write
`ace-command.handoff.json` beside the cloned Skillbook files without persisting
proposals. Non-prepare `--provider-backed` runs set `provider_backed = true` and
`external_model_invoked = true` after the external command is invoked.

`ace-native-smoke --json` must keep these fields available:

- smoke kind, database path, output directory, source fixture path, command path,
  profile id, pass/fail, installed-ACE/provider/live-model flags
- nested `ace-native-run` report for the installed legacy ACE OfflineAdapter
  smoke

`bundled-assets --json` returns packaged runtime/demo assets with:

- `assets`, each with `path` and `kind`
- `exported`, empty for list-only calls or entries with `asset` and
  `output_path` when `--output-dir` or `--asset --output` is supplied
- `output_dir` when all assets were exported with `--output-dir`

Asset paths are relative to the packaged `kyoko.assets` root and use POSIX
separators, for example
`source-events/hermes-news-research-minimal.json`.
The export contract for `--output-dir` must include the same asset list, one
exported item per asset, the requested `output_dir`, and real copied files at
each reported `output_path`.

## Storage And Retention Fields

`status --json` must keep these fields available:

- `db_path`, `initialized`, `schema_version`, `migration_versions`, and
  per-table `counts`

`blob-put --json` must keep these fields available:

- content-addressed `blob_id`, `sha256`, `size_bytes`, stored `path`, and
  `created`

`blobs --json` must keep these fields available for each row:

- blob id/hash/path, `profile_id`, `kind`, `media_type`, `size_bytes`,
  `preview`, `redaction_mode`, optional `retained_until`, metadata, and
  timestamps
- `preview` is raw content only when `redaction_mode = "unredacted"`; redacted
  blobs must use a placeholder preview rather than leaking blob bytes through
  listing surfaces.

`storage-report --json` must keep these fields available:

- `db_path`, `blob_root`, database/WAL byte counts, registered blob count/bytes,
  `missing_blobs`, and `orphan_files`

`prune --json` must keep these fields available:

- `dry_run`, optional `cutoff`, `pruned_blobs` with blob id/path/size/reason,
  and `pruned_bytes`

`prune-retention --json` must keep these fields available:

- selected `profile_id`, `dry_run`, effective trace/replay/operator cutoffs,
  `pruned_rows`, `skipped_rows`, and summary counts

Storage and retention golden projections normalize the SQLite path to
`<DB_PATH>`, the blob root to `<BLOB_ROOT>`, content-addressed payload files to
`<BLOB_PATH>`, and surrounding temporary files to `<TMP>`.

## Dashboard And Run Detail Fields

`dashboard-metrics --json` must keep these fields available:

- `profile_id`, `profile_name`, `scope`, `cards`, `issues`, `runs`, `checks`,
  `replay`, `autonomy`, and `before_after`
- card ids and ordering for `issues`, `proposal_status`, `checks`, `replay`,
  `autonomy`, and `before_after`

`dashboard-smoke --json` must return a browser-smoke report with:

- `kind = dashboard_browser_smoke`, `passed`, selected database/output paths,
  temporary flag, server URL, seeded-demo flag, and browser backend
- API readiness counts for `/api/status` and `/api/dashboard-metrics`
- console errors, page errors, request failures, and per-viewport metric-card
  overflow reports
- desktop and mobile viewport results with dimensions, metric counts, optional
  screenshot paths, and pass/fail flags

The browser dependency is optional for normal local tests. The command should
use Python Playwright when installed and otherwise support an isolated
`@playwright/test` install under `--output-dir` when
`--install-browser-deps` is explicitly requested.

`runs --json` must keep these fields available for each run:

- run id/profile/source refs, status, summary, root span and task attempt refs,
  input/output refs, agent identity/name/kind, span/handoff/failure counts,
  metadata, and timestamps

`run-detail --json` must keep these fields available:

- run/source/agent/task/task-attempt summary
- flat spans plus `span_tree` parent/child shape, including failed span
  attributes
- handoffs, timeline events, replay run links, summary counts, and related
  proposals with matched evidence refs

Run-detail golden projections normalize fixture workspace paths to
`<FIXTURE_ROOT>` and keep timestamp presence instead of requiring exact local
trace dates.

## Governance And Privacy Fields

`policy --json` and `policy-set --json` must keep these fields available:

- profile id, autonomy `mode` (`hitl`/`autonomous`), `recurrence_threshold`,
  `regression_threshold`, `auto_rollback_on_regression`,
  `max_auto_fix_attempts`, `allow_repo_patch`, allowed and protected path globs,
  `dirty_worktree_policy`, and the `updated_at` policy timestamp

Redaction is a fixed global "redact on export" default with no per-profile
policy command and no audit ledger. Evidence bundles (operator prompt, MCP, and
`/api/evidence-summary`) still carry a `redaction` summary with the policy
(payload access mode, sensitive-value flag), redacted status/count/path summary,
and a `consumer` label.

`run-autonomy --json` must keep these fields available:

- `profile_id` and a `decisions` list, each decision carrying `proposal_id`,
  `profile_id`, `section`, `state_before`/`state_after`, `action`, `reason`,
  `applied_skill_ids`, `applied_context_rule_ids`, `patch_transaction_ids`, and
  `detail`
- action/reason strings follow the two-mode gate: HITL yields
  `awaiting_human_review` / `hitl_awaiting_human_approve`; autonomous context
  yields `applied` / `autonomous_auto_apply`; autonomous harness yields
  `applied` when `allow_repo_patch` else `blocked` / `repo_patch_not_allowed`
- a `policy` snapshot carrying the policy fields listed above (mode,
  thresholds, `allow_repo_patch`, path globs, `dirty_worktree_policy`)

`apply-proposal <proposal_id> --json` is the explicit HITL gate #2 apply. It
returns `proposal_id`, `profile_id`, `section`, `state`, `applied_skill_ids`,
`applied_context_rule_ids`, and `patch_transaction_ids`.

`monitor-guards --json` returns `profile_id`, `mode`, `regression_threshold`,
and an `actions` list (rollbacks/escalations the guard monitor performed this
run; empty when nothing applied has regressed). It only rolls back an applied
fix in `autonomous` mode with `auto_rollback_on_regression`.

## Harness Patch Fields

`prepare-harness --json` must keep these fields available:

- proposal id, profile id, prepared patch transaction ids, and resulting
  proposal state

`harness-patches --json` must keep these fields available:

- patch transaction id, proposal/profile ids, patch kind, status,
  side-effect mode, target paths, optional diff ref, command plan, rollback
  availability/requirement/reason/preimage state, and row timestamps

`harness-target-locks --json`, `harness-target-lock --json`, and
`harness-target-unlock --json` must keep these fields available:

- profile id, target path, lock state, reason, actor agent identity for direct
  lock/unlock reports, and lock row timestamps for list output

`apply-harness --json` and `rollback-harness --json` must keep these fields
available:

- patch transaction id, proposal/profile ids, target paths, resulting status,
  and observable target-file side effects in the contract projection

## Learned Context Governance Fields

`skills --json` must keep these fields available:

- skill id, profile/proposal/source-run ids, section, issue, insight,
  keywords, evidence occurrences, active state, human-lock state/reason,
  helpful/harmful/neutral counters, and timestamps

`skill-revisions --json` and `skill-rollback --json` must keep these fields
available:

- skill id, profile/proposal ids, operation, before/after presence and skill
  snapshot, generated revision id shape, rollback revision id shape, rollback
  status, and revision timestamps

`skill-lock --json` and `skill-unlock --json` must keep these fields available:

- skill id, profile id, lock state, reason, and actor agent identity id

`context-rules --json` must keep these fields available:

- context delivery rule id, profile/proposal ids, target ref, rule payload,
  active state, human-lock state/reason, and timestamps

`context-rule-revisions --json` and `context-rule-rollback --json` must keep
these fields available:

- rule id, profile/proposal ids, operation, before/after presence and rule
  snapshot, generated revision id shape, rollback revision id shape, rollback
  status, and revision timestamps

`context-rule-lock --json` and `context-rule-unlock --json` must keep these
fields available:

- rule id, profile id, lock state, reason, and actor agent identity id

## Operator Prompt And MCP Install Fields

`operator-prompt --json` must keep these fields available:

- target, profile id/name, output directory, evidence path, prompt path, schema
  path, and redaction audit id
- artifact existence for evidence, prompt, and schema files
- proposal-output block start/end markers and target-specific command guidance

`analyze --operator mock --json` must keep these fields available (analysis is
diagnosis-only — it surfaces Issues, never a proposal):

- operator kind, profile id, surfaced `issue_ids` / `new_issue_ids` /
  `bundled_issue_ids`, operator-run id, persisted flag, attempts, and artifact
  paths (evidence + prompt)
- artifact existence for evidence and prompt files
- issues-output block markers in raw operator output

`mcp install-plan --json` and `mcp install --json` must keep these fields
available:

- target name, server name, server command vector, config path hint, install
  notes, and manual-config flag
- MCP config payload with server name, command, args, and environment
- native install command shape for targets that support native registration
- config output path and creation status for explicit config-output installs

`operator-adapter-bootstrap --list-presets --json` returns:

- `operator_presets`, with `adapter_id`, `name`, `operator_kind`, `command`, and
  `note`

`operator-adapter-bootstrap --json` returns:

- `registered`, with adapter id, profile id, command vector, output directory,
  timeout, enabled state, name, and operator kind
- `skipped`, with adapter id, executable command, and skip reason

`operator-adapters --json` returns:

- `operator_adapters`, with persisted adapter ids, command vectors, profile ids,
  output directories, timeout, enabled state, timestamps, and metadata

The contract fixture exercises a mixed local-CLI state: Codex and Hermes are
available and registered, while Claude and OpenClaw are reported as skipped
because their executables are missing. This proves bootstrap is a no-live-model
registration step rather than an operator invocation.

`operator-adapter-register --json` returns:

- adapter id, profile id, name, operator kind, parsed command vector, output
  directory, timeout, and enabled state

`operator-adapter-run --json` returns (analysis surfaces Issues, not a
proposal):

- adapter id, operator label, profile id, surfaced `issue_ids` /
  `new_issue_ids` / `bundled_issue_ids`, operator-run id, persisted flag,
  attempts, and evidence/prompt/raw-output artifact paths

`operator-runs --json` returns:

- `operator_runs`, each with run id, operator/adapter/profile ids,
  `proposal_id` (null for diagnosis runs), status, timestamps, artifact refs,
  failure fields, attempt counts, retry metadata, command vector, and schema
  path

The fixture-backed registered operator flow uses Kyoko's local fixture command.
It exercises the same prompt/evidence/issue-surfacing path as a real registered
operator adapter, but does not invoke external model CLIs.

`replay-adapter-register --json` returns:

- adapter id, profile id, name, kind, parsed command vector, server fields,
  explicit remote-server opt-in state, output directory, default replay mode,
  side-effect mode, timeout, and enabled state

`replay-adapters --json` returns:

- `replay_adapters`, with persisted adapter ids, command vectors, profile ids,
  output directories, default replay safety boundary, remote-server opt-in
  state, timeout, enabled state, timestamps, kind, and metadata

`replay-adapter-run --json` returns:

- adapter id, replay run id, profile id, check spec id, output run id, replay
  status, request/result/raw-output artifact paths, replay result, and optional
  check run result

The fixture-backed replay adapter flow uses Kyoko's local fixture replay command
with `--run-check`. It proves a command adapter can run bounded mocked replay,
write replay artifacts, ingest the replay result, run deterministic regression
assertions, and promote trust to `L2_regression` without live network side
effects.

## Direct Replay Command Fields

`replay --json` must keep these fields stable:

- `replay_run_id`, `profile_id`, `proposal_id`, `check_spec_id`,
  `source_run_id`, `mode`, `side_effect_mode`, `status`, and `result`

`complete-replay --json` must keep these fields stable:

- `replay_run_id`, `profile_id`, `check_spec_id`, `output_run_id`, `status`,
  `ingested_counts`, and `result`

`replay-command --json` must keep these fields available:

- `replay_run_id`, `profile_id`, `check_spec_id`, `output_run_id`, `status`,
  `result`, and optional `check_run`
- request/result/raw-output artifact path fields and file creation
- raw output markers `BEGIN_KYOKO_REPLAY_RESULT_JSON`,
  `END_KYOKO_REPLAY_RESULT_JSON`, replay result schema text, and command
  completion marker

The replay-command golden projection normalizes artifact paths to
`<OUTPUT_DIR>` and checks marker presence instead of storing the full command
stdout.

`judge-command --json` must keep these fields available:

- `profile_id`, `proposal_id`, `check_spec_id`, `judgment`, and `check_run`
- request/result/raw-output artifact path fields and file creation
- raw output markers `BEGIN_KYOKO_JUDGE_RESULT_JSON`,
  `END_KYOKO_JUDGE_RESULT_JSON`, and judge result schema text

The judge-command golden projection normalizes artifact paths to `<OUTPUT_DIR>`
and checks marker presence instead of storing the full command stdout.

`judge-smoke --json` must keep these fields available:

- smoke database path, output directory, request/result/raw-output/handoff paths,
  and artifact creation
- command, shell command, prepare-only state, provider-backed state,
  external-command/model invocation flags, and pass/fail status
- check spec id, check run id/status, promoted trust level, judgment summary, and
  non-gateable external judge result

The judge-smoke golden projection normalizes artifact paths to `<OUTPUT_DIR>`
and command paths to `<PYTHON>`/`<REPO>`.

## Source Adapter And Integration Smoke Fields

`source-adapter-template --json` must keep these fields available:

- `output_path`, `framework`, `profile_name`, and `wrote`
- generated file existence, executable bit, framework/profile constants,
  `KYOKO_SOURCE_HOOK` wiring, `--output` and `--post-url` support, and the
  `kyoko.source_events.v1` schema marker

`integration-smoke source --json` must keep these fields available:

- `kind`, `db_path`, `adapter_path`, `hook`, `output_dir`,
  `source_events_path`, `stdout_path`, `stderr_path`, `exit_code`,
  `profile_id`, `ingested_counts`, and database `status`
- creation of the source-events/stdout/stderr artifacts and initialized smoke
  database

`integration-smoke framework-source --json` must keep these fields available:

- `kind`, `framework`, `framework_package`, `framework_version`,
  `python_executable`, `db_path`, `output_dir`, generated adapter/hook paths,
  nested `source_smoke`, final database `status`, `passed`, and explicit
  `installed_framework_invoked`, `external_model_invoked`, and
  `live_operator_invoked` flags
- proof that the generated source adapter imported and ran the installed
  framework package while preserving no-live-model semantics

`integration-smoke framework-replay --json` must keep these fields available:

- `kind`, `framework`, `framework_package`, `framework_version`,
  `python_executable`, `output_dir`, generated replay server/hook paths,
  nested `replay_smoke`, `replay_server_url`, `passed`, and explicit
  `installed_framework_invoked`, `external_model_invoked`, and
  `live_operator_invoked` flags
- proof that the generated replay server imported and ran the installed
  framework package, returned a replay result with source events, and preserved
  no-live-model semantics

`integration-smoke opentelemetry-python --json` must keep these fields available:

- `kind`, `python_executable`, `opentelemetry_sdk_version`, `db_path`,
  `output_dir`, `workspace_root`, generated script/payload/normalized/stdout/
  stderr paths, `exit_code`, `profile_id`, `run_ids`, `span_ids`,
  `ingested_counts`, final database `status`, `passed`, and explicit
  `opentelemetry_sdk_invoked`, `external_model_invoked`, and
  `live_operator_invoked` flags
- proof that an installed OpenTelemetry Python SDK emitted OTLP/HTTP-style JSON
  and Kyoko ingested it through the OTLP normalizer with no-live-model
  semantics

`integration-smoke replay-server --json` must keep these fields available:

- `kind`, command vector, `server_url`, `health_path`, `output_dir`,
  `state_path`, `stdout_path`, `stderr_path`, pid presence, `started`,
  `healthy`, `stopped`, health report, optional replay request/response,
  `replay_ok`, and bounded logs

`integration-smoke improve --json` must keep these fields available:

- `kind`, `framework`, `db_path`, `output_dir`, generated source/replay
  artifact paths, `source_smoke`, registered `replay_adapter`,
  `replay_server_url`, `improve`, final database `status`, `passed`, and the
  explicit no-live-model flags
- replay/check/apply evidence showing the generated source adapter, managed
  replay server, mock operator, and autonomy apply path were invoked

Source and integration-smoke golden projections normalize generated temp paths
to `<TMP>`, smoke artifact paths to `<OUTPUT_DIR>`, loopback URLs to
`<SERVER_URL>`, and selected replay-server ports to `<PORT>`.

## Replay Server Command Fields

`replay-server-template --json` must keep these fields available:

- `output_path`, `framework`, `profile_name`, and `wrote`
- generated file existence, executable bit, framework/profile constants,
  `/health` handler, `/replay` handler, `KYOKO_REPLAY_HOOK` wiring, and replay
  result schema marker

`replay-server-health --json` must keep these fields available:

- `server_url`, `health_path`, `ok`, and server `response`

`replay-server-run --json` must keep these fields available:

- replay run id, profile id, check spec id, output run id, replay path, status,
  server URL, health report, replay result, and optional check run result

`replay-server-start --json`, `replay-server-status --json`, and
`replay-server-stop --json` must keep these fields available for registered
managed HTTP replay adapters:

- `adapter_id`, `server_url`, `health_path`, normalized server command vector,
  `output_dir`, `state_path`, `stdout_path`, `stderr_path`, pid presence,
  `running`, `healthy`, `started`, `stopped`, optional health report, and
  optional error
- creation or retention of state/stdout/stderr artifacts for inspection

`replay-server-logs --json` must keep these fields available:

- `adapter_id`, `output_dir`, `stdout_path`, `stderr_path`, bounded stdout and
  stderr previews, truncation flags, and `max_bytes`

The replay-server golden projections normalize loopback `server_url` values to
`<SERVER_URL>`, template and process paths to `<OUTPUT_DIR>`, and selected
managed server ports to `<PORT>`.

Import command JSON must keep these fields stable:

- `profile_id`
- source path field: `kanban_db_path` or `source_path`
- `normalized_path`
- `counts`
- `ingested_counts`

`counts` describes normalized source-event rows before ingest.
`ingested_counts` describes rows actually inserted into Kyoko storage and may
include storage-side materialization such as `payload_blobs`.

## Volatile Fields

Absolute local paths are volatile and may differ per machine or temp directory.
Golden tests normalize only those path fields:

- `kanban_db_path` -> `<KANBAN_DB_PATH>`
- `source_path` -> `<OPENCLAW_SESSION_PATH>`

No other fields are normalized.

## Proposal List Fields

`proposals --json` must keep these fields stable for each proposal:

- `id`
- `profile_id`
- `state`
- `section`
- `section_label`
- `section_description`
- `title`
- `summary`
- `confidence`
- `operator_confidence`
- `kyoko_confidence`
- `confidence_level`
- `confidence_delta`
- `created_at`

## Proposal Detail Contract Projection

`proposal-detail --json` may add rich diagnostic fields over time. The stable
contract projection must keep these fields available:

- proposal identity, state, title, canonical section, display label, display
  description, validation errors, and problem severity
- target ref and target-found state
- evidence refs with entity type, entity id, role, and found state
- autonomy gate action, reason, mutating flag, and section
- check guidance for gateable check types, informational check types, replay-safe
  side-effect modes, assertion presets, and recorded-judge-only status
- confidence summary, evidence coverage, and check/replay verification counts
- check/replay/patch/timeline/gate-history counts
- evidence-chain readiness, blocking reason, and ordered stage statuses

## Issues Contract Projection

`issues --json` lists first-class issues (evidence; see
[0012-issue-model.md](0012-issue-model.md)). Issue ids (`issue_<uuid>`) and timestamps are
volatile, so the stable contract projection normalizes them. Each issue keeps these fields
available:

- `id` (prefix `issue_`), `title`, `section`, `category`, `severity`, `status`
- `proposal_ids` backlinks
- `affected_agent_identity_ids`, `affected_workflow_node_ids`, `affected_task_ids`,
  `affected_span_ids`
- `evidence_refs`, `created_at` presence, and `updated_at`

## Issue Detail Contract Projection

`issue-detail --json` hydrates one issue. The stable contract projection must keep these
available:

- the issue projection (above), plus `section_label` / `section_description`
- `evidence` refs with entity type, entity id, and found state
- `affected` groups (agent identities, workflow nodes, tasks, spans) with entity type,
  entity id, and found state
- `linked_proposals` with proposal id, link kind (`explicit` | `related`), section, state
- `summary` counts of evidence refs, resolved refs, affected entities, and linked proposals

## Improve Contract Projection

`improve --json` is the coding-agent orchestration contract. Analysis now
surfaces Issues only; for each newly-surfaced issue the profile's autonomy
`mode` (gate #1) decides whether a proposal is authored this run. In `hitl`
nothing is authored on a fresh diagnosis run (issues await a human accept); in
`autonomous` a proposal is authored for an issue only once its
`recurrence_count >= recurrence_threshold`, then auto-applied. The stable
contract projection must keep these fields available:

- `profile_id`, `proposal_id` (first authored, or null), `proposal_ids`
  (all authored), `operator`, `notes` (with per-issue gate #1 outcomes),
  `gate1_outcome_count`, `guard_count`
- `analyze` presence (issue-centric: `issue_ids` / `new_issue_ids` /
  `bundled_issue_ids`, no proposal fields) and `source_import` presence
- autonomy profile id and a `policy` snapshot (`mode`, `recurrence_threshold`,
  `regression_threshold`, `allow_repo_patch`)
- autonomy decision action, reason, section, before/after state, applied
  skill/context-rule ids, and patch transaction ids

`ImproveReport` no longer carries `check_spec_ids`,
`generated_check_spec_ids`, `existing_check_spec_ids`, or `replay_runs`; replay
is no longer wired into the improve loop and the check plane is demoted (its
commands remain available standalone).
- `consolidation_present`: whether the post-analysis skillbook-consolidation turn
  produced a report. The `improve --json` payload carries a `consolidation` key
  that is `null` when consolidation was disabled or found no duplicate skills, and
  otherwise a `ConsolidationReport` (`profile_id`, `duplicate_group_count`,
  `proposal_ids`, `applied_proposal_ids`, `notes`). Consolidation proposals flow
  through the SAME autonomy gate as any proposal; consolidation never writes skills
  directly.

When `--harness-workspace-root` is supplied, `improve` passes it to the final
autonomy evaluator so eligible harness patch transactions can apply inside that
workspace. If the flag is omitted and the profile `root_path` is an existing
directory, `improve` snapshots that root before replay completion and uses it
for the same final autonomy step. The resulting JSON still reports the applied
`patch_transaction_ids` through the autonomy decision payload.

## Consolidate Skillbook Contract Projection

`consolidate-skillbook --json` returns a `ConsolidationReport`. The stable
contract projection keeps these fields available:

- `profile_id`
- `duplicate_group_count` — number of deterministically-detected duplicate skill
  groups (active skills sharing a normalized keyword set or identical issue text
  within a section)
- `proposal_ids` — one gated consolidation `LearningProposal` id per group
  (deterministic `proposal_consolidate_{winner_id}`)
- `applied_proposal_ids` — consolidation proposals the autonomy gate applied this
  run (only when `--run-autonomy` and the gate's check passed); otherwise empty
- `notes`

A MERGE decomposes into existing skillbook apply ops only: `update` the winner
with the union of keywords/occurrences plus a combined issue/insight, `deactivate`
each loser, and `link_occurrence` to move each loser's occurrences onto the
winner. Consolidation is evidence/proposal-only — it never writes skills directly;
only the gate applies a merge.

## Autonomy Events Contract Projection

`autonomy-events --json` must keep these fields available for each returned
event:

- `profile_id`, `entity_type`, `entity_id`, and `kind`
- metadata action, reason, decision kind, section, before/after proposal state,
  applied skill ids, applied context rule ids, and patch transaction ids

The golden projection intentionally excludes event `id` and `at` timestamp so
the contract remains stable while preserving the fields coding agents branch
on.

## Check Capabilities Contract

`check-capabilities --json` must keep these top-level fields stable:

- `check_types`
- `executable_check_types`
- `gateable_check_types`
- `trust_levels`
- `deterministic_assertions`
- `assertion_presets`
- `judge`
- `replay`

The payload is the coding-agent discovery contract for supported check types,
gateability, replay side-effect safety, assertion names, assertion presets, and
recorded-judge verdict handling.

## Check Lifecycle Contract Projection

`generate-checks --json`, `checks --json`, `run-check --json`,
`judge-command --json`, and `check-detail --json` must keep these fields
available:

- generated check spec ids, proposal id, profile id, and existing check spec ids
- check spec id, name, type, trust level, side-effect mode, status, target ref,
  human lock state, and definition assertions/evidence refs
- check run id/status, replay run id/status, replay side-effect mode, replay
  result mode, output run id, source run id, and target map
- check result comparison, baseline status, replay observed status, failure
  statuses, assertion counts, assertion statuses, field paths, actual/expected
  values, and matched entity ids
- check-detail proposal summary/gate expectations, source run summary, resolved
  target status/attributes, latest summary counts, and timeline event metadata

The golden projection intentionally replaces check spec, check run, replay run, and
event timestamps with presence booleans and excludes timeline event ids. The
contract still preserves the fields coding agents branch on when deciding whether
a replay-backed check proves a regression fix and promotes generated trust.

`check-assertion-presets --json` must keep these fields stable:

- preset `name`, `description`, `assertions`, `gateable_check_types`, and
  `options`

## Check Governance And Replay Detail Contract Projection

`check-lock --json`, `check-unlock --json`, and
`check-approve --json` must keep these direct report fields stable:

- `check_spec_id`, `profile_id`, `human_locked`, `reason`, and
  `actor_agent_identity_id` for lock/unlock reports
- `check_spec_id`, `profile_id`, `previous_trust_level`, `trust_level`,
  `reason`, and `actor_agent_identity_id` for human approval reports

`check-locks --json` must keep these fields available for each returned lock:

- `check_spec_id`, `profile_id`, `human_locked`, and `reason`

The lock-list projection intentionally replaces `created_at` and `updated_at`
with presence booleans.

`replay-detail --json` must keep these fields available:

- replay run id/status/mode, source/output run ids, side-effect mode, actual
  side-effect mode, executed-agent flag, target map, and timestamp presence
- linked check spec, check run result, assertion outcomes, promoted replay target,
  proposal gate expectations, and source/output run summaries
- source/output span ids, kinds, names, statuses, parent refs, attributes, and
  workflow node ids
- artifact refs and detail rows with kind, media type, existence, normalized
  path, preview presence, replay result markers, replay request schema marker,
  replay result schema marker, replay run id marker, and target-map marker
- timeline event entity refs, kind, metadata, profile id, and source id

The replay-detail projection intentionally excludes artifact byte-for-byte
previews, local artifact paths, replay timestamps, and timeline event ids while
still proving that operator agents can inspect replay evidence without scraping
human text.
