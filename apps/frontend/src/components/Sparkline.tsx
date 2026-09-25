interface Props {
  series: { t: string; v: number }[];
  width?: number;
  height?: number;
}

export function Sparkline({ series, width = 260, height = 56 }: Props) {
  if (series.length < 2) return null;
  const max = Math.max(1, ...series.map((p) => p.v));
  const step = width / (series.length - 1);
  const pts = series.map((p, i) => `${(i * step).toFixed(1)},${(height - 4 - (p.v / max) * (height - 12)).toFixed(1)}`);
  const area = `0,${height} ${pts.join(" ")} ${width},${height}`;
  return (
    <svg className="spark" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Weekly alarm count trend">
      <polygon points={area} className="spark-area" />
      <polyline points={pts.join(" ")} className="spark-line" />
      {series.map((p, i) => (
        <circle key={p.t} cx={i * step} cy={height - 4 - (p.v / max) * (height - 12)} r={2.2} className="spark-dot">
          <title>{`${p.t}: ${p.v} alarms`}</title>
        </circle>
      ))}
    </svg>
  );
}
