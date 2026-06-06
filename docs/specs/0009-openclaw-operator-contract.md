# 0009 - OpenClaw Operator Contract

Status: implemented for local contract smoke
Date: 2026-06-01

## Purpose

OpenClaw can appear in two Kyoko roles:

- source workflow: Kyoko imports persisted OpenClaw sessions as telemetry;
- operator agent: OpenClaw analyzes Kyoko evidence and emits a strict
  `LearningProposal`.

These roles are separate. Importing OpenClaw session history must not grant
OpenClaw direct write access to Kyoko state. Running OpenClaw as an operator
still produces proposals that Kyoko validates, evaluates, replays, and gates
before any context or harness write.

## V0 Command Contract

The v0 OpenClaw operator preset is:

```text
openclaw agent --agent main --local --message {prompt} --timeout 120
```

Kyoko expands `{prompt}` to the full operator instruction prompt. The same
prompt is also passed on stdin for consistency with other command operators.
The command receives these environment variables:

- `KYOKO_EVIDENCE_PATH`
- `KYOKO_OPERATOR_PROMPT_PATH`
- `KYOKO_PROFILE_ID`
- `KYOKO_OPERATOR_TARGET=openclaw`
- `KYOKO_PROPOSAL_BLOCK_BEGIN`
- `KYOKO_PROPOSAL_BLOCK_END`
- `KYOKO_LEARNING_PROPOSAL_SCHEMA_PATH` when a schema path is supplied

OpenClaw output must contain exactly one proposal block:

```text
BEGIN_KYOKO_LEARNING_PROPOSAL_JSON
{ "...": "schema-valid LearningProposal JSON" }
END_KYOKO_LEARNING_PROPOSAL_JSON
```

Kyoko parses, validates, persists, and gates the proposal. OpenClaw does not
write directly to skills, checks, replay state, or repository files.

## Evidence

Preset implementation:

- `kyoko/operator_presets.py`

Schema-valid proposal fixture:

- `docs/fixtures/learning-proposals/openclaw-local-operator-proposal.json`

Local fake-OpenClaw smoke:

- `tests/fixtures/openclaw_operator_command.py`
- `tests/test_operator_adapters.py::OperatorAdapterTests.test_bootstrap_openclaw_preset_runs_local_message_operator`

The fake command is installed as a temporary executable named `openclaw`, then
`bootstrap_operator_adapters(target="openclaw")` registers the real preset
shape. The registered adapter is run through the normal operator bridge,
receives the prompt through `--message`, emits one proposal block, and persists
a proposal against the Hermes/news-research fixture.

Gate validation:

- `scripts/validate_gate_artifacts.py`
- `tests/test_gate_artifacts.py`

## Remaining Evidence

This proves Kyoko's noninteractive OpenClaw command boundary and proposal
validation path without invoking a live OpenClaw model. Before release claims
stronger than "contract supported", run `kyoko operator-smoke --operator
openclaw` against a real installed/authenticated OpenClaw CLI and record the
live proposal output behavior, timeout behavior, local/Gateway mode behavior,
and auth/subscription assumptions.
