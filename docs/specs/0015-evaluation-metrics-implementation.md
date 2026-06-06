# 0015 — Evals & LLM-Evals (IMPLEMENTATION)

Status: planning (not yet implemented)
Date: 2026-06-03

> Implements the scope fixed in `docs/specs/0014-evaluation-metrics.md`. Specifies
> two measurement planes — **`eval`** (deterministic Python detectors, kayba-hosted
> style) and **`llm_eval`** (LLM-judge templates, Langfuse style) — over shared run /
> result / aggregate / compare / issues infrastructure. Assumes the `eval → check`
> rename (Phase 0) has landed; "check" below is post-rename.
>
> **Validation note (2026-06-03):** the rename target is **`check`, not `gate`** —
> `kyoko/gates.py` already exists (the artifact validator) and `gate`/`gated` is the
> autonomy-*decision* vocabulary. See `docs/specs/0014` "Validation correction".

## 0. Terms (post-rename)

- **gate** — the autonomy **decision** that allows/blocks an apply. Existing,
  unchanged by this work (keeps `gates.py`, `_evaluate_*_gate`, `"gated"` state).
- **check** — the deterministic/replay **apply-check** the gate evaluates (formerly
  "eval": `check_specs`, `check_runs`, `GATEABLE_CHECK_TYPES`). Renamed from `eval`.
- **eval** — a **deterministic Python detector** run over a trace **corpus**,
  returning hit counts → `value = numerator/denominator`. No model. Evidence only.
- **llm_eval** — an **LLM-as-judge** template scoring a unit (0–1 / boolean). Model
  runs **outside** core via `judge-command`. Evidence only.
- **eval run** — one execution of an `eval` or `llm_eval` over a corpus → per-unit
  results + aggregate.
- **unit** — what one result row covers: an `event`/`llm_span`/`run` (see below).

Both `eval` and `llm_eval` are **evidence only**: neither writes a `check_run`,
mutates a skill, or edits a harness file. Deterministic `eval`s are the natural
future candidates for promotion to gate-eligible **checks**, but not in this scope.

## 1. Shared data model

New module `kyoko/evals_measure.py` (kept separate from the renamed `checks.py`
apply-check module). Three tables, discriminated by `kind` (`python` | `llm`).
`SCHEMA_VERSION` is currently **24** → bump to **25** (Phase 0's check-rename
migration takes 24→25; this feature's tables land in the same or the next bump —
sequence per phasing). Migration is additive `CREATE TABLE IF NOT EXISTS` (the
`storage.py` mechanism; `_ensure_column` for any later column). Depends on Phase 0
having renamed the old `eval_*` tables to `check_*`, which frees the `eval_*` name
space. Update canonical-model doc `0001`.

