import { useEffect, useState } from "react";
import { api } from "../api";
import type { ToolSpec } from "../types";

export function ToolsPanel() {
  const [tools, setTools] = useState<ToolSpec[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [server, setServer] = useState("");
  const [loading, setLoading] = useState(false);

  const load = () => {
    setLoading(true);
    setErr(null);
    api
      .tools()
      .then((r) => {
        setTools(r.tools);
        setServer(`${r.server} @ ${r.url}`);
      })
      .catch((e: Error) => setErr(e.message))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  return (
    <div className="panel-body">
      <section className="card">
        <header className="card-h">
          <h3>MCP tool discovery</h3>
          <button type="button" className="btn-ghost" onClick={load} disabled={loading}>
            {loading ? "Discovering…" : "Refresh"}
          </button>
        </header>
        {server && <div className="muted small mono">{server}</div>}
        {err && <div className="alert alert-error">Tool discovery failed: {err}</div>}
        {!tools && !err && <div className="skeleton" />}
      </section>
      {tools?.map((t) => (
        <details key={t.name} className="card tool-card">
          <summary>
            <code className="tool">{t.name}</code>
            {t.read_only && <span className="badge conf-high">read-only</span>}
            <span className="muted small"> {t.title}</span>
          </summary>
          <p className="small">{t.description}</p>
          <div className="schemas">
            <div>
              <h4>Input schema</h4>
              <pre className="json">{JSON.stringify(t.input_schema, null, 2)}</pre>
            </div>
            <div>
              <h4>Output schema</h4>
              <pre className="json">{JSON.stringify(t.output_schema, null, 2)}</pre>
            </div>
          </div>
        </details>
      ))}
    </div>
  );
}
