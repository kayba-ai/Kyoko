# Kyoko

Kyoko is a local, self-hosted optimization loop for agentic workflows. It is
designed as a single-player product: one developer, one local workflow profile,
and an end-to-end loop from telemetry to issues, insights, evals, replay,
context updates, and harness improvements.

Current status: planning docs, pre-build gates, the local runtime slice, the
bundled first-run demo loop, first-run doctor checks, command and HTTP replay
adapters, and conservative context autonomy are implemented. Managed
replay-server lifecycle controls are available through the CLI, JSON API, and
dashboard. Native ACE compatibility checks, ACE Skillbook diff-to-proposal
import, and a high-level `kyoko improve` pipeline are available through the
CLI.

## Install

Full instructions are in [docs/INSTALL.md](docs/INSTALL.md). Kyoko is a local,
single-user tool; nothing runs or listens until you start `kyoko serve`, which is
loopback-only.

```bash
# One-line installer (prefers pipx, then uv, then pip --user)
curl -fsSL https://raw.githubusercontent.com/kayba-ai/kyoko/main/scripts/install.sh | bash

# Or install the package directly with your preferred tool
pipx install kyoko        # isolated, recommended
uv tool install kyoko     # if you use uv
python3 -m pip install kyoko
```

Requires Python >= 3.12; the only runtime dependency is `jsonschema`. A
dependency-free TypeScript SDK for recording telemetry into Kyoko lives under
[`sdk/typescript/`](sdk/typescript/) (a Python `KyokoClient`/`KyokoRecorder`
ships in `kyoko/sdk.py`).

> Publishing the package to PyPI/npm and standing up the `kayba-ai/kyoko` repo and
> install domain are owner actions; until then, install from a local checkout
> (`python3 -m pip install .`).

## Planning Docs

- [Install guide](docs/INSTALL.md)
- [Project plan](docs/kyoko-project-plan.md)
- [Solution forward](docs/kyoko-solution-forward.md)
- [Critical research plan](docs/kyoko-critical-research-plan.md)
- [Pre-build critical review](docs/kyoko-prebuild-critical-review.md)
- [Open questions](docs/kyoko-open-questions.md)
- [Local dashboard auth decision](docs/decisions/0007-local-dashboard-auth.md)
- [Open-source boundary decision](docs/decisions/0008-open-source-boundary.md)

## Gate Artifacts

- [Canonical model spec](docs/specs/0001-canonical-model.md)
- [LearningProposal contract](docs/specs/0002-learning-proposal-contract.md)
- [Autonomy policy spec](docs/specs/0003-autonomy-policy.md)
- [Dashboard metrics contract](docs/specs/0004-dashboard-metrics.md)
- [CLI JSON contracts](docs/specs/0005-cli-json-contracts.md)
- [Product vocabulary](docs/specs/0006-product-vocabulary.md)
- [First-run demo and install path](docs/specs/0007-first-run-demo.md)
- [Hermes operator contract](docs/specs/0008-hermes-operator-contract.md)
- [OpenClaw operator contract](docs/specs/0009-openclaw-operator-contract.md)
- [Evals and replay contract](docs/specs/0010-evals-replay-contract.md)
- [Human locks spec](docs/specs/0011-human-locks.md)
- [Issue model spec](docs/specs/0012-issue-model.md)
- [Event envelope spec](docs/specs/0013-event-envelope.md)
- [Evaluation metrics spec](docs/specs/0014-evaluation-metrics.md)
- [Evaluation metrics implementation](docs/specs/0015-evaluation-metrics-implementation.md)
- [LearningProposal JSON Schema](docs/schemas/learning-proposal.schema.json)
- [Event envelope JSON Schema](docs/schemas/event-envelope.schema.json)
- [Hermes/news-research fixture](docs/fixtures/source-events/hermes-news-research-minimal.json)
- [Controlled replay success fixture](docs/fixtures/replay-results/researcher-fetch-timeout-success.json)
- [Valid context proposal fixture](docs/fixtures/learning-proposals/valid-context-proposal.json)
- [Valid harness proposal fixture](docs/fixtures/learning-proposals/valid-harness-proposal.json)
- [Valid generated-file harness proposal fixture](docs/fixtures/learning-proposals/valid-harness-generated-file-proposal.json)
- [Hermes operator proposal fixture](docs/fixtures/learning-proposals/hermes-one-shot-proposal.json)
- [OpenClaw operator proposal fixture](docs/fixtures/learning-proposals/openclaw-local-operator-proposal.json)
- [Invalid hallucinated-span fixture](docs/fixtures/learning-proposals/invalid-hallucinated-span.json)
- [Bundled assets CLI JSON contract golden](docs/fixtures/cli-json/bundled-assets.contract.golden.json)
- [Bundled assets export CLI JSON contract golden](docs/fixtures/cli-json/bundled-assets-export.contract.golden.json)
- [Demo CLI JSON contract golden](docs/fixtures/cli-json/demo.contract.golden.json)
- [Status CLI JSON contract golden](docs/fixtures/cli-json/status.contract.golden.json)
- [Ingest CLI JSON contract golden](docs/fixtures/cli-json/ingest.contract.golden.json)
- [OTLP ingest CLI JSON contract golden](docs/fixtures/cli-json/ingest-otlp.contract.golden.json)
- [WAL checkpoint CLI JSON contract golden](docs/fixtures/cli-json/wal-checkpoint.contract.golden.json)
- [Load smoke CLI JSON contract golden](docs/fixtures/cli-json/load-smoke.contract.golden.json)
- [ACE compatibility CLI JSON contract golden](docs/fixtures/cli-json/ace-compat.contract.golden.json)
- [ACE diff proposals CLI JSON contract golden](docs/fixtures/cli-json/ace-diff-proposals.contract.golden.json)
- [ACE native run CLI JSON contract golden](docs/fixtures/cli-json/ace-native-run.contract.golden.json)
- [ACE native run prepare CLI JSON contract golden](docs/fixtures/cli-json/ace-native-run-prepare.contract.golden.json)
- [ACE native smoke CLI JSON contract golden](docs/fixtures/cli-json/ace-native-smoke.contract.golden.json)
- [Blob put CLI JSON contract golden](docs/fixtures/cli-json/blob-put.contract.golden.json)
- [Blob list CLI JSON contract golden](docs/fixtures/cli-json/blobs.contract.golden.json)
- [Storage report CLI JSON contract golden](docs/fixtures/cli-json/storage-report.contract.golden.json)
- [Payload prune CLI JSON contract golden](docs/fixtures/cli-json/prune.contract.golden.json)
- [Retention prune CLI JSON contract golden](docs/fixtures/cli-json/prune-retention.contract.golden.json)
- [Dashboard metrics CLI JSON contract golden](docs/fixtures/cli-json/dashboard-metrics.contract.golden.json)
- [Dashboard smoke CLI JSON contract golden](docs/fixtures/cli-json/dashboard-smoke.contract.golden.json)
- [Run list CLI JSON contract golden](docs/fixtures/cli-json/runs.contract.golden.json)
- [Run detail CLI JSON contract golden](docs/fixtures/cli-json/run-detail.contract.golden.json)
- [Policy CLI JSON contract golden](docs/fixtures/cli-json/policy.contract.golden.json)
- [Policy set CLI JSON contract golden](docs/fixtures/cli-json/policy-set.contract.golden.json)
- [Prepare harness CLI JSON contract golden](docs/fixtures/cli-json/prepare-harness.contract.golden.json)
- [Harness patches CLI JSON contract golden](docs/fixtures/cli-json/harness-patches.contract.golden.json)
- [Harness target locks CLI JSON contract golden](docs/fixtures/cli-json/harness-target-locks.contract.golden.json)
- [Harness target lock CLI JSON contract golden](docs/fixtures/cli-json/harness-target-lock.contract.golden.json)
- [Harness target unlock CLI JSON contract golden](docs/fixtures/cli-json/harness-target-unlock.contract.golden.json)
- [Apply harness CLI JSON contract golden](docs/fixtures/cli-json/apply-harness.contract.golden.json)
- [Rollback harness CLI JSON contract golden](docs/fixtures/cli-json/rollback-harness.contract.golden.json)
- [Skills CLI JSON contract golden](docs/fixtures/cli-json/skills.contract.golden.json)
- [Skill revisions CLI JSON contract golden](docs/fixtures/cli-json/skill-revisions.contract.golden.json)
- [Skill lock CLI JSON contract golden](docs/fixtures/cli-json/skill-lock.contract.golden.json)
- [Skill unlock CLI JSON contract golden](docs/fixtures/cli-json/skill-unlock.contract.golden.json)
- [Skill rollback CLI JSON contract golden](docs/fixtures/cli-json/skill-rollback.contract.golden.json)
- [Context rules CLI JSON contract golden](docs/fixtures/cli-json/context-rules.contract.golden.json)
- [Context rule revisions CLI JSON contract golden](docs/fixtures/cli-json/context-rule-revisions.contract.golden.json)
- [Context rule lock CLI JSON contract golden](docs/fixtures/cli-json/context-rule-lock.contract.golden.json)
- [Context rule unlock CLI JSON contract golden](docs/fixtures/cli-json/context-rule-unlock.contract.golden.json)
- [Context rule rollback CLI JSON contract golden](docs/fixtures/cli-json/context-rule-rollback.contract.golden.json)
- [Run autonomy CLI JSON contract golden](docs/fixtures/cli-json/run-autonomy.contract.golden.json)
- [Operator prompt CLI JSON contract golden](docs/fixtures/cli-json/operator-prompt.contract.golden.json)
- [Analyze mock CLI JSON contract golden](docs/fixtures/cli-json/analyze-mock.contract.golden.json)
- [MCP install plan CLI JSON contract golden](docs/fixtures/cli-json/mcp-install-plan.contract.golden.json)
- [MCP install CLI JSON contract golden](docs/fixtures/cli-json/mcp-install.contract.golden.json)
- [Operator preset CLI JSON contract golden](docs/fixtures/cli-json/operator-presets.contract.golden.json)
- [Operator adapter bootstrap CLI JSON contract golden](docs/fixtures/cli-json/operator-adapter-bootstrap.contract.golden.json)
- [Operator adapters CLI JSON contract golden](docs/fixtures/cli-json/operator-adapters.contract.golden.json)
- [Operator adapter register CLI JSON contract golden](docs/fixtures/cli-json/operator-adapter-register.contract.golden.json)
- [Operator adapter run CLI JSON contract golden](docs/fixtures/cli-json/operator-adapter-run.contract.golden.json)
- [Operator runs CLI JSON contract golden](docs/fixtures/cli-json/operator-runs.contract.golden.json)
- [Replay adapter register CLI JSON contract golden](docs/fixtures/cli-json/replay-adapter-register.contract.golden.json)
- [Replay adapters CLI JSON contract golden](docs/fixtures/cli-json/replay-adapters.contract.golden.json)
- [Replay adapter run CLI JSON contract golden](docs/fixtures/cli-json/replay-adapter-run.contract.golden.json)
- [Replay CLI JSON contract golden](docs/fixtures/cli-json/replay.contract.golden.json)
- [Complete replay CLI JSON contract golden](docs/fixtures/cli-json/complete-replay.contract.golden.json)
- [Replay command CLI JSON contract golden](docs/fixtures/cli-json/replay-command.contract.golden.json)
- [Replay server template CLI JSON contract golden](docs/fixtures/cli-json/replay-server-template.contract.golden.json)
- [Replay server health CLI JSON contract golden](docs/fixtures/cli-json/replay-server-health.contract.golden.json)
- [Replay server run CLI JSON contract golden](docs/fixtures/cli-json/replay-server-run.contract.golden.json)
- [Replay server start CLI JSON contract golden](docs/fixtures/cli-json/replay-server-start.contract.golden.json)
- [Replay server status CLI JSON contract golden](docs/fixtures/cli-json/replay-server-status.contract.golden.json)
- [Replay server logs CLI JSON contract golden](docs/fixtures/cli-json/replay-server-logs.contract.golden.json)
- [Replay server stop CLI JSON contract golden](docs/fixtures/cli-json/replay-server-stop.contract.golden.json)
- [Source adapter template CLI JSON contract golden](docs/fixtures/cli-json/source-adapter-template.contract.golden.json)
- [Source integration smoke CLI JSON contract golden](docs/fixtures/cli-json/integration-smoke-source.contract.golden.json)
- [Installed framework source integration smoke CLI JSON contract golden](docs/fixtures/cli-json/integration-smoke-framework-source.contract.golden.json)
- [Installed framework replay integration smoke CLI JSON contract golden](docs/fixtures/cli-json/integration-smoke-framework-replay.contract.golden.json)
- [Installed framework improve integration smoke CLI JSON contract golden](docs/fixtures/cli-json/integration-smoke-framework-improve.contract.golden.json)
- [OpenTelemetry Python SDK integration smoke CLI JSON contract golden](docs/fixtures/cli-json/integration-smoke-opentelemetry-python.contract.golden.json)
- [Replay-server integration smoke CLI JSON contract golden](docs/fixtures/cli-json/integration-smoke-replay-server.contract.golden.json)
- [Improve integration smoke CLI JSON contract golden](docs/fixtures/cli-json/integration-smoke-improve.contract.golden.json)
- [Hermes import CLI JSON golden](docs/fixtures/cli-json/import-hermes-kanban.golden.json)
- [OpenClaw import CLI JSON golden](docs/fixtures/cli-json/import-openclaw-sessions.golden.json)
- [Source discovery CLI JSON contract golden](docs/fixtures/cli-json/discover-sources.contract.golden.json)
- [Discovered-source import CLI JSON contract golden](docs/fixtures/cli-json/import-discovered-source.contract.golden.json)
- [Proposal list CLI JSON golden](docs/fixtures/cli-json/proposals-context.golden.json)
- [Proposal detail CLI JSON contract golden](docs/fixtures/cli-json/proposal-detail-context.contract.golden.json)
- [Profile-next CLI JSON contract golden](docs/fixtures/cli-json/profile-next-context.contract.golden.json)
- [Issue list CLI JSON contract golden](docs/fixtures/cli-json/issues.contract.golden.json)
- [Issue detail CLI JSON contract golden](docs/fixtures/cli-json/issue-detail.contract.golden.json)
- [Improve CLI JSON contract golden](docs/fixtures/cli-json/improve-existing-proposal.contract.golden.json)
- [Autonomy events CLI JSON contract golden](docs/fixtures/cli-json/autonomy-events.contract.golden.json)
- [Eval capabilities CLI JSON contract golden](docs/fixtures/cli-json/eval-capabilities.contract.golden.json)
- [Generate evals CLI JSON contract golden](docs/fixtures/cli-json/generate-evals.contract.golden.json)
- [Eval list CLI JSON contract golden](docs/fixtures/cli-json/evals.contract.golden.json)
- [Eval assertion presets CLI JSON contract golden](docs/fixtures/cli-json/eval-assertion-presets.contract.golden.json)
- [Run eval CLI JSON contract golden](docs/fixtures/cli-json/run-eval.contract.golden.json)
- [Judge command CLI JSON contract golden](docs/fixtures/cli-json/judge-command.contract.golden.json)
- [Judge smoke CLI JSON contract golden](docs/fixtures/cli-json/judge-smoke.contract.golden.json)
- [Eval detail CLI JSON contract golden](docs/fixtures/cli-json/eval-detail.contract.golden.json)
- [Eval spec lock CLI JSON contract golden](docs/fixtures/cli-json/eval-spec-lock.contract.golden.json)
- [Eval spec locks CLI JSON contract golden](docs/fixtures/cli-json/eval-spec-locks.contract.golden.json)
- [Eval spec unlock CLI JSON contract golden](docs/fixtures/cli-json/eval-spec-unlock.contract.golden.json)
- [Eval spec approve CLI JSON contract golden](docs/fixtures/cli-json/eval-spec-approve.contract.golden.json)
- [Replay detail CLI JSON contract golden](docs/fixtures/cli-json/replay-detail.contract.golden.json)
- [Operator smoke matrix CLI JSON contract golden](docs/fixtures/cli-json/operator-smoke-prepare-matrix.contract.golden.json)
- [Operator smoke command CLI JSON contract golden](docs/fixtures/cli-json/operator-smoke-command.contract.golden.json)
- [Operator smoke expected-failure CLI JSON contract golden](docs/fixtures/cli-json/operator-smoke-failure-command.contract.golden.json)
- [Release smoke CLI JSON contract golden](docs/fixtures/cli-json/release-smoke.contract.golden.json)
- [Release smoke matrix CLI JSON contract golden](docs/fixtures/cli-json/release-smoke-matrix.contract.golden.json)
- [MCP install smoke matrix CLI JSON contract golden](docs/fixtures/cli-json/mcp-install-smoke-matrix.contract.golden.json)
- [Project bootstrap CLI JSON contract golden](docs/fixtures/cli-json/project-bootstrap.contract.golden.json)

