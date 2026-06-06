# 0014 — Evaluation Metrics (SCOPE)

Status: scoping (not yet implemented)
Date: 2026-06-03

> This is a **scope** doc, not an implementation spec. It fixes the boundaries,
> vocabulary, and the metric set so the follow-up spec can detail schema, CLI/API
> contracts, and goldens without re-litigating *what* we are building. It inherits
> and must not contradict `docs/SCOPE.md` (the constitution) or the safety boundary
> in `CLAUDE.md`.

## One-sentence scope

Add a **measurement** plane that scores agent traces to surface the
quality/severity/prevalence of issues — in two flavors: **`eval`** (deterministic
Python detectors run over the trace corpus, kayba-hosted style) and **`llm_eval`**
(out-of-the-box LLM-as-judge templates, Langfuse style) — as **evidence only**,
never as a new apply-gate, and (for `llm_eval`) with the model call kept **outside**
Kyoko's trusted core.

## Why now (the naming collision) — three-way split

Kyoko already uses the word "eval" for its deterministic pass/fail **apply-check**
(`eval_specs`, `eval_runs`, `GATEABLE_EVAL_TYPES`, "the eval gate"). That is not
what the industry (Langfuse, Ragas, kayba-app/kayba-hosted) means by "eval": there,
an *eval* is a **scored measurement** of agent output. Using one word for both is
ambiguous in code, CLI, API, and UI.

> **Validation correction (2026-06-03):** an earlier draft renamed the existing
> apply-check `eval → gate`. **That is invalid** — `grep` confirms "gate" is already
> taken twice: (1) `kyoko/gates.py` exists and is the *artifact validator*
> (`validate_gate_artifacts`, the `validate-gates` "correctness gate"); (2)
> "gate"/"gated" is already the **autonomy-decision** vocabulary
> (`_evaluate_eval_gate`, `inspect_proposal_autonomy_gate`, `gate_expectations`,
> `"gated"` proposal state). The autonomy *gate* is the **decision**; the eval_specs
> are the **checks** it evaluates. So the existing apply-check renames to **`check`**,
> not `gate`, and the word `gate` stays reserved for the decision (unchanged).

**Decision — distinct concepts:**

| Term | Meaning | Status |
|---|---|---|
| **`gate`** | the autonomy **decision** that allows/blocks an apply | existing, unchanged |
| **`check`** | the deterministic/replay **apply-check** the gate evaluates (the old Kyoko "eval": `eval_specs`/`eval_runs`) | **renamed from `eval`** |
| **`eval`** | a **deterministic Python detector** over a trace corpus → numerator/denominator prevalence (kayba-hosted `/run-eval`) | new |
| **`llm_eval`** | an **LLM-as-judge** scored measurement of a trace, 0–1 / boolean (kayba-app / Langfuse) | new |

Renaming the existing apply-check `eval → check` frees the word `eval` for the
Python-detector measurement; `llm_eval` names the judge measurement; `gate` and
`kyoko/gates.py` are left untouched. (`check` is collision-free at the entity level —
no `checks.py`, `check_specs` table, or `run-check` command exist; only a mild
overlap with `doctor.py`'s readiness "checks", a different domain. Alternative if
zero overlap is wanted: `guard`. Confirm before Phase 0.)

## What we are building — two planes

### Plane 1 — `eval` (Python detectors, kayba-hosted style)

A deterministic detector subsystem ported from kayba-hosted's `/run-eval`
(`patterns/ace-pipeline/server.py`). A detector is **user-authored Python** that
inspects the trace corpus and returns hit counts; Kyoko aggregates to a
prevalence value. No model, no judge — pure code over traces.

- Detector contract mirrors kayba-hosted: a `detect(...)` function, dispatched
  either folder-style (`detect(traces_folder)`) or per-trace
  (`detect(trace_data, trace_id)`), returning `(numerator, denominator, event_ids)`
  or a list of `{event_id, has_problem}` dicts → `value = numerator/denominator`.
- This is the **severity/prevalence** signal Kyoko lacks: "X% of traces hit this
  issue." Detectors are deterministic, so they are the natural future candidates
  for promotion to gate-eligible **checks** — but in this scope they are **evidence
  only**.
