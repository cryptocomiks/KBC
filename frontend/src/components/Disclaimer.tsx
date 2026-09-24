import { ShieldAlert } from "lucide-react";

export default function Disclaimer({ text }: { text?: string }) {
  return (
    <div className="border-b border-orange-200 bg-orange-50 text-orange-900 dark:border-orange-900/50 dark:bg-orange-950/40 dark:text-orange-200">
      <div className="mx-auto flex max-w-[1600px] items-start gap-2 px-4 py-2 text-xs">
        <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
        <p>
          <strong>Analytical aid only.</strong>{" "}
          {text?.replace(/^Analytical aid only\.\s*/, "") ??
            "Automated matches may be false positives or false negatives and must be verified by a qualified analyst."}
        </p>
      </div>
    </div>
  );
}