Validate the current gate artifacts:

```bash
python3 scripts/validate_gate_artifacts.py
python3 -m kyoko validate-gates
python3 -m unittest discover -s tests
```

## Local Runtime Slice

Install from a checkout for local smoke testing:

```bash
python3 -m pip install .
python3 -m kyoko doctor --smoke-demo --json
python3 -m kyoko release-smoke --artifact both --json
python3 -m kyoko release-smoke --artifact wheel --dashboard-smoke --json
python3 -m kyoko release-smoke --python-matrix --artifact both --json
```

For offline or pre-provisioned environments, the package metadata also supports
local `--no-build-isolation` installs with stock `setuptools>=58` and
`wheel>=0.37`.
The packaging smoke tests build both a wheel and an sdist from a temporary
source checkout and verify the CLI entry point plus bundled schema, demo, and
proposal assets, including the Apache-2.0 `LICENSE` file in release artifacts.
`release-smoke` builds wheel/sdist artifacts from an isolated source copy,
installs each into a clean virtual environment outside the checkout, verifies
the console script and installed package metadata, and runs
`kyoko doctor --smoke-demo`.
With `--dashboard-smoke`, release smoke also runs installed-package
`kyoko doctor --dashboard-smoke` for each artifact, retaining browser smoke
artifacts under that artifact's isolated run directory and installing browser
test dependencies there when Python Playwright is unavailable.
For sdists, release-smoke first bootstraps `setuptools>=58` and `wheel>=0.37`
into the clean install venv when `setuptools.build_meta` or `wheel.bdist_wheel`
is unavailable, then runs modern pip installation with `--no-build-isolation`.
In offline no-dependency mode it may still fall back from that modern install
to legacy `setup.py install`; the JSON artifact report exposes
`install_strategy`, `legacy_fallback_used`, and the modern install return code
so the fallback is explicit.
Use `--python-matrix` to run the same artifact install smoke across Python
targets. By default it tries `python3.12` and `python3.13`,
reports missing interpreters as `skipped`, bootstraps `setuptools>=58` and
`wheel>=0.37` in an isolated build venv when an available target lacks
`setuptools.build_meta` or `wheel.bdist_wheel`, and fails the matrix only when
no target ran or an available target failed.
`--python-version` and `--python-target` can narrow or extend the matrix.

Bootstrap a local agent project in one command. This creates `.kyoko/kyoko.db`,
seeds a workflow profile, writes source/replay adapter scaffolds, writes an MCP
config, registers available Codex/Claude/Hermes/OpenClaw operator presets, and
leaves a `.kyoko/NEXT_STEPS.md` file with copyable profile-routing,
source-discovery, source-adapter, Hermes Kanban import, OpenClaw session
import, dashboard, managed replay-adapter registration, replay-server, and MCP
commands. The generated verification section includes `doctor --safe-smokes`
with `--smoke-output-dir .kyoko/smoke/doctor` for the no-live-model
demo/operator-prepare/judge-prepare/native-ACE-prepare/integration/improve/MCP smoke bundle,
and the replay section includes a hook-backed
`integration-smoke replay-server --run-replay` command that retains logs under
`.kyoko/smoke/replay`. It does not run live models, replay, autonomy, or apply
during bootstrap:

```bash
python3 -m kyoko project-bootstrap --project-dir . --profile-name news-research --source-framework langgraph-python --replay-framework hermes-python --mcp-target codex --json
```

Run the bundled first-run demo. This initializes a local SQLite database,
ingests the Hermes/news-research fixture, persists the current issue/insight
proposal, generates the eval, runs a mocked replay adapter, evaluates the
before/after result, and applies the resulting context skill:

```bash
python3 -m kyoko demo --db /tmp/kyoko-demo.db --json
```

The exact demo profile, expected failure, expected improvement, and smoke
evidence are documented in
[First-run demo and install path](docs/specs/0007-first-run-demo.md).

Check local first-run readiness without mutating the default user database:

```bash
python3 -m kyoko doctor --json
python3 -m kyoko doctor --safe-smokes --json
python3 -m kyoko doctor --smoke-demo --json
python3 -m kyoko doctor --operator-smoke-prepare --json
python3 -m kyoko doctor --judge-smoke-prepare --json
python3 -m kyoko doctor --ace-native-prepare --json
python3 -m kyoko doctor --integration-smoke --json
python3 -m kyoko doctor --improve-smoke --json
python3 -m kyoko doctor --opentelemetry-smoke --opentelemetry-python-executable /path/to/venv/bin/python --json
python3 -m kyoko doctor --ace-native-smoke --json
python3 -m kyoko doctor --dashboard-smoke --smoke-output-dir .kyoko/smoke/doctor --dashboard-smoke-screenshot --json
```

`doctor` verifies Python, SQLite initialization, schema validation support,
packaged schema/demo/proposal assets, the fixture replay command and HTTP
server modules, package metadata, optional operator CLIs on `PATH`,
release-smoke Python matrix targets and build backend readiness, Codex/Claude
MCP client availability, and local dashboard port availability. Missing
external release, MCP, or live operator evidence prerequisites are warning-only
readiness checks with follow-up matrix commands in the JSON payload. Doctor text
output includes a readiness line, and doctor JSON includes a top-level
`readiness` object that separates `local_runtime_ready`, `local_v0_ready`,
pending safe smoke checks, blocking checks, warning checks, and pending external
evidence commands. By default, doctor also scans `.kyoko/smoke` for retained
live operator, provider-backed judge, and provider-backed native ACE run
evidence, reports satisfied evidence in
`readiness.satisfied_external_evidence_commands`, and omits matching follow-up
commands. Use `--smoke-evidence-dir` to point this scan at another retained
artifact root or at a non-existent directory for a clean readiness projection.
Doctor JSON also includes top-level `suggested_commands`
using argument vectors, labels, mutation flags, and prerequisite notes for the
safe optional smokes plus release, MCP, OpenTelemetry, live operator, and live
judge smoke follow-ups. The live operator and live judge follow-ups are marked
mutating, retain artifacts under `.kyoko/smoke/...`, and are separate from the
safe doctor bundle because they may invoke installed operator CLIs or configured
model/provider backends. With `--safe-smokes`, it runs every no-live-model
doctor smoke in one command: bundled demo, operator prepare-only rehearsal,
judge-command prepare-only handoff, generated integration checks, native ACE
prepare-only handoff, generated improve smoke, and isolated MCP client install
smoke. With `--smoke-output-dir`, optional smoke artifacts such as the demo
database, operator prompts/evidence, judge request/handoff files, native ACE
before/after/handoff files, generated source adapter output, replay-server logs,
generated improve smoke artifacts, and isolated MCP config homes are retained
for inspection instead of being discarded with temporary directories.
With `--smoke-demo`, it runs the bundled telemetry to proposal to eval/replay to
context-apply loop against a temporary database. With
`--operator-smoke-prepare`, it runs the all-preset operator prepare-only smoke
against a temporary demo database without invoking live model CLIs. With
`--judge-smoke-prepare`, it generates the bundled judge request and
`judge-command.handoff.json` without invoking a provider. With
`--ace-native-prepare`, it writes a cloned ACE Skillbook before/after pair and
`ace-command.handoff.json` without invoking ACE or a provider. With
`--integration-smoke`, it generates temporary Python source-adapter and
replay-server templates, runs the source adapter smoke, and verifies the
generated replay server with a hook-backed bounded `/replay` request against
temporary files. It does not invoke live model CLIs.
With `--improve-smoke`, it generates source/replay adapters and hooks, runs the
high-level `improve` loop through replay/eval/autonomy apply, and still avoids
live model CLIs.
With `--opentelemetry-smoke`, it imports `opentelemetry-sdk` from the selected
Python executable, emits OTLP/HTTP-style JSON through the SDK tracer/provider
APIs, and ingests it through Kyoko's OTLP normalizer without a live provider
call. This smoke is optional and separate from `--safe-smokes` because it
depends on an installed third-party OpenTelemetry package.
With `--ace-native-smoke`, it seeds the bundled fixture, invokes the installed
legacy ACE `OfflineAdapter` package through Kyoko's external `ace-native-run`
clone/diff boundary, and imports the resulting `native_ace` proposal without a
live provider call. This smoke is optional and separate from `--safe-smokes`
because it depends on an installed third-party ACE package.
With `--dashboard-smoke`, it starts a loopback dashboard against a bundled demo
database, opens desktop and mobile browser viewports through Playwright, and
checks console errors, page errors, request failures, and metric-card overflow.
This smoke is optional and separate from `--safe-smokes` because it depends on a
browser test runtime. Add `--dashboard-smoke-install-browser-deps` with
`--smoke-output-dir` to install isolated Node Playwright dependencies under the
retained smoke directory when Python Playwright is unavailable.
The dashboard Integrations panel exposes the same safe doctor bundle through
`POST /api/doctor`, shows the runtime/local-v0/safe-smoke readiness summary,
can run the optional dashboard browser smoke, and retains artifacts under the
selected smoke output directory.

