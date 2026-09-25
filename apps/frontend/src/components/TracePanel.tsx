import { useState } from "react";
import type { InvestigationResponse, ToolCallRecord } from "../types";
import { fmtMs, groupByWave } from "../utils";
import { StepStatus } from "./Badges";

function Json({ value }: { value: unknown }) {
  return <pre className="json">{JSON.stringify(value, null, 2)}</pre>;
}

function Row({ rec }: { rec: ToolCallRecord }) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<"args" | "request" | "response" | "http">("args");
  return (
    <li className={`trace-row trace-${rec.status}`}>
      <button type="button" className="trace-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="chev">{open ? "▾" : "▸"}</span>
        <span className={`kind kind-${rec.kind}`}>{rec.kind === "mcp" ? "MCP" : "RAG"}</span>
        <code className="tool">{rec.tool}</code>
        {rec.iteration != null && <span className="muted small">#{rec.iteration + 1}</span>}
        <span className="purpose">{rec.purpose}</span>
        <span className="spacer" />
        {rec.retries > 0 && <span className="badge retry">{rec.retries} retr{rec.retries > 1 ? "ies" : "y"}</span>}
        <StepStatus s={rec.status} />
        <span className="mono small dur">{fmtMs(rec.duration_ms)}</span>
      </button>
      {rec.error && (
        <div className="trace-err">
          <strong>{rec.error.code}</strong> {rec.error.message}
        </div>
      )}
      {open && (
        <div className="trace-body">
          <div className="tabs small-tabs" role="tablist">
            {(["args", "request", "response", "http"] as const).map((t) => (
              <button key={t} type="button" role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>
                {t === "http" ? `API calls (${rec.api_calls.length})` : t}
              </button>
            ))}
          </div>
          {tab === "args" && <Json value={rec.arguments} />}
          {tab === "request" && <Json value={rec.request ?? null} />}
          {tab === "response" && <Json value={rec.response ?? rec.error ?? null} />}
          {tab === "http" &&
            (rec.api_calls.length === 0 ? (
              <div className="muted small">No upstream HTTP calls recorded for this step.</div>
            ) : (
              <div className="table-wrap">
                <table className="small">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Request</th>
                      <th>Status</th>
                      <th>Outcome</th>
                      <th>Duration</th>
                      <th>Request id</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rec.api_calls.map((c, i) => (
                      <tr key={i} className={c.outcome !== "ok" ? "row-warn" : ""}>
                        <td>{c.attempt}</td>
                        <td className="mono">
                          {c.method} {c.path}
                        </td>
                        <td>{c.status ?? "-"}</td>
                        <td>
                          {c.outcome}
                          {c.error ? ` (${c.error})` : ""}
                        </td>
                        <td>{fmtMs(c.duration_ms)}</td>
                        <td className="mono">{c.request_id}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
        </div>
      )}
    </li>
  );
}

export function TracePanel({ r }: { r: InvestigationResponse }) {
  const mcp = r.tool_trace.filter((t) => t.kind === "mcp" && t.step_id !== "discover_tools");
  const retries = r.tool_trace.reduce((a, t) => a + t.retries, 0);
  const failed = r.tool_trace.filter((t) => t.status !== "ok").length;
  return (
    <div className="panel-body">
      <section className="card">
        <header className="card-h">
          <h3>Execution</h3>
          <span className="mono small muted">{r.trace_id}</span>
        </header>
        <div className="stats">
          <div className="stat">
            <div className="stat-v">{r.intent.name.replace(/_/g, " ")}</div>
            <div className="stat-l">intent ({r.intent.source}, {Math.round(r.intent.confidence * 100)}%)</div>
          </div>
          <div className="stat">
            <div className="stat-v">{mcp.length}</div>
            <div className="stat-l">MCP tool calls</div>
          </div>
          <div className="stat">
            <div className={`stat-v ${retries ? "warn-text" : ""}`}>{retries}</div>
            <div className="stat-l">retries</div>
          </div>
          <div className="stat">
            <div className={`stat-v ${failed ? "err-text" : ""}`}>{failed}</div>
            <div className="stat-l">failed / skipped</div>
          </div>
          <div className="stat">
            <div className="stat-v">{fmtMs(r.timings.total_ms)}</div>
            <div className="stat-l">total</div>
          </div>
        </div>
        <p className="muted small">{r.intent.rationale}</p>
      </section>
      {groupByWave(r.tool_trace).map(([wave, rows]) => (
        <section key={wave} id={`wave-${wave}`} className="wave">
          <div className="wave-h">
            {wave === 0 ? "Discovery" : `Wave ${wave}`}
            {rows.length > 1 && wave > 0 && <span className="muted small"> · {rows.length} calls in parallel</span>}
          </div>
          <ul className="trace">
            {rows.map((rec, i) => (
              <Row key={`${rec.step_id}-${rec.iteration ?? i}`} rec={rec} />
            ))}
          </ul>
        </section>
      ))}
      <details className="card">
        <summary>Plan ({r.plan.length} steps)</summary>
        <Json value={r.plan} />
      </details>
    </div>
  );
}
