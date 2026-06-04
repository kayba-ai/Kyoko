import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { fmtBytes, tryParseJson } from "@/lib/format";
import { Tabs } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Spinner, ErrorNote, Empty } from "@/components/ui/misc";
import { JsonView } from "@/components/JsonView";

// Reads a span's input/output payload from /api/span-payload (already redacted +
// sliceable server-side). Lets the user toggle input/output and apply a dotted path
// (e.g. messages.0.content) which the server extracts.

export function PayloadViewer({ spanId }: { spanId: string }) {
  const [target, setTarget] = useState<"input" | "output">("input");
  const [path, setPath] = useState("");
  const [appliedPath, setAppliedPath] = useState("");

  const { data, error, loading } = useApi(
    () => api.spanPayload(spanId, { target, path: appliedPath || undefined, maxChars: 20000 }),
    [spanId, target, appliedPath],
  );

  const parsed = data?.available ? tryParseJson(data.content) : null;

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border px-3 py-2.5">
        <Tabs
          variant="segment"
          tabs={[
            { value: "input", label: "Input" },
            { value: "output", label: "Output" },
          ]}
          value={target}
          onChange={(v) => setTarget(v as "input" | "output")}
        />
        <form
          className="flex flex-1 items-center gap-1.5"
          onSubmit={(e) => {
            e.preventDefault();
            setAppliedPath(path.trim());
          }}
        >
          <Input
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder="path e.g. messages.0.content"
            className="h-7 font-mono text-xs"
          />
        </form>
        {data?.available && data.media_type && (
          <Badge tone="neutral">{data.media_type.replace("application/", "")}</Badge>
        )}
        {data?.available && data.size_bytes !== undefined && (
          <Badge tone="neutral" className="font-mono normal-case">{fmtBytes(data.size_bytes)}</Badge>
        )}
      </div>
      <div className="flex-1 overflow-auto p-3">
        {loading && !data ? (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        ) : error ? (
          <ErrorNote error={error} />
        ) : !data?.available ? (
          <Empty title={`No ${target} payload`} hint="This span has no captured payload for the selected side." />
        ) : parsed !== null && typeof parsed === "object" ? (
          <div className="surface-muted p-3">
            <JsonView data={parsed} />
          </div>
        ) : (
          <pre className="whitespace-pre-wrap break-all rounded-lg border border-border bg-muted/60 p-3 font-mono text-xs text-foreground">
            {data.content}
          </pre>
        )}
        {data?.truncated && (
          <div className="mt-2">
            <Badge tone="warn">payload truncated</Badge>
          </div>
        )}
      </div>
    </div>
  );
}
