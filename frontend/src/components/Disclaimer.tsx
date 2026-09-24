import { ShieldAlert } from "lucide-react";

export default function Disclaimer({ text }: { text?: string }) {
  return (
    <div className="text-slate-600 dark:text-slate-400">
      <div className="mx-auto flex max-w-[1600px] items-start gap-2 px-4 pt-3 text-[11px]">
        <ShieldAlert className="mt-px h-3.5 w-3.5 shrink-0 text-[#ff9500]" />
        <p>
          <strong>Analytical aid only.</strong>{" "}
          {text?.replace(/^Analytical aid only\.\s*/, "") ??
            "Automated matches may be false positives or false negatives and must be verified by a qualified analyst."}
        </p>
      </div>
    </div>
  );
}