Use `--setup-only` to create the fixture/proposal/eval/adapter without running
replay, and `--no-apply` to run replay/eval without applying the context skill.
The local dashboard exposes the same flow through a `Run demo` button and
`POST /api/demo`.

For coding agents and local operator workflows, `kyoko improve` runs the normal
improvement pipeline in one command. It can either start from an existing
proposal or run an operator agent, then generate eval specs, run a registered
replay adapter for each eval, run the evals, and finally call the same
policy-gated autonomy evaluator used by the dashboard:

```bash
python3 -m kyoko improve --db /tmp/kyoko.db --proposal-id proposal_context_timeout_001 --replay-adapter fixture_replay --json
python3 -m kyoko improve --db /tmp/kyoko.db --proposal-id proposal_harness_generated_eval_001 \
  --replay-adapter fixture_replay --harness-workspace-root /tmp/kyoko-workspace --json
python3 -m kyoko improve --db /tmp/kyoko.db --operator codex --replay-adapter local_http_replay --json
python3 -m kyoko improve --db /tmp/kyoko.db --operator command --command "codex exec ..." --replay-adapter fixture_replay --json
python3 -m kyoko improve --db /tmp/kyoko.db --source-candidate-id openclaw_main --operator codex --replay-adapter fixture_replay --json
```

`improve` does not bypass safety. Operator output is still stored as a
`LearningProposal`, eval/replay use registered Kyoko adapters, and final writes
only happen if the profile autonomy policy allows them. When
`--replay-adapter` is omitted, Kyoko uses the latest enabled replay adapter for
the resolved profile; if none is registered, the loop still generates evals but
cannot collect replay/eval evidence for the autonomy gate. When
`--source-candidate-id` is provided, Kyoko explicitly imports the selected
local source candidate before running analysis, then scopes the loop to the
imported profile unless `--profile-id` is supplied. If an operator proposal
contains context or harness changes but no explicit eval spec, Kyoko creates a
conservative L0 deterministic gate from the cited failure evidence instead of
applying without an eval. When harness autonomy and repo patch writes are
enabled, `improve` can apply eligible generated-file or strict unified-diff
harness patches through the same rollback-capable patch transaction path.
`--harness-workspace-root` explicitly selects the target workspace; when it is
omitted, `improve` snapshots an existing profile `root_path` before replay so
fixture completion cannot redirect the patch target.

Kyoko keeps the operator's `confidence` value for audit, but it also computes a
separate `kyoko_confidence` score from resolved evidence refs, target coverage,
eval/replay results, duplicate proposal history, and validation state. Proposal
lists, proposal detail, and the dashboard show the Kyoko score so confidence is
not just whatever the operator claimed.

Initialize a SQLite database, export the packaged first-run assets, ingest the
included Hermes/news-research fixture, and inspect machine-readable status:

```bash
python3 -m kyoko bundled-assets --output-dir /tmp/kyoko-assets --json
python3 -m kyoko init --db /tmp/kyoko.db
python3 -m kyoko ingest --db /tmp/kyoko.db /tmp/kyoko-assets/source-events/hermes-news-research-minimal.json --json
python3 -m kyoko ingest-fixture --db /tmp/kyoko.db /tmp/kyoko-assets/source-events/hermes-news-research-minimal.json
python3 -m kyoko status --db /tmp/kyoko.db --json
python3 -m kyoko dashboard-metrics --db /tmp/kyoko.db --json
python3 -m kyoko profile-next --db /tmp/kyoko.db --json
python3 -m kyoko profile-next --db /tmp/kyoko.db --run --json
python3 -m kyoko discover-sources --db /tmp/kyoko.db --profile-id profile_news_research_001 --json
python3 -m kyoko import-discovered-source --db /tmp/kyoko.db openclaw_main --profile-id profile_news_research_001 --json
python3 -m kyoko runs --db /tmp/kyoko.db --json
python3 -m kyoko runs --db /tmp/kyoko.db --profile-id profile_news_research_001 --json
python3 -m kyoko run-detail --db /tmp/kyoko.db run_research_topic_001 --json
```

Status JSON includes the current schema version and recorded migration
versions. Kyoko refuses to open a database marked with a newer schema version
than the installed package supports.
Kyoko runs a single implicit workflow profile (SCOPE Decision 1); there is no
profile picker. Commands still accept an optional `--profile-id` that defaults
to that implicit profile. `profile-next --json` (with no `--run`) returns the
routing guidance for that profile: the next local action, such as analyze,
generate evals, run replay/eval, review proposal, run autonomy, or monitor.
Routing also includes structured `suggested_commands` argument vectors with
mutating/prerequisite metadata, so operator agents can execute the next local
Kyoko command without scraping human text.
`profile-next` reads that routing state and either returns a dry-run plan or,
with `--run`, executes the next local Kyoko-owned step when it is safe to do so,
such as running a registered operator adapter, preparing redacted operator
evidence/prompt artifacts, eval generation, registered replay/eval execution,
or autonomy. It returns `blocked` for steps that still require source import,
human review, repo patch permission, or an existing harness workspace root. Its
JSON also exposes top-level `suggested_commands` from the current post-step
routing state, so operators can continue without digging through nested routing
payloads. For analysis steps,
`--operator-adapter` selects a registered adapter;
when neither `--operator-adapter` nor `--operator-target` is supplied, Kyoko uses
the latest enabled profile operator adapter. Supplying `--operator-target` keeps
the step prompt-only and targets the prepared operator artifacts. When no
`--replay-adapter` is supplied for a replay/eval next step, Kyoko uses the same
latest-enabled profile adapter ordering exposed in routing suggested commands.
For autonomous harness proposals, routing marks whether the profile root can be
used as `--harness-workspace-root`; when it is available, the suggested
`run-autonomy` command includes it.

`discover-sources` is read-only. It inspects local Hermes and OpenClaw default
state locations, returns candidate metadata, and prints import-ready commands
for the selected Kyoko database/profile. `import-discovered-source` is the
explicit follow-up action that imports one selected candidate by id. The
dashboard `Integrations` panel can also run `Improve` on a ready discovered
source, which imports the candidate and creates the first proposal/eval without
applying autonomy from that UI action.

Large payloads and raw artifacts should live in the content-addressed payload
blob store instead of hot SQLite rows. The default store is `<db-parent>/blobs`
which is `~/.kyoko/blobs` for the default database. Kyoko never prunes local
evidence automatically. Pruning is always a manual, explicit action: both
`prune` (payload blobs) and `prune-retention` (relational runtime rows) are
dry-run by default and only delete when `--apply` is provided. Blob listings
expose bounded preview metadata only for blobs explicitly marked `unredacted`;
the default `redacted` mode stores a `[REDACTED:blob_preview]` placeholder while
leaving the immutable local blob bytes available on disk.

```bash
python3 -m kyoko blob-put --db /tmp/kyoko.db /tmp/operator-output.json --kind operator_output --media-type application/json --retention-days 30 --json
python3 -m kyoko blobs --db /tmp/kyoko.db --json
python3 -m kyoko storage-report --db /tmp/kyoko.db --json
python3 -m kyoko wal-checkpoint --db /tmp/kyoko.db --mode TRUNCATE --json
python3 -m kyoko load-smoke --runs 120 --spans-per-run 5 --read-workers 4 --read-iterations 10 --json
python3 -m kyoko load-smoke --db /tmp/kyoko.db --use-db --runs 120 --spans-per-run 5 --read-workers 4 --read-iterations 10 --json
python3 -m kyoko prune --db /tmp/kyoko.db --json
python3 -m kyoko prune --db /tmp/kyoko.db --older-than-days 90 --apply --json
python3 -m kyoko prune-retention --db /tmp/kyoko.db --older-than-days 30 --json
python3 -m kyoko prune-retention --db /tmp/kyoko.db --older-than-days 30 --apply --json
```

Retention is a single manual prune, not a configurable policy. There is no
retention policy table, no `retention-policy`/`retention-policy-set` command,
and no `/api/retention-policy` route. `prune-retention --older-than-days N` sets
the age cutoff for every category; per-category overrides
`--trace-older-than-days`, `--replay-older-than-days`, and
`--operator-older-than-days` are also accepted. It is dry-run by default and only
deletes when `--apply` is passed, and it never auto-deletes. Pruning is
conservative: runs and replay rows referenced by applied skills, active replay
rows, eval specs, or proposals (learning/replay artifacts) are protected —
skipped and reported rather than deleted.

Source adapters may provide inline payload siblings instead of pre-registering
blob refs. During ingest, Kyoko writes `input_payload`, `output_payload`,
`raw_payload`, `body_payload`, `summary_payload`, `error_payload`,
`reason_payload`, and timeline/handoff `payload` values into the blob store,
then replaces the matching `*_ref` field with the generated blob id. Inline
payloads can be plain strings, JSON values, or wrapper objects with `content`,
`encoding`, `media_type`, `kind`, `retention_days`, `retained_until`, and
`metadata`.
HTTP replay-server responses are retained the same way: the full server
response is stored as a `replay_server_response` payload blob, and the replay
result row keeps only the side-effect mode, output run id, target map, note,
response key list, and blob ref. The response blob is registered with redacted
preview metadata so server-returned payloads or secrets do not leak through blob
list/API/MCP surfaces. HTTP replay server completion also requires a
returned `replay_run_id` or `idempotency_key` matching Kyoko's replay request
before the response can complete the canonical replay run. Replay completion
also rejects responses whose actual side-effect mode exceeds the requested
replay boundary; an actual result may report `none`, the requested safe mode, or
`filesystem_read` for a `sandboxed_filesystem` request. Replay requests sent to
external replay commands or HTTP replay servers go through the same fixed
redact-on-export behavior first, hiding payload refs and secret-shaped values
before anything leaves the machine.

