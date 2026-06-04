"""Local, editable model-price table for deriving an approximate trace cost.

Cost is **not** an OpenTelemetry field — a span carries token counts, not money.
Langfuse computes cost the same way: tokens x a per-model price table it maintains.
This is that table for Kyoko, kept deliberately small and local. It is a heuristic
convenience for the dashboard, not authoritative billing, and it is off the trace
data path entirely. Unknown models return ``None`` so the UI shows "—" rather than a
fabricated number. Edit ``MODEL_PRICING`` to add models or correct prices.

Prices are USD per 1,000,000 tokens.
"""

from __future__ import annotations

from typing import Optional

# USD per 1M tokens, keyed by a lowercase model-name fragment matched as a prefix
# (so "gpt-4o-2024-08-06" matches "gpt-4o"). Order matters only for readability;
# the longest matching key wins so specific variants override family defaults.
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "o3-mini": {"input": 1.10, "output": 4.40},
    "claude-3-5-haiku": {"input": 0.80, "output": 4.00},
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-7-sonnet": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4": {"input": 3.00, "output": 15.00},
    "claude-opus-4": {"input": 15.00, "output": 75.00},
    "claude-haiku-4": {"input": 1.00, "output": 5.00},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
}


def _match_pricing(model: str) -> Optional[dict[str, float]]:
    key = model.strip().lower()
    if not key:
        return None
    # Longest matching prefix wins so "gpt-4o-mini" beats "gpt-4o".
    best: Optional[str] = None
    for candidate in MODEL_PRICING:
        if key.startswith(candidate) and (best is None or len(candidate) > len(best)):
            best = candidate
    return MODEL_PRICING[best] if best is not None else None


def estimate_cost(
    model: Optional[str],
    input_tokens: Optional[int],
    output_tokens: Optional[int],
) -> Optional[float]:
    """Return approximate USD cost for a known model, else ``None``.

    Missing token counts are treated as 0; a model with no pricing entry returns
    ``None`` (the caller renders "—")."""
    if not model:
        return None
    pricing = _match_pricing(model)
    if pricing is None:
        return None
    inp = int(input_tokens or 0)
    out = int(output_tokens or 0)
    cost = (inp * pricing["input"] + out * pricing["output"]) / 1_000_000
    return round(cost, 6)
