import type { InvestigationResponse } from "../types";
import { fmtPct, fmtTime } from "../utils";
import { Conf, RecStatus, Sev } from "./Badges";
import { Sparkline } from "./Sparkline";

interface Props {
  r: InvestigationResponse;
  onCite: (id: string) => void;
}

function CiteChips({ ids, onCite }: { ids: string[]; onCite: (id: string) => void }) {
  return (
    <>
      {ids.map((id) => (
        <button key={id} type="button" className="cite" onClick={() => onCite(id)}>
          {id}
        </button>
      ))}
    </>
  );
}

export function SummaryPanel({ r, onCite }: Props) {
  const s = r.alarm_summary;
  const api = r.recommendations.filter((x) => x.source === "api");
  const docs = r.recommendations.filter((x) => x.source === "document");
  return (
    <div className="panel-body">
      {r.errors.length > 0 && (
        <div className="alert alert-error" role="alert">
          {r.errors.map((e) => (
            <div key={e}>{e}</div>
          ))}
        </div>
      )}
      {s ? (
        <section className="card">
          <header className="card-h">
            <h3>Alarm summary</h3>
            <span className="muted">{s.window?.label}</span>
          </header>
          {s.asset && (
            <div className="asset">
              <div>
                <div className="asset-name">{s.asset.asset_name}</div>
                <div className="muted mono">
                  {s.asset.asset_id} · {s.asset.site} · {s.asset.unit} · {s.asset.asset_type}
                </div>
              </div>
              <span className={`badge crit-${s.asset.criticality}`}>criticality {s.asset.criticality}</span>
            </div>
          )}
          {(s.total_alarms > 0 || s.trend) && (
          <div className="stats">
            <div className="stat">
              <div className="stat-v">{s.total_alarms}</div>
              <div className="stat-l">alarms</div>
            </div>
            {Object.entries(s.by_severity).map(([k, v]) => (
              <div className="stat" key={k}>
                <div className={`stat-v sevtext-${k}`}>{v}</div>
                <div className="stat-l">{k}</div>
              </div>
            ))}
            {s.trend && (
              <div className="stat stat-wide">
                <Sparkline series={s.trend.series} />
                <div className="stat-l">
                  weekly trend: <strong>{s.trend.direction}</strong> ({s.trend.first_half_count} → {s.trend.second_half_count})
                </div>
              </div>
            )}
          </div>
          )}
          {s.primary_alarm && (
            <div className="primary">
              <div>
                <span className="muted">Focus alarm </span>
                <strong>{s.primary_alarm.alarm_name}</strong> <span className="mono muted">{s.primary_alarm.alarm_id}</span>{" "}
                <Sev s={s.primary_alarm.severity} />
              </div>
              {s.primary_alarm.priority_score != null && (
                <div className="prio">
                  <span className={`badge band-${s.primary_alarm.priority_band}`}>{s.primary_alarm.priority_band}</span>
                  <span className="prio-score">{s.primary_alarm.priority_score}</span>
                </div>
              )}
            </div>
          )}
          {s.priority_rationale && <p className="muted small">{s.priority_rationale}</p>}
          {s.active_alarms.length > 0 && (
            <>
              <h4>Active alarms</h4>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Alarm</th>
                      <th>Asset</th>
                      <th>Severity</th>
                      <th>Since</th>
                      <th>Ack</th>
                      <th>Priority</th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.active_alarms.map((a) => (
                      <tr key={a.alarm_id}>
                        <td>
                          {a.alarm_name}
                          <div className="mono muted small">{a.alarm_id}</div>
                        </td>
                        <td>{a.asset_name}</td>
                        <td>
                          <Sev s={a.severity} />
                        </td>
                        <td className="mono small">{fmtTime(a.start_time)}</td>
                        <td>{a.acknowledged ? "yes" : <span className="warn-text">no</span>}</td>
                        <td>{a.priority_score != null ? `${a.priority_score} ${a.priority_band}` : "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          {s.top_alarm_groups.length > 0 && (
            <>
              <h4>Most frequent alarms</h4>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Alarm</th>
                      <th>Count</th>
                      <th>Recurring &lt;24h</th>
                      <th>Avg ack</th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.top_alarm_groups.map((g) => (
                      <tr key={g.alarm_name}>
                        <td>{g.alarm_name}</td>
                        <td>
                          <div className="barcell">
                            <span className="bar" style={{ width: `${Math.min(100, (g.count / Math.max(1, s.top_alarm_groups[0].count)) * 100)}%` }} />
                            <span>{g.count}</span>
                          </div>
                        </td>
                        <td>{fmtPct(g.recurring_rate)}</td>
                        <td>{g.avg_ack_delay_s != null ? `${Math.round(g.avg_ack_delay_s)} s` : "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          {Object.keys(s.kpis).length > 0 && (
            <>
              <h4>KPIs</h4>
              <pre className="json small">{JSON.stringify(s.kpis, null, 2)}</pre>
            </>
          )}
          {s.related_assets.length > 0 && (
            <>
              <h4>Related assets</h4>
              <ul className="chips">
                {s.related_assets.map((a) => (
                  <li key={a.asset_id} className="chip" title={a.asset_id}>
                    {a.asset_name} <span className="muted">· {a.relationship.replace(/_/g, " ")}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      ) : (
        <div className="empty">No alarm data for this answer (document-only or clarification).</div>
      )}

      {r.likely_causes.length > 0 && (
        <section className="card">
          <header className="card-h">
            <h3>Likely causes</h3>
          </header>
          <ol className="causes">
            {r.likely_causes.map((c) => (
              <li key={c.cause}>
                <div className="cause-h">
                  <strong>{c.cause}</strong> <Conf c={c.confidence} />
                </div>
                <ul className="evidence">
                  {c.evidence.map((e, i) => (
                    <li key={i}>
                      {e.kind === "tool" ? <code>{e.ref}</code> : <CiteChips ids={[e.ref]} onCite={onCite} />} {e.detail}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        </section>
      )}

      {(api.length > 0 || docs.length > 0) && (
        <section className="card">
          <header className="card-h">
            <h3>Recommendations</h3>
            <span className="muted small">API actions verified against retrieved procedures</span>
          </header>
          <ul className="recs">
            {[...api, ...docs].map((x, i) => (
              <li key={i} className={`rec rec-row-${x.status}`}>
                <div className="rec-top">
                  <RecStatus s={x.status} />
                  <span className="badge src">{x.source === "api" ? "API" : "document"}</span>
                  {x.urgency && <span className="muted small">{x.urgency}</span>}
                </div>
                <div className="rec-action">{x.action}</div>
                <div className="muted small">
                  {x.explanation} <CiteChips ids={x.citations} onCite={onCite} />
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