`load-smoke` seeds deterministic local telemetry, expired payload blobs, and
then measures concurrent dashboard-style read paths including status, runs, run
detail, proposals, skills, context rules, eval/replay lists, evidence summary,
storage report, and retention dry-run. By default it uses a temporary database;
pass `--use-db` to seed the selected `--db`. The same action is exposed as
`POST /api/load-smoke` and as `Load smoke` in the dashboard Storage panel.

Framework adapters and local SDKs can post the same canonical source-event JSON
to the self-hosted API:

```bash
curl -X POST http://127.0.0.1:8765/api/ingest \
  -H "Content-Type: application/json" \
  --data @docs/fixtures/source-events/hermes-news-research-minimal.json
```

Generate a source telemetry adapter scaffold for a framework and wire one hook
function instead of hand-building the Kyoko JSON envelope:

```bash
python3 -m kyoko source-adapter-template scripts/kyoko_source_adapter.py --framework langgraph-python --profile-name news-research --json
KYOKO_SOURCE_HOOK=/absolute/path/to/source_hook.py:collect python3 scripts/kyoko_source_adapter.py --output /tmp/source-events.json
python3 -m kyoko ingest --db /tmp/kyoko.db /tmp/source-events.json --json
python3 -m kyoko integration-smoke source --db /tmp/kyoko.db scripts/kyoko_source_adapter.py --hook /absolute/path/to/source_hook.py:collect --json
```

The generated source adapter supports `generic-python`, `langgraph-python`,
`pydantic-ai-python`, `openai-agents-python`, `crewai-python`,
`hermes-python`, `openclaw-python`, `generic-typescript`, and
`ai-sdk-typescript`. Python templates are stdlib-only and run with `python3`;
TypeScript/Node templates are dependency-free ESM files that run with `node`
and use `.mjs` by default. The hook returns canonical Kyoko source events or
`{"source_events": ...}`; it can also POST directly to `/api/ingest` with
`--post-url`. `integration-smoke source` runs the generated adapter with the
right local runtime, captures stdout/stderr and `source-events.json`, ingests
the result into a Kyoko database, and returns machine-readable status. The
dashboard exposes the same scaffolding flow in the `Integrations` panel through
`GET /api/integration-frameworks`, `POST /api/source-adapter-template`, and
`POST /api/replay-server-template`; it can also run the same validation through
`POST /api/integration-smoke/source` and
`POST /api/integration-smoke/replay-server`.

To prove a real installed framework can be imported, replayed, and improved
through generated Kyoko adapters, run installed-framework smokes with a Python
environment that has the target package installed:

```bash
python3 -m kyoko integration-smoke framework-source --db /tmp/kyoko.db --framework langgraph-python --python-executable /path/to/venv/bin/python --output-dir /tmp/kyoko-langgraph-source-smoke --json
python3 -m kyoko integration-smoke framework-source --db /tmp/kyoko.db --framework pydantic-ai-python --python-executable /path/to/venv/bin/python --output-dir /tmp/kyoko-pydantic-ai-source-smoke --json
python3 -m kyoko integration-smoke framework-source --db /tmp/kyoko.db --framework openai-agents-python --python-executable /path/to/venv/bin/python --output-dir /tmp/kyoko-openai-agents-source-smoke --json
python3 -m kyoko integration-smoke framework-source --db /tmp/kyoko.db --framework crewai-python --python-executable /path/to/venv/bin/python --output-dir /tmp/kyoko-crewai-source-smoke --json
python3 -m kyoko integration-smoke framework-replay --framework langgraph-python --python-executable /path/to/venv/bin/python --output-dir /tmp/kyoko-langgraph-replay-smoke --json
python3 -m kyoko integration-smoke framework-replay --framework pydantic-ai-python --python-executable /path/to/venv/bin/python --output-dir /tmp/kyoko-pydantic-ai-replay-smoke --json
python3 -m kyoko integration-smoke framework-replay --framework openai-agents-python --python-executable /path/to/venv/bin/python --output-dir /tmp/kyoko-openai-agents-replay-smoke --json
python3 -m kyoko integration-smoke framework-replay --framework crewai-python --python-executable /path/to/venv/bin/python --output-dir /tmp/kyoko-crewai-replay-smoke --json
python3 -m kyoko integration-smoke framework-improve --db /tmp/kyoko.db --framework langgraph-python --python-executable /path/to/venv/bin/python --output-dir /tmp/kyoko-langgraph-improve-smoke --json
python3 -m kyoko integration-smoke framework-improve --db /tmp/kyoko.db --framework pydantic-ai-python --python-executable /path/to/venv/bin/python --output-dir /tmp/kyoko-pydantic-ai-improve-smoke --json
python3 -m kyoko integration-smoke framework-improve --db /tmp/kyoko.db --framework openai-agents-python --python-executable /path/to/venv/bin/python --output-dir /tmp/kyoko-openai-agents-improve-smoke --json
python3 -m kyoko integration-smoke framework-improve --db /tmp/kyoko.db --framework crewai-python --python-executable /path/to/venv/bin/python --output-dir /tmp/kyoko-crewai-improve-smoke --json
```

These smokes execute deterministic LangGraph `StateGraph`, Pydantic AI
`TestModel`, OpenAI Agents SDK local-model-provider, or CrewAI local-LLM
crew/task workflows, ingest or return the emitted Kyoko source/replay events,
and report
`installed_framework_invoked: true` while keeping `external_model_invoked:
false`. The replay smoke starts a generated replay server, posts a bounded
`/replay` request, and verifies the replay response.
The installed framework improve smoke runs the same framework source adapter,
registers a generated managed replay server, then runs `improve` through
analysis, eval generation, replay/eval, and autonomous context apply.
Retained local evidence on 2026-06-03 passed source, replay, and improve
smokes for LangGraph `0.6.11`, Pydantic AI `1.105.0`, OpenAI Agents `0.17.4`,
and CrewAI `1.14.6` under `.kyoko/smoke/framework-*-source-real`,
`.kyoko/smoke/framework-*-replay-real`, and
`.kyoko/smoke/framework-*-improve-real`.

Run an installed OpenTelemetry Python SDK smoke to prove Kyoko can ingest OTLP
JSON generated by the actual SDK exporter path:

```bash
python3 -m kyoko integration-smoke opentelemetry-python --db /tmp/kyoko.db --python-executable /path/to/venv/bin/python --output-dir /tmp/kyoko-opentelemetry-smoke --json
```

This smoke imports `opentelemetry-sdk`, records an agent span and failed tool
span through the SDK tracer/provider APIs, writes OTLP/HTTP-style JSON, and
ingests it through Kyoko's OTLP normalizer. It reports
`opentelemetry_sdk_invoked: true`, `external_model_invoked: false`, and
`live_operator_invoked: false`.
Retained local evidence on 2026-06-03 passed with `opentelemetry-sdk 1.41.1`
under `.kyoko/smoke/opentelemetry-python-real`, and the explicit doctor smoke
surface passed under `.kyoko/smoke/doctor-opentelemetry-real`.

Run a no-live-model end-to-end improvement smoke that generates a source
adapter, ingests failed framework-style telemetry, registers a managed replay
server, and runs `improve` through replay/eval/autonomy apply:

```bash
python3 -m kyoko integration-smoke improve --db /tmp/kyoko.db --output-dir /tmp/kyoko-improve-smoke --json
```

For AI SDK or other TypeScript agents:

```bash
python3 -m kyoko source-adapter-template scripts/kyoko_source_adapter.mjs --framework ai-sdk-typescript --profile-name news-research --json
KYOKO_SOURCE_HOOK=/absolute/path/to/source_hook.mjs:collect node scripts/kyoko_source_adapter.mjs --output /tmp/source-events.json
python3 -m kyoko integration-smoke source --db /tmp/kyoko.db scripts/kyoko_source_adapter.mjs --hook /absolute/path/to/source_hook.mjs:collect --json
```

Copyable hook examples are available under `examples/source-hooks/`:

```bash
python3 -m kyoko source-adapter-template /tmp/kyoko_source_adapter.py --framework langgraph-python --profile-name news-research --json
python3 -m kyoko integration-smoke source --db /tmp/kyoko.db /tmp/kyoko_source_adapter.py --hook examples/source-hooks/langgraph_source_hook.py:collect --json

python3 -m kyoko source-adapter-template /tmp/kyoko_source_adapter.py --framework pydantic-ai-python --profile-name news-research --json
python3 -m kyoko integration-smoke source --db /tmp/kyoko.db /tmp/kyoko_source_adapter.py --hook examples/source-hooks/pydantic_ai_source_hook.py:collect --json

python3 -m kyoko source-adapter-template /tmp/kyoko_source_adapter.py --framework openai-agents-python --profile-name news-research --json
python3 -m kyoko integration-smoke source --db /tmp/kyoko.db /tmp/kyoko_source_adapter.py --hook examples/source-hooks/openai_agents_source_hook.py:collect --json

python3 -m kyoko source-adapter-template /tmp/kyoko_source_adapter.py --framework crewai-python --profile-name news-research --json
python3 -m kyoko integration-smoke source --db /tmp/kyoko.db /tmp/kyoko_source_adapter.py --hook examples/source-hooks/crewai_source_hook.py:collect --json

python3 -m kyoko source-adapter-template /tmp/kyoko_source_adapter.py --framework hermes-python --profile-name news-research --json
python3 -m kyoko integration-smoke source --db /tmp/kyoko.db /tmp/kyoko_source_adapter.py --hook examples/source-hooks/hermes_source_hook.py:collect --json

python3 -m kyoko source-adapter-template /tmp/kyoko_source_adapter.py --framework openclaw-python --profile-name news-research --json
python3 -m kyoko integration-smoke source --db /tmp/kyoko.db /tmp/kyoko_source_adapter.py --hook examples/source-hooks/openclaw_source_hook.py:collect --json

python3 -m kyoko source-adapter-template /tmp/kyoko_source_adapter.mjs --framework ai-sdk-typescript --profile-name news-research --json
python3 -m kyoko integration-smoke source --db /tmp/kyoko.db /tmp/kyoko_source_adapter.mjs --hook examples/source-hooks/ai_sdk_source_hook.mjs:collect --json
```

The Python examples include inline `input_payload`, `output_payload`,
`raw_payload`, task/handoff payloads, and timeline payloads. Ingest
materializes those values into registered `payload_blobs` and replaces the row
refs before canonical storage.

Normalize and ingest an OTLP/GenAI-style JSON trace export:

```bash
python3 -m kyoko ingest-otlp --db /tmp/kyoko.db docs/fixtures/source-events/otlp-genai-minimal.json --profile-id profile_otlp_news --profile-name "OTLP News" --json
curl -X POST "http://127.0.0.1:8765/v1/traces?profile_id=profile_otlp_news" \
  -H "Content-Type: application/json" \
  --data @docs/fixtures/source-events/otlp-genai-minimal.json
```

It maps common OpenTelemetry GenAI attributes such as `gen_ai.operation.name`,
`gen_ai.agent.name`, `gen_ai.request.model`, and `error.type` into Kyoko runs,
spans, agent identities, workflow nodes, and failure timeline events while
preserving the original span attributes. The self-hosted app accepts the same
JSON through `POST /api/ingest-otlp` and the OTLP-style `POST /v1/traces`
endpoint. If `profile_id` is omitted, Kyoko infers a stable profile id from
`kyoko.profile.id`, `service.namespace`, or `service.name`.

Both the CLI and `POST /v1/traces` also accept **binary OTLP protobuf**
(`ExportTraceServiceRequest`) — what most OpenTelemetry exporters send by default. The
CLI auto-detects protobuf vs JSON (or force it with `--protobuf`); over HTTP, send
`Content-Type: application/x-protobuf`. Decoding is a dependency-free stdlib decoder, so
no `protobuf` runtime is pulled into the core.

```bash
# protobuf exporter → Kyoko
curl -X POST "http://127.0.0.1:8765/v1/traces?profile_id=profile_otlp_news" \
  -H "Content-Type: application/x-protobuf" --data-binary @trace.pb
python3 -m kyoko ingest-otlp trace.pb --profile-id profile_otlp_news --json   # auto-detects protobuf
```

