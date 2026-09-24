import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { ChatTurn } from "../types";
import { EXAMPLES } from "../utils";
import { Conf } from "./Badges";
import { Markdown } from "./Markdown";

interface Props {
  turns: ChatTurn[];
  busy: boolean;
  selectedId: string | null;
  onSend: (text: string) => void;
  onSelect: (id: string) => void;
  onCite: (turnId: string, cite: string) => void;
  onReset: () => void;
}

export function Chat({ turns, busy, selectedId, onSend, onSelect, onCite, onReset }: Props) {
  const [text, setText] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }), [turns.length, busy]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const t = text.trim();
    if (!t || busy) return;
    onSend(t);
    setText("");
  };

  return (
    <div className="chat">
      <div className="chat-scroll" aria-live="polite">
        {turns.length === 0 && (
          <div className="welcome">
            <h2>Investigate an alarm</h2>
            <p className="muted">
              Ask in plain language. The copilot resolves assets and alarms through the <strong>MCP server</strong>, retrieves
              procedures with <strong>RAG</strong>, and answers with citations and a full tool trace.
            </p>
            <div className="examples">
              {EXAMPLES.map((ex) => (
                <button key={ex} type="button" className="example" onClick={() => onSend(ex)} disabled={busy}>
                  {ex}
                </button>
              ))}
            </div>
          </div>
        )}
        {turns.map((t) =>
          t.role === "user" ? (
            <div key={t.id} className="msg user">
              <div className="bubble">{t.text}</div>
            </div>
          ) : (
            <div
              key={t.id}
              className={`msg assistant ${selectedId === t.id ? "selected" : ""}`}
              onClick={() => t.response && onSelect(t.id)}
            >
              <div className="bubble">
                {t.pending && (
                  <div className="thinking">
                    <span className="dot" />
                    <span className="dot" />
                    <span className="dot" />
                    <span className="muted small">Discovering tools, calling MCP and retrieving documents…</span>
                  </div>
                )}
                {t.error && (
                  <div className="alert alert-error" role="alert">
                    {t.error}
                  </div>
                )}
                {t.response && (
                  <>
                    <div className="msg-meta">
                      <span className="badge intent">{t.response.intent.name.replace(/_/g, " ")}</span>
                      <Conf c={t.response.answer.confidence} label="confidence" />
                      <span className="muted small">
                        {t.response.tool_trace.filter((x) => x.kind === "mcp" && x.step_id !== "discover_tools").length} MCP calls ·{" "}
                        {t.response.citations.length} sources · {t.response.answer.generator}
                      </span>
                    </div>
                    <Markdown text={t.response.answer.markdown} onCite={(c) => onCite(t.id, c)} />
                  </>
                )}
              </div>
            </div>
          ),
        )}
        <div ref={endRef} />
      </div>
      <form className="composer" onSubmit={submit}>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) submit(e);
          }}
          placeholder="e.g. Why are compressor discharge pressure alarms repeatedly occurring?"
          rows={2}
          maxLength={2000}
          aria-label="Message"
        />
        <div className="composer-actions">
          <button type="button" className="btn-ghost" onClick={onReset} disabled={busy || turns.length === 0}>
            New conversation
          </button>
          <button type="submit" className="btn" disabled={busy || !text.trim()}>
            {busy ? "Working…" : "Send"}
          </button>
        </div>
      </form>
    </div>
  );
}