```sql
CREATE TABLE IF NOT EXISTS eval_definitions (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  kind TEXT NOT NULL,                   -- python | llm
  name TEXT NOT NULL,
  version INTEGER NOT NULL,
  partner TEXT,                         -- "ragas" for ported llm_evals, else NULL
  source TEXT NOT NULL,                 -- bundled | user
  unit_type TEXT NOT NULL,              -- event | llm_span | run
  output_type TEXT NOT NULL,            -- numeric | boolean
  direction TEXT NOT NULL,              -- lower_is_better | higher_is_better | true_is_notable | false_is_notable
  problem_statement TEXT,
  -- python:
  detector_ref TEXT,                    -- blob/path of the detector .py (NULL for llm)
  -- llm:
  prompt TEXT, vars_json TEXT, bindings_json TEXT,   -- (NULL for python)
  output_json TEXT,                     -- {type, range} for llm numeric
  severity_bands_json TEXT,
  status TEXT NOT NULL,                 -- active | archived
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id)
);

CREATE TABLE IF NOT EXISTS eval_measure_runs (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL,
  eval_definition_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  definition_snapshot_json TEXT NOT NULL,   -- frozen def used this run
  corpus_json TEXT NOT NULL,                -- selector (§2)
  unit_type TEXT NOT NULL,
  status TEXT NOT NULL,                     -- pending|running|complete|failed
  unit_total INTEGER NOT NULL DEFAULT 0,
  unit_scored INTEGER NOT NULL DEFAULT 0,
  unit_skipped INTEGER NOT NULL DEFAULT 0,
  aggregate_json TEXT,                      -- {value, numerator, denominator, mean?, ...} (§5)
  baseline_run_id TEXT,                     -- compare lineage (optional)
  started_at TEXT, ended_at TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profiles(id),
  FOREIGN KEY (eval_definition_id) REFERENCES eval_definitions(id),
  FOREIGN KEY (baseline_run_id) REFERENCES eval_measure_runs(id)
);

CREATE TABLE IF NOT EXISTS eval_measure_results (
  id TEXT PRIMARY KEY,
  eval_run_id TEXT NOT NULL,
  profile_id TEXT NOT NULL,
  unit_type TEXT NOT NULL,
  unit_ref TEXT NOT NULL,               -- event_id | span_id | run_id
  status TEXT NOT NULL,                 -- scored | skipped | error
  score_numeric REAL,                   -- llm numeric
  score_bool INTEGER,                   -- python has_problem, or llm boolean
  reasoning TEXT,                       -- llm only, redacted one-liner
  degraded INTEGER NOT NULL DEFAULT 0,
  detail_json TEXT NOT NULL,            -- raw detector/judge output, skip/err reason
  created_at TEXT NOT NULL,
  FOREIGN KEY (eval_run_id) REFERENCES eval_measure_runs(id),
  FOREIGN KEY (profile_id) REFERENCES profiles(id)
);
CREATE INDEX IF NOT EXISTS eval_measure_results_run ON eval_measure_results(eval_run_id);
```

Bundled `llm_eval` definitions are upserted from assets at first use (like ACE
skillbook seeds); `eval` detectors are registered by the user (or bundled examples).
Large raw payloads → blob store via `detail` refs, not hot rows.

## 2. Corpus selector (shared)

`corpus_json` resolved to a unit list at run start:

```json
{ "unit": "run",                      // event | llm_span | run
  "source_id": "source_...",          // optional
  "run_ids": ["run_a", "run_b"],       // optional explicit set (used for before/after)
  "since": "2026-06-01T00:00:00Z", "until": null,
  "span_filter": { "kind": "llm" },    // llm_span units default to LLM spans
  "limit": 500 }                       // hard cap; over-cap logged, never silent
```

- `eval` (python detectors) iterate **runs** (each exported as a trace JSON, §3) and
  emit their own `event` units; `eval_definitions.unit_type = event`.
- `llm_eval` units are `llm_span` or `run` per the template (§4).
- A named, saved selector = the kayba-hosted "trace folder" analog — deferred;
  `run_ids` / `source_id` cover v1 before/after.

## 3. Plane 1 — `eval` (Python detectors)

Faithful port of kayba-hosted `patterns/ace-pipeline/server.py:_run_eval_background`.

### Detector contract (mirrors kayba-hosted)

A detector is a Python file defining `detect(...)`. Dispatch + returns match
kayba-hosted exactly so detectors are portable both ways:

- **Function discovery:** use `detect`; if absent and exactly one user function is
  defined, fall back to it (kayba-hosted behavior).
- **Signature dispatch:**
  - param named `traces_folder|folder|path|dir|directory|traces_dir` →
    **folder mode**: `detect(traces_dir)`, detector reads files itself.
  - otherwise → **per-trace mode**: `detect(trace_data, trace_id)` called once per
    trace file, results aggregated.
- **Return shapes:**
  - `(numerator, denominator, event_ids)` tuple, or
  - a list of `{event_id, has_problem}` dicts → `den = len`, `num = count(not has_problem)`.
- **Aggregate:** `value = numerator / denominator`.

### Execution (out-of-process for isolation)

`kyoko serve` is long-lived, so unlike kayba-hosted's in-process `exec`, Kyoko runs
the detector in a **subprocess** via a bundled runner `kyoko/assets/eval_runner.py`:

1. Resolve corpus → export each selected run to `<tmp>/<run_id>.json` using the
   existing canonical trace export (`inspection.py` / `evidence.py`). Filenames are
   the unit ids.
2. Spawn `python3 eval_runner.py` with `KYOKO_EVAL_*` env (traces dir, detector ref,
   contract). The runner `exec`s the user detector, performs the signature dispatch
   above, aggregates, and prints a `BEGIN_KYOKO_EVAL_RESULT_JSON … END` block:
   `{ "numerator", "denominator", "events": [{event_id, has_problem}] }`.
