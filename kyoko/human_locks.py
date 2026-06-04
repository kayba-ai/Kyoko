"""Human locks are per-target boolean state with enforcement.

A lock is a boolean (plus an optional reason) on a skill, context delivery
rule, eval spec, or harness target. The lock/unlock operations and their
enforcement live next to each surface (``kyoko/apply.py``, ``kyoko/evals.py``,
``kyoko/harness.py``). There is no lock/unlock event ledger.
"""

from __future__ import annotations

LOCK_ENTRY_TYPES = ("skill", "context_rule", "eval_spec", "harness_target")
