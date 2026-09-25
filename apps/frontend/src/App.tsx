import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "./api";
import { Conf } from "./components/Badges";
import { ChatPanel } from "./components/ChatPanel";
import { Markdown } from "./components/Markdown";
import { Sidebar } from "./components/Sidebar";
import { Sources } from "./components/Sources";
import { overviewSections, SummaryPanel } from "./components/SummaryPanel";
import { ToolsPanel } from "./components/ToolsPanel";
import { TracePanel } from "./components/TracePanel";
import type { Health, InvestigationResponse, InvestigationRun } from "./types";
import { fmtMs, groupByWave } from "./utils";

type Tab = "overview" | "evidence" | "trace" | "tools";
const uid = () => Math.random().toString(36).slice(2, 10);
const clock = () => new Date().toTimeString().slice(0, 5);

const PIPELINE: [string, string][] = [
  ["Resolve the asset", "The MCP server's search_assets tool maps the name to an asset id."],
  ["Collect alarm evidence", "Alarms, summary, trend, correlation, priority and recommendations, via MCP tools in parallel waves."],
  ["Retrieve procedures", "Hybrid search over the document index, filtered by what the MCP data returned."],
  ["Verify and cite", "API actions are checked against the procedures; every claim links to its source."],
];

function caseTitle(r: InvestigationResponse): string {
  const s = r.alarm_summary;
  return s?.asset?.asset_name ?? s?.scope_label ?? r.intent.name.replace(/_/g, " ");
}

function jumpTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function Steps({ running }: { running?: boolean }) {
  return (
    <ol className={`steps ${running ? "running" : ""}`}>
      {PIPELINE.map(([name, how]) => (
        <li key={name}>
          <div className="step-name">{name}</div>
          <div className="step-how">{how}</div>
        </li>
      ))}
    </ol>
  );
}

