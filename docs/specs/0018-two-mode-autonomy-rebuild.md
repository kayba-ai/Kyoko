# 0018 — Two-Mode Autonomy + Recurrence Trigger + Guard/Rollback (rebuild)

Status: IMPLEMENTED (2026-06-05, schema version 31) on branch `issue-centric-loop`. Supersedes
the trust-ladder + three-mode + per-section machinery in [0003](0003-autonomy-policy.md),
[0016](0016-issue-centric-loop.md), and [0017](0017-analysis-issue-decoupling-and-consolidation.md).
Pre-production: bad logic deleted, no backward-compat.

> **Implementation note (what shipped vs. this plan):** the new two-mode model, gates,
> recurrence-triggered improve loop, guard monitor + auto-rollback, watermark/escalation
> columns, and all surfaces (CLI/web/MCP/dashboard) are built. **One deviation:** the
> apply-CHECK plane and replay were *demoted out of the autonomy gate* rather than physically
> deleted (Open Decision #3's "demote" option). `checks.py`, the `check_*`/`replay_*` tables,
> and the generate-checks/run-check/replay-* commands still exist as standalone manual tools;
> they are simply no longer part of the gate or the improve loop, and check writes are no longer
> policy-gated. Physically removing those modules is a clean follow-up. `gate_expectations_json`
> on proposals was likewise kept (unused by the gate) to avoid the proposal-schema/fixture cascade.

Branch: `issue-centric-loop` (continue here). Test under `/tmp/kyoko-venv/bin/python3`
(py3.9 default is wrong); `rm -rf kyoko.egg-info` before full-suite runs; never `git add`
`docs/`; commit per phase (local only).

This revision is grounded against the current code (functions/signatures verified on branch
`issue-centric-loop`); every "reuse X" below names a function that exists today, and every
"NEW" is genuinely net-new.

---

## Why (the decisions that led here)

1. **You can't pre-prove a probabilistic agent's fix.** The agent's output is a sample from
   a stochastic policy. A single replay "fail→pass" is n=1 noise. So preflight proof (the
   whole L-ladder) is the wrong frame.
2. **L1 was near-tautological** — re-running a deterministic check gives the same answer; for
   context changes the check can't even validate the fix. **L2** pretended one replay proved a
   stochastic fix. **L0–L3 isn't one axis** (reproducible verdict / regression fixed / human
   approved are different *kinds* of evidence stacked into a fake ladder).
3. **Two human checkpoints + three modes + per-section** was overcooked. A gate is a decision
   *point*; the *mode* decides who approves it. Reduce the **modes**, keep the gates.
4. **Per-section (context vs harness) doesn't matter for the mode** — "either a human reviews
   it or the machine does it on its own."

The realistic model for a probabilistic system: **gate on real evidence (recurrence), apply,
then monitor + roll back** (a control loop / canary), not preflight certainty.

**Consistency corollary (drives the rollback design):** if a single replay pass is too weak to
*prove* a fix works, then a single guard fire is too weak to *prove* a fix failed. The rollback
trigger must therefore be **recurrence-based, not single-fire** — symmetric with the gate-#1
trigger (see "Guard-monitoring loop").

---

## The model

Two gates (real pipeline decision points), **two modes** (who/what approves each gate):

| | **Gate #1** — issue → propose ("work on this?") | **Gate #2** — propose → apply ("ship this fix?") |
|---|---|---|
| **HITL** | a human accepts the issue | a human approves the proposal |
| **Autonomous** | `recurrence_count >= recurrence_threshold` (auto) | auto-apply, then guard + rollback validate |

