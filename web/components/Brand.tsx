/** A contour line rising to a peak: the riskiest point in your history, marked. */
export function BrandMark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M3 18 9 9l4 5 3-4 5 8" stroke="var(--accent)" strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx="9" cy="9" r="1.7" fill="var(--accent)" />
    </svg>
  );
}

export function Brand() {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 9, fontFamily: "var(--display)", fontWeight: 600, fontSize: 17, letterSpacing: "-0.01em" }}>
      <BrandMark />
      RepoPilot
    </span>
  );
}
