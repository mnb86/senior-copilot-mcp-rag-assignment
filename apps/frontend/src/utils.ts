// Pure helpers (unit-tested in utils.test.ts).

export type Inline =
  | { kind: "text"; value: string }
  | { kind: "bold"; value: string }
  | { kind: "italic"; value: string }
  | { kind: "code"; value: string }
  | { kind: "cite"; value: string };

/** Tokenise one line of the copilot's limited Markdown dialect. Never produces HTML (XSS-safe). */
export function parseInline(line: string): Inline[] {
  const out: Inline[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\[S\d+\]|_[^_]+_)/g;
  let last = 0;
  for (const m of line.matchAll(re)) {
    const idx = m.index ?? 0;
    if (idx > last) out.push({ kind: "text", value: line.slice(last, idx) });
    const tok = m[0];
    if (tok.startsWith("**")) out.push({ kind: "bold", value: tok.slice(2, -2) });
    else if (tok.startsWith("`")) out.push({ kind: "code", value: tok.slice(1, -1) });
    else if (tok.startsWith("[S")) out.push({ kind: "cite", value: tok.slice(1, -1) });
    else out.push({ kind: "italic", value: tok.slice(1, -1) });
    last = idx + tok.length;
  }
  if (last < line.length) out.push({ kind: "text", value: line.slice(last) });
  return out;
}

export interface Block {
  kind: "p" | "li";
  text: string;
}

export function parseBlocks(md: string): Block[] {
  return md
    .split("\n")
    .map((l) => l.trimEnd())
    .filter((l) => l.trim().length > 0)
    .map((l) => (/^\s*[-*]\s+/.test(l) ? { kind: "li", text: l.replace(/^\s*[-*]\s+/, "") } : { kind: "p", text: l }));
}

/**
 * Split an answer into its summary lines and the detailed sections that follow (from the first
 * bold-only heading line). Answers that open with a heading are returned whole.
 */
export function splitAnswer(md: string): [string, string] {
  const lines = md.split("\n");
  const idx = lines.findIndex((l, i) => i > 0 && /^\*\*[^*]+\*\*:?\s*$/.test(l.trim()));
  if (idx <= 0) return [md, ""];
  return [lines.slice(0, idx).join("\n").trim(), lines.slice(idx).join("\n").trim()];
}

export function fmtMs(ms: number | undefined | null): string {
  if (ms === undefined || ms === null) return "-";
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)} s` : `${Math.round(ms)} ms`;
}

export function fmtPct(v: number | null | undefined): string {
  return typeof v === "number" ? `${Math.round(v * 100)}%` : "n/a";
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toISOString().replace("T", " ").slice(0, 16) + "Z";
}

export function groupByWave<T extends { wave: number }>(rows: T[]): [number, T[]][] {
  const m = new Map<number, T[]>();
  for (const r of rows) m.set(r.wave, [...(m.get(r.wave) ?? []), r]);
  return [...m.entries()].sort((a, b) => a[0] - b[0]);
}

export interface Scenario {
  title: string;
  scope: string;
  query: string;
}

/** Saved investigation scenarios shown in the sidebar (follow-ups reuse the current case context). */
export const SCENARIOS: Scenario[] = [
  {
    title: "Recurring high-severity alarms",
    scope: "Boiler Feed Pump 101 · 90 days",
    query:
      "Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last 90 days, identify likely contributing factors, retrieve the relevant operating procedure, and provide recommended actions with source evidence.",
  },
  {
    title: "Active critical alarms",
    scope: "Boiler Feed Pump 102",
    query: "Show active critical alarms for Boiler Feed Pump 102 and recommend immediate actions.",
  },
  {
    title: "Repeated discharge-pressure alarms",
    scope: "Compressors",
    query: "Why are compressor discharge pressure alarms repeatedly occurring?",
  },
  {
    title: "Highest-priority alarm",
    scope: "EastRefinery",
    query: "Which alarm has the highest priority in EastRefinery, and why?",
  },
  {
    title: "Assets to inspect after a motor trip",
    scope: "Motors",
    query: "What related assets should be inspected for this motor trip alarm?",
  },
  {
    title: "Applicable operating procedure",
    scope: "Follow-up on current case",
    query: "Which operating procedure applies to this alarm?",
  },
  {
    title: "API actions vs maintenance manual",
    scope: "Follow-up on current case",
    query: "Are the API recommendations consistent with the maintenance manual?",
  },
  {
    title: "Degraded source (engine outage)",
    scope: "Cooling Water Pump 301",
    query: "Investigate alarms for Cooling Water Pump 301",
  },
];
