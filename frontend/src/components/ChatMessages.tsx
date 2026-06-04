import type { SpanNode } from "@/lib/types";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Empty } from "@/components/ui/misc";
import { JsonView } from "@/components/JsonView";
import { humanize } from "@/lib/format";
import { cn } from "@/lib/utils";

// Chat-style render of a normalized span. For llm spans: a system bubble, the
// message turns (role-colored), and the assistant output. For tool spans: tool
// name + args + result. Everything here comes from the server's redacted
// `normalized` view — no raw attributes.

function roleTone(role: string): NonNullable<BadgeProps["tone"]> {
  const r = role.toLowerCase();
  if (r === "system") return "warn";
  if (r === "user") return "primary";
  if (r === "assistant") return "llm";
  if (r === "tool") return "tool";
  return "neutral";
}

function contentToString(content: unknown): string {
  if (content === null || content === undefined) return "";
  if (typeof content === "string") return content;
  // OpenAI-style content parts: [{type:"text", text:"..."}], or arbitrary objects.
  if (Array.isArray(content)) {
    return content
      .map((part) => {
        if (typeof part === "string") return part;
        if (part && typeof part === "object" && "text" in part) return String((part as Record<string, unknown>).text);
        return JSON.stringify(part, null, 2);
      })
      .join("\n");
  }
  return JSON.stringify(content, null, 2);
}

function Bubble({
  role,
  content,
}: {
  role: string;
  content: unknown;
}) {
  const text = contentToString(content);
  return (
    <div className="flex flex-col gap-1.5">
      <Badge tone={roleTone(role)} className="self-start">
        {humanize(role)}
      </Badge>
      <div
        className={cn(
          "whitespace-pre-wrap break-words rounded-lg border px-3 py-2 text-xs leading-relaxed",
          "border-border bg-muted/40 text-foreground",
        )}
      >
        {text || <span className="italic text-muted-foreground">empty</span>}
      </div>
    </div>
  );
}

export function ChatMessages({ node }: { node: SpanNode }) {
  const n = node.normalized ?? { kind: "other", adapter: "" };

  if (n.kind === "tool") {
    return (
      <div className="space-y-4 p-3">
        <div className="flex items-center gap-2">
          <Badge tone="tool">Tool</Badge>
          <span className="font-mono text-xs font-semibold text-foreground">
            {n.tool_name || node.name || "tool"}
          </span>
          {n.is_error && <Badge tone="danger">Error</Badge>}
        </div>
        {n.args !== undefined && n.args !== null && (
          <div className="space-y-1.5">
            <div className="text-xs font-medium text-muted-foreground">Arguments</div>
            <div className="surface-muted p-3">
              <JsonView data={n.args} toolbar />
            </div>
          </div>
        )}
        {n.result !== undefined && n.result !== null && (
          <div className="space-y-1.5">
            <div className="text-xs font-medium text-muted-foreground">Result</div>
            <div
              className={cn(
                "p-3",
                n.is_error ? "rounded-lg border border-danger/30 bg-danger/10" : "surface-muted",
              )}
            >
              <JsonView data={n.result} toolbar />
            </div>
          </div>
        )}
        {(n.args === undefined || n.args === null) && (n.result === undefined || n.result === null) && (
          <Empty title="No tool detail" hint="This tool span has no captured arguments or result." />
        )}
      </div>
    );
  }

  if (n.kind === "llm") {
    const messages = Array.isArray(n.messages) ? n.messages : [];
    const hasAny = !!n.system || messages.length > 0 || !!n.output_text;
    if (!hasAny) {
      return <Empty title="No structured messages" hint="This llm span has no normalized messages." />;
    }
    return (
      <div className="space-y-4 p-3">
        {n.system && <Bubble role="system" content={n.system} />}
        {messages.map((m, i) => (
          <Bubble key={i} role={m.role || "message"} content={m.content} />
        ))}
        {n.output_text && <Bubble role="assistant" content={n.output_text} />}
      </div>
    );
  }

  return <Empty title="No structured messages" hint="This span is not an llm or tool span." />;
}