Ingested spans are enriched on read: `run-outline` attaches a normalized view per span
(`{kind: llm|tool|other, model, messages, tool_name, …}`, adapting ai-sdk / traceloop /
claude-agent-sdk / generic gen_ai layouts) and a `subagents` list inferred from the span
tree (agent spans, `agent.subagent` children, or agentic LLM→tool loops) — even when the
source emitted no explicit handoffs.

### Live debugging (push observability)

In addition to post-hoc batch ingest, Kyoko accepts **live events** — token deltas,
tool start/result, status and message events emitted while an agent runs — and pushes
them to the dashboard in real time over Server-Sent Events. This is the local
"watch your agent think" loop (the Workshop-style live tail), reusing Kyoko's canonical
model: live events attach to runs/spans by id and are **redacted by default** before
they are stored or served. Live serving is loopback-only.

```bash
# Ingest a batch of live events (file or stdin); each event: {kind, run_id?, span_id?, content, ...}
python3 -m kyoko ingest-live --db /tmp/kyoko.db events.json --profile-id profile_otlp_news --json
echo '{"kind":"token","run_id":"run_a","content":"Hello"}' | python3 -m kyoko ingest-live --db /tmp/kyoko.db --json

# Read recorded live events for a run (Workshop-style live tail)
python3 -m kyoko live-tail run_a --db /tmp/kyoko.db
python3 -m kyoko live-tail run_a --db /tmp/kyoko.db --kinds token,tool_result --after-seq 12 --json
```

Over HTTP (the self-hosted app):

```bash
# Push a live event
curl -X POST "http://127.0.0.1:8765/v1/live" -H "Content-Type: application/json" \
  --data '{"kind":"token","run_id":"run_a","content":"Hello"}'
# Subscribe to the live stream (SSE: run_upsert, live_event, ... events)
curl -N "http://127.0.0.1:8765/api/events/stream"
# Query stored live events
curl "http://127.0.0.1:8765/api/live-events?run_id=run_a"
```

`event` kinds are `token | tool_start | tool_result | status | message | error | other`;
each event gets a monotonic per-run `seq`. Batch ingest (`/v1/traces`, `/api/ingest`)
also publishes a `run_upsert` SSE event so the runs list updates without a manual refresh.

### MCP communication log (agent ↔ Kyoko)

Kyoko records the JSON-RPC traffic on its stdio MCP server — every `initialize`,
`tools/list`, and `tools/call` from a coding agent (Claude Code, Codex, …) and Kyoko's
response, with timing, the resolved tool name, error status, and **redacted**
request/response bodies. This is a live, inspectable log of what your agent asks Kyoko
and what it gets back. Logging is on by default and writes to the active DB; disable it
with `KYOKO_MCP_LOG=0`. Each logged exchange is also published over the live stream as an
`mcp_log` SSE event.

```bash
# Show recorded MCP traffic
python3 -m kyoko mcp-log --db /tmp/kyoko.db
python3 -m kyoko mcp-log --db /tmp/kyoko.db --tool-name kyoko_get_run_detail --json

# Over HTTP
curl "http://127.0.0.1:8765/api/mcp-log?session_id=mcpsess_..."
```

An agent can also inspect its own recent calls through the read-only MCP tool
`kyoko_get_mcp_log`. Like every default MCP tool this is read-only — the log adds
observability only and never widens the apply/harness-write boundary.

### Trace inspection and annotations

For debugging a captured run without dumping whole payloads, Kyoko offers Workshop-style
inspection over CLI, the `/api/*` surface, and read-only MCP tools:

```bash
python3 -m kyoko current-run --db /tmp/kyoko.db                  # the run you most likely just produced
python3 -m kyoko run-outline <run_id> --db /tmp/kyoko.db         # span-tree skeleton + counts, no payloads
python3 -m kyoko search-run <run_id> "timeout" --db /tmp/kyoko.db   # SQLite FTS5-backed full-text run search
python3 -m kyoko span-payload <span_id> --path messages.0.content --db /tmp/kyoko.db   # redacted, sliceable
python3 -m kyoko span-context <span_id> --db /tmp/kyoko.db
```

Equivalent endpoints: `GET /api/current-run`, `/api/run-outline`, `/api/run-search`,
`/api/span-context`, `/api/span-payload`; equivalent MCP tools: `kyoko_get_current_run`,
`kyoko_get_run_outline`, `kyoko_search_run`, `kyoko_get_span_context`,
`kyoko_get_span_payload`. Run search is backed by SQLite FTS5 for fast full-text
matching across a run's spans (same `search-run` / `/api/run-search` /
`kyoko_search_run` surface). Payload content is **redacted** before it leaves the
machine; `span-payload` supports a small JSON path (e.g. `messages.0.content`)
plus `--offset`/`--max-chars` slicing.

Annotations are durable `issue` / `good` / `note` markers on a run or span — lightweight
evidence the user or an agent can leave. An annotation may *seed* a learning proposal but
never applies a change itself, so it stays outside the safety gate.

```bash
python3 -m kyoko annotate issue --run-id <run_id> --note "fetch step times out" --db /tmp/kyoko.db
python3 -m kyoko annotations --run-id <run_id> --db /tmp/kyoko.db
```

Equivalent: `GET/POST /api/annotations` (+ `POST /api/annotations/delete`) and MCP tools
`kyoko_annotate` / `kyoko_list_annotations`. New annotations publish an `annotation` event
on the live stream.

Import a Hermes Kanban SQLite board directly. This reads Hermes `tasks`,
`task_runs`, `task_events`, `task_comments`, and `task_links`, then normalizes
them into Kyoko queues, tasks, task attempts, runs, spans, handoffs, and
timeline events:

```bash
python3 -m kyoko import-hermes-kanban --db /tmp/kyoko.db ~/.hermes/kanban.db --board default --profile-id profile_hermes_default --json
python3 -m kyoko import-hermes-kanban --db /tmp/kyoko.db ~/.hermes/kanban/boards/news/kanban.db --board news --output /tmp/hermes-source-events.json --json
```

This is an offline importer. It proves Hermes coordination preservation inside
Kyoko; live Hermes replay and Hermes-as-operator remain separate integration
paths. The same import is available from the self-hosted dashboard
`Integrations` panel and through `POST /api/import-hermes-kanban`.

Import OpenClaw session stores directly. This reads a sessions directory,
`sessions.json`, or one JSONL transcript, then normalizes sessions into Kyoko
tasks, runs, spans, handoffs, and timeline events:

```bash
python3 -m kyoko import-openclaw-sessions --db /tmp/kyoko.db ~/.openclaw/agents/main/sessions --agent-id main --profile-id profile_openclaw_main --json
python3 -m kyoko import-openclaw-sessions --db /tmp/kyoko.db ~/.openclaw/agents/main/sessions/sessions.json --session-key agent:main:main --output /tmp/openclaw-source-events.json --json
```

This is also an offline importer. It uses OpenClaw's persisted local session
shape, not a live gateway call, so it can run without a separate model API key.
The same import is available from the self-hosted dashboard `Integrations`
panel and through `POST /api/import-openclaw-sessions`.

Python agents can use the dependency-free recorder instead of hand-building
canonical JSON:

```python
from kyoko import KyokoClient, KyokoRecorder

recorder = KyokoRecorder(
    profile_id="profile_news_research_local",
    profile_name="News Research",
    root_path=".",
    agent_name="researcher",
)

with recorder.run("research topic") as run:
    with run.span("fetch_source", kind="tool"):
        pass
    run.summary = "completed with one source fetch"

KyokoClient("http://127.0.0.1:8765").ingest(recorder.to_source_events())
```

Persist a validated learning proposal after evidence has been ingested:

```bash
python3 -m kyoko propose --db /tmp/kyoko.db /tmp/kyoko-assets/learning-proposals/valid-context-proposal.json
python3 -m kyoko proposals --db /tmp/kyoko.db --json
python3 -m kyoko proposals --db /tmp/kyoko.db --profile-id profile_news_research_001 --json
python3 -m kyoko proposal-detail --db /tmp/kyoko.db proposal_context_timeout_001 --json
```

`proposal-detail` includes an `evidence_chain` summary with stable stages for
the observed issue, proposed fix, eval gate, replay, and autonomy decision. The
payload also includes compact `eval_guidance` with gateable eval types,
informational eval types, safe replay side-effect modes, assertion presets, and
recorded-judge-only status. The dashboard renders the same chain and guidance
in proposal details so the before/after proof and next gate choices are visible
without opening raw artifacts first.

### Issues

An **Issue** is a first-class evidence entity: a durable record of an observed
problem, with a status (`open`/`resolved`/`dismissed`), section
(`context`/`harness`), optional category and severity, and links to the
proposals that address it. Issues are evidence only — like annotations, creating
one never changes agent behavior and sits outside the autonomy gate. The model is
specified in [docs/specs/0012-issue-model.md](docs/specs/0012-issue-model.md).

```bash
python3 -m kyoko issues --db /tmp/kyoko.db --json
python3 -m kyoko issues --db /tmp/kyoko.db --status open --section context --json
python3 -m kyoko issue-detail --db /tmp/kyoko.db issue_... --json
python3 -m kyoko issue-create --db /tmp/kyoko.db "Researcher fetch times out" \
  --body "Fetch tool exceeds 30s on large pages" --section context \
  --category reliability --severity high --proposal-id proposal_context_timeout_001 --json
```

`issue-detail` resolves linked proposals and affected entities. The same surface
is exposed as `GET /api/issues`, `GET /api/issue-detail`, and `POST /api/issues`
(a JSON-content-type-guarded, propose-style write), the MCP tools
`kyoko_list_issues` / `kyoko_get_issue` / `kyoko_create_issue` (read/propose
only), and a dashboard **Issues** page.

Apply a context proposal into the ACE-compatible skillbook table:

```bash
python3 -m kyoko apply --db /tmp/kyoko.db proposal_context_timeout_001
python3 -m kyoko skills --db /tmp/kyoko.db --json
python3 -m kyoko skill-revisions --db /tmp/kyoko.db --json
python3 -m kyoko skill-rollback --db /tmp/kyoko.db skill_revision_id --json
python3 -m kyoko context-rules --db /tmp/kyoko.db --json
python3 -m kyoko context-rule-revisions --db /tmp/kyoko.db --json
python3 -m kyoko context-rule-rollback --db /tmp/kyoko.db context_delivery_rule_revision_id --json
python3 -m kyoko skill-lock --db /tmp/kyoko.db skill_proposal_context_timeout_001_1 --json
python3 -m kyoko skill-unlock --db /tmp/kyoko.db skill_proposal_context_timeout_001_1 --json
python3 -m kyoko context-rule-lock --db /tmp/kyoko.db context_rule_researcher_timeout --json
python3 -m kyoko context-rule-unlock --db /tmp/kyoko.db context_rule_researcher_timeout --json
python3 -m kyoko harness-target-lock --db /tmp/kyoko.db evals/generated_timeout_eval.py --reason "manual owner review" --json
python3 -m kyoko harness-target-locks --db /tmp/kyoko.db --json
python3 -m kyoko harness-target-unlock --db /tmp/kyoko.db evals/generated_timeout_eval.py --json
```

A human lock is just boolean state plus an optional reason — there is no
lock/unlock event ledger. Human-locked skills and context delivery rules remain
active for delivery, but Kyoko blocks later proposals that try to write the same
locked id. Human-locked eval specs can still run, but Kyoko will not auto-promote
their trust level. Human-locked harness target paths block both harness
preparation and prepared patch application for the same normalized path. The
dashboard exposes simple per-entity skill, context-rule, eval-spec, and
harness-target lock/unlock toggles. Set the dashboard `Lock Actor` field to
include an `actor_agent_identity_id` in the lock/unlock request. A server
default can also be supplied with `kyoko serve
--default-lock-actor-agent-identity-id` or
`KYOKO_DEFAULT_LOCK_ACTOR_AGENT_IDENTITY_ID`; explicit dashboard/API payload
actors still take precedence. Set `Lock Reason` to attach a human-readable
reason.

