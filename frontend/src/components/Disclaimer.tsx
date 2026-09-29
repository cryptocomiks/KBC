export default function Disclaimer({ text }: { text?: string }) {
  return (
    <div className="bg-slate-50 text-[#636366] dark:bg-[#0a0a0a] dark:text-[#86868b]">
      <p className="mx-auto max-w-[980px] px-4 py-2.5 text-center text-[12px] leading-snug">
        <span className="font-semibold text-[#1d1d1f] dark:text-[#f5f5f7]">Analytical aid only.</span>{" "}
        {text?.replace(/^Analytical aid only\.\s*/, "") ??
          "Automated matches may be false positives or false negatives and must be verified by a qualified analyst."}
      </p>
    </div>
  );
}
