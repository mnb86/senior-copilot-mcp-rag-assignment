import type { ReactElement } from "react";
import { parseBlocks, parseInline } from "../utils";

interface Props {
  text: string;
  onCite?: (id: string) => void;
}

/** Renders the copilot's limited Markdown as React nodes (no innerHTML => XSS-safe). */
export function Markdown({ text, onCite }: Props) {
  const blocks = parseBlocks(text);
  const nodes: ReactElement[] = [];
  let list: ReactElement[] = [];
  const flush = (key: string) => {
    if (list.length) nodes.push(<ul key={`ul-${key}`}>{list}</ul>);
    list = [];
  };
  blocks.forEach((b, i) => {
    const inline = parseInline(b.text).map((t, j) => {
      switch (t.kind) {
        case "bold":
          return <strong key={j}>{t.value}</strong>;
        case "italic":
          return <em key={j}>{t.value}</em>;
        case "code":
          return <code key={j}>{t.value}</code>;
        case "cite":
          return (
            <button key={j} type="button" className="cite" onClick={() => onCite?.(t.value)} title={`Open source ${t.value}`}>
              {t.value}
            </button>
          );
        default:
          return <span key={j}>{t.value}</span>;
      }
    });
    if (b.kind === "li") list.push(<li key={i}>{inline}</li>);
    else {
      flush(String(i));
      nodes.push(<p key={i}>{inline}</p>);
    }
  });
  flush("end");
  return <div className="md">{nodes}</div>;
}
