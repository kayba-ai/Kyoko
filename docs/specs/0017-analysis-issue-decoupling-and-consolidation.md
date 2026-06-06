# 0017 — Analysis/Proposal Decoupling + Skillbook Consolidation

> **GATE MODEL SUPERSEDED (2026-06-05) by [0018](0018-two-mode-autonomy-rebuild.md).** The
> analysis/proposal decoupling and consolidation here remain current; the acceptance gate's
> reuse of context_mode/harness_mode and the check/replay apply gate were replaced by 0018's
> two-mode model (gate #1 = recurrence/human-accept; gate #2 = auto-apply + guard rollback).

Status: implemented (schema version 30)
Date: 2026-06-04

Inverts the issue-centric loop of [0016](0016-issue-centric-loop.md) so that **analysis
surfaces Issues only** and a `LearningProposal` is authored in a **separate, gate-#1-guarded
step**. Adds a deterministic **skillbook-consolidation turn** that runs after every analysis
to keep the skillbook live and tracked. Does not change the `LearningProposal` JSON contract
([0002](0002-learning-proposal-contract.md)); adds one authoring contract for issues
(`kyoko.issue.v1`). The proposal-apply gate ([0003](0003-autonomy-policy.md)) is unchanged.

This **supersedes** the proposal-first origination in 0016: `originate_issue_for_proposal`
(proposal → derived issue) is removed; the direction is now issue → proposal.

## Motivation

0016 made the Issue the spine but kept analysis *proposal-first*: an operator authored a
`LearningProposal` and Kyoko back-derived an Issue from it. That welds the diagnosis to a
one-shot fix, burns operator tokens authoring fixes for problems no one approved, and makes
it impossible to bundle recurrences of the same problem across time. It also does not match
how humans fix things: surface a problem → decide it's worth fixing → design the fix.

The new flow separates the two cognitive jobs and seats the human/auto decision entirely on
the **existing per-section autonomy toggle** (`context_mode` / `harness_mode`), adding no new
policy switch.

## The flow

```
ANALYSIS (diagnosis only — cheap, no fix authored)
  operator turn 1: read evidence → emit kyoko.issue.v1 issue(s)
        │
  deterministic dedup net (surface_issue): a recurrence of the same failure folds into the
        │  existing issue (bump recurrence_count; re-open a resolved/guarded one as a regression)
        ▼
  GATE #1 — per issue, on the section's autonomy mode:
        off        → issue stays diagnosed; stop
        propose    → issue awaits HUMAN acceptance; stop
        autonomous → accept_issue → operator turn 2: author one LearningProposal for THIS issue
        ▼
  GATE #2 — the unchanged apply gate (generate checks → replay → run_autonomy → apply)
        ▼
  resolve issue → mint deterministic guard (0016, unchanged)
        ▼
  SKILLBOOK CONSOLIDATION (after every analysis): deterministically detect duplicate skills
        and submit gated MERGE/UPDATE/DEACTIVATE proposals through the same gate.
```

Acceptance is the gate-#1 action: in `propose` mode a human accepts an issue (CLI
`accept-issue`, API `POST /api/issues/accept`, or the dashboard); in `autonomous` mode the
improve loop auto-accepts and authors inline.

## Data model (schema 29 → 30, additive)

`issues` gains:

- `signature` — deterministic dedup fingerprint (`compute_issue_signature`): run-independent
  anchors = section + affected span **names** (resolved from per-run ids) + stable target ids;
  falls back to a normalized title slug when there are no structural anchors.
- `recurrence_count` — times the failure has been surfaced (≥1).
- `accepted_at` — when gate #1 accepted the issue.

The lifecycle `status` gains **`accepted`** between `diagnosed` and `proposed`:
`open → prioritized → diagnosed → accepted → proposed → applied → resolved → guarded`
(+ `dismissed`).

## The issue-authoring contract (`kyoko.issue.v1`)