- **One global `mode ∈ {hitl, autonomous}`** — NOT per-section, NOT three-way. (`off`/observe
  is just HITL with the human taking no action; analysis/surfacing always runs — see Decision #1.)
- **Gate #1 evidence = recurrence in production** (real samples via the existing dedup net),
  not a check. Autonomous waits for the pattern; HITL lets a human act on a single occurrence.
- **Gate #2 validation = the guard, post-hoc.** Autonomous applies immediately, mints the
  guard (already built), and **rolls back + re-opens** if the guard *re-recurs* past threshold
  (regression). No checks, no replay, no trust levels in the gate.
- **Asymmetry that falls out:** autonomous *needs* evidence at gate #1 (can't ask a human);
  HITL uses human judgment. A failing fix never abandons the issue — it re-opens for a new fix
  (bounded by `max_auto_fix_attempts`, then escalates to HITL — see Decision #5).

### The unification insight (reduces branching — apply this in code)

Both modes converge on the **same two state transitions**; the mode only decides *what triggers*
each transition:

```
issue: ... → ACCEPTED → (propose) → proposal: PENDING → APPLIED → resolve + mint guard
                ▲                                          ▲
        gate #1 trigger                            gate #2 trigger
   HITL: human calls accept_issue            HITL: human calls apply (approve action)
   AUTO: loop calls accept_issue when        AUTO: loop calls apply immediately
         recurrence_count >= threshold
```

So **autonomous gate #1 == auto-invoke the existing `accept_issue()`** when the threshold is
crossed; HITL gate #1 == a human invokes the same `accept_issue()`. Likewise gate #2 is one
apply path (`apply_context_proposal` / `apply_patch_transaction`); the gate only decides whether
a human or the loop pulls the trigger. **Do not write two parallel pipelines** — write one, with
a two-line trigger difference at each gate.

### The recurrence loop (the spine)
```
surface issue (recurrence 1)
  → recurs → dedup net bumps recurrence_count (2, 3, …)
  → AUTONOMOUS: at threshold → accept_issue → author proposal → auto-apply → resolve → mint guard
       guard re-recurs past regression_threshold (after applied_at) → roll back + re-open
       → after max_auto_fix_attempts rollbacks → set autonomy_blocked (escalate to HITL)
  → HITL: human accepts → author proposal → human approves → apply → resolve → mint guard
```

---

## What is REMOVED

- **Trust ladder** `L0_generated/L1_repeated/L2_regression/L3_human_approved`, `TRUST_ORDER`,
  and all promotion logic (`checks._maybe_promote_trust_level`, `CHECK_TRUST_LEVELS`,
  `GATEABLE_CHECK_TYPES`, `_stricter_level`).
- **Gate eval in `autonomy_runner`**: `_evaluate_check_gate`, `_gate_requirements`,
  `CheckGateStatus`, and the `gate_expectations_json` plumbing on proposals.
- **Gate-#1 helper**: `autonomy.evaluate_issue_to_proposal_gate` and its three-way
  `off`/`propose`/`autonomous` result — replaced by `evaluate_gate1` (below). The **`propose`
  middle mode** (auto-author + human-apply) is gone.
- **Policy fields**: `context_mode`, `harness_mode`, `required_check_level_context`,
  `required_check_level_harness`, `allow_skillbook_write`, `allow_check_write`,
  `allow_profile_config_write`, `allow_replay_server_patch` (Decision #4 keeps only the repo fence).
- **The apply-CHECK plane as a gate**: `generate_checks_for_proposal` + check-running + replay
  as the gate-#2 mechanism. Tables `check_specs`/`check_locks`/`check_runs`/`replay_runs` dropped
  (Decision #3 = full delete).
- Per-section autonomy entirely.

## What is KEPT (do not break)

- Issues + lifecycle + **dedup net / `recurrence_count`** ([0017](0017-analysis-issue-decoupling-and-consolidation.md))
  — gate #1's evidence. `surface_issue` / `bundle_into_issue` / `compute_issue_signature` /
  `accept_issue` (idempotent, stamps `accepted_at`) all stay as-is.
- The **two-turn operator**: diagnosis (surface issues) + proposal-authoring (`propose_for_issue`).
- **Apply + rollback** (verified to exist, reused verbatim):
  - context: `apply.apply_context_proposal(db_path, proposal_id, allowed_states=("pending",))`;
    reverse via `apply.rollback_skill_revision` + `apply.rollback_context_delivery_rule_revision`.
  - harness: `harness.apply_patch_transaction`; reverse via `harness.rollback_patch_transaction`
    (uses `patch_transactions.rollback_json`).
- **Guards** (`issue_guard.mint_guard_for_issue` → a deterministic `eval_detectors` python
  detector, bound to the issue via `set_issue_evaluator`, advancing it to `guarded`) +
  **`eval_detectors`** — KEEP this module even though the rest of the check plane goes.
- The **measurement plane** (`eval` / `llm_eval`, `eval_issues.raise_issue_for_run`) — already
  evidence-only, non-gating; it is how a guard fire re-opens/bundles the issue.
- **Skillbook consolidation** ([0017](0017-analysis-issue-decoupling-and-consolidation.md),
  `run_skillbook_consolidation`) — gating simplifies to gate #2 only (see below).
- The **Scheduler** (`analysis_runner.Scheduler`, daemon thread, `poll_seconds` default 60,
  `analysis_schedules.watermark`) — reused to run the guard-monitoring loop.

## What is NEW (the only real build — the rest is deletion)

Most of the rebuild is removal. The genuinely net-new code is small and concentrated in the
**guard-monitoring + auto-rollback loop** (gate #2's autonomous validator):

1. **`apply.rollback_applied_change_for_issue(db_path, issue_id)`** *(NEW, thin)* — traverses
   `issue.id → learning_proposals.issue_id → {skill_revisions,context_delivery_rule_revisions,
   patch_transactions}.proposal_id` and calls the existing per-revision rollbacks. No new table:
   the traversal path already exists. Reverses context freely; for harness/repo see Decision #6.
2. **`autonomy_runner.monitor_guarded_issues(db_path, profile_id)`** *(NEW)* — the validator
   pass the Scheduler runs. For each issue in `resolved`/`guarded` with an applied fix, decide
   regression by the **recurrence-since-apply** rule (below); on regression and
   `auto_rollback_on_regression`, call `rollback_applied_change_for_issue`, re-open the issue,
   bump `auto_fix_attempts`; if attempts reach `max_auto_fix_attempts`, set `autonomy_blocked`
   (escalate to HITL — autonomous gate #1 will skip blocked issues).
3. **Apply-time watermark** *(NEW columns, not a new table)* — stamp `issues.applied_at` and
   snapshot `issues.recurrence_count_at_apply` when a fix is applied, so the monitor counts only
   *post-fix* recurrences and never rolls back on stale pre-fix traces.

The detection half is **not** new: guard detectors already fire via the measurement plane and
`eval_issues` already bundles the fire back into the same issue (same signature), bumping
`recurrence_count`. The monitor only reads that counter against the watermark and pulls the
rollback trigger.

### Guard-monitoring loop — regression criterion (the consistency-critical detail)

Define **regression** symmetrically with gate #1, not as a single fire:

```
post_apply_recurrences = issue.recurrence_count - issue.recurrence_count_at_apply
regression := issue.applied_at is not None
              AND post_apply_recurrences >= policy.regression_threshold   # default 2
```

Only recurrences bundled *after* `applied_at` count (the dedup net stamps evidence with the
guard `eval_run`'s time; the monitor ignores fires whose evidence predates `applied_at`). This:
- avoids rolling back a genuinely-helpful-but-imperfect fix on one stochastic recurrence (n=1),
- reuses the existing dedup/recurrence machinery — no rate model, no new counters in hot paths,
- mirrors gate #1: the *same kind* of evidence (repeated recurrence) that authorized the fix is
  what revokes it.

`regression_threshold` is a policy field (default 2; may differ from `recurrence_threshold`).
A future refinement (out of scope for v1) is rate-vs-baseline (`post_rate < pre_rate`); the
count rule is the v1 default because it needs no pre-fix rate storage.

---

## Data model (schema 30 → 31; pre-prod, drop/recreate freely)

**`autonomy_policies`** — DROP and recreate (single invisible profile; pre-prod, no data
migration). New shape:
- `profile_id TEXT PRIMARY KEY`
- `mode TEXT` — `hitl` | `autonomous` (default `hitl`).
- `recurrence_threshold INTEGER` — gate-#1 N for autonomous (default 3).
- `regression_threshold INTEGER` — post-apply recurrences that confirm a regression (default 2).
- `auto_rollback_on_regression INTEGER` — default 1 (renamed from `rollback_on_regression`).
- `max_auto_fix_attempts INTEGER` — K rollbacks before escalating an issue to HITL (default 1).
- `allow_repo_patch INTEGER` — default 0 (the ONE hard capability guard kept; repo/file writes
  are uniquely dangerous, SCOPE bakes off-by-default).
- `allowed_paths_json` / `protected_paths_json` / `dirty_worktree_policy` — **kept only as the
  repo-patch fence** (they bound where a harness patch may write and how a dirty tree is
  handled); inert unless `allow_repo_patch=1`.
- `updated_at TEXT`.
- **Drop**: `context_mode`, `harness_mode`, `required_check_level_*`, `allow_skillbook_write`,
  `allow_check_write`, `allow_profile_config_write`, `allow_replay_server_patch`.

**`issues`** — add columns (`_ensure_column`, additive):
- `applied_at TEXT` — when this issue's fix was applied (monitor watermark).
- `recurrence_count_at_apply INTEGER` — recurrence snapshot at apply (regression baseline).
- `auto_fix_attempts INTEGER` (default 0) — autonomous apply→rollback cycles so far.
- `autonomy_blocked INTEGER` (default 0) + `autonomy_blocked_reason TEXT` — when set, this issue
  is handled as HITL even in autonomous mode (post-escalation). Autonomous `evaluate_gate1`
  returns False for blocked issues.

**Drop tables** (Decision #3 = full delete): `check_specs`, `check_locks`, `check_runs`,
`replay_runs`. Drop `learning_proposals.gate_expectations_json`.

Bump `SCHEMA_VERSION` to 31. The v31 migration block (version-guarded, runs once): `DROP TABLE
IF EXISTS autonomy_policies` + recreate + seed the single default row; `DROP TABLE IF EXISTS`
the four check/replay tables; `_ensure_column` the four new `issues` columns.
`eval_definitions`/issues(core)/skills/measurement/`patch_transactions`/revision tables unchanged.

---

## Gate logic (replaces the `autonomy_runner` check-gate eval)

```
evaluate_gate1(issue, policy):                       # issue -> propose
    if issue.status == "dismissed":      return False
    if policy.mode == "hitl":            return issue.status == "accepted"     # human accepted
    # autonomous:
    if issue.autonomy_blocked:           return False                          # escalated -> HITL
    return issue.recurrence_count >= policy.recurrence_threshold
           or (SEVERITY_OVERRIDE and issue.severity == "high"
               and issue.recurrence_count >= max(2, policy.recurrence_threshold - 1))
           # Decision #2: high severity LOWERS the bar, never to n=1.

evaluate_gate2(proposal, policy):                    # propose -> apply
    if policy.mode == "hitl":            return proposal.human_approved        # explicit approve action
    return True   # autonomous auto-apply; repo/harness writes still gated by allow_repo_patch
```

- **Idempotency / fire-once**: gate #1 only fires on an issue not already past `accepted`
  (`open`/`prioritized`/`diagnosed`), and autonomous gate #1 routes through the existing
  `accept_issue()` (stamps `accepted_at`), so re-running the loop won't re-author. Gate #2 only
  fires on a `pending` proposal with no applied revisions.
- **HITL gate #1 action** = `accept_issue` (exists). **HITL gate #2 action** = a human-triggered
  apply (new CLI/web/MCP entrypoint that calls the *existing* `apply_context_proposal` /
  `apply_patch_transaction`; sets `proposal.human_approved` then applies).
- **Autonomous**: when recurrence crosses threshold the loop runs the chain; gate #2 auto-applies
  (repo/harness still subject to `allow_repo_patch` + the path fence), stamps `applied_at` +
  `recurrence_count_at_apply`, resolves, mints the guard. The monitor handles regression → rollback.

`improve.run_improvement_loop`: delete `generate_checks_for_proposal`, replay, and the
trust-level gate (its current Gate-#2 block). New shape: surface issues → per issue
`evaluate_gate1` → (`accept_issue` + `propose_for_issue`) → per proposal `evaluate_gate2` →
(apply via existing entrypoints, stamp watermark) → resolve + `mint_guard_for_issue` →
consolidation. `ImproveReport` loses `check_spec_ids`/`generated_check_spec_ids`/
`existing_check_spec_ids`/`replay_runs`; keeps `issue`/`proposal_ids`/`gate1_outcomes`/
`guard_reports`/`consolidation` + adds per-gate-2 apply outcomes.

### Consolidation proposals (the one path that skips gate #1)

`run_skillbook_consolidation` runs after every analysis and emits MERGE proposals. These are
**housekeeping, not issue-fixes**: they have no originating issue and no recurrence evidence, so
**gate #1 does not apply** — they enter directly at **gate #2** (HITL = human approves the merge;
autonomous = auto-apply). They get **no guard** (a merge has no failure signature to monitor) and
are therefore **out of the rollback loop**. State this explicitly so consolidation isn't wedged
into the recurrence machinery.

---

## Surfaces

- **CLI**: `policy-set --mode hitl|autonomous --recurrence-threshold N --regression-threshold N
  --auto-rollback on|off --max-auto-fix-attempts K --repo-patch on|off`. Remove
  `--context-mode/--harness-mode/--required-check-level-*` and the `allow-*` flags except the
  repo fence. Keep `accept-issue` (HITL gate #1); add `apply-proposal <id>` (HITL gate #2,
  human-approve+apply). Remove `generate-checks`/`run-check` (check plane deleted).
- **Web**: `/api/policy` new shape; `/api/issues/accept` (gate #1 HITL, exists); new
  `/api/proposals/apply` (gate #2 HITL). Remove check endpoints.
- **MCP**: keep read/propose/`kyoko_submit_issue` + measurement (eval/llm_eval) tools; remove
  check-request tools. Safety contract stays (no direct apply/harness tools exposed to the agent).
- **Dashboard (Autonomy page)**: replace per-section dropdowns + check-level selectors with a
  single **mode toggle (HITL / Autonomous)** + recurrence-threshold + regression-threshold +
  auto-rollback + max-attempts + repo-patch switch. **Issues page**: in HITL show Accept (gate #1)
  then, once a proposal is authored, Approve/Apply (gate #2); show **recurrence progress toward
  threshold**, guard + rollback status, `auto_fix_attempts`, and an **escalated/`autonomy_blocked`
  badge**. Rebuild the bundle (`cd frontend && npm run build`).

---

## Phased rebuild (commit per phase, suite green at each)

- **A — Policy + gates + columns**: schema 31 (recreate `autonomy_policies`; add the four
  `issues` columns; drop check/replay tables); `evaluate_gate1`/`evaluate_gate2`; delete trust
  levels, `_evaluate_check_gate`, `_gate_requirements`, `evaluate_issue_to_proposal_gate`.
  (Policy tests/goldens.)
- **B — Improve loop rewrite**: gate #1 (`accept_issue` on human-accept | recurrence≥N) → author;
  gate #2 (human-approve | auto-apply) → apply + stamp `applied_at`/`recurrence_count_at_apply`;
  remove generate-checks/replay/trust gating from `run_improvement_loop`; trim `ImproveReport`.
- **C — Guard-monitoring + auto-rollback** (the new capability): `rollback_applied_change_for_issue`
  + `monitor_guarded_issues` + a recurring Scheduler pass; recurrence-since-apply regression rule;
  `auto_fix_attempts` + escalate-to-HITL at `max_auto_fix_attempts`.
- **D — Remove the apply-check plane**: delete `checks.py` gate code, replay-as-gate wiring,
  `generate-checks`/`run-check`/check-request MCP tools, and confirm tables dropped in A.
- **E — Surfaces**: CLI/web/mcp per above.
- **F — Dashboard**: single mode toggle + Issues gate actions + escalation/rollback status;
  rebuild bundle.
- **G — Specs/goldens/docs cleanup**; mark 0003/0016/0017 superseded where relevant; regenerate
  every affected `*.golden.json` (schema_version 31, migration range, removed-command contracts).

Order rationale: stand up the new model (A,B) and its validator (C) before deleting the old gate
(D), so nothing is gateless mid-rebuild.

---

## Decisions (resolved — confirm the starred ones at kickoff)

1. **`off`/observe-only** — **DROP.** Surfacing/analysis always runs (pre-gate); "observe only"
   is exactly HITL with no human action, so a third state is redundant. ✔ decided.
2. **★ Severity override at autonomous gate #1** — high severity **lowers** the threshold
   (`max(2, N-1)`), **never** to n=1. Keeps the "real evidence, never one sample" thesis while
   letting rare-but-severe issues act a touch sooner. Gated by a `SEVERITY_OVERRIDE` flag (default
   on). *Confirm: enabled by default?*
3. **Check/replay code** — **FULL DELETE** (tables + `checks.py` gate + replay-as-gate +
   `generate-checks`/`run-check`). `eval_detectors` + measurement plane stay (guards). Replay
   *infrastructure* (`replay_adapters`/`replay_servers`) is also removed unless trivially
   retainable as a manual debug tool — lean delete. ✔ decided (lean delete).
4. **Capability guards** — keep **only** `allow_repo_patch` + its path fence
   (`allowed_paths_json`/`protected_paths_json`/`dirty_worktree_policy`); drop every other
   `allow_*` toggle. ✔ decided.
5. **Autonomous regression** — auto-rollback **and escalate**: after `max_auto_fix_attempts`
   (default K=1) apply→rollback cycles, set `autonomy_blocked` so the issue falls back to HITL
   (stop retrying autonomously). ✔ decided.
6. **★ Auto-rollback of harness/repo patches** — context/skillbook changes auto-rollback freely
   (clean, reversible). For **repo patches**, auto-rollback only when the worktree is clean and
   the `patch_transactions.rollback_json` applies cleanly; otherwise **escalate** (set
   `autonomy_blocked`) rather than force a revert onto a diverged tree. *Confirm: escalate-not-force
   on dirty/diverged repo?* (Recommended: yes.)

---

## SCOPE check

This is a large net **removal** of machinery (trust ladder, modes, per-section, check-as-gate)
— squarely the anti-slop direction. Single global mode, single invisible profile, loopback-only,
deterministic guards, repo-patches-off-by-default all preserved. The only additions are a watermark,
two issue counters, and a ~one-function monitor loop reusing the existing dedup net and Scheduler.
It moves Kyoko closer to how a human actually fixes a recurring agent problem: notice it keeps
happening → write/approve the fix → ship → watch → undo if it keeps happening.
