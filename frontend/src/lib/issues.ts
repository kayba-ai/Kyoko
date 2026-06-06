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

// "Still open" = a tracked failure that has not yet cleared gate #1 (no fix
// authored), been resolved, or been dismissed — i.e. the active problem surface.
// This is the set the Overview groups into failure categories.
export function isOpenIssue(issue: Issue): boolean {
  return issueBucket(issue.status) === "open";
}
