import type { Issue } from "./types";

// Single source of truth for how an Issue's lifecycle status maps onto the
// review-queue buckets. Used by both the Issues page (status tabs) and the
// Overview (open-failure surface) so the two can never drift.
export type IssueBucket = "open" | "accepted" | "resolved" | "dismissed";

// Gate #1 splits the queue: pre-accept (triage) → "open"; accepted/proposed
// (gate #1 cleared, a fix is being authored / awaiting gate #2 on Proposals) →
// "accepted"; applied/resolved end-states → "resolved"; dismissed → "dismissed".
export function issueBucket(status: string): IssueBucket {
  if (status === "resolved" || status === "applied" || status === "guarded") return "resolved";
  if (status === "accepted" || status === "proposed") return "accepted";
  if (status === "dismissed") return "dismissed";
  return "open";
}

// "Unresolved" = a tracked failure that has NOT reached a resolved end-state
// (applied/resolved/guarded) and was not dismissed. Accepted/proposed issues —
// where a fix is authored but not yet applied and verified — are NOT resolved,
// so they stay on the active failure surface until the fix actually lands. This
// is the set the Overview surfaces and groups into failure categories.
export function isUnresolvedIssue(issue: Issue): boolean {
  const b = issueBucket(issue.status);
  return b !== "resolved" && b !== "dismissed";
}