3. Kyoko parses the block → writes one `eval_measure_results` row per event
   (`score_bool = has_problem`) + the run aggregate; emits SSE.

Detectors receive **real local trace data** (a trusted local subprocess on the
user's own machine — SCOPE: no adversary on the same machine). Redaction applies to
**stored/served** outputs (event excerpts, reasoning) per §7, not to the detector's
input. Detector crash/timeout → run `status=failed`, captured stderr in `detail`.

## 4. Plane 2 — `llm_eval` (LLM-judge templates)

The 10 ported templates ship as bundled assets
`kyoko/assets/llm_evals/<id>.json` with an authoring copy under `docs/llm_evals/`.
**Asset mirroring:** `kyoko/gates.py` `validate_gate_artifacts` enforces that every
`docs/` artifact has a byte-identical `kyoko/assets/` mirror — add the 10 `llm_eval`
assets (and bundled `eval` detectors) to that mirror list so `validate-gates` checks
both copies. Schema `kyoko.llm_eval.v1`:

```json
{ "schema_version": "kyoko.llm_eval.v1", "id": "hallucination", "name": "Hallucination",
  "version": 1, "partner": null, "unit": "llm_span",
  "output": {"type": "numeric", "range": [0,1]}, "direction": "lower_is_better",
  "prompt": "Evaluate ... Query: {{query}}\nGeneration: {{generation}}\nThink step by step.",
  "vars": ["query","generation"],
  "bindings": {"query":"unit.user_query","generation":"unit.output_text"},
  "severity_bands": {"low":0.2,"medium":0.5,"high":0.8} }
```

Prompts lifted verbatim from kayba-app `worker/src/constants/managed-evaluators.json`
(preserve `partner:"ragas"` for Faithfulness v1 + Goal Accuracy; verify license).

### The 10, unit + bindings

| id | unit | output | direction | vars → binding |
|---|---|---|---|---|
| hallucination | llm_span | numeric | lower_is_better | query→user_query, generation→output_text |
| helpfulness | llm_span | numeric | higher_is_better | query, generation |
| relevance | llm_span | numeric | higher_is_better | query, generation |
| toxicity | llm_span | numeric | lower_is_better | query, generation |
| conciseness | llm_span | numeric | higher_is_better | query, generation |
| faithfulness_v1 | llm_span | numeric | higher_is_better | question→user_query, answer→output_text |
| user_distress | run | boolean | true_is_notable | conversation_history→run.transcript, last_user_message→run.last_user_message |
| user_disagreement | run | boolean | true_is_notable | conversation_history, last_user_message |
| out_of_scope_request | run | boolean | true_is_notable | last_user_message, system_prompt→run.system_prompt |
| goal_accuracy | run | boolean | false_is_notable | user_goal→run.first_user_message, desired_outcome→(note-annotation\|=user_goal), achieved_outcome→run.final_output |

### Variable resolution (`kyoko/metric_bindings.py`)

Off `span_normalize.normalize_span` → `{kind,model,system,messages,output_text}`:
`unit.output_text`, `unit.user_query` (last user message), `run.transcript`,
`run.last_user_message`, `run.first_user_message`, `run.system_prompt`,
`run.final_output`. Missing var → unit **skipped** (`skipped: missing_var:<name>`),
never silently scored.

**Goal Accuracy `desired_outcome`:** no ground-truth plane. `annotations.py` has no
`label` kind (only `issue`/`good`/`note`), so resolve from a **`note`** annotation on
the run carrying `metadata.label_type == "desired_outcome"` via
`list_annotations(db_path, run_id=…)`; if absent, degrade to `user_goal` and set
`degraded:true`. Documented limitation.

### Execution (model outside core)

Reuses the `judge-command` pattern. Per unit: resolve bindings → build **redacted**
`kyoko.llm_eval_request.v1` (`redact_evidence_bundle`, `consumer="llm_eval:<id>"`) →
invoke user `--command` (stdin + `KYOKO_LLM_EVAL_*` env) → parse a **distinct**
`BEGIN_KYOKO_LLM_EVAL_RESULT_JSON … END` block `{score, reasoning}` → validate vs
`output.type/range` → write result row. Distinct block from the `check` apply-judge so
verdict/score wire formats never conflate. v1 = one invocation per unit;
`--batch-size` deferred. `--prepare-only` writes per-unit requests + a handoff and
stops (like `ace-native-run --prepare-only`).

## 5. Aggregate (shared shape)

```json
// python eval (and boolean llm_eval) → prevalence
{ "type": "boolean", "numerator": 6, "denominator": 50, "value": 0.12 }
// numeric llm_eval
{ "type": "numeric", "value": 0.81, "scored": 47, "skipped": 3,
  "histogram": {"0-0.2":2,"0.2-0.5":5,"0.5-0.8":12,"0.8-1":28} }
```

`value` is the canonical 0–1 prevalence/quality number both planes expose for
compare + dashboard.

## 6. Before/after comparison (shared)

`compare_eval_runs(run_a, run_b)` over two completed runs of the **same
`eval_definition_id`** (baseline corpus vs post-change corpus):

```json
{ "eval_id":"helpfulness", "baseline":"er_a","compare":"er_b",
  "baseline_value":0.71, "compare_value":0.83, "delta":0.12, "direction":"improved" }
```

`direction = improved|regressed|unchanged` (|delta|<0.02), oriented by the
definition's `direction`. Dashboard rolls many single-eval comparisons into
improved/regressed/unchanged counts (kayba-hosted run-comparison).

## 7. Severity → issues (evidence only, both planes)

Wires into the **first-class Issue entity** (`kyoko/issues.py`, `issues` table — added
in the `Finish-plan` commit), not a bespoke shape.

- **Per-unit severity** from `direction` + `severity_bands`:
  `lower_is_better` → higher=worse; `higher_is_better` → `1-value`; boolean
  `*_is_notable` → notable polarity = `medium` (configurable). Bands → `low|medium|high`
  matching the `issues.severity` column.
- **Issue raising** is threshold-gated + opt-in (`--raise-issues`): when aggregate
  `value` (inverted by `direction`) exceeds a threshold, call
  `issues.create_issue(db_path=…, title=…, severity=…, section=…, status="open",
  evidence_refs=[…], affected_span_ids=[worst-scoring unit refs])`. The Issue carries
  the metric run + worst units as `evidence_refs`; the existing improve/proposal flow
  picks it up. The score is **evidence**, never a `check_run`, and never satisfies the
  autonomy gate. (0014 open-Q6 resolved.)

## 8. Redaction & safety (restated)

- `llm_eval`: every var value + stored `reasoning` redacted before disk/prompt/API.
- `eval`: detector input is real local data (trusted local subprocess); stored event
  excerpts/served payloads redacted.
- No live model in core: `eval` is deterministic; `llm_eval` judge is the user's
  `--command`. `doctor --safe-smokes` + unit tests never call a provider.
- Evidence-only: nothing here writes a `check_run` / mutates skill / edits harness.

## 9. CLI surface (all `--json`)

**`eval` (Python detectors)** — the old `run-eval` apply-check command is renamed to
`run-check` in Phase 0, which frees `run-eval` to mean "run a detector" here (matches
kayba-hosted `/run-eval`):

| Command | Purpose |
|---|---|
| `kyoko evals` | list registered + bundled detectors |
| `kyoko eval-detail <id>` | one detector's contract/problem statement |
| `kyoko eval-register <path>` | register a user detector `.py` |
| `kyoko run-eval <id> --corpus <file\|inline> [--baseline <er>] [--raise-issues] [--persist]` | run a detector over a corpus |
| `kyoko eval-runs` / `eval-run-detail <er>` | history / per-event results + aggregate |
| `kyoko eval-compare <er_a> <er_b>` | before/after delta |

**`llm_eval` (judges)** — parallel family:

| Command | Purpose |
|---|---|
| `kyoko llm-evals` / `llm-eval-detail <id>` | catalog of the 10 |
| `kyoko run-llm-eval <id> --corpus … --command "<judge>" [--prepare-only] [--baseline] [--raise-issues] [--persist]` | run a judge over a corpus |
| `kyoko llm-eval-runs` / `llm-eval-run-detail <er>` | history / per-unit scores |
| `kyoko llm-eval-compare <er_a> <er_b>` | before/after delta |

## 10. API & MCP parity

- **API** (`web.py`, loopback): `GET /api/evals`, `/api/evals/{id}`,
  `POST /api/run-eval`, `GET /api/eval-runs[/{id}]`, `GET /api/eval-compare`, and the
  `llm-eval` equivalents. Progress over existing `GET /api/events/stream`.
- **MCP** (`mcp.py`): read tools (`kyoko_list_evals`, `kyoko_eval_run_detail`, +
  llm variants) and run tools (`kyoko_run_eval`, `kyoko_run_llm_eval`) modeled on the
  existing `kyoko_run_judge_command` — write **evidence only**, no apply/gate path.

## 11. Live progress (SSE)

`LiveBus.publish` per unit (`live_event` envelope, `kind="eval_progress"`):
`{eval_run_id, scored, total, last_value}`, terminal `kind="eval_complete"` carrying
the aggregate. React `useLiveBus` subscribes; no new transport.

## 12. Dashboard (Phase F)

New **Evaluation** section, two sub-areas:
- **Evals (detectors):** registered detectors, run over corpus, run history,
  per-event results, before/after compare.
- **LLM-Evals (judges):** the 10-template catalog, run, history, per-unit scores +
  reasoning, compare.
Color bands red/amber/green via `direction`. Distinct from the existing
"Evals & Replay" dashboard page (the `check`/gate apply path, post-rename).

## 13. Testing

- **Asset/contract validation**: validate the 10 `llm_eval` assets
  (`kyoko.llm_eval.v1`: prompt vars match `vars`, bindings resolvable, output valid)
  and the detector runner contract; wire into `kyoko validate-gates`.
- **Deterministic smokes (no model):**
  - `eval`: a bundled example detector over a fixture corpus → known
    numerator/denominator (`doctor --eval-smoke`).
  - `llm_eval`: a mock judge command returning fixed scores
    (`doctor --llm-eval-smoke`), like `ace-native-smoke`.
- **JSON goldens** for `evals`, `eval-detail`, `run-eval`, `eval-runs`,
  `eval-run-detail`, `eval-compare` + the `llm-eval` set; update
  `docs/specs/0005-cli-json-contracts.md`.
- **Unit tests:** detector signature dispatch + both return shapes; bindings per unit
  type; aggregate math (prevalence + numeric mean); severity per `direction`;
  skip-on-missing-var; redaction applied; migration idempotency + refuse-newer-version.

## 14. Phasing

- **Phase 0 — rename `eval → check`** (own PR, per 0014; target is `check`, **not**
  `gate` — `gates.py` is taken). Land first; frees the `eval_*` table namespace + the
  `run-eval` command for Plane 1.
- **Phase 1 — shared model**: 3 tables + schema bump + corpus selector + migration.
- **Phase 2 — `eval` plane**: detector runner (`eval_runner.py`), `evals` /
  `eval-register` / `run-eval` / `eval-runs` + deterministic smoke + goldens.
- **Phase 3 — `llm_eval` plane**: 10 assets + `metric_bindings.py` + judge-command
  runner + `llm-eval*` commands + mock smoke + goldens.
- **Phase 4 — compare** (`*-compare`, before/after) for both planes.
- **Phase 5 — issues wiring** (`--raise-issues` severity → analyze/issues evidence).
- **Phase 6 — dashboard + SSE** Evaluation pages.

Each phase independently shippable; CLI/API/golden parity maintained.

## 15. Remaining decisions

1. Default `--raise-issues` thresholds per definition, or manual-only in v1.
2. Detector packaging: a single `.py` with `detect()` (kayba-hosted parity) vs an
   importable module dir; where the detector body is stored (blob vs path ref).
3. `eval → check` CLI: hard cut vs deprecated aliases (single-player → likely hard
   cut). Also confirm `check` vs `guard` as the rename target before Phase 0.
4. Boolean severity: fixed `medium` vs escalate by prevalence `value`.
5. Compare strictness: identical selectors vs same `eval_definition_id` only.
6. Whether deterministic `eval`s become gate-eligible in a later spec (out of scope
   now, but the model should not preclude it).
