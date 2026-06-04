import { useEffect, useState } from "react";
import { Trash2, AlertCircle, ThumbsUp, StickyNote } from "lucide-react";
import type { Annotation, AnnotationKind } from "@/lib/types";
import { api } from "@/lib/api";
import { useLiveEvent } from "@/hooks/useLiveBus";
import { ago } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { Tabs } from "@/components/ui/tabs";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Kbd } from "@/components/ui/misc";

const KINDS: {
  value: AnnotationKind;
  label: string;
  icon: typeof AlertCircle;
  badge: NonNullable<BadgeProps["tone"]>;
}[] = [
  { value: "issue", label: "Issue", icon: AlertCircle, badge: "danger" },
  { value: "good", label: "Good", icon: ThumbsUp, badge: "ok" },
  { value: "note", label: "Note", icon: StickyNote, badge: "neutral" },
];

// Annotations are first-class, single-user evidence markers on a run/span (issue /
// good / note). They never apply changes; they can seed a proposal. Live over SSE.

export function Annotations({ runId, spanId }: { runId: string; spanId?: string }) {
  const [items, setItems] = useState<Annotation[]>([]);
  const [kind, setKind] = useState<AnnotationKind>("note");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const reload = () => api.annotations({ runId }).then(setItems);

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  useLiveEvent("annotation", (payload: { op: string; annotation: Annotation }) => {
    if (!payload?.annotation || payload.annotation.run_id !== runId) return;
    setItems((prev) => {
      if (payload.op === "delete") return prev.filter((a) => a.id !== payload.annotation.id);
      if (prev.some((a) => a.id === payload.annotation.id)) return prev;
      return [...prev, payload.annotation];
    });
  });

  async function submit() {
    if (!note.trim()) return;
    setBusy(true);
    try {
      await api.createAnnotation({ kind, run_id: runId, span_id: spanId, note: note.trim(), source: "user" });
      setNote("");
      reload();
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    await api.deleteAnnotation(id);
    setItems((prev) => prev.filter((a) => a.id !== id));
  }

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 space-y-2.5 border-b border-border p-3">
        <Tabs
          variant="segment"
          tabs={KINDS.map((k) => ({ value: k.value, label: k.label }))}
          value={kind}
          onChange={(v) => setKind(v as AnnotationKind)}
        />
        <Textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder={spanId ? "Annotate this span…" : "Annotate this run…"}
          rows={2}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") submit();
          }}
        />
        <div className="flex items-center justify-between gap-2">
          <span className="flex items-center gap-1.5 text-label text-muted-foreground">
            {spanId ? "attached to span" : "attached to run"} · <Kbd>⌘⏎</Kbd> to save
          </span>
          <Button size="sm" onClick={submit} disabled={busy || !note.trim()}>
            Add {kind}
          </Button>
        </div>
      </div>
      <div className="flex-1 space-y-1.5 overflow-auto p-2">
        {items.length === 0 ? (
          <div className="p-4 text-center text-xs text-muted-foreground">No annotations on this run yet.</div>
        ) : (
          items.map((a) => {
            const def = KINDS.find((k) => k.value === a.kind) ?? KINDS[2];
            const Icon = def.icon;
            return (
              <div
                key={a.id}
                className="group flex items-start gap-2.5 rounded-lg border border-border bg-muted/40 px-2.5 py-2 transition-colors hover:bg-muted"
              >
                <span className="mt-0.5 shrink-0">
                  <Badge tone={def.badge}>
                    <Icon className="h-3 w-3" />
                    {def.label}
                  </Badge>
                </span>
                <div className="min-w-0 flex-1">
                  <div className="whitespace-pre-wrap break-words text-xs text-foreground">{a.note}</div>
                  <div className="mt-1 flex items-center gap-2 text-label text-muted-foreground">
                    <span>{a.source}</span>
                    <span>·</span>
                    <span>{ago(a.created_at)}</span>
                    {a.span_id && <span className="font-mono">span {a.span_id.slice(0, 8)}</span>}
                  </div>
                </div>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7 shrink-0 opacity-0 transition-opacity group-hover:opacity-100 hover:text-danger"
                  onClick={() => remove(a.id)}
                  title="Delete annotation"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
