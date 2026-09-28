/** KYC 1 CLICK monogram: K and 1 in a rounded square, monochrome like Apple's marks: the "1" in blue. */
export default function Logo({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <rect x="1" y="1" width="30" height="30" rx="8.5" className="fill-[#1d1d1f] dark:fill-[#f5f5f7]" />
      <path d="M9.5 9v14M9.5 16.2 16 9M12.2 13.3 16.4 23" fill="none" className="stroke-white dark:stroke-[#1d1d1f]" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M20.2 11.6 23.4 9v14" fill="none" className="stroke-[#2997ff]" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
