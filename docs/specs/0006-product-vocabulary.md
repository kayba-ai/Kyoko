# 0006 - Product Vocabulary

Status: implemented
Date: 2026-06-01

## Purpose

Kyoko adopts the ACE/Kayba learning words `issue` and `insight`, but the UI
must also make the write plane obvious. A context change and a harness change
can appear on the same dashboard, but they have different risk, autonomy gates,
and apply paths.

## Terms

| Term | UI label | Meaning |
|---|---|---|
| `issue` | Issue | A specific observed failure or weakness backed by trace, task, check, or replay evidence. |
| `insight` | Insight | The reusable lesson or change Kyoko proposes from the issue evidence. |
| `context` | Context fix | A change to agent-facing skillbook context or context delivery. |
| `harness` | Harness fix | A change to check, replay, instrumentation, or repository harness files. |

## `gate` vs `check` vs `eval`/`llm_eval` (the measurement split)

These three concepts are distinct and must not share a word:

| Term | Meaning | Status |
|---|---|---|
| `gate` | The autonomy **decision** that allows or blocks an apply (`autonomy_runner.py`; the `validate-gates` artifact validator in `gates.py` is unrelated naming). | unchanged |
| `check` | The deterministic/replay **apply-check** the gate evaluates: `check_specs`, `check_runs`, `check_locks`, `GATEABLE_CHECK_TYPES`, CLI `checks`/`run-check`/`check-detail`. | **renamed from `eval`** (schema 25) |
| `eval` / `llm_eval` | **Measurements** that score a trace corpus for evidence only — `eval` is a deterministic Python detector → prevalence; `llm_eval` is an LLM-as-judge template. Neither satisfies the autonomy gate. | new measurement plane (specs 0014/0015) |

Mental model: the autonomy **gate** (decision) evaluates **checks**; `eval`/`llm_eval`
are **measurements** that produce evidence, never an apply path. Renaming the old
apply-check `eval → check` frees the word `eval` for the measurement plane.

## Contract

Canonical stored proposal rows keep `section = context | harness`. API, CLI
JSON, and MCP proposal list/detail payloads add presentation metadata:

```json
{
  "section": "context",
  "section_label": "Context fix",
  "section_description": "A change to agent-facing skillbook context or context delivery."
}
```

Clients should branch automation on `section`, not `section_label`. UI surfaces
should show `section_label` and may use `section` as a stable CSS/test kind.

The shared implementation is `kyoko/vocabulary.py`. Proposal list payloads are
enriched in `kyoko/proposals.py`; proposal detail payloads are enriched in
`kyoko/details.py`; the dashboard renders `section_label` in list badges and
detail cells.

## Examples

Context fix example:

- Fixture: `docs/fixtures/learning-proposals/valid-context-proposal.json`
- Stored section: `context`
- UI label: `Context fix`
- Apply plane: ACE-compatible skillbook/context delivery
- Trust cue: lower-risk than repository patching, but still requires check gate
  evidence before autonomous apply.

Harness fix example:

- Fixture: `docs/fixtures/learning-proposals/valid-harness-proposal.json`
- Stored section: `harness`
- UI label: `Harness fix`
- Apply plane: generated check, replay, instrumentation, or repository harness
  patch transaction
- Trust cue: higher-risk path that requires stronger replay/check evidence,
  allowed paths, lock checks, and rollback support before autonomous apply.

## Remaining Review

This spec resolves the machine/UI terminology contract. Before a public V0
release, run a short usability pass against the dashboard to confirm that users
understand the distinction between context delivery changes and harness/code
changes without reading the docs.
