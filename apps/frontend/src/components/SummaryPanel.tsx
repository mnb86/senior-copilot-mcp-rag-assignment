import type { ReactNode } from "react";
import type { InvestigationResponse } from "../types";
import { fmtPct, fmtTime, splitAnswer } from "../utils";
import { Conf, RecStatus, Sev } from "./Badges";
import { Markdown } from "./Markdown";
import { Sparkline } from "./Sparkline";

interface Props {
  r: InvestigationResponse;
  onCite: (id: string) => void;
}

/** Sections the overview renders for this response, in page order (feeds the "On this page" rail). */
export function overviewSections(r: InvestigationResponse): [string, string][] {
  const s = r.alarm_summary;
  const out: [string, string][] = [["assessment", "Assessment"]];
  if (s) out.push(["asset", s.asset ? "Asset" : "Scope"]);
  if (r.likely_causes.length) out.push(["causes", "Likely causes"]);
  if (r.recommendations.length) out.push(["actions", "Recommended actions"]);
  if (s?.primary_alarm) out.push(["focus", "Focus alarm"]);
  if (s?.active_alarms.length) out.push(["active", "Active alarms"]);
  if (s?.top_alarm_groups.length) out.push(["frequent", "Most frequent alarms"]);
  if (s?.related_assets.length) out.push(["related", "Related assets"]);
  if (s && Object.keys(s.kpis).length) out.push(["kpi", "KPI calculation"]);
  return out;
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

function Section({ id, title, aside, children }: { id: string; title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section id={`sec-${id}`} className="doc-sec">
      <div className="doc-sec-h">
        <h2>{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

export function SummaryPanel({ r, onCite }: Props) {
  const s = r.alarm_summary;
  const recs = [...r.recommendations.filter((x) => x.source === "api"), ...r.recommendations.filter((x) => x.source === "document")];
  const [lead, rest] = splitAnswer(r.answer.markdown);
  return (
    <div className="docpage">
      {r.errors.length > 0 && (
        <div className="callout callout-err" role="alert">
          {r.errors.map((e) => (
            <div key={e}>{e}</div>
          ))}
        </div>
      )}

      <Section id="assessment" title="Assessment" aside={<Conf c={r.answer.confidence} label="confidence" />}>
        <div className="prose">
          <Markdown text={lead} onCite={onCite} />
        </div>
        {rest && (
          <details className="disclosure">
            <summary>Full written answer</summary>
            <div className="prose">
              <Markdown text={rest} onCite={onCite} />
            </div>
          </details>
        )}
      </Section>

      {s && (
        <Section id="asset" title={s.asset ? "Asset" : "Scope"} aside={<span className="muted small">{s.window?.label}</span>}>
          <div className="frame">
            <div className="asset-row">
              <div>
                <div className="asset-name">{s.asset?.asset_name ?? s.scope_label}</div>
                {s.asset && (
                  <div className="muted small">
                    <span className="mono">{s.asset.asset_id}</span> · {s.asset.site} · {s.asset.unit} · {s.asset.asset_type}
                  </div>
                )}
              </div>
              {s.asset && <span className={`badge crit-${s.asset.criticality}`}>criticality {s.asset.criticality}</span>}
            </div>
            {(s.total_alarms > 0 || s.trend) && (
              <div className="metrics">
                <div className="metric">
                  <div className="metric-v">{s.total_alarms}</div>
                  <div className="metric-l">Alarms</div>
                </div>
                {Object.entries(s.by_severity).map(([k, v]) => (
                  <div className="metric" key={k}>
                    <div className={`metric-v sevtext-${k}`}>{v}</div>
                    <div className="metric-l">{k}</div>
                  </div>
                ))}
                {s.trend && (
                  <div className="metric metric-wide">
                    <Sparkline series={s.trend.series} />
                    <div className="metric-l">
                      Weekly trend {s.trend.direction} ({s.trend.first_half_count} → {s.trend.second_half_count})
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </Section>
      )}

      {r.likely_causes.length > 0 && (
        <Section id="causes" title="Likely causes">
          <ol className="causes">
            {r.likely_causes.map((c) => (
              <li key={c.cause}>
                <div className="cause-h">
                  <span className="cause-name">{c.cause}</span>
                  <Conf c={c.confidence} />
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
        </Section>
      )}

      {recs.length > 0 && (
        <Section id="actions" title="Recommended actions">
          <p className="muted">Actions from the Alarm API, each checked against the retrieved procedures.</p>
          <div className="frame table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Verdict</th>
                  <th>Action</th>
                  <th>Source</th>
                  <th>Evidence</th>
                </tr>
              </thead>
              <tbody>
                {recs.map((x, i) => (
                  <tr key={i} className={x.status === "conflict" ? "row-conflict" : ""}>
                    <td>
                      <RecStatus s={x.status} />
                    </td>
                    <td>
                      <div className="action-text">{x.action}</div>
                      <div className="muted small">{x.explanation}</div>
                    </td>
                    <td className="nowrap">
                      {x.source === "api" ? "Alarm API" : "Procedure"}
                      {x.urgency && <div className="muted small">{x.urgency}</div>}
                    </td>
                    <td className="nowrap">
                      <CiteChips ids={x.citations} onCite={onCite} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {s?.primary_alarm && (
        <Section id="focus" title="Focus alarm">
          <div className="frame">
            <div className="asset-row">
              <div>
                <div className="asset-name">{s.primary_alarm.alarm_name}</div>
                <div className="mono muted small">{s.primary_alarm.alarm_id}</div>
              </div>
              <div className="focus-prio">
                <Sev s={s.primary_alarm.severity} />
                {s.primary_alarm.priority_score != null && (
                  <>
                    <span className={`badge band-${s.primary_alarm.priority_band}`}>{s.primary_alarm.priority_band}</span>
                    <span className="prio-score">{s.primary_alarm.priority_score}</span>
                  </>
                )}
              </div>
            </div>
            {s.priority_rationale && <p className="muted small frame-note">{s.priority_rationale}</p>}
          </div>
        </Section>
      )}

      {s && s.active_alarms.length > 0 && (
        <Section id="active" title="Active alarms">
          <div className="frame table-wrap">
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
                    <td className="mono small nowrap">{fmtTime(a.start_time)}</td>
                    <td>{a.acknowledged ? "Yes" : <span className="warn-text">No</span>}</td>
                    <td className="nowrap">{a.priority_score != null ? `${a.priority_score} ${a.priority_band}` : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {s && s.top_alarm_groups.length > 0 && (
        <Section id="frequent" title="Most frequent alarms">
          <div className="frame table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Alarm</th>
                  <th>Count</th>
                  <th>Repeat within 24 h</th>
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
                    <td className="nowrap">{g.avg_ack_delay_s != null ? `${Math.round(g.avg_ack_delay_s)} s` : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {s && s.related_assets.length > 0 && (
        <Section id="related" title="Related assets">
          <div className="frame table-wrap">
            <table>
              <tbody>
                {s.related_assets.map((a) => (
                  <tr key={a.asset_id}>
                    <td>{a.asset_name}</td>
                    <td className="mono muted small">{a.asset_id}</td>
                    <td className="muted">{a.relationship.replace(/_/g, " ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {s && Object.keys(s.kpis).length > 0 && (
        <Section id="kpi" title="KPI calculation">
          <pre className="json">{JSON.stringify(s.kpis, null, 2)}</pre>
        </Section>
      )}

      {!s && <p className="muted">No alarm data for this run (document-only question or clarification needed).</p>}
    </div>
  );
}
