import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "./api";
import { Chat } from "./components/Chat";
import { Markdown } from "./components/Markdown";
import { Sources } from "./components/Sources";
import { SummaryPanel } from "./components/SummaryPanel";
import { ToolsPanel } from "./components/ToolsPanel";
import { TracePanel } from "./components/TracePanel";
import type { ChatTurn, Health } from "./types";

type Tab = "investigation" | "sources" | "trace" | "tools";
const uid = () => Math.random().toString(36).slice(2, 10);

export default function App() {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("investigation");
  const [focusCite, setFocusCite] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthErr, setHealthErr] = useState<string | null>(null);

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch((e: Error) => setHealthErr(e.message));
  }, []);

  const selected = useMemo(() => turns.find((t) => t.id === selectedId)?.response, [turns, selectedId]);

  const send = useCallback(
    async (text: string) => {
      const user: ChatTurn = { id: uid(), role: "user", text };
      const pending: ChatTurn = { id: uid(), role: "assistant", text: "", pending: true };
      setTurns((t) => [...t, user, pending]);
      setBusy(true);
      try {
        const r = await api.chat(text, conversationId);
        setConversationId(r.conversation_id);
        setTurns((t) => t.map((x) => (x.id === pending.id ? { ...x, pending: false, response: r } : x)));
        setSelectedId(pending.id);
        setFocusCite(null);
        setTab((cur) => (cur === "tools" ? "investigation" : cur));
      } catch (e) {
        const msg = e instanceof ApiError ? `${e.message}${e.code ? ` (${e.code})` : ""}` : String(e);
        setTurns((t) => t.map((x) => (x.id === pending.id ? { ...x, pending: false, error: msg } : x)));
      } finally {
        setBusy(false);
      }
    },
    [conversationId],
  );

  const onCite = (turnId: string, cite: string) => {
    setSelectedId(turnId);
    setTab("sources");
    setFocusCite(cite);
    setTimeout(() => document.getElementById(`src-${cite}`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 50);
  };

  const reset = () => {
    setTurns([]);
    setConversationId(undefined);
    setSelectedId(null);
    setFocusCite(null);
  };

  const warnings = selected?.warnings ?? [];
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden>
            ▲
          </span>
          <div>
            <h1>Alarm Investigation Copilot</h1>
            <div className="muted small">Procedure guidance · MCP + RAG</div>
          </div>
        </div>
        <div className="status">
          {healthErr ? (
            <span className="badge step-error">backend offline</span>
          ) : health ? (
            <>
              <span className="badge step-ok">backend ok</span>
              <span className="badge doc">
                RAG {health.rag.documents ?? "?"} docs / {health.rag.chunks ?? "?"} chunks
              </span>
              <span className="badge doc">LLM: {health.llm_provider}</span>
            </>
          ) : (
            <span className="badge">connecting…</span>
          )}
          {conversationId && <span className="muted small mono">conv {conversationId}</span>}
        </div>
      </header>
      <main className="layout">
        <section className="left">
          <Chat
            turns={turns}
            busy={busy}
            selectedId={selectedId}
            onSend={send}
            onSelect={setSelectedId}
            onCite={onCite}
            onReset={reset}
          />
        </section>
        <section className="right">
          <nav className="tabs" role="tablist">
            {(
              [
                ["investigation", "Investigation"],
                ["sources", `Sources${selected ? ` (${selected.citations.length})` : ""}`],
                ["trace", `MCP trace${selected ? ` (${selected.tool_trace.length})` : ""}`],
                ["tools", "Tools"],
              ] as [Tab, string][]
            ).map(([k, label]) => (
              <button key={k} type="button" role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>
                {label}
              </button>
            ))}
          </nav>
          {warnings.length > 0 && tab !== "tools" && (
            <div className="alert alert-warn">
              <strong>Degraded / notes</strong>
              <ul>
                {warnings.map((w) => (
                  <li key={w}>
                    <Markdown text={w} />
                  </li>
                ))}
              </ul>
            </div>
          )}
          {tab === "tools" ? (
            <ToolsPanel />
          ) : !selected ? (
            <div className="empty big">
              Ask a question to see the alarm summary, likely causes, recommendations, cited sources and the MCP execution trace here.
            </div>
          ) : tab === "investigation" ? (
            <SummaryPanel r={selected} onCite={(c) => onCite(selectedId!, c)} />
          ) : tab === "sources" ? (
            <Sources r={selected} focus={focusCite} />
          ) : (
            <TracePanel r={selected} />
          )}
        </section>
      </main>
    </div>
  );
}
