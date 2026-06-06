# 0006 - Native ACE Bridge

Status: accepted for first compatibility slice
Date: 2026-06-01

## Decision

Native ACE integration must run against cloned Skillbook state. Kyoko never
lets ACE mutate canonical Kyoko rows directly.

The implemented bridge has three surfaces:

- `kyoko ace-compat`: exports Kyoko's current ACE Skillbook v2 shape and loads
  it through ACE's public `ace.core.skillbook.Skillbook.from_dict(...)` API.
- `kyoko ace-diff-proposals`: reads an ACE Skillbook v2 `before` snapshot and
  an ACE-mutated `after` snapshot, diffs material skill fields, and converts
  the delta into Kyoko `LearningProposal` records with `producer.kind =
  native_ace`.
- `kyoko ace-native-run`: writes a cloned `before.skillbook.json` and
  `after.skillbook.json`, invokes a user-supplied external ACE command with
  `KYOKO_ACE_*` environment variables, captures stdout/stderr, then imports only
  the validated before/after diff as normal Kyoko proposals.
- `kyoko ace-native-run --prepare-only`: writes the cloned Skillbook files,
  empty command log files, and `ace-command.handoff.json` with the expanded
  command and Kyoko ACE environment contract, then stops before invoking the
  external command or persisting proposals.
- `kyoko ace-native-smoke`: seeds the bundled fixture and invokes the installed
  legacy ACE `OfflineAdapter` package through the same external clone/diff
  boundary without a live provider call.

## Evidence

Local ACE source inspected:

- `/Users/filip/Desktop/agentic-context-engine/pyproject.toml`
- `/Users/filip/Desktop/agentic-context-engine/ace/core/skillbook.py`
- `/Users/filip/Desktop/agentic-context-engine/ace/core/outputs.py`
- `/Users/filip/Desktop/agentic-context-engine/ace/core/insight_source.py`

Important findings:

- The local ACE package is `ace-framework` version `0.12.0`.
- The package declares `requires-python = ">=3.12"` and license text
  `FSL-1.1-MIT`, so Kyoko should not make it a hard dependency while Kyoko
  still advertises broader Python support and an Apache-2.0 package.
- ACE Skillbook v2 uses `schema_version = "2"`, section values `context` and
  `harness`, and skill fields `issue`, `insight`, `keywords`, `occurrences`,
  active flag, and counters.
- ACE's online SkillManager mutates the real Skillbook immediately. That is
  acceptable inside an ACE-owned clone, but not against Kyoko's canonical
  store.

Local smoke status:

- `python3` is Python `3.9.6`; the local ACE checkout cannot import there
  because it uses Python 3.12-era typing.
- An isolated Python 3.12 venv with `pydantic>=2.0.0` can import the local ACE
  0.12.0 checkout's public Skillbook API, round-trip Kyoko's Skillbook v2 export
  through `kyoko ace-compat`, and pass `kyoko doctor --ace-path ... --json`.
- A separate temporary Python 3.12 venv can install the PyPI
  `ace-framework==0.12.0` wheel plus `pydantic` runtime dependencies and pass
  `kyoko ace-compat` through `site-packages/ace/core/skillbook.py`.
- On 2026-06-03, the default local Python imports `ace-framework==0.2.0`, which
  exposes the legacy `ace.Playbook`/`OfflineAdapter` API rather than
  `ace.core.skillbook.Skillbook`; `kyoko ace-compat --json` reports
  `detected_api = legacy_playbook` for that environment.
- `kyoko ace-native-smoke --json` runs that installed legacy ACE package with
  `DummyLLMClient`, writes real before/after cloned Skillbook files, and imports
  the resulting diff as a gated `native_ace` proposal.
- `kyoko ace-native-run --prepare-only --json` renders the same command,
  Skillbook, and environment handoff locally without invoking the user-supplied
  external command.
- This means the Kyoko bridge, external command wrapper, and JSON diff boundary
  are implemented, unit tested, contract-tested, and smoke-tested against both
  local-source/package-installed ACE Skillbook APIs and an installed legacy ACE
  package. On 2026-06-03, a provider-backed ACE-compatible Claude command also
  ran through `ace-native-run --provider-backed`, wrote a cloned before/after
  Skillbook pair, and imported a persisted `native_ace` proposal; the retained
  artifacts are under `.kyoko/smoke/ace-provider-live`.

## Boundary

Native ACE may:

- load a Kyoko-exported Skillbook clone,
- run ACE `TraceAnalyser` or ACE-compatible roles when provider access is
  configured,
- add/update/deactivate/link occurrences inside that clone,
- write a before/after ACE Skillbook JSON pair for Kyoko to inspect.

Native ACE may not:

- write Kyoko SQLite rows directly,
- bypass `LearningProposal` validation,
- bypass eval/replay gates,
- bypass human locks,
- bypass context/harness autonomy policy,
- apply repository harness patches directly.

## Diff Mapping

Kyoko compares material fields:

- `section`
- `issue`
- `insight`
- `keywords`
- `active`
- `occurrences`

The first bridge maps:

- new ACE skill -> `skillbook_update.operation = create`
- changed material fields -> `skillbook_update.operation = update`
- inactive or removed ACE skill -> `skillbook_update.operation = deactivate`
- new occurrence only -> `skillbook_update.operation = link_occurrence`

Every generated proposal also includes a conservative deterministic eval spec
with:

- `target_status_not_failed`
- `replay_no_failed_spans`

That eval is intentionally generic. Framework-native assertion presets and
judge-backed evals remain separate work.

## Consequences

Positive:

- Kyoko now has an implemented path for native ACE compatibility without
  making ACE a mandatory dependency.
- Provider-backed ACE learning can be represented as normal Kyoko proposals.
- No-key operator-agent mode and native ACE mode converge on the same
  validation, eval/replay, autonomy, and apply machinery.

Costs:

- This does not run ACE's model-backed analyser by itself; `ace-native-run`
  executes a supplied command and imports the resulting Skillbook diff.
- `ace-native-smoke` proves the external process boundary with an installed
  legacy ACE package, not a provider-backed `TraceAnalyser`.
- Update/deactivate/link-occurrence proposals are represented and the context
  apply engine writes them with skill revision preimages.
- The generic eval spec is useful as a gate scaffold, not a full domain-aware
  regression test.
