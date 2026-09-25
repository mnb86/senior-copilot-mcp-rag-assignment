import type { InvestigationRun } from "../types";
import { SCENARIOS } from "../utils";

interface Props {
  runs: InvestigationRun[];
  selectedId: string | null;
  busy: boolean;
  onRun: (query: string) => void;
  onSelect: (id: string) => void;
  onNewCase: () => void;
  toc: [string, string][];
  onJump: (id: string) => void;
}

function runLabel(r: InvestigationRun): string {
  const s = r.response?.alarm_summary;
  return s?.asset?.asset_name ?? s?.scope_label ?? r.query;
}

export function Sidebar({ runs, selectedId, busy, onRun, onSelect, onNewCase, toc, onJump }: Props) {
  const selectedQuery = runs.find((r) => r.id === selectedId)?.query;
  return (
    <aside className="nav">
      {toc.length > 0 && (
        <div className="nav-group">
          <div className="nav-h">
            <span>On this page</span>
          </div>
          <ul>
            {toc.map(([id, label]) => (
              <li key={id}>
                <button type="button" className="nav-item nav-toc" onClick={() => onJump(id)}>
                  <span className="nav-text">{label}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="nav-group">
        <div className="nav-h">
          <span>Case history</span>
          {runs.length > 0 && (
            <button type="button" className="nav-action" onClick={onNewCase} disabled={busy}>
              New case
            </button>
          )}
        </div>
        {runs.length === 0 ? (
          <p className="nav-empty">No runs yet.</p>
        ) : (
          <ul>
            {[...runs].reverse().map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  className={`nav-item ${selectedId === r.id ? "on" : ""}`}
                  onClick={() => onSelect(r.id)}
                  disabled={r.pending}
                  title={r.query}
                >
                  <span className={`dot ${r.pending ? "dot-busy" : r.error ? "dot-err" : `dot-${r.response?.answer.confidence}`}`} />
                  <span className="nav-text">{r.pending ? "Running…" : runLabel(r)}</span>
                  <span className="nav-time">{r.startedAt}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="nav-group">
        <div className="nav-h">
          <span>Saved scenarios</span>
        </div>
        <ul>
          {SCENARIOS.map((s) => (
            <li key={s.title}>
              <button
                type="button"
                className={`nav-item ${selectedQuery === s.query && !selectedId ? "on" : ""}`}
                onClick={() => onRun(s.query)}
                disabled={busy}
                title={s.query}
              >
                <span className="nav-text">
                  {s.title}
                  <span className="nav-sub">{s.scope}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}
