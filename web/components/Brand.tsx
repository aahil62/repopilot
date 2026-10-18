/** Three lines of code; the one that matters is highlighted. */
export function BrandMark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <rect x="2" y="4" width="14" height="2.6" rx="1.3" fill="currentColor" opacity="0.35" />
      <rect x="1" y="9.6" width="22" height="5.4" rx="1.2" fill="var(--mark)" />
      <rect x="2" y="11" width="17" height="2.6" rx="1.3" fill="#17202b" />
      <rect x="2" y="18" width="10" height="2.6" rx="1.3" fill="currentColor" opacity="0.35" />
    </svg>
  );
}

export function Brand() {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 9, fontWeight: 700, fontSize: 17, letterSpacing: "-0.01em" }}>
      <BrandMark />
      RepoPilot
    </span>
  );
}
