import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { InvestigationRun } from "../types";
import { fmtMs, SCENARIOS, splitAnswer } from "../utils";
import { Conf } from "./Badges";
import { Markdown } from "./Markdown";

interface Props {
  runs: InvestigationRun[];
  selectedId: string | null;
  busy: boolean;
  onSend: (text: string) => void;
  onOpenReport: (runId: string) => void;
  onCite: (runId: string, cite: string) => void;
}

/** Right-hand chat panel: the conversation transcript with one message box pinned at the bottom. */
export function ChatPanel({ runs, selectedId, busy, onSend, onOpenReport, onCite }: Props) {
  const [text, setText] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // block body: scrollIntoView may return a value in newer browsers, and an effect must only return a cleanup
    if (runs.length > 0) endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [runs.length, busy]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const q = text.trim();
    if (!q || busy) return;
    onSend(q);
    setText("");
  };

  return (
    <aside className="chatrail" aria-label="Chat">
      <div className="chat-h">
        <span>Chat</span>
        {runs.length > 0 && <span className="muted small">follow-ups keep the asset in context</span>}
      </div>
      <div className="chat-scroll" aria-live="polite">
        {runs.length === 0 && (
          <div className="chat-empty">
            <p>Ask about an asset, alarm or procedure. Try one of these:</p>
            <ul className="suggestions">
              {SCENARIOS.slice(0, 4).map((s) => (
                <li key={s.title}>
                  <button type="button" onClick={() => onSend(s.query)} disabled={busy} title={s.query}>
                    {s.title}
                    <span>{s.scope}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {runs.map((r) => {
          const res = r.response;
          const [lead, rest] = res ? splitAnswer(res.answer.markdown) : ["", ""];
          const mcpCalls = res ? res.tool_trace.filter((t) => t.kind === "mcp" && t.step_id !== "discover_tools").length : 0;
          return (
            <article key={r.id} id={`turn-${r.id}`} className={`turn ${selectedId === r.id ? "on" : ""}`}>
              <div className="turn-who">
                You <span className="turn-time">{r.startedAt}</span>
              </div>
              <p className="turn-q">{r.query}</p>
              <div className="turn-who">Copilot</div>
              {r.pending && (
                <div className="turn-busy">
                  <div className="progress" role="progressbar" aria-label="Investigation running" />
                  <span className="muted small">Discovering tools, calling the MCP server and retrieving documents…</span>
                </div>
              )}
              {r.error && (
                <div className="callout callout-err" role="alert">
                  {r.error}
                </div>
              )}
              {res && (
                <>
                  <div className="prose">
                    <Markdown text={lead} onCite={(c) => onCite(r.id, c)} />
                  </div>
                  {rest && (
                    <details className="disclosure">
                      <summary>Full written answer</summary>
                      <div className="prose">
                        <Markdown text={rest} onCite={(c) => onCite(r.id, c)} />
                      </div>
                    </details>
                  )}
                  {res.warnings.length > 0 && <p className="warn-text small">{res.warnings.length} warning(s) in the report</p>}
                  <div className="turn-meta">
                    <Conf c={res.answer.confidence} label="confidence" />
                    <span>{mcpCalls} MCP calls</span>
                    <span>{res.citations.length} sources</span>
                    <span>{fmtMs(res.timings.total_ms)}</span>
                  </div>
                  <button type="button" className="link" onClick={() => onOpenReport(r.id)}>
                    {selectedId === r.id ? "Showing report" : "Open report"} →
                  </button>
                </>
              )}
            </article>
          );
        })}
        <div ref={endRef} />
      </div>
      <form className="composer" onSubmit={submit}>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) submit(e);
          }}
          placeholder={runs.length ? "Ask a follow-up…" : "Ask about an asset, alarm or procedure…"}
          rows={3}
          maxLength={2000}
          aria-label="Message"
          disabled={busy}
        />
        <div className="composer-row">
          <span className="muted small">Enter to send · Shift+Enter for a new line</span>
          <button type="submit" className="send" disabled={busy || !text.trim()}>
            {busy ? "Running…" : "Send"}
          </button>
        </div>
      </form>
    </aside>
  );
}
