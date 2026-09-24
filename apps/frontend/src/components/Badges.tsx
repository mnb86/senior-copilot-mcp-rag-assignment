export function Sev({ s }: { s: string }) {
  return <span className={`badge sev-${s}`}>{s}</span>;
}

export function Conf({ c, label }: { c: string; label?: string }) {
  return <span className={`badge conf-${c}`}>{label ? `${label}: ` : ""}{c}</span>;
}

const REC_LABEL: Record<string, string> = {
  consistent: "consistent",
  conflict: "conflict",
  not_covered: "not covered",
  document_guidance: "procedure",
};

export function RecStatus({ s }: { s: string }) {
  return <span className={`badge rec-${s}`}>{REC_LABEL[s] ?? s}</span>;
}

export function StepStatus({ s }: { s: string }) {
  return <span className={`badge step-${s}`}>{s}</span>;
}
