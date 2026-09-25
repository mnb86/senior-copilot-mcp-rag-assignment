import type { InvestigationResponse } from "../types";

interface Props {
  r: InvestigationResponse;
  focus?: string | null;
}

export function Sources({ r, focus }: Props) {
  const ret = r.retrieval;
  return (
    <div className="panel-body">
      {ret && (
        <section className="card">
          <header className="card-h">
            <h3>Retrieval</h3>
            {ret.low_confidence ? (
              <span className="badge conf-low">low confidence</span>
            ) : (
              <span className="badge conf-high">confidence {Math.round(ret.top_confidence * 100)}%</span>
            )}
          </header>
          <div className="kv">
            <span>Queries</span>
            <span className="mono small">{ret.query}</span>
            <span>Filters</span>
            <span className="mono small">{JSON.stringify(ret.filters)}</span>
            {ret.fallback_used && (
              <>
                <span>Fallback</span>
                <span className="small">hard filters relaxed (no confident match within filters)</span>
              </>
            )}
          </div>
          {ret.quarantined.length > 0 && (
            <div className="alert alert-warn">
              <strong>Quarantined passages (possible prompt injection):</strong>
              <ul>
                {ret.quarantined.map((q) => (
                  <li key={q.chunk_id} className="mono small">
                    {q.chunk_id} - patterns: {q.patterns.join(", ")}
                  </li>
                ))}
              </ul>
              <div className="small">These passages were excluded from the answer and are never followed as instructions.</div>
            </div>
          )}
        </section>
      )}
      {r.citations.length === 0 ? (
        <div className="empty">No document sources were cited for this answer.</div>
      ) : (
        r.citations.map((c) => (
          <article key={c.id} id={`src-${c.id}`} className={`card source ${focus === c.id ? "focus" : ""}`}>
            <header className="card-h">
              <div>
                <span className="cite static">{c.id}</span> <strong>{c.doc_id}</strong> <span className="muted">rev {c.revision ?? "-"}</span>
              </div>
              <div className="src-meta">
                <span className="badge doc">{c.doc_type.replace(/_/g, " ")}</span>
                {c.trust_level === "external" && <span className="badge conf-low">external / unverified</span>}
              </div>
            </header>
            <div className="src-title">{c.title}</div>
            <div className="muted small">
              § {c.section} · <span className="mono">{c.source_path}</span>
            </div>
            <blockquote>{c.snippet}</blockquote>
            <div className="muted small mono">
              score {c.score.toFixed(3)} · confidence {Math.round(c.confidence * 100)}% · chunk {c.chunk_id}
            </div>
          </article>
        ))
      )}
    </div>
  );
}
