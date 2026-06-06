# 0019 — Issue/Skillbook unification (the living ACE skillbook)

Status: implemented (branch `issue-centric-loop`, SCHEMA_VERSION 32)
Supersedes the two-table split introduced by 0016 where it conflicts.

## Why

Kyoko previously split the agent's problem-space into two tables: `issues` (the living
log — evidence, root_cause, status lifecycle, recurrence, guard binding, regression
watermarks) and `skills` (the gated, injected content). ACE (the reference engine,
`~/Desktop/agentic-context-engine`, v0.12.0) does **not** split: one `Skill` record *is*
the atomic unit — it holds the problem (`issue`), the evidence trail (`occurrences`), the
effectiveness feedback (`helpful/harmful/neutral/used` counts), and the solution
(`insight`), and it evolves over runs via `add/update/tag/mark_used/remove`.

The owner asked for Kyoko's skillbook to behave the same way: **the issue lives in the
skillbook, not in a separate table.** This is a lean port of ACE's model, not a rewrite —
the existing `skills` table was already ~90% of ACE's `Skill`.

## The model

One `skills` row is the living skillbook entry. It carries:

- **Problem facet** (was the Issue): `issue` (problem statement), `body`, `status`,
  `severity`, `category`, `source`, `root_cause`, `evidence_refs_json`, `affected_*_ids_json`,
  `signature` + `recurrence_count` (a recurrence folds into the SAME row).
- **Living state** (ACE): `occurrences_json`, `helpful_count`/`harmful_count`/
  `neutral_count`, `used_count`, `active`. Evolved in place by `tag_skill` / `mark_skills_used`.
- **Solution**: `insight`, `keywords_json` (NULL/empty until proposed).
- **Gate + guard + regression**: `proposal_id` + `proposal_ids_json`, `accepted_at`,
  `applied_at`, `recurrence_count_at_apply`, `auto_fix_attempts`, `autonomy_blocked`,
  `evaluator_id` (the standing guard), and the durable detecting-metric link
  `source_eval_definition_id` / `source_measure_run_id`.

(Removed at v33: the `skill_similarity_decisions` table and the separate
`skillbook_manager` consolidation pass — the analysing agent now reconciles the skillbook in
place at authoring time, so the deterministic second-pass dedup and its KEEP memory are
retired. See "The analysing agent integrates into the living skillbook" below.)

## The three adaptations from ACE

1. **SQLite-backed**, not a JSON document — Kyoko convention. `ace_bridge.export_skillbook`
   still emits ACE's v2 JSON shape as a derived view (the rows are the source of truth, so
   the entry keeps its FK links to proposals, guards, evidence, and telemetry).
2. **The gate stays.** ACE mutates and activates skills directly; Kyoko does not. An entry
   stays `active = 0` (never injected into a run) until it passes the autonomy gate. The
   skillbook is the living state, but only gated entries get rendered. This is the one
   non-negotiable divergence. `tag`/`mark_used`/similarity-decision are measurement-only and
   so mutate in place like ACE (they never change *what* is injected).
3. **Guard/regression ride along** as columns on the entry (the `issues` table is gone).

## Lifecycle (lean — replaces the 8-state issue machine)

```
surfaced (active=0) ─► diagnose ─► gate #1 (accept) ─► author insight (proposal)
   ─► gate #2 / apply: ACTIVATE the insight on the SAME row (active=1, status='applied')
   ─► mint guard ─► regression watermark ─► on confirmed regression: deactivate (active=0)
     + reopen (status='open')
```

`apply._apply_skillbook_updates` activates the originating entry (the proposal's
`issue_id`) in place rather than inserting a second row; a direct proposal with no origin
inserts a fresh, already-active skill.

## The analysing agent integrates into the living skillbook (ACE SkillManager)

The diagnosis turn no longer authors issues blind. `build_diagnosis_prompt` renders the
**current living skillbook** — the active (injected, read-only) skills and the open
problem-phase issues with their ids — and asks the operator to *integrate* its findings via
a per-item `op` on `kyoko.issue.v1`:

- **`add`** (default) — surface a genuinely new problem-phase entry.
- **`update`** + `target_id` — refine an existing open entry in place (sharper
  `root_cause`, more evidence). Scalars overwrite; `evidence_refs`/`affected_span_ids`
  union (`kyoko.issues.update_issue`).
- **`merge`** + `target_id` — fold a recurrence into an existing open entry (union evidence,
  bump `recurrence_count`; `kyoko.issues.merge_observation` → `bundle_into_issue`).

This is the ACE SkillManager move, adapted to Kyoko's gate: **the agent reconciles the
problem-phase layer directly (ungated — issues change nothing that runs)**, but may **only**
target open issues. An `update`/`merge` whose target has vanished or gone `active`
(injected) **falls back to `add`** so the observation is never lost — an active entry's
injected content evolves solely through the proposal → gate path. The deterministic
signature net (`surface_issue`/`compute_issue_signature`) remains as a free backstop under
`add`, folding an obvious recurrence the agent missed. Proposals are unchanged and remain
downstream of this turn.

## Lenses (per-step views over one table)

- **Issues lens** (`kyoko/issues.py`, the `issues`/`issue-*` CLI/API/MCP surface): entries
  in a problem-phase `status`, used by the analyzer/diagnose/gate steps.
- **Skillbook lens** (`render_skillbook_prompt`, `list_skills`, `skills` surface): `active`
  entries, rendered into runs (only `issue`+`insight`+`keywords` are injected).
- **Proposals** gained `state` filtering (pending/applied/rolled_back) so a gate-step agent
  sees just its slice.

## Migration

Pre-prod, no data migration: `DROP TABLE issues`; `skills` carries the lifecycle. Indexes
over v32-added skill columns are created after the column migration so legacy DBs migrate
cleanly. Existing pre-v32 DBs should be recreated.

## What was deliberately dropped (cruft, per the lean directive)

The 8-state issue lifecycle machine is collapsed; `rank`/`category`/`review_comment` are
retained as nullable columns only to keep the issues lens a trivial projection (they are no
longer load-bearing). Analysis/measurement still surface entries the same way; the
behavior-change safety boundary (proposal → gate → apply) is unchanged.
