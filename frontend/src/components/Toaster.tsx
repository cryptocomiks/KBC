import { AlertCircle, CheckCircle2, Info } from "lucide-react";
import { useEffect, useState } from "react";
import type { ToastItem } from "../lib/toast";

const ICON = { success: CheckCircle2, info: Info, error: AlertCircle };
const TONE = { success: "text-[#34c759]", info: "text-brand-500 dark:text-[#2997ff]", error: "text-[#ff3b30]" };

/** Notifications in a glass pill at the bottom of the screen (Apple HUD style). */
export default function Toaster() {
  const [items, setItems] = useState<(ToastItem & { leaving?: boolean })[]>([]);
  useEffect(() => {
    const onToast = (e: Event) => {
      const t = (e as CustomEvent<ToastItem>).detail;
      setItems((list) => [...list.slice(-2), t]);
      setTimeout(() => setItems((list) => list.map((x) => (x.id === t.id ? { ...x, leaving: true } : x))), 3200);
      setTimeout(() => setItems((list) => list.filter((x) => x.id !== t.id)), 3600);
    };
    window.addEventListener("kbc-toast", onToast);
    return () => window.removeEventListener("kbc-toast", onToast);
  }, []);
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-6 z-[60] flex flex-col items-center gap-2 px-4" aria-live="polite" role="status">
      {items.map((t) => {
        const Icon = ICON[t.kind];
        return (
          <div key={t.id} className={`toast glass-panel pointer-events-auto flex items-center gap-2.5 rounded-full px-5 py-3 text-[14px] font-medium ${t.leaving ? "toast-out" : ""}`}>
            <Icon className={`h-[18px] w-[18px] ${TONE[t.kind]}`} />
            {t.text}
          </div>
        );
      })}
    </div>
  );
}