Inspect or update the profile autonomy policy. Context and harness modes are
independent, and repository patch writes are off by default:

```bash
python3 -m kyoko policy --db /tmp/kyoko.db --json
python3 -m kyoko policy-set --db /tmp/kyoko.db --context-mode autonomous --harness-mode propose --repo-patch on --json
```

Run the local autonomy gate evaluator. Proposal lifecycle states are
`pending → applied → rolled_back` (plus an internal `failed`); the autonomy gate
holds a proposal in `pending` until its evidence requirements are met. In
`context_mode=autonomous`, this will generate missing eval specs for a context
proposal, keep the proposal `pending` until the required eval/replay evidence
exists, and apply only after the gate passes. Harness autonomy follows the same missing-eval fallback before
patch preparation and apply eligibility checks. When `rollback_on_regression`
is enabled, later `run-autonomy` calls roll back applied context skillbook and
context delivery rule changes if the latest proposal-linked eval run fails.
Skill and rule rollbacks use latest-revision before/after snapshots and respect
human locks. In
`harness_mode=autonomous`, Kyoko prepares harness
patch transactions, waits for the required eval/replay evidence, and may apply
eligible `generated_file` or strict `unified_diff` transactions when repository
patch writes are enabled. Use `--harness-workspace-root` to provide the target
workspace explicitly; if omitted, Kyoko falls back to the profile `root_path`.
The same regression policy rolls back applied harness patch transactions if the
latest proposal-linked eval run fails:

```bash
python3 -m kyoko run-autonomy --db /tmp/kyoko.db --harness-workspace-root /tmp/kyoko-workspace --json
python3 -m kyoko autonomy-events --db /tmp/kyoko.db --kind autonomy_decision --entity-id proposal_context_timeout_001 --json
```

Recent autonomy decisions, gate holds, applies, prepare steps, failures, and
regression rollbacks are available through `kyoko autonomy-events`,
`GET /api/autonomy-events`, and the dashboard `Autonomy History` panel, with
filters for event kind, entity type, and exact proposal id.

Prepare a harness proposal into a reviewable patch transaction. This validates
the harness section, side-effect mode, allowed paths, protected paths, rollback
requirement, generated-file content, and unified-diff additions for common
secret patterns. `command_plan` patches remain review-only. `generated_file`
and `unified_diff` patches can be applied only with an explicit workspace root
and can be rolled back from captured preimages. Unified diffs use `diff_ref`
pointing at a registered payload blob:

```bash
python3 -m kyoko propose --db /tmp/kyoko.db /tmp/kyoko-assets/learning-proposals/valid-harness-proposal.json
python3 -m kyoko prepare-harness --db /tmp/kyoko.db proposal_harness_timeout_eval_001 --json
python3 -m kyoko harness-patches --db /tmp/kyoko.db --json
python3 -m kyoko propose --db /tmp/kyoko.db /tmp/kyoko-assets/learning-proposals/valid-harness-generated-file-proposal.json
python3 -m kyoko prepare-harness --db /tmp/kyoko.db proposal_harness_generated_eval_001 --json
python3 -m kyoko policy-set --db /tmp/kyoko.db --repo-patch on --json
python3 -m kyoko apply-harness --db /tmp/kyoko.db patch_proposal_harness_generated_eval_001_1 --workspace-root /tmp/kyoko-workspace --json
python3 -m kyoko rollback-harness --db /tmp/kyoko.db patch_proposal_harness_generated_eval_001_1 --workspace-root /tmp/kyoko-workspace --json
python3 -m kyoko blob-put --db /tmp/kyoko.db /tmp/harness.patch --kind patch_diff --media-type text/x-diff --json
```

Create generated eval specs, record a bounded dry-run replay request, and run
the deterministic baseline eval:

```bash
python3 -m kyoko generate-evals --db /tmp/kyoko.db proposal_context_timeout_001 --json
python3 -m kyoko replay --db /tmp/kyoko.db eval_proposal_context_timeout_001_1 --json
python3 -m kyoko complete-replay --db /tmp/kyoko.db replay_eval_proposal_context_timeout_001_1_001 /tmp/kyoko-assets/replay-results/researcher-fetch-timeout-success.json --json
python3 -m kyoko run-eval --db /tmp/kyoko.db eval_proposal_context_timeout_001_1 --json
python3 -m kyoko judge-command --db /tmp/kyoko.db eval_proposal_judge_001_1 --command "python /path/to/provider-judge.py" --output-dir /tmp/kyoko-judge --json
python3 -m kyoko judge-smoke --prepare-only --provider-backed --output-dir .kyoko/smoke/judge-provider-prepare --json
python3 -m kyoko judge-smoke --command "python /path/to/provider-judge.py" --provider-backed --output-dir .kyoko/smoke/judge-provider-live --json
python3 -m kyoko evals --db /tmp/kyoko.db --json
python3 -m kyoko eval-capabilities --json
python3 -m kyoko eval-assertion-presets --json
python3 -m kyoko eval-spec-lock --db /tmp/kyoko.db eval_proposal_context_timeout_001_1 --reason "manual baseline review" --json
python3 -m kyoko eval-spec-locks --db /tmp/kyoko.db --json
python3 -m kyoko eval-spec-unlock --db /tmp/kyoko.db eval_proposal_context_timeout_001_1 --json
python3 -m kyoko eval-spec-approve --db /tmp/kyoko.db eval_proposal_context_timeout_001_1 --reason "reviewed replay evidence" --json
python3 -m kyoko eval-detail --db /tmp/kyoko.db eval_proposal_context_timeout_001_1 --json
python3 -m kyoko replay-detail --db /tmp/kyoko.db replay_eval_proposal_context_timeout_001_1_001 --json
```

The first replay implementation is intentionally conservative. It can record a
bounded dry-run replay, ingest a controlled replay result fixture, and compare
the original failed evidence to the replay output. Deterministic evals support
target field checks plus replay trace-shape checks such as output run status,
no failed spans, minimum span count, and minimum handoff count. Live replay is
still blocked until side-effect controls are implemented. `smoke_run` evals can
check already-recorded source runs or completed replay output runs for status,
failed spans, span count, and handoff count, but they are informational only:
they do not auto-promote trust and cannot satisfy autonomy gates. `eval-spec-approve`
is the explicit human path to `L3_human_approved`; Kyoko never auto-promotes an
eval to that level, and human-locked eval specs must be unlocked before
approval.
`run-eval` never invokes a live judge provider. To use a model-backed or
provider-backed judge, run `judge-command` explicitly. Kyoko writes a redacted
`judge-request.json`, passes it on stdin and through `KYOKO_JUDGE_REQUEST_PATH`,
expects one delimited `kyoko.judge_result.v1` block, persists the returned
verdict as the eval spec's recorded judgment, runs the normal non-gateable judge
eval, and attaches request/result/raw-output artifact refs to the eval run. The
same explicit handoff is available through `POST /api/judge-command`, the
dashboard's judge controls, and the `kyoko_run_judge_command` MCP tool.
Use judge output as review evidence for subjective quality, rubric scoring,
or cases where deterministic assertions cannot yet express the concern. Do not
treat it as an autonomy gate in v0: Kyoko keeps judge evals informational even
when the external command uses a strong provider model.
`judge-smoke --prepare-only` creates a bundled demo database, a judge eval, the
redacted request, and `judge-command.handoff.json` without invoking the command.
Run it without `--prepare-only` and with `--provider-backed` to retain explicit
provider-backed judge evidence under `.kyoko/smoke/...`.

Run an external replay command. The command receives
`KYOKO_REPLAY_REQUEST_PATH` and must print exactly one delimited replay-result
block:

```bash
python3 -m kyoko replay-command --db /tmp/kyoko.db eval_proposal_context_timeout_001_1 --command "python3 -m kyoko.fixture_replay" --output-dir /tmp/kyoko-replay --run-eval --json
```

Required replay-command stdout contract:

```text
BEGIN_KYOKO_REPLAY_RESULT_JSON
{ "...": "kyoko.replay_result.v1 JSON" }
END_KYOKO_REPLAY_RESULT_JSON
```

Register a replay adapter once and run it by name:

```bash
python3 -m kyoko replay-adapter-register --db /tmp/kyoko.db fixture_replay --name "Fixture replay" --command "python3 -m kyoko.fixture_replay" --output-dir /tmp/kyoko-replay --json
python3 -m kyoko replay-adapters --db /tmp/kyoko.db --json
python3 -m kyoko replay-adapter-run --db /tmp/kyoko.db fixture_replay eval_proposal_context_timeout_001_1 --run-eval --json
```

Workshop-style HTTP replay servers are supported as first-class replay
adapters:

```bash
python3 -m kyoko replay-server-template scripts/kyoko_replay_server.py --framework langgraph-python --profile-name news-research --json
python3 -m kyoko integration-smoke replay-server --command "python3 scripts/kyoko_replay_server.py --port 61200" --server-url http://127.0.0.1:61200 --json
python3 -m kyoko integration-smoke replay-server --command "python3 scripts/kyoko_replay_server.py --port 61200" --server-url http://127.0.0.1:61200 --hook /absolute/path/to/replay_hook.py:replay --run-replay --json
KYOKO_REPLAY_HOOK=/absolute/path/to/replay_hook.py:replay python3 scripts/kyoko_replay_server.py --port 61200
python3 -m kyoko replay-server-health http://127.0.0.1:61200 --json
python3 -m kyoko replay-server-run --db /tmp/kyoko.db http://127.0.0.1:61200 eval_proposal_context_timeout_001_1 --run-eval --json
python3 -m kyoko replay-adapter-register --db /tmp/kyoko.db local_http_replay --name "Local HTTP replay" --server-url http://127.0.0.1:61200 --json
python3 -m kyoko replay-adapter-register --db /tmp/kyoko.db managed_http_replay --name "Managed HTTP replay" --command "python3 -m kyoko.fixture_replay_server --port 61200" --server-url http://127.0.0.1:61200 --startup-timeout 15 --json
python3 -m kyoko replay-server-start --db /tmp/kyoko.db managed_http_replay --json
python3 -m kyoko replay-server-status --db /tmp/kyoko.db managed_http_replay --json
python3 -m kyoko replay-server-logs --db /tmp/kyoko.db managed_http_replay --json
python3 -m kyoko replay-server-stop --db /tmp/kyoko.db managed_http_replay --json
```

HTTP replay server URLs are loopback-only by default (`127.0.0.1`,
`localhost`, or `::1`) because Kyoko sends replay/eval context to that endpoint.
Use `--allow-remote-server` on `replay-server-health`,
`replay-server-run`, or `replay-adapter-register` only after deliberately
trusting the remote replay service and its network path. Registered replay
adapters expose `allow_remote_server` in JSON so the boundary is auditable. If
server `/health` advertises `capabilities`, Kyoko requires it to include
`replay`; if it advertises `side_effect_modes`, Kyoko verifies the requested
replay side-effect mode is supported before posting `/replay`. Older servers
that omit those fields are still checked at replay completion. The replay
request body sent to the server is redacted with the profile evidence policy
before the POST, so default local replay handoff hides payload refs and
secret-shaped values while keeping replay ids, eval ids, and trace shape.

Generated replay servers are dependency-free: Python framework labels produce
stdlib-only `.py` servers, and TypeScript framework labels produce Node ESM
`.mjs` servers. Set `KYOKO_REPLAY_HOOK` to a `module:function` or
`/path/to/file:function`; the hook should run the agent under mocked or
sandboxed side effects and return `output_run_id`, `target_map`, and either
Kyoko `source_events` or an already-ingested output run id. Replay-server
templates support `generic-python`, `langgraph-python`,
`pydantic-ai-python`, `openai-agents-python`, `crewai-python`,
`hermes-python`, `openclaw-python`, `generic-typescript`, and
`ai-sdk-typescript`.
`integration-smoke replay-server` starts the server command, waits for
`/health`, captures bounded stdout/stderr logs, and stops the process. Pass
`--hook module_or_path:function --run-replay` to also POST a generated bounded
request to `/replay` and fail if the hook response does not pass. Use
`replay-server-run` for the full Kyoko replay/eval path against a real eval
spec. The same smoke action is available in the dashboard `Integrations` panel
and JSON API.