The diagnosis turn returns a JSON array of issues in a
`BEGIN_KYOKO_ISSUES_JSON … END_KYOKO_ISSUES_JSON` block. Required: `schema_version`,
`title`, `section` (context|harness — selects the gate-#1 mode), `root_cause`,
`evidence_refs` (≥1, referentially checked). Optional: `body`, `severity`, `category`,
`keywords`, `affected_{span,agent_identity,workflow_node,task}_ids`. Validated by
`issues.validate_issue` (schema + enums + referential integrity, mirroring
`validate_learning_proposal`). Schema authored at
[`../schemas/issue.schema.json`](../schemas/issue.schema.json); the runtime copy bundles at
`kyoko/assets/schemas/issue.schema.json`.

## Skillbook consolidation

Modeled on ACE's `DeduplicationManager` but **deterministic-first and gated** — no embeddings,
no new dependency, no new apply primitive, no new check type, no LLM in the mock path.

- `detect_duplicate_skill_groups` — groups ACTIVE skills by `(section, normalized keyword set)`
  or identical issue text (run-independent, stable ordering; conservative/precision-favoring).
- `build_consolidation_proposal` — one `kyoko.learning_proposal.v1` per group. A **MERGE** is
  expressed with the **existing** `skillbook_update` ops: `update` the winner (union of
  keywords/occurrences + combined issue/insight), `deactivate` each loser, `link_occurrence`
  to move losers' occurrences onto the winner. Winner = most occurrences, tie-break oldest
  `created_at` then smallest id.
- `run_skillbook_consolidation` — submits the proposals (PENDING) and, with
  `run_autonomy_after`, runs the same gate. Consolidation **never writes skills directly** —
  apply still happens solely in `run_autonomy`. Gate fallback: a deterministic
  `target_status_not_failed` check at `L0_generated`; the merge applies under the section's
  autonomy mode once promoted to the required level, otherwise stays pending for human review.

Issue bundling across time is the deterministic dedup net (above); semantic/fuzzy bundling
and embedding-based skill similarity (ACE's `[deduplication]` path) are a deliberate future
optimization, gated behind growth (ACE's ~50-skill heuristic), not built here.

## Implementation

- [`../../kyoko/issues.py`](../../kyoko/issues.py) — `surface_issue` (dedup net),
  `compute_issue_signature`, `find_issue_by_signature`, `bundle_into_issue`, `accept_issue`,
  `validate_issue`; lifecycle gains `accepted`.
- [`../../kyoko/operator_prompts.py`](../../kyoko/operator_prompts.py) — `kind` ∈
  diagnose|propose|consolidate; `write_diagnosis_prompt_artifacts`,
  `write_proposal_prompt_artifacts`, `write_consolidation_prompt_artifacts`.
- [`../../kyoko/analyze.py`](../../kyoko/analyze.py) — issue-centric `AnalyzeReport`; operators
  surface issues; `extract_issues_from_output`; mock split (`mock_issues_from_bundle`,
  `mock_proposal_from_issue`); `propose_for_issue` (the proposal-authoring turn).
- [`../../kyoko/proposals.py`](../../kyoko/proposals.py) — proposal-first origination removed.
- [`../../kyoko/autonomy.py`](../../kyoko/autonomy.py) — `evaluate_issue_to_proposal_gate`
  (gate #1) now seats on the issue at acceptance time.
- [`../../kyoko/improve.py`](../../kyoko/improve.py) — drives analyze → per-issue gate #1
  (accept + propose) → gate #2 → resolve + guard → consolidation; `ImproveReport` gains
  `proposal_ids`, `gate1_outcomes`, `consolidation`.
- [`../../kyoko/analyze.py`](../../kyoko/analyze.py) and
  [`../../kyoko/issues.py`](../../kyoko/issues.py) — the issue integration and consolidation
  path.
- CLI: `accept-issue`, `consolidate-skillbook`. API: `POST /api/issues/accept`,
  `POST /api/skillbook/consolidate`. MCP: `kyoko_submit_issue` (validates against the issue
  schema, surfaces evidence-only; not an apply/harness tool).

## SCOPE compliance

Single-player/local throughout. No new policy table — gate #1 reuses `context_mode`/
`harness_mode`. Acceptance is a status flip + trigger, not an approval state machine (no
assignees/SLAs). Consolidation adds no dependency and no new gate type; it routes through the
existing safety boundary (every behavior change is a gated proposal; apply only in
`run_autonomy`). Guards and consolidation checks stay deterministic.

## Contracts

`analyze`, `improve`, `accept-issue`, `consolidate-skillbook`, and `bundled-assets` `--json`
shapes are frozen in [0005](0005-cli-json-contracts.md) with goldens under
`../fixtures/cli-json/`.
