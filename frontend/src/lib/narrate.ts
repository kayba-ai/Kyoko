// Natural-language narration for issues and proposals. The dashboard's job is to
// let a human understand — at a glance, in plain English — what is happening with
// a tracked problem or a drafted fix, and what (if anything) they need to do next.
// All the technical detail still exists; this layer just says it like a human would.

import type { Issue } from "@/lib/types";

export type Tone = "neutral" | "ok" | "warn" | "danger" | "primary";

// A coarse "what kind of moment is this" key. The UI maps it to an icon; the copy
// below carries the actual sentence the human reads.
export type StageKind =
  | "review" // a problem waiting for a human decision
  | "drafting" // a fix is being authored right now
  | "ready" // a fix is drafted and waiting for approval
  | "applied" // a change is live
  | "guarded" // live + a guard watches for regressions
  | "resolved" // done
  | "dismissed" // a human said no
  | "escalated" // autonomy gave up; needs a human
  | "failed"; // an apply attempt didn't go through

export interface Narration {
  /** Short stage label, e.g. "Needs review". */
  stage: string;
  /** One-sentence description of the current state — only when it adds real
   *  information beyond the stage label and the on-screen action. Null when the
   *  stage + visible buttons already say everything (no filler). */
  headline: string | null;
  /** What the human should do next, when it isn't already obvious from a
   *  visible control. Null otherwise. */
  next: string | null;
  tone: Tone;
  kind: StageKind;
}

/** Plain-English name for where a change lands. */
export function sectionPhrase(section: string | null | undefined): string {
  switch ((section ?? "").toLowerCase()) {
    case "context":
      return "the agent's instructions";
    case "harness":
      return "the agent's tools and setup";
    case "skill":
    case "skillbook":
      return "the skillbook";
    default:
      return "the agent";
  }
}

/** Plain-English severity, no jargon. */
export function severityPhrase(severity: string | null | undefined): string | null {
  switch ((severity ?? "").toLowerCase()) {
    case "high":
      return "High impact";
    case "medium":
      return "Medium impact";
    case "low":
      return "Low impact";
    default:
      return null;
  }
}

/**
 * Narrate an issue's current state. The copy is deliberately sparse: when the
 * stage label and the on-screen buttons already convey the situation (a problem
 * waiting for Accept/Reject), there is no headline or next-step prose to read.
 * Prose appears only where it carries information a button can't — a fix being
 * drafted in the background, where to go next, or why autonomy escalated.
 */
export function narrateIssue(issue: Issue): Narration {
  const where = sectionPhrase(issue.section);
  const hasFix = (issue.proposal_ids?.length ?? 0) > 0;

  if (issue.autonomy_blocked) {
    return {
      stage: "Needs your attention",
      headline: "Kyoko's automatic fixes didn't stick — the problem kept recurring.",
      next: issue.autonomy_blocked_reason ?? null,
      tone: "danger",
      kind: "escalated",
    };
  }

  switch (issue.status) {
    case "dismissed":
      return { stage: "Dismissed", headline: null, next: null, tone: "neutral", kind: "dismissed" };

    case "guarded":
      return {
        stage: "Fixed & watched",
        headline: `The fix is live in ${where}; a guard now watches for it coming back.`,
        next: null,
        tone: "ok",
        kind: "guarded",
      };

    case "applied":
      return {
        stage: "Fixed",
        headline: `Kyoko applied a fix to ${where}.`,
        next: null,
        tone: "ok",
        kind: "applied",
      };

    case "resolved":
      return { stage: "Resolved", headline: null, next: null, tone: "ok", kind: "resolved" };

    case "proposed":
      return {
        stage: "Fix ready",
        headline: "Kyoko drafted a fix — review and approve it on the Proposals tab.",
        next: null,
        tone: "primary",
        kind: "ready",
      };

    case "accepted":
      if (hasFix) {
        return {
          stage: "Fix ready",
          headline: "Kyoko drafted a fix — review and approve it on the Proposals tab.",
          next: null,
          tone: "primary",
          kind: "ready",
        };
      }
      return {
        stage: "Drafting a fix",
        headline: "Kyoko is drafting a fix in the background; it'll appear on the Proposals tab when ready.",
        next: null,
        tone: "primary",
        kind: "drafting",
      };

    case "diagnosed":
    case "prioritized":
    case "open":
    default:
      return { stage: "Needs review", headline: null, next: null, tone: "warn", kind: "review" };
  }
}

/** Narrate a proposal's current state. Accepts either the list shape or the
 *  richer detail record (which may carry a `section` field). */
export function narrateProposal(p: { state: string | null | undefined; section: string | null | undefined }): Narration {
  const where = sectionPhrase(p.section);
  switch ((p.state ?? "").toLowerCase()) {
    case "pending":
      return {
        stage: "Waiting for approval",
        headline: `Kyoko drafted this change to ${where} to fix the problem.`,
        next: null,
        tone: "primary",
        kind: "ready",
      };
    case "applied":
      return {
        stage: "Applied",
        headline: `This change is now live in ${where}.`,
        next: null,
        tone: "ok",
        kind: "applied",
      };
    case "rolled_back":
      return {
        stage: "Rolled back",
        headline: "This change was applied and then undone.",
        next: null,
        tone: "danger",
        kind: "failed",
      };
    case "failed":
      return {
        stage: "Couldn't apply",
        headline: "Kyoko tried to apply this change but it didn't go through.",
        next: "Check the details below for what blocked it.",
        tone: "danger",
        kind: "failed",
      };
    default:
      return {
        stage: "Draft",
        headline: `Kyoko drafted this change to ${where}.`,
        next: null,
        tone: "neutral",
        kind: "review",
      };
  }
}
