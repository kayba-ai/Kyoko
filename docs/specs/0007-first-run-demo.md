# 0007 - First-Run Demo And Install Path

Status: implemented
Date: 2026-06-01

## Purpose

Kyoko's first public experience must prove the optimization loop without asking
the user to configure a live model, a live framework adapter, and a replay
server before they see value.

The v0 first-run path is therefore local, fixture-backed, and self-contained.
It demonstrates the same product loop that real integrations use:

```text
telemetry -> issue/insight proposal -> check -> replay -> before/after check -> gated apply
```

## Demo Profile

The selected demo workflow profile is the Hermes/news-research fixture:

- Profile id: `profile_news_research_001`
- Source fixture: `docs/fixtures/source-events/hermes-news-research-minimal.json`
- Proposal fixture: `docs/fixtures/learning-proposals/valid-context-proposal.json`
- Replay implementation: `python -m kyoko.fixture_replay`
- Replay HTTP fixture implementation: `python -m kyoko.fixture_replay_server`
- Replay side-effect mode: `network_mocked`
- Expected issue: the researcher fetch span times out before retry context is
  available.
- Expected improvement: the replay output succeeds with retry behavior and the
  generated check passes at `L2_regression`.
- Expected apply result: one ACE-compatible context skill is applied:
  `skill_proposal_context_timeout_001_1`.

Installed packages expose the first-run schema/source/proposal/replay JSON
through `kyoko bundled-assets --output-dir <dir> --json`, so the manual
ingest/propose/complete-replay flow does not require a source checkout.

This profile is deliberately narrow. It exercises tasks, handoffs, spans,
proposal evidence, check generation, replay, before/after verification, and
context apply without requiring live Hermes, OpenClaw, Codex, Claude, or ACE
provider access.

## User Paths

Self-contained demo:

```bash
kyoko demo --db /tmp/kyoko-demo.db --json
```

First-run readiness without mutating the user's default database:

```bash
kyoko doctor --json
kyoko doctor --safe-smokes --json
kyoko doctor --smoke-demo --json
kyoko doctor --ace-native-prepare --json
```

Project bootstrap for a real local agent repository:

```bash
kyoko project-bootstrap --project-dir . --profile-name news-research --source-framework langgraph-python --replay-framework hermes-python --mcp-target codex --json
```

The generated `.kyoko/NEXT_STEPS.md` includes the same no-live-model
`doctor --safe-smokes` readiness command before source import, replay, autonomy,
or apply. It also passes `--smoke-output-dir .kyoko/smoke/doctor` so the demo
database, operator handoff artifacts, generated source adapter output,
native ACE before/after/handoff artifacts, replay-server logs, generated
improve smoke artifacts, and isolated MCP smoke homes remain inspectable after
the command exits. The replay section also
includes an `integration-smoke replay-server --run-replay` command with
retained logs under `.kyoko/smoke/replay` once the generated replay hook
placeholder has been replaced.

Release-package smoke:

```bash
kyoko release-smoke --artifact both --json
```

Dashboard path:

- Start `kyoko serve --db /tmp/kyoko-demo.db`.
- Click `Run demo`.
- Inspect proposals, check/replay state, applied context, and the proposal
  evidence chain.

## Non-Goals

The first-run demo does not claim:

- live operator-agent output quality,
- live framework replay safety,
- live provider-backed ACE learning,
- autonomous harness repository writes,
- broad OpenTelemetry/framework parity.

Those are separate release evidence items.

## Evidence

Implementation:

- `kyoko/demo.py`
- `kyoko/fixture_replay.py`
- `kyoko/fixture_replay_server.py`
- `kyoko/doctor.py`
- `kyoko/project_bootstrap.py`
- `kyoko/release_smoke.py`
- `kyoko/web.py` `POST /api/demo`

Tests:

- `tests/test_demo.py`
- `tests/test_doctor.py`
- `tests/test_packaging.py`
- `tests/test_project_bootstrap.py`
- `tests/test_web.py::WebTests.test_demo_endpoint_runs_first_run_loop`

Current local verification command:

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/kyoko-pycache python3 -m unittest
```