Copyable replay hook examples are available under `examples/replay-hooks/`:

```bash
python3 -m kyoko replay-server-template /tmp/kyoko_replay_server.py --framework langgraph-python --profile-name news-research --json
KYOKO_REPLAY_HOOK=examples/replay-hooks/langgraph_replay_hook.py:replay python3 /tmp/kyoko_replay_server.py --port 61200

python3 -m kyoko replay-server-template /tmp/kyoko_replay_server.py --framework pydantic-ai-python --profile-name news-research --json
KYOKO_REPLAY_HOOK=examples/replay-hooks/pydantic_ai_replay_hook.py:replay python3 /tmp/kyoko_replay_server.py --port 61200

python3 -m kyoko replay-server-template /tmp/kyoko_replay_server.py --framework openai-agents-python --profile-name news-research --json
KYOKO_REPLAY_HOOK=examples/replay-hooks/openai_agents_replay_hook.py:replay python3 /tmp/kyoko_replay_server.py --port 61200

python3 -m kyoko replay-server-template /tmp/kyoko_replay_server.py --framework crewai-python --profile-name news-research --json
KYOKO_REPLAY_HOOK=examples/replay-hooks/crewai_replay_hook.py:replay python3 /tmp/kyoko_replay_server.py --port 61200

python3 -m kyoko replay-server-template /tmp/kyoko_replay_server.py --framework hermes-python --profile-name news-research --json
KYOKO_REPLAY_HOOK=examples/replay-hooks/hermes_replay_hook.py:replay python3 /tmp/kyoko_replay_server.py --port 61200

python3 -m kyoko replay-server-template /tmp/kyoko_replay_server.py --framework openclaw-python --profile-name news-research --json
KYOKO_REPLAY_HOOK=examples/replay-hooks/openclaw_replay_hook.py:replay python3 /tmp/kyoko_replay_server.py --port 61200

python3 -m kyoko replay-server-template /tmp/kyoko_replay_server.mjs --framework ai-sdk-typescript --profile-name news-research --json
KYOKO_REPLAY_HOOK=examples/replay-hooks/ai_sdk_replay_hook.mjs:replay node /tmp/kyoko_replay_server.mjs --port 61200
```

The examples return `output_run_id`, `target_map`, and Kyoko `source_events`
for the replay output run. Tests run them through generated replay servers and
the bundled eval/replay fixture, promoting the eval to `L2_regression`.

Deliver learned context to an agent or export ACE Skillbook v2 JSON:

```bash
python3 -m kyoko context --db /tmp/kyoko.db
python3 -m kyoko context --db /tmp/kyoko.db --target-type agent_identity --target-id agent_researcher_001
python3 -m kyoko context --db /tmp/kyoko.db --profile-id profile_news_research_001
python3 -m kyoko export-skillbook --db /tmp/kyoko.db --format json
python3 -m kyoko export-skillbook --db /tmp/kyoko.db --format json --profile-id profile_news_research_001
python3 -m kyoko export-skillbook --db /tmp/kyoko.db --format prompt --output /tmp/kyoko-context.md
```

When a target is provided, active context delivery rules can scope delivered
skills with `include_skill_ids`, `exclude_skill_ids`, `include_keywords`,
`exclude_keywords`, and `max_skills`. The rendered prompt also includes the
matching rule ids so operator agents can audit why context was included.
Targeted context delivery infers the target profile from Kyoko's agent, run,
span, queue, task, or workflow-node tables and fails closed when a target cannot
be resolved, avoiding cross-profile context leakage.

Check that Kyoko's ACE-compatible export loads through ACE's public
`Skillbook` API, then convert a cloned ACE Skillbook before/after diff back
into gated Kyoko proposals:

```bash
python3 -m kyoko ace-compat --db /tmp/kyoko.db --ace-path /Users/filip/Desktop/agentic-context-engine --json
python3 -m kyoko ace-diff-proposals --db /tmp/kyoko.db --before /tmp/skillbook-before.json --after /tmp/skillbook-after.json --evidence-run-id run_research_topic_001 --output-dir /tmp/kyoko-ace-proposals --json
python3 -m kyoko ace-diff-proposals --db /tmp/kyoko.db --before /tmp/skillbook-before.json --after /tmp/skillbook-after.json --evidence-run-id run_research_topic_001 --persist --json
python3 -m kyoko ace-native-run --db /tmp/kyoko.db --command "python /path/to/run-ace.py --after {after_path}" --output-dir /tmp/kyoko-ace-native --prepare-only --provider-backed --json
python3 -m kyoko ace-native-run --db /tmp/kyoko.db --command "python /path/to/run-ace.py" --evidence-run-id run_research_topic_001 --output-dir /tmp/kyoko-ace-native --persist --provider-backed --json
python3 -m kyoko ace-native-smoke --db /tmp/kyoko.db --output-dir /tmp/kyoko-ace-native-smoke --persist --json
```

`ace-compat` requires an ACE runtime that can actually import the selected ACE
package or checkout. Kyoko's baseline is Python 3.12 with
`ace-framework>=0.12.0` (installable via the `ace` extra: `pip install .[ace]`),
which exposes the `ace.core.skillbook.Skillbook` v2 API; against that baseline
`ace-compat --json` reports `detected_api: "skillbook_v2"` and round-trips
Kyoko's exported skillbook through ACE's own `Skillbook.from_dict`/`to_dict`.
Kyoko reports missing runtime dependencies instead of silently treating
compatibility as proven. Older `ace-framework` releases that only expose the
legacy `ace.Playbook`/`OfflineAdapter` API are reported as
`detected_api: "legacy_playbook"` rather than claiming Skillbook-v2 compatibility.
`ace-native-smoke` uses the installed ACE 0.12.0 package deterministically
through the real `Skillbook` v2 API (`Skillbook.add_skill`), writes an actual
cloned before/after Skillbook pair, and lets Kyoko import the diff as a gated
proposal. No model or provider is invoked: the learned issue/insight are fixed
inputs and ACE performs only the skill construction, occurrence linkage, and
serialization. It proves the external native ACE process boundary for an
installed package. `ace-native-run --prepare-only`
writes the same cloned snapshots, empty command log files, and
`ace-command.handoff.json` command/environment contract without invoking the
external command. Add `--provider-backed` when the prepared or invoked command
uses a model/provider backend; prepare-only reports still keep
`external_model_invoked: false`, while run reports set it true. Completed runs
also write `ace-native-run-report.json` in the output directory; doctor uses
that durable report plus the retained SQLite proposals and
before/after/stdout/stderr artifacts as provider-backed ACE evidence. Retained
provider-backed ACE-compatible evidence exists under
`.kyoko/smoke/ace-provider-live` from a Claude-backed wrapper command.

This is the native ACE safety boundary: ACE can mutate a temporary cloned
Skillbook, but Kyoko converts the delta into `native_ace` LearningProposals and
still owns evidence validation, eval/replay gates, autonomy policy, and final
writes. `ace-native-run` makes that boundary executable for provider-backed ACE
wrappers: Kyoko writes `before.skillbook.json`, provides `KYOKO_ACE_BEFORE_PATH`,
`KYOKO_ACE_AFTER_PATH`, `KYOKO_ACE_OUTPUT_DIR`, `KYOKO_ACE_DB_PATH`, and
`KYOKO_ACE_PROFILE_ID`, records those values in `ace-command.handoff.json`,
captures stdout/stderr when the command is actually invoked, and imports only
the validated after-snapshot diff.

Create an operator-facing evidence bundle and run the deterministic mock
operator bridge:

```bash
python3 -m kyoko evidence --db /tmp/kyoko.db --output /tmp/kyoko-evidence.json
python3 -m kyoko analyze --db /tmp/kyoko.db --operator mock --output-dir /tmp/kyoko-analysis --json
```

Create an operator-facing evidence bundle plus a strict prompt for a local
agent, or run an external operator command directly:

```bash
python3 -m kyoko operator-prompt --db /tmp/kyoko.db --target codex --output-dir /tmp/kyoko-operator --json
python3 -m kyoko analyze --db /tmp/kyoko.db --operator command --command "codex exec ..." --output-dir /tmp/kyoko-analysis --json
```

Run an external operator command. Kyoko writes `evidence-bundle.json` and
`operator-instructions.md`, sets `KYOKO_EVIDENCE_PATH` and
`KYOKO_OPERATOR_PROMPT_PATH`, passes the prompt on stdin, supports command
placeholders such as `{prompt}`, `{prompt_path}`, `{evidence_path}`,
`{profile_id}`, and `{schema_path}`, records an `operator_runs` row, and
requires exactly one delimited proposal block.

Use `--max-retries` when you want Kyoko to retry malformed or semantically
invalid operator output with a corrective prompt. Retries are explicit and
audited: Kyoko records the attempt count and per-attempt status in
`operator_runs.metadata`, writes retry prompts as
`operator-instructions-attempt-N.md`, and preserves every attempt's stdout and
stderr in `operator-output.txt`. The operator-runs API/dashboard also surfaces
derived failure categories such as invalid output, invalid proposal, timeout,
nonzero exit, and command missing, so failed operator runs are visible without
opening artifact files first.

Operator evidence is redacted by default before it is written to disk, embedded
in prompts, served through MCP, or shown through API summaries. Redaction is a
single fixed global "redact on export" behavior with no configuration: there is
no redaction policy table, no `redaction-policy`/`redaction-policy-set` or
`redaction-audit`/`redaction-audit-acknowledge` command, no
`/api/redaction-policy` or `/api/redaction-audit` route, no
`kyoko_*_redaction_audit_event` MCP tool, and no `Evidence Privacy` dashboard
panel. Before any evidence leaves the machine — through operator prompts, MCP, or
the API — Kyoko scrubs payload/artifact refs and redacts common secret keys and
token-shaped values. Generated evidence bundles and operator prompts also include
Kyoko's eval capability summary, including executable/gateable eval
types, safe replay side-effect modes, deterministic assertions, and assertion
presets, so operator agents can propose supported gates without separate
discovery calls.

Register a local operator once and run it by id. Registered ids can be used
directly through `analyze --operator <id>`, so ids like `codex`, `claude`,
`hermes`, and `openclaw` become stable no-key operator aliases:

```bash
python3 -m kyoko operator-adapter-bootstrap --db /tmp/kyoko.db --json
python3 -m kyoko operator-adapter-register --db /tmp/kyoko.db codex --name "Codex" --kind codex --command "codex exec ..." --output-dir /tmp/kyoko-operator --json
python3 -m kyoko operator-adapters --db /tmp/kyoko.db --json
python3 -m kyoko analyze --db /tmp/kyoko.db --operator codex --output-dir /tmp/kyoko-operator --json
python3 -m kyoko operator-adapter-run --db /tmp/kyoko.db codex --json
python3 -m kyoko operator-runs --db /tmp/kyoko.db --json
```

`operator-adapter-bootstrap` registers conservative built-in presets for
installed local CLIs. The Codex preset uses `codex exec` in read-only mode and
the Claude preset uses `claude --print` with only the `Read` tool allowed.
Hermes uses `hermes -z {prompt}` and OpenClaw uses
`openclaw agent --agent main --local --message {prompt} --timeout 120`.
No preset runs the model during registration.

Smoke-test operator proposal output explicitly before wiring it into an
improvement loop:

```bash
python3 -m kyoko operator-smoke --operator mock --json
python3 -m kyoko operator-smoke --all-presets --prepare-only --output-dir /tmp/kyoko-operator-smoke --json
python3 -m kyoko operator-smoke --operator codex --output-dir /tmp/kyoko-codex-smoke --prepare-only --json
python3 -m kyoko operator-smoke --operator codex --output-dir /tmp/kyoko-codex-smoke --json
python3 -m kyoko operator-smoke --operator codex --output-dir /tmp/kyoko-codex-failure-smoke --expect-failure --json
python3 -m kyoko operator-smoke --db /tmp/kyoko.db --operator claude --output-dir /tmp/kyoko-claude-smoke --json
```

Without `--db`, `operator-smoke` creates a demo SQLite database under the
artifact directory, runs the selected operator against the bundled
Hermes/news-research fixture, validates and persists the resulting proposal in
that smoke database, and stops before replay, autonomy, or apply.
Use `--prepare-only` to write the exact evidence bundle and operator prompt,
expand command placeholders, resolve the schema path to an existing absolute
file when possible, and print the environment contract without invoking the
live operator CLI. Use `--all-presets` to prepare or run the same smoke contract
for every built-in operator preset. Missing preset executables are reported as
`skipped` by default; `--fail-on-missing` turns them into failures. When
validating failure handling, use `--expect-failure` to append a negative-path
prompt override and pass only when Kyoko captures the expected operator-output
failure kind without persisting a proposal. Use `--expected-failure-kind any`
to accept any captured failure kind. When installed operator CLIs are present,
`doctor --json` suggests the retained live
evidence command
`python3 -m kyoko operator-smoke --all-presets --output-dir .kyoko/smoke/operator-live --json`
and the retained expected-failure command
`python3 -m kyoko operator-smoke --all-presets --expect-failure --output-dir .kyoko/smoke/operator-failure-live --json`,
marking both mutating because they invoke live operators and write artifacts.
The dashboard exposes the same readiness path in the `Operators` panel through
preset bootstrap, `Prepare all presets`, and smoke actions backed by
`/api/operator-adapters/bootstrap` and `/api/operator-smoke`.

Required operator stdout contract:

```text
BEGIN_KYOKO_LEARNING_PROPOSAL_JSON
{ "...": "schema-valid LearningProposal JSON" }
END_KYOKO_LEARNING_PROPOSAL_JSON
```

Run the agent-facing MCP server over stdio, or generate a config block for an
MCP-capable operator agent. The first MCP surface is intentionally
read/propose/eval-request oriented with local readiness checks; it does not
expose direct apply or harness write tools. Storage and retention MCP cleanup
tools are dry-run only; explicit rollback tools are state-changing and should
be treated as privileged by MCP clients.
The `kyoko_run_improve` MCP tool provides the high-level import/analyze/eval
orchestration path for coding agents, but it always disables autonomy/apply so
the MCP path cannot mutate the skillbook or harness directly.

```bash
python3 -m kyoko mcp serve --db /tmp/kyoko.db
python3 -m kyoko mcp config --db /tmp/kyoko.db --target codex
python3 -m kyoko mcp install-plan --db /tmp/kyoko.db --target codex --json
python3 -m kyoko mcp install-plan --db /tmp/kyoko.db --target claude --scope user --json
python3 -m kyoko mcp install-smoke --db /tmp/kyoko.db --target codex --json
python3 -m kyoko mcp install-smoke --db /tmp/kyoko.db --target claude --scope user --json
python3 -m kyoko mcp install-smoke --db /tmp/kyoko.db --all-targets --json
python3 -m kyoko mcp install --db /tmp/kyoko.db --target codex --output /tmp/kyoko-mcp.json --json
```

`mcp install-plan` prints the target-specific native install command where it
is locally verified: `codex mcp add ...` for Codex and
`claude mcp add-json ...` for Claude Code. Hermes, OpenClaw, and generic
targets still use explicit JSON config until their current native MCP install
contracts are verified. `mcp install` writes a standard JSON `mcpServers` block.
If the output file already exists, Kyoko preserves unknown top-level keys and
existing servers, then upserts the selected Kyoko server entry for the requested
target label. `mcp install-smoke` executes the native Codex or Claude install
command with `HOME`, `CODEX_HOME`, and `XDG_CONFIG_HOME` redirected to a
temporary directory, uses an isolated smoke database when `--db` is omitted,
then verifies that the expected isolated config file was created and that the
client's `mcp list` output includes a verified Kyoko server entry. Source
checkout configs include a `PYTHONPATH` entry so native clients can start Kyoko
from outside the repo directory. Relative `--output-dir` values are resolved to
absolute isolated HOME/config/database paths before invoking client commands,
so retained smoke artifacts under `.kyoko/smoke/...` do not leak relative paths
into Codex or Claude configuration checks.
Use `--skip-list-verify` only when checking a client version whose list command
is not compatible with the current smoke contract. Use `--all-targets` to audit
Codex, Claude, Hermes, and OpenClaw in one command. Codex and Claude run native
install smokes; Hermes/OpenClaw are reported as skipped with
`mcp_install_smoke_no_native_command` until their native installer contracts are
verified. Missing verified-native clients are reported as `skipped` by default;
`--fail-on-missing` turns them into failures.
The same matrix smoke is available from the dashboard Integrations panel as
`Smoke MCP clients` and through `POST /api/mcp-install-smoke`.

Implemented MCP tools:

- `kyoko_status`
- `kyoko_mcp_safety_contract`
- `kyoko_list_profiles`
- `kyoko_run_profile_next_step`
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
- `kyoko_get_mcp_log`
- `kyoko_get_current_run`
- `kyoko_get_run_outline`
- `kyoko_search_run`
- `kyoko_get_span_context`
- `kyoko_get_span_payload`
- `kyoko_annotate`
- `kyoko_list_annotations`
- `kyoko_list_issues`
- `kyoko_get_issue`
- `kyoko_create_issue`
- `kyoko_run_judge_command`

Run the self-hosted dashboard and JSON API:

```bash
python3 -m kyoko serve --db /tmp/kyoko.db
python3 -m kyoko doctor --dashboard-smoke --smoke-output-dir .kyoko/smoke/doctor --dashboard-smoke-screenshot --json
python3 -m kyoko dashboard-smoke --output-dir .kyoko/smoke/dashboard-browser --install-browser-deps --screenshot --json
```

The dashboard is available at `http://127.0.0.1:8765` by default.

#### Dashboard UI (React SPA)

The shipping dashboard is a React/Vite/TypeScript single-page app in `frontend/`,
served by `kyoko serve` as static files. Build it once and `serve` ships it:

```bash
cd frontend
npm install
npm run build          # emits the bundle into kyoko/assets/web/
```

`kyoko serve` then serves the SPA at `/`, its hashed assets under `/assets/*`
(cached immutably), and falls back to `index.html` for client-side routes (so a
browser refresh on `/runs/...` works). If no bundle has been built, `serve`
transparently falls back to the legacy inline HTML dashboard described below.

For UI development, run Vite's dev server (it proxies `/api` + `/v1` to a running
`kyoko serve`):

```bash
# terminal 1
python3 -m kyoko serve --db /tmp/kyoko.db
# terminal 2
cd frontend && npm run dev          # override target with KYOKO_SERVE_URL=...
```

The SPA is loopback-only with **no auth and no profile selector** (single invisible
profile, per `docs/SCOPE.md`). Live updates use **Server-Sent Events**
(`GET /api/events/stream`): the runs list, live-event tail, the Agent ↔ Kyoko
MCP-communication log, and annotations all stream in real time. Pages: **Overview**
(database + product-loop metrics), **Runs** (span tree + flame timeline, a redacted
sliceable payload viewer with FTS5-backed run search, live tail, and run/span
annotations), **Issues** (the first-class Issue evidence entity — list, detail, and
create), **Agent ↔ Kyoko** (the live MCP JSON-RPC log), **Proposals**, **Autonomy**
(policy + timeline, read-only), **Evals & Replay**, and **Settings** (storage plus
the static redaction/retention posture and manual prune controls, read-only).
Client→server actions (creating/deleting annotations, creating issues, ingesting
live events) are plain `application/json` POSTs through the same loopback CSRF
guard.

#### Inline fallback dashboard

When no `frontend/` bundle is present, `serve` renders the inline HTML dashboard
from `web.py` `_dashboard_html()`. It exposes
status, product-loop dashboard metrics, the single implicit profile's routing
state plus `Plan next`/`Run next` controls (there is no profile selector or
Profiles panel — single invisible profile per `docs/SCOPE.md`),
runs/proposals, applied skills, context delivery rules, harness patch
transactions, eval/replay state, delivered context, detail inspection with
assertion-level eval evidence, persisted gate-decision history, filterable
autonomy history, replay adapter execution, managed
replay-server start/status/logs/stop controls, a local apply action for context
proposals, a local prepare action for harness proposals, and a one-click
improve action backed by `POST /api/improve`. The Autonomy Policy panel includes
an optional `Harness Root` field used by dashboard `Improve`, `Run autonomy`,
and `Run next` actions when an explicit harness workspace target
is needed, plus a replay adapter selector used by dashboard
`Improve`, discovery-card `Improve`, and `Run next`. It also
includes an operator adapter selector; discovery-card `Improve`
uses that registered local operator when selected, otherwise it falls back to
the deterministic mock operator. `Run next` also uses the
selected operator adapter to run the next analysis step through
`profile-next`. Discovery-card `Improve` also uses the selected
replay adapter when set, so a ready candidate can import source, generate
evals, and collect replay evidence while remaining non-applying. After
source-discovery Import or Improve, the dashboard refreshes the affected
profile/proposal/eval panels while preserving the latest discovery-card result.
The policy-card actions
render their returned autonomy/profile-next
outcomes after refresh. Proposal-level `Improve` refreshes the dashboard and
reopens the proposal detail with the returned replay/autonomy outcome,
including the concrete operator adapter label, replay adapter ids, and patch
transaction ids when harness apply runs. The Operators panel shows recent
operator runs with running, succeeded, failed, retry, and failure-kind state.
The top status strip is backed by `GET /api/dashboard-metrics` and is limited
to product-loop health: issues/proposals, eval pass/fail, replay result,
autonomy actions, and before/after verification.
`dashboard-smoke` starts an isolated loopback dashboard against a bundled demo
database, opens it in desktop and mobile Playwright browser viewports, checks
for console errors, page errors, request failures, and metric-card horizontal
overflow, and can retain screenshots under the selected output directory. It
uses Python Playwright when installed; otherwise `--install-browser-deps`
installs `@playwright/test` and Chromium under the smoke output directory.
Proposal list/detail payloads keep canonical `section = context | harness` and
also include `section_label`/`section_description` so the dashboard can show
`Context fix` and `Harness fix` without breaking agent-readable JSON contracts.
The dashboard exposes simple per-entity human-lock toggles. A lock is just a
boolean plus reason with enforcement — there is no lock-event history, no
`human-locks-bulk` command, no `/api/human-locks/bulk` route, and no
`GET /api/human-lock-events` ledger. The dashboard `Lock Actor` input lets you
record who is locking, and `kyoko serve --default-lock-actor-agent-identity-id`
can apply a server-side default actor when dashboard/API lock requests omit one.
The Storage panel shows database/blob size, missing/orphan blob counts, WAL
size, payload blob prune controls, the static redaction/retention posture, a
manual `prune-retention` (trace/replay/operator) dry-run/apply control, and WAL
checkpoint controls backed by
`GET /api/storage-report`,
`POST /api/prune`, `POST /api/prune-retention`, and
`POST /api/wal-checkpoint`.
The replay detail API/CLI also returns bounded previews of Kyoko-owned replay
artifacts.

Localhost serves without auth by default. If you bind outside loopback, Kyoko
requires a bearer token and the CLI prints a tokenized URL. Mutating dashboard
and API requests must use `Content-Type: application/json`, which blocks simple
cross-origin browser form/text POSTs before privileged endpoints dispatch:

```bash
KYOKO_AUTH_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')" \
  python3 -m kyoko serve --db /tmp/kyoko.db --host 0.0.0.0
```