export default function App() {
  const [runs, setRuns] = useState<InvestigationRun[]>([]);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [focusCite, setFocusCite] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthErr, setHealthErr] = useState<string | null>(null);

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch((e: Error) => setHealthErr(e.message));
  }, []);

  const selected = useMemo(() => runs.find((r) => r.id === selectedId), [runs, selectedId]);
  const r = selected?.response;

  const openTab = (k: Tab) => {
    setTab(k);
    document.getElementById("content")?.scrollTo({ top: 0 });
  };

  const run = useCallback(
    async (query: string) => {
      const id = uid();
      setRuns((rs) => [...rs, { id, query, startedAt: clock(), pending: true }]);
      setSelectedId(id);
      setTab((t) => (t === "tools" ? "overview" : t));
      setFocusCite(null);
      setBusy(true);
      try {
        const res = await api.chat(query, conversationId);
        setConversationId(res.conversation_id);
        setRuns((rs) => rs.map((x) => (x.id === id ? { ...x, pending: false, response: res } : x)));
      } catch (e) {
        const msg = e instanceof ApiError ? `${e.message}${e.code ? ` (${e.code})` : ""}` : String(e);
        setRuns((rs) => rs.map((x) => (x.id === id ? { ...x, pending: false, error: msg } : x)));
      } finally {
        setBusy(false);
      }
    },
    [conversationId],
  );

  const onCite = (cite: string) => {
    setTab("evidence");
    setFocusCite(cite);
    setTimeout(() => {
      document.getElementById(`src-${cite}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 50);
  };

  const openReport = (runId: string) => {
    setSelectedId(runId);
    openTab("overview");
  };

  const selectRun = (runId: string) => {
    setSelectedId(runId);
    jumpTo(`turn-${runId}`);
  };

  const newCase = () => {
    setRuns([]);
    setConversationId(undefined);
    setSelectedId(null);
    setFocusCite(null);
  };

  let toc: [string, string][] = [];
  if (r && tab === "overview") toc = overviewSections(r).map(([id, label]) => [`sec-${id}`, label]);
  if (r && tab === "evidence") toc = r.citations.map((c) => [`src-${c.id}`, `${c.id} · ${c.doc_id}`]);
  if (r && tab === "trace")
    toc = groupByWave(r.tool_trace).map(([w, rows]) => [`wave-${w}`, w === 0 ? "Discovery" : `Wave ${w} (${rows.length})`]);
  const mcpCalls = r ? r.tool_trace.filter((t) => t.kind === "mcp" && t.step_id !== "discover_tools").length : 0;

  const tabs: [Tab, string][] = [
    ["overview", "Overview"],
    ["evidence", r ? `Evidence (${r.citations.length})` : "Evidence"],
    ["trace", r ? `Execution trace (${r.tool_trace.length})` : "Execution trace"],
    ["tools", "Tool catalog"],
  ];

  return (
    <div className="app">
      <header className="hdr">
        <div className="hdr-top">
          <div className="brand">
            <svg className="brand-mark" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M2 12h4l3-7 4 14 3-7h6" />
            </svg>
            <span className="brand-name">Alarm Investigation</span>
            <span className="brand-sub">Procedure guidance</span>
          </div>
          <div className="hdr-links">
            {healthErr ? (
              <span className="sys">
                <span className="dot dot-err" /> Backend offline
              </span>
            ) : !health ? (
              <span className="sys">
                <span className="dot dot-busy" /> Connecting
              </span>
            ) : (
              <>
                <span className="sys" title="Copilot backend and MCP client">
                  <span className="dot dot-high" /> Backend
                </span>
                <span className="sys" title={`${health.rag.chunks ?? "?"} chunks`}>
                  Index · {health.rag.documents ?? "?"} docs
                </span>
                <span className="sys">LLM · {health.llm_provider}</span>
              </>
            )}
          </div>
        </div>
        <nav className="hdr-tabs" role="tablist">
          {tabs.map(([k, label]) => (
            <button key={k} type="button" role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => openTab(k)}>
              {label}
            </button>
          ))}
        </nav>
      </header>

      <div className="body">
        <Sidebar
          runs={runs}
          selectedId={selectedId}
          busy={busy}
          onRun={run}
          onSelect={selectRun}
          onNewCase={newCase}
          toc={toc}
          onJump={jumpTo}
        />

        <main className="content" id="content">
          <div className="page">
            {tab === "tools" ? (
              <>
                <div className="page-h">
                  <div className="eyebrow">Reference</div>
                  <h1>Tool catalog</h1>
                  <p className="lede">Tools discovered live from the MCP server, with their input and output schemas.</p>
                </div>
                <ToolsPanel />
              </>
            ) : !selected ? (
              <>
                <div className="page-h">
                  <div className="eyebrow">Investigations</div>
                  <h1>Investigate an alarm</h1>
                  <p className="lede">
                    Ask in the chat on the right, or open a saved scenario from the left. Each run follows the same four steps,
                    and its report opens here.
                  </p>
                </div>
                <Steps />
              </>
            ) : selected.pending ? (
              <>
                <div className="page-h">
                  <div className="eyebrow">Running</div>
                  <h1>Investigation in progress</h1>
                  <p className="lede">{selected.query}</p>
                </div>
                <div className="progress" role="progressbar" aria-label="Investigation running" />
                <Steps running />
              </>
            ) : selected.error ? (
              <>
                <div className="page-h">
                  <div className="eyebrow">Failed</div>
                  <h1>The run did not complete</h1>
                  <p className="lede">{selected.query}</p>
                </div>
                <div className="callout callout-err" role="alert">
                  {selected.error}
                </div>
              </>
            ) : r ? (
              <>
                <div className="page-h">
                  <div className="eyebrow">{r.intent.name.replace(/_/g, " ")}</div>
                  <div className="title-row">
                    <h1>{caseTitle(r)}</h1>
                    <Conf c={r.answer.confidence} label="confidence" />
                  </div>
                  <p className="lede">{selected.query}</p>
                  <div className="facts-row">
                    <span>
                      <b>{mcpCalls}</b> MCP calls
                    </span>
                    <span>
                      <b>{r.citations.length}</b> sources
                    </span>
                    <span>
                      <b>{fmtMs(r.timings.total_ms)}</b>
                    </span>
                    <span>{r.answer.generator} generator</span>
                    <span className="mono">{r.trace_id}</span>
                  </div>
                </div>
                {r.warnings.length > 0 && (
                  <div className="callout callout-warn">
                    <strong>{r.answer.confidence === "high" ? "Notes" : "Degraded result"}</strong>
                    <ul>
                      {r.warnings.map((w) => (
                        <li key={w}>
                          <Markdown text={w} />
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {tab === "overview" && <SummaryPanel r={r} onCite={onCite} />}
                {tab === "evidence" && <Sources r={r} focus={focusCite} />}
                {tab === "trace" && <TracePanel r={r} />}
              </>
            ) : null}
          </div>
        </main>

        <ChatPanel
          runs={runs}
          selectedId={selectedId}
          busy={busy}
          onSend={run}
          onOpenReport={openReport}
          onCite={(runId, cite) => {
            setSelectedId(runId);
            onCite(cite);
          }}
        />
      </div>
    </div>
  );
}
