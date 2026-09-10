import { beforeAll, describe, expect, it, vi, afterEach } from "vitest";
import type { AgentEvent } from "../../api";

// api.ts reads window.__AMIX_BASE__ at module scope for the AMIX portal
// prefix, and vitest runs in node. Stub the global, then import for real.
type ChatFn = (body: { message: string; conversation?: string })
  => AsyncGenerator<AgentEvent>;
let agentChat: ChatFn;

beforeAll(async () => {
  vi.stubGlobal("window", { location: { origin: "http://localhost" } });
  agentChat = (await import("../../api")).agentChat as ChatFn;
});

/** Feed the parser a fetch response whose body arrives in the given byte
 *  chunks, so frame boundaries land wherever the test wants them. */
function mockFetch(chunks: string[], ok = true, status = 200) {
  const encoder = new TextEncoder();
  const queue = chunks.map((c) => encoder.encode(c));
  let i = 0;
  const body = {
    getReader: () => ({
      read: async () =>
        i < queue.length ? { done: false, value: queue[i++] } : { done: true, value: undefined },
    }),
  };
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok, status, body: ok ? body : null })));
}

async function drain(): Promise<AgentEvent[]> {
  const out: AgentEvent[] = [];
  for await (const e of agentChat({ message: "hi" })) out.push(e);
  return out;
}

const frame = (obj: unknown) => `data: ${JSON.stringify(obj)}\n\n`;

// Only fetch needs resetting between tests; api.ts captured the base URL
// once at import, so the window stub is not needed again.
afterEach(() => vi.unstubAllGlobals());

describe("agentChat SSE parsing", () => {
  it("yields one event per frame", async () => {
    mockFetch([
      frame({ type: "start", conversation: "c1" }),
      frame({ type: "delta", text: "hello" }),
      frame({ type: "done", stop: "end_turn" }),
    ]);
    expect((await drain()).map((e) => e.type)).toEqual(["start", "delta", "done"]);
  });

  it("reassembles a frame split across chunk boundaries", async () => {
    // The network does not respect frame boundaries; the parser must.
    const whole = frame({ type: "delta", text: "split me" });
    mockFetch([whole.slice(0, 9), whole.slice(9, 20), whole.slice(20)]);
    const events = await drain();
    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({ type: "delta", text: "split me" });
  });

  it("handles several frames arriving in one chunk", async () => {
    mockFetch([frame({ type: "delta", text: "a" }) + frame({ type: "delta", text: "b" })]);
    const events = await drain();
    expect(events.map((e) => (e as { text: string }).text)).toEqual(["a", "b"]);
  });

  it("keeps going when one frame is unparseable", async () => {
    mockFetch([
      "data: {not json}\n\n",
      frame({ type: "done", stop: "end_turn" }),
    ]);
    expect((await drain()).map((e) => e.type)).toEqual(["done"]);
  });

  it("ignores an unterminated trailing frame rather than yielding half of it", async () => {
    mockFetch([frame({ type: "delta", text: "ok" }), 'data: {"type":"delta","te']);
    expect(await drain()).toHaveLength(1);
  });

  it("survives multi-byte characters split across chunks", async () => {
    const whole = frame({ type: "delta", text: "°Bx — ünïcode" });
    const bytes = new TextEncoder().encode(whole);
    const decoder = new TextDecoder();
    // Cut mid-character on purpose: the streaming decoder must stitch it.
    const cut = 12;
    mockFetch([]);
    const body = {
      getReader: () => {
        const parts = [bytes.slice(0, cut), bytes.slice(cut)];
        let i = 0;
        return {
          read: async () =>
            i < parts.length ? { done: false, value: parts[i++] } : { done: true, value: undefined },
        };
      },
    };
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200, body })));
    const events = await drain();
    expect((events[0] as { text: string }).text).toBe("°Bx — ünïcode");
    expect(decoder.decode(bytes)).toContain("°Bx");
  });

  it("reports a failed request as an error event instead of throwing", async () => {
    mockFetch([], false, 502);
    const events = await drain();
    expect(events).toEqual([{ type: "error", message: "chat failed (HTTP 502)" }]);
  });
});
