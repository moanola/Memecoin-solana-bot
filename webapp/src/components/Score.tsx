export function ScoreRing({ score, size = 42 }: { score: number; size?: number }) {
  const r = 16;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, score)) / 100;
  const color = score >= 72 ? "var(--gain)" : score >= 54 ? "var(--amber)" : "var(--loss)";
  return (
    <svg width={size} height={size} viewBox="0 0 42 42" aria-hidden>
      <circle cx="21" cy="21" r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="3" />
      <circle
        cx="21"
        cy="21"
        r={r}
        fill="none"
        stroke={color}
        strokeWidth="3"
        strokeLinecap="round"
        strokeDasharray={`${c * pct} ${c}`}
        transform="rotate(-90 21 21)"
      />
      <text x="21" y="23" textAnchor="middle" fontSize="11" fill="var(--text)" fontFamily="IBM Plex Mono, monospace">
        {Math.round(score)}
      </text>
    </svg>
  );
}
