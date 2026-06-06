# 0008 - Hermes Operator Contract

Status: implemented for local contract smoke
Date: 2026-06-01

## Purpose

Hermes can appear in two Kyoko roles:

- source workflow: Kyoko imports Hermes board/task/run history as telemetry;
- operator agent: Hermes analyzes Kyoko evidence and emits a strict
  `LearningProposal`.

These roles are intentionally separate. Importing Hermes telemetry must not
imply that Hermes has permission to mutate Kyoko state, and running Hermes as
an operator must still go through the same proposal, check, replay, and autonomy
gates as Codex, Claude, OpenClaw, or any other operator.

## V0 Command Contract

The v0 Hermes operator preset is:

```text
hermes -z {prompt}
```

Kyoko expands `{prompt}` to the full operator instruction prompt. The same
prompt is also passed on stdin for consistency with other command operators.
The command receives these environment variables:

- `KYOKO_EVIDENCE_PATH`
- `KYOKO_OPERATOR_PROMPT_PATH`
- `KYOKO_PROFILE_ID`
- `KYOKO_OPERATOR_TARGET=hermes`
- `KYOKO_PROPOSAL_BLOCK_BEGIN`
- `KYOKO_PROPOSAL_BLOCK_END`
- `KYOKO_LEARNING_PROPOSAL_SCHEMA_PATH` when a schema path is supplied

Hermes output must contain exactly one proposal block:

```text
BEGIN_KYOKO_LEARNING_PROPOSAL_JSON
{ "...": "schema-valid LearningProposal JSON" }
END_KYOKO_LEARNING_PROPOSAL_JSON
```

Kyoko parses, validates, persists, and gates the proposal. Hermes does not
write directly to skills, checks, replay state, or repository files.

## Evidence

Preset implementation:

- `kyoko/operator_presets.py`

Schema-valid proposal fixture:

- `docs/fixtures/learning-proposals/hermes-one-shot-proposal.json`

Local fake-Hermes smoke:

- `tests/fixtures/hermes_operator_command.py`
- `tests/test_operator_adapters.py::OperatorAdapterTests.test_bootstrap_hermes_preset_runs_one_shot_prompt_argument_operator`

The fake command is installed as a temporary executable named `hermes`, then
`bootstrap_operator_adapters(target="hermes")` registers the real preset shape.
The registered adapter is run through the normal operator bridge, receives the
prompt through `-z`, emits one proposal block, and persists a proposal against
the Hermes/news-research fixture.

Gate validation:

- `scripts/validate_gate_artifacts.py`
- `tests/test_gate_artifacts.py`

## Remaining Evidence

This proves Kyoko's noninteractive Hermes command boundary and proposal
validation path without invoking a live Hermes model. Before release claims
stronger than "contract supported", run `kyoko operator-smoke --operator hermes`
against a real installed/authenticated Hermes CLI and record the live proposal
output behavior, timeout behavior, and auth/subscription assumptions.