- Kyoko ships a couple of example detectors; users author their own. (No
  LLM-generated detectors in scope — that is kayba-hosted's authoring story, not
  Kyoko's.)

### Plane 2 — `llm_eval` (LLM-judge templates, Langfuse style)

Ported from kayba-app's managed evaluator library
(`worker/src/constants/managed-evaluators.json` in
`/Users/filip/Desktop/Kayba local/Code/kayba-app`). Each is a pure prompt template
+ output schema — **no proprietary code** — so they port as bundled assets.

We take **Groups A, B, C only** (10 metrics). Inputs are listed because they decide
feasibility: Kyoko can feed `query`/`generation` from any LLM span and conversation
history from a run; it generally **cannot** feed `ground_truth` or retrieval
`context`, which is why Groups D–G are dropped.

### Group A — need only `query` + `generation` (work on any LLM span)
| Metric | Measures | Output |
|---|---|---|
| Hallucination | generation unsupported by facts/logic | 0–1 |
| Helpfulness | addresses the user's query | 0–1 |
| Relevance | stays on-topic, no fluff | 0–1 |
| Toxicity | harmful/offensive language | 0–1 |
| Conciseness | answers directly, no padding | 0–1 |
| Faithfulness v1 (ragas) | answer sentences grounded in the question | 0–1 |

### Group B — conversation signals (agentic/support traces)
| Metric | Inputs | Output |
|---|---|---|
| User Distress | conversation_history, last_user_message | boolean |
| User Disagreement | conversation_history, last_user_message | boolean |
| Out-of-Scope Request | last_user_message, system_prompt | boolean |

### Group C — agent goal completion
| Metric | Inputs | Output |
|---|---|---|
| Goal Accuracy (ragas) | user_goal, desired_outcome, achieved_outcome | 0/1 |

### Explicitly dropped (out of scope for this work)
- **Group D** (Simple Criteria, Answer Critic) — generic bring-your-own-rubric
  judges. Deferred; revisit once the core 10 land.
- **Group E** (Correctness, Answer Correctness, Contextcorrectness) — need
  `ground_truth`; Kyoko has no labeled-dataset plane.
- **Group F** (Contextrelevance, Context Precision/Recall, Faithfulness v2) — need
  retrieval `context`; only meaningful for RAG agents.
- **Group G** (SQL Semantic Equivalence, Topic Adherence ×2, Answer Relevance) —
  niche / require extra reference inputs.

Ragas-attributed metrics (Faithfulness v1, Goal Accuracy) keep a `partner: "ragas"`
attribution field on the ported asset; confirm license/attribution before shipping.

## Non-negotiable boundaries (inherited)

1. **Evidence, not a gate.** Evaluation metrics produce scores that inform *which
   issues to fix* and *whether a fix helped* (before/after). They **never** auto-apply
   a skill or harness change. The apply-gate (decision) stays as is; it evaluates the
   deterministic/replay **`check`** path (the renamed `eval`). Restated: a metric score
   can raise an issue and add evidence to a proposal, but cannot satisfy the autonomy
   gate.
2. **Model call outside the trusted core.** Kyoko core invokes no live model
   (`doctor --safe-smokes`, tests). LLM-judge execution reuses the existing
   **`judge-command`** external-process pattern (BYO key/CLI), exactly as the native
   ACE bridge keeps model work in a supplied command. No provider SDK in core.
3. **Single-player / local.** No metric is per-tenant, per-reviewer, or hosted. One
   invisible profile, loopback dashboard, `--json` as the machine contract
   (`docs/SCOPE.md`).
4. **Redacted by default.** Trace text fed into a judge prompt and any stored
   reasoning string passes through redaction before disk/prompt/API, like all other
   evidence.

## In scope

- **`eval` (Python detectors):** the kayba-hosted detector contract, a runner that
  executes a detector over a corpus, and a couple of bundled example detectors.
- **`llm_eval` catalog:** the 10 templates above under `kyoko/assets/**`, each
  `{ name, version, partner?, prompt, vars[], output: numeric|boolean }` (authoring
  copy under `docs/`).
- A shared way to **run either over a corpus** (selected traces/spans), producing
  per-unit results plus an aggregate (`value = numerator/denominator`, or mean for
  numeric judges) — the severity/prevalence signal Kyoko lacks today.
- **Before/after comparison** across two corpora (Kyoko sources/runs) with
  improved / regressed / unchanged deltas (kayba-hosted's run-comparison model).
- CLI + `--json` + API parity, with **SSE progress** over the existing `LiveBus`.
- Surfacing scores into the **analyze → issues** path as evidence and into proposal
  detail.

## Out of scope

- Any new auto-apply path or gate type (see Boundary 1) — even deterministic `eval`s
  stay evidence-only in this scope.
- A live model client inside Kyoko core (see Boundary 2); `llm_eval` judges run via
  the external `judge-command`.
- **LLM-generated** detectors / a prompt editor (kayba-hosted's authoring flow,
  Group D and beyond) — later.
- Ground-truth datasets, RAG context capture, experiment/dataset planes.
- Multi-tenant anything.

## Migration step: rename `eval → check`

> **Rename target is `check`, not `gate`** (see the Validation correction above):
> `kyoko/gates.py` already exists (the artifact validator) and `gate`/`gated` is the
> autonomy-decision vocabulary. **Do not create `gates.py` or `gate_specs`.**

Land this rename **before or alongside** the metric work so the concepts never share
the word. It is a schema + contract change: `SCHEMA_VERSION` is currently **24** →
bump to **25** with a forward migration, plus golden/spec updates. Surface to cover:

- **Storage** (`kyoko/storage.py`): tables `eval_specs → check_specs`,
  `eval_runs → check_runs`, `eval_spec_locks → check_locks`; columns/indexes
  `eval_type → check_type`, `eval_spec_id → check_spec_id`,
  `required_eval_level_context/harness → required_check_level_*`,
  `allow_eval_write → allow_check_write`. Per the additive-migration mechanism, an
  in-place table rename needs an explicit migration (create new + copy + drop, or
  `ALTER TABLE … RENAME`); `_ensure_column` covers new columns only.
- **Python**: module `evals.py → checks.py` (NOT `gates.py` — taken); `EvalError →
  CheckError`, `GATEABLE_EVAL_TYPES → GATEABLE_CHECK_TYPES`, `EXECUTABLE_EVAL_TYPES`,
  `EVAL_TRUST_LEVELS → CHECK_TRUST_LEVELS`, and call sites in `autonomy_runner.py`
  (which keeps its `gate`/`gated` decision words — those stay), `apply.py`,
  `replay_adapters.py`, `improve.py`, `details.py`, `web.py`, `mcp.py`.
- **CLI** (`kyoko/cli.py`): `evals → checks`, `run-eval → run-check`,
  `generate-evals → generate-checks`, `eval-detail → check-detail`,
  `eval-capabilities → check-capabilities`,
  `eval-assertion-presets → check-assertion-presets`,
  `eval-spec-{approve,lock,unlock,locks} → check-{approve,lock,unlock,locks}`; flags
  `--eval-write → --check-write`, `--run-eval → --run-check`. (Mild overlap with
  `doctor.py`'s readiness "checks" is acceptable — different domain.)
- **Contracts**: rename and re-freeze the 10 goldens under
  `docs/fixtures/cli-json/*eval*` and update
  `docs/specs/0005-cli-json-contracts.md`. Rename
  `docs/specs/0010-evals-replay-contract.md → check-replay-contract` and fix
  cross-references in specs 0001, 0002, 0003, 0004, 0007, 0008, 0009, 0011.
- **Vocabulary**: update `docs/specs/0006-product-vocabulary.md` and
  `kyoko/vocabulary.py` — document the split (gate = decision, check = apply-check,
  eval/llm_eval = measurements).
- **MCP/API/dashboard**: rename `eval`-named MCP tools/endpoints/pages to `check`;
  keep the read/propose boundary intact. Leave `validate-gates` / `gates.py` and the
  autonomy-`gate` decision surface **unchanged**.

Backward-compat aliases for the renamed CLI commands are optional and, given the
single-player local scope, probably unnecessary — decide in the spec.

## Open questions (resolve in the implementation spec)

1. Aggregate shape per metric run: mean of 0–1 scores, threshold→pass-rate, or both?
   How is a boolean metric's prevalence stored (numerator/denominator)?
2. Variable mapping: how do `{{query}}`, `{{generation}}`, `{{conversation_history}}`,
   `{{system_prompt}}`, `{{user_goal}}`… resolve from Kyoko's span/run model? Reuse
   `span_normalize.py`?
3. Judge execution: one `judge-command` invocation per (metric × span), or batched?
   Cost/latency envelope for a corpus run.
4. Where results live: a new `eval_metric_results` table vs. extending annotations.
5. How a metric scopes its corpus (a source, a run set, a trace "folder" analog).
6. Exactly how a score feeds `analyze → issues` severity without becoming a gate.
