// Live push backbone. Kyoko serves Server-Sent Events at GET /api/events/stream
// (SCOPE/plan Design Decision 1: SSE, not WebSocket — every live need here is
// one-directional server->client). This module wraps a single shared EventSource
// in a tiny pub/sub so many components can subscribe to named events, and exposes
// connection status. Client->server signals (annotations, ingest) are plain POSTs.

import { useEffect, useRef, useState } from "react";

export type LiveEventName = "run_upsert" | "live_event" | "mcp_log" | "annotation" | "clear";
export type ConnectionStatus = "connecting" | "open" | "closed";

type Handler = (data: any) => void;

const EVENT_NAMES: LiveEventName[] = ["run_upsert", "live_event", "mcp_log", "annotation", "clear"];

class LiveBusClient {
  private source: EventSource | null = null;
  private handlers = new Map<string, Set<Handler>>();
  private statusListeners = new Set<(s: ConnectionStatus) => void>();
  private status: ConnectionStatus = "closed";
  private refCount = 0;

  private setStatus(s: ConnectionStatus) {
    this.status = s;
    for (const l of this.statusListeners) l(s);
  }

  getStatus() {
    return this.status;
  }

  private connect() {
    if (this.source) return;
    this.setStatus("connecting");
    const src = new EventSource("/api/events/stream");
    this.source = src;
    src.onopen = () => this.setStatus("open");
    src.onerror = () => {
      // EventSource reconnects automatically; reflect the gap as connecting.
      this.setStatus(this.source ? "connecting" : "closed");
    };
    for (const name of EVENT_NAMES) {
      src.addEventListener(name, (ev: MessageEvent) => {
        let data: unknown = null;
        try {
          data = ev.data ? JSON.parse(ev.data) : null;
        } catch {
          data = ev.data;
        }
        const set = this.handlers.get(name);
        if (set) for (const h of set) h(data);
      });
    }
  }

  private disconnect() {
    if (this.source) {
      this.source.close();
      this.source = null;
    }
    this.setStatus("closed");
  }

  acquire() {
    this.refCount += 1;
    if (this.refCount === 1) this.connect();
  }

  release() {
    this.refCount = Math.max(0, this.refCount - 1);
    if (this.refCount === 0) this.disconnect();
  }

  on(name: string, handler: Handler) {
    let set = this.handlers.get(name);
    if (!set) {
      set = new Set();
      this.handlers.set(name, set);
    }
    set.add(handler);
    return () => set!.delete(handler);
  }

  onStatus(listener: (s: ConnectionStatus) => void) {
    this.statusListeners.add(listener);
    return () => this.statusListeners.delete(listener);
  }
}

const bus = new LiveBusClient();

/** Keep the shared EventSource alive while any mounted component needs it. */
export function useLiveConnection(): ConnectionStatus {
  const [status, setStatus] = useState<ConnectionStatus>(bus.getStatus());
  useEffect(() => {
    bus.acquire();
    const off = bus.onStatus(setStatus);
    setStatus(bus.getStatus());
    return () => {
      off();
      bus.release();
    };
  }, []);
  return status;
}

/** Subscribe to a named live event. The handler ref is kept current across renders. */
export function useLiveEvent(name: LiveEventName, handler: Handler) {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    bus.acquire();
    const off = bus.on(name, (data) => ref.current(data));
    return () => {
      off();
      bus.release();
    };
  }, [name]);
}
