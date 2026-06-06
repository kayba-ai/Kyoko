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
  /** Short stage label, e.g. "Needs your review". */
  stage: string;
  /** One-sentence plain-English description of the current state. */
  headline: string;
  /** What the human should do next, if anything. */
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

function seenSentence(count: number | null | undefined): string {
  const n = count ?? 1;
  if (n <= 1) return "";
  return ` It has come up ${n} times.`;
}

/**
 * Narrate an issue's current state. `hasFix` lets the caller signal that a
 * drafted proposal already exists (the issue carries proposal_ids), which
 * distinguishes "still drafting" from "ready to approve".
 */
export function narrateIssue(issue: Issue): Narration {
  const where = sectionPhrase(issue.section);
  const seen = seenSentence(issue.recurrence_count);
  const hasFix = (issue.proposal_ids?.length ?? 0) > 0;

  if (issue.autonomy_blocked) {
    return {
      stage: "Needs your attention",
      headline:
        "Kyoko tried to fix this on its own, but the problem kept coming back — so it has handed the decision to you.",
      next: issue.autonomy_blocked_reason
        ? `Reason: ${issue.autonomy_blocked_reason}`
        : "Review the problem and decide how to proceed.",
      tone: "danger",
      kind: "escalated",
    };
  }

  switch (issue.status) {
    case "dismissed":
      return {
        stage: "Dismissed",
        headline: "You set this problem aside, so Kyoko won't act on it.",
        next: "Reopen it if you'd like Kyoko to take another look.",
        tone: "neutral",
        kind: "dismissed",
      };

    case "guarded":
      return {
        stage: "Fixed & watched",
        headline: `The fix is live in ${where}, and a guard now watches in case the problem comes back.`,
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
      return {
        stage: "Resolved",
        headline: "This problem has been resolved.",
        next: null,
        tone: "ok",
        kind: "resolved",
      };

    case "proposed":
      return {
        stage: "Fix ready to approve",
        headline: "Kyoko has drafted a fix for this problem.",
        next: "Review and approve it on the Proposals tab.",
        tone: "primary",
        kind: "ready",
      };

    case "accepted":
      if (hasFix) {
        return {
          stage: "Fix ready to approve",
          headline: "You accepted this problem and Kyoko has drafted a fix.",
          next: "Review and approve it on the Proposals tab.",
          tone: "primary",
          kind: "ready",
        };
      }
      return {
        stage: "Drafting a fix",
        headline: "You accepted this problem. Kyoko is drafting a fix right now.",
        next: "This can take a minute — the fix will appear on the Proposals tab when it's ready.",
        tone: "primary",
        kind: "drafting",
      };

    case "diagnosed":
      return {
        stage: "Ready to review",
        headline: `Kyoko found this problem in your agent's traces and worked out why it happens.${seen}`,
        next: "Accept it to have Kyoko draft a fix, or reject it.",
        tone: "warn",
        kind: "review",
      };

    case "prioritized":
    case "open":
    default:
      return {
        stage: "Needs your review",
        headline: `Kyoko found this problem in your agent's traces.${seen}`,
        next: "Accept it to have Kyoko draft a fix, or reject it.",
        tone: "warn",
        kind: "review",
      };
  }
}

/** Narrate a proposal's current state. Accepts either the list shape or the
 *  richer detail record (which may carry a `section` field). */
export function narrateProposal(p: { state: string | null | undefined; section: string | null | undefined }): Narration {
  const where = sectionPhrase(p.section);
  switch ((p.state ?? "").toLowerCase()) {
    case "pending":
      return {
        stage: "Waiting for your approval",
        headline: `Kyoko drafted this change to ${where} to fix the problem.`,
        next: "Approve it to apply the change, or leave it as a suggestion for now.",
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
