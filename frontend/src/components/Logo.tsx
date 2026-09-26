/** KYC 1 CLICK monogram: K and 1 in a rounded square — the "1" in the brand colour. */
export default function Logo({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <rect x="1" y="1" width="30" height="30" rx="8" className="fill-[#0b0e11]" stroke="currentColor" strokeWidth="1.5" style={{ color: "var(--color-brand-500)" }} />
      <path d="M9.5 9v14M9.5 16.2 16 9M12.2 13.3 16.4 23" fill="none" stroke="#eef2f4" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M20.2 11.6 23.4 9v14" fill="none" stroke="var(--color-brand-500)" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
