/** A line with no axis: the shape of a series beside its figure. */
export function Spark({ values, color, className = "mt-auto h-6 w-full" }: { values: number[]; color: string; className?: string }) {
  if (values.length < 3) return null;
  const lo = Math.min(...values), hi = Math.max(...values);
  const span = hi - lo || 1;
  const line = values.map((v, i) => `${((i / (values.length - 1)) * 100).toFixed(2)},${(22 - ((v - lo) / span) * 20).toFixed(2)}`).join(" ");
  return (
    <svg viewBox="0 0 100 24" preserveAspectRatio="none" className={className} aria-hidden>
      <polyline points={line} fill="none" stroke={color} strokeWidth={1.5} vectorEffect="non-scaling-stroke" strokeLinejoin="round" opacity={0.85} />
    </svg>
  );
}
