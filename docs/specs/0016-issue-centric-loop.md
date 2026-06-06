# 0016 — Issue-Centric Optimization Loop

> **GATE MODEL SUPERSEDED (2026-06-05) by [0018](0018-two-mode-autonomy-rebuild.md).** The
> issue spine / dedup net / recurrence machinery remain current; the gate #1 (context_mode/
> harness_mode) and gate #2 (check/replay) described below were replaced by 0018's two-mode model.

Status: implemented (schema version 29); **partly superseded by
[0017](0017-analysis-issue-decoupling-and-consolidation.md)** (schema 30), which inverts
the direction — analysis now surfaces Issues and a proposal is authored separately
(gate #1 moves to issue *acceptance*), so the proposal-first `originate_issue_for_proposal`
chokepoint described below is removed. The spine, guard codegen (step 08), and gate #2 are
unchanged.
Date: 2026-06-04

Re-architects Kyoko's optimization loop so the **Issue** is the central spine. Supersedes
the dead-end Issue model in [0012-issue-model.md](0012-issue-model.md) and adds gate #1
(issue → proposal) on top of the unchanged proposal-apply gate in
[0003-autonomy-policy.md](0003-autonomy-policy.md). It does **not** change the
`LearningProposal` JSON contract ([0002](0002-learning-proposal-contract.md)) beyond one
optional `issue_id` field.

Implementation:

- [`../../kyoko/issues.py`](../../kyoko/issues.py) — Issue entity + lifecycle mutators
  (`set_issue_rank`, `set_issue_diagnosis`, `link_proposal_to_issue`, `set_issue_evaluator`)
- [`../../kyoko/proposals.py`](../../kyoko/proposals.py) — `originate_issue_for_proposal`
  (the single chokepoint) + referential `issue_id` check in `validate_learning_proposal`
- [`../../kyoko/analyze.py`](../../kyoko/analyze.py) — analysis routes through the spine and
  evaluates gate #1 at the persist boundary
- [`../../kyoko/autonomy.py`](../../kyoko/autonomy.py) — `IssueProposalGate` /
  `evaluate_issue_to_proposal_gate` (gate #1)
- [`../../kyoko/improve.py`](../../kyoko/improve.py) — orchestrates analyze → check/replay →
  gate #2 (apply) → resolve + guard
- [`../../kyoko/issue_guard.py`](../../kyoko/issue_guard.py) — `mint_guard_for_issue` /
  `generate_guard_detector_source` (deterministic guard codegen, step 08)
- [`../../kyoko/eval_issues.py`](../../kyoko/eval_issues.py) — measurement aggregate →
  Issue (`raise_issue_for_run`), tagging provenance `source`
- [`../../kyoko/eval_detectors.py`](../../kyoko/eval_detectors.py) —
  `register_detector_source(..., issue_id=...)` binds a guard to its issue
- [`../../kyoko/storage.py`](../../kyoko/storage.py) — schema version 29 (issue columns,
  `eval_definitions.issue_id`, `learning_proposals.issue_id`)

## Purpose

Before this spec, analysis created a `LearningProposal` directly and the `Issue` entity was
a parallel, optional record that nothing required — a dead-end (see
[0012](0012-issue-model.md)). Measurements ([0014](0014-evaluation-metrics.md)/
[0015](0015-evaluation-metrics-implementation.md)) could raise issues, but those issues had
nowhere to go.

This spec makes the Issue the **mandatory origin** of every proposal. The loop reads:
analysis and the measurement planes flow **into** issues; issues flow **into** proposals;
proposals are gated and applied; a resolved issue grows a standing **guard evaluator** that
watches future traces and re-enters the spine on recurrence. The Issue is the durable
through-line that ties capture → diagnosis → fix → monitoring together.

The Issue itself stays **pure evidence** — creating, prioritizing, diagnosing, or resolving
an issue never changes agent behavior. All behavior change still happens downstream through
the proposal → check/replay → autonomy gate, exactly as before.

## The 8-step human job map

The spine maps one-to-one onto the eight steps a human does when they fix an agent failure:

| Step | Job | Where it lands |
|---|---|---|
| 01 | **capture** the failure (a trace, a measurement hit, a manual note) | evidence refs on a new Issue (`source = analysis \| eval \| llm_eval \| manual`) |
| 02 | **surface + prioritize** | Issue `status = open → prioritized`, `rank` (lower = more urgent) |
| 03 | **locate** the trace / affected operations | `affected_span_ids` / `affected_*` on the Issue |
| 04 | **diagnose** the root cause | `root_cause` text, Issue `status = diagnosed`, fix `section` chosen |
| 05 | **determine the fix** | `LearningProposal` originated from the Issue, `status = proposed` |
| 06 | **validate** | generated `check` spec(s) + replay (`improve.py`) |
| 07 | **implement** | gate #2 applies; Issue `status = applied → resolved` |
| 08 | **monitor + guard** | a guard evaluator is minted, bound to the Issue, `status = guarded` |

Steps 01–04 are the issue side (evidence). Step 05 crosses into the proposal side via
**gate #1**. Steps 06–07 are the existing **gate #2** (check/replay + apply). Step 08 closes
the loop back onto the spine.

## Issue lifecycle state machine

Schema version 29. The lifecycle lives entirely in the existing `status` column; v29 adds
four columns (`rank`, `root_cause`, `source`, `evaluator_id`) — no new status table.

```
open ──► prioritized ──► diagnosed ──► proposed ──► applied ──► resolved ──► guarded
  │           │              │            │            │           │
  └───────────┴──────────────┴───── dismissed ◄───────┴───────────┘
```

- `open` → `prioritized`: `set_issue_rank` (step 02). Auto-advances an `open` issue when a
  non-null rank is set.
- `prioritized` → `diagnosed`: `set_issue_diagnosis` records `root_cause` and (optionally)
  the fix `section` (step 04). Analysis surfaces *and* diagnoses in one move, so an
  analysis-originated issue is created already `diagnosed` (see "The spine in code").
- `diagnosed` → `proposed`: `link_proposal_to_issue` (step 05), after gate #1 allows
  generation and the proposal is persisted.
- `proposed` → `applied` → `resolved`: gate #2 applies the proposal, then `improve.py`
  marks the originating issue `resolved` (step 07).
- `resolved` → `guarded`: `set_issue_evaluator` binds the minted guard and reaches the
  terminal "loop closed" state (step 08).
- `dismissed`: a terminal off-ramp reachable from any state.

`ISSUE_LIFECYCLE_ORDER` in `issues.py` records the forward progression (`dismissed` is
omitted as it is reachable from anywhere). The plain `update_issue_status` mutator stays
**permissive** — it accepts any valid status for manual triage/correction; the typed
mutators (`set_issue_rank`, `set_issue_diagnosis`, etc.) are the ones that advance the
machine in normal flow. `open` / `resolved` / `dismissed` are retained for backward
compatibility with the 0012 model.

New v29 columns on `issues`:

| Column | Notes |
|---|---|
| `rank` | nullable int; prioritization order, lower = more urgent (step 02) |
| `root_cause` | nullable text; diagnosis narrative (step 04). Authored — **not** redacted |
| `source` | nullable; `analysis \| eval \| llm_eval \| manual` — provenance |
| `evaluator_id` | nullable; the guard `eval_definitions.id` once resolved (step 08) |

Validated in `kyoko/issues.py`, not in the DB (matching the rest of the schema). Index
`idx_issues_evaluator_id`. v29 also adds `learning_proposals.issue_id` and
`eval_definitions.issue_id` (both nullable FKs to `issues(id)`).

## The spine in code (origin invariant)

`originate_issue_for_proposal(db_path, proposal, source, profile_id)` in `proposals.py` is
the **single chokepoint** that enforces the spine: every production proposal producer routes
through it, so a proposal can never exist without an issue. It creates the originating Issue
(already `diagnosed`, carrying the proposal's `insight` as `root_cause`, plus the proposal's
`section` / `evidence_refs` / target span) and stamps `proposal["issue_id"]` in place.

`validate_learning_proposal` referentially checks `issue_id` when present
(`issue_not_found:<id>`). The field is **schema-optional** so legacy static fixtures still
validate, but all production producers stamp it.

`analyze.py` (mock + command operators) is the canonical producer: surface+diagnose an Issue
via `originate_issue_for_proposal(source="analysis")`, evaluate **gate #1**, and — if
allowed — persist the proposal and `link_proposal_to_issue` to backlink and advance to
`proposed`. On the command operator's retry path the issue is created **once** and the same
`issue_id` is re-stamped across retries, so a failed attempt never orphans a fresh issue.

## The two gates

There are two distinct gates. Gate #1 is new; gate #2 is unchanged.

### Gate #1 — issue → proposal (generate / no-generate)

`evaluate_issue_to_proposal_gate` / `IssueProposalGate` in `autonomy.py`. It **reuses the
existing `context_mode` / `harness_mode` switches** — no new policy surface. The fix
`section` of the issue selects which mode applies:

| Mode (for the fix section) | Gate #1 outcome |
|---|---|
| `off` | stop at `diagnosed` — surface + diagnose only, **no proposal** generated |
| `propose` | generate a proposal; a human applies it (gate #2 still required to apply) |
| `autonomous` | generate a proposal that **flows on** to gate #2 |

This is purely a **generate / no-generate** decision; the apply decision stays with gate #2.
An unsupported/absent section yields `allow_generate = False`
(`unsupported_section:<section>`).

**Gate #1 lives at the analyze persist boundary.** In `analyze.py`, after the Issue is
originated, the gate is evaluated against the proposal's `section`; when `allow_generate` is
false the operator run is marked `succeeded`, the `AnalyzeReport` returns `proposal_id =
None` with `gate1_*` fields set, and no proposal JSON is written or submitted. `improve.py`
sees the `None` proposal and returns a diagnosed-only `ImproveReport`
(`note: gate1_blocked:<reason>`) — there is nothing to check/replay/apply.

### Gate #2 — proposal → apply (unchanged)

The existing autonomy gate from [0003](0003-autonomy-policy.md), evaluated by
`autonomy_runner.py`: **context** autonomy requires a passing check at trust ≥ **L1**
(replay **not** required); **harness** autonomy requires trust ≥ **L2** (regression proof,
so replay **is** required), plus a clean/allowed git worktree, allowed paths, secret scan,
and a captured rollback preimage. Repo patches remain off by default
(`allow_repo_patch`). None of this changes — gate #1 only governs whether a proposal is born;
gate #2 governs whether it is applied.

## Guard evaluators — closing the loop (step 08)

When gate #2 applies a proposal, `improve.py` walks each applied decision, marks the
originating Issue `resolved`, and calls `mint_guard_for_issue` (`issue_guard.py`). A resolved
issue is **not truly closed** until it owns a guard.

**Deterministic-first by strong owner preference.** `mint_guard_for_issue` generates a
**Python detector** (`generate_guard_detector_source`) — a `detect(trace_data, trace_id)`
function that re-flags spans which fail in the **originally-affected operations**, scoped by
span **name** (resolved from the issue's `affected_span_ids`). With no known span names it
degrades to a generic failed-span guard. The generated detector is registered via
`register_detector_source(source="guard", issue_id=...)`, which binds it to the issue through
`eval_definitions.issue_id`, and `set_issue_evaluator` stores the reverse link
(`issues.evaluator_id`) and advances the issue to `guarded`. Minting is idempotent —
re-minting upserts the same `guard_<issue_id>` definition.

An **LLM-judge guard is a deliberate last resort**, used only when the failure genuinely
cannot be expressed as code (`prefer_llm`); see [0015](0015-evaluation-metrics-implementation.md)
for the `llm_eval` plane. The default path is always code.

**Recurrence re-enters the spine.** A guard is an `eval` definition; when it (or any
measurement) scores past threshold, `eval_issues.raise_issue_for_run` raises a **fresh
Issue** with `source = eval` (deterministic detector / guard) or `source = llm_eval` (judge),
carrying the metric run + worst-scoring units as evidence. That new issue starts at `open`
and walks the lifecycle again — the loop is closed.

```
   analysis ─┐
   eval ─────┼──► Issue ──(gate #1)──► Proposal ──(gate #2: check/replay)──► applied
   llm_eval ─┤      ▲                                                            │
   manual ───┘      │                                                       resolved
                    │                                                            │
                    │                                                        guarded
                    │                                                            │
                    └──────────── recurrence (eval/llm_eval) ◄── guard evaluator ┘
```

## What changed vs. the old architecture

- **Before:** `analyze.py` created a `LearningProposal` directly. The `Issue` entity
  ([0012](0012-issue-model.md)) was an optional, parallel record — nothing required it and
  nothing consumed it downstream; it was a dead-end. Measurements could raise issues, but
  those issues led nowhere.
- **Now:** the **Issue is the mandatory origin** of every proposal. `analyze.py` routes
  through `originate_issue_for_proposal` (the single chokepoint), gate #1 decides whether the
  diagnosed issue generates a proposal at all, and on apply the issue is resolved and grows a
  standing guard that watches for recurrence. Analysis and both measurement planes all
  funnel into issues; the proposal is always born of one.
- The proposal-apply gate (gate #2 / [0003](0003-autonomy-policy.md)) and the
  `LearningProposal` JSON contract ([0002](0002-learning-proposal-contract.md)) are
  otherwise unchanged; the only proposal-shape addition is the optional `issue_id`.

## SCOPE compliance

Per [docs/SCOPE.md](../SCOPE.md), this is a **single-player, single-machine, single
invisible profile** feature. The single implicit profile is resolved whenever a `profile_id`
is omitted; there is no profile picker. Issues, ranks, root causes, and guards are the one
user's own evidence and the one user's own repo/skillbook being optimized.

The 8-step job map is borrowed only as a description of one person's debugging workflow. Any
**cross-customer / multi-tenant** framing of that job map is **explicitly NOT implemented** —
Kyoko optimizes exactly one agentic workflow stream. There is no per-tenant prioritization,
no shared issue queue, no second reviewer, and no fan-out across workflows. Gate #1 adds no
new policy table, no approval state machine, and no audit ledger; it is a pure read of the
two autonomy modes that already exist. Authored issue text (`title` / `body` / `root_cause`)
is the user's own and is not redacted; `evidence_refs` are still resolved/served through the
standard redact-on-export path.
