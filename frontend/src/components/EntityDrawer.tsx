import { ArrowLeft, Search, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { usePresence } from "../lib/motion";
import type { Entity, Investigation } from "../types";
import EntityPanel from "./EntityPanel";

interface Props {
  investigation: Investigation;
  entityId: string | null;
  onClose: () => void;
  /** Starts a full investigation on this entity (its own network, lists, documents). */
  onInvestigate?: (entity: Entity) => void;
}

/** A person's or company's file, sliding in from the right; links inside it navigate within the drawer. */
export default function EntityDrawer({ investigation: inv, entityId, onClose, onInvestigate }: Props) {
  const { mounted, visible } = usePresence(entityId !== null);
  const [stack, setStack] = useState<string[]>([]);
  const last = useRef<string | null>(null);
  if (entityId) last.current = entityId;

  useEffect(() => setStack(entityId ? [entityId] : []), [entityId]);
  useEffect(() => {
    if (!entityId) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [entityId, onClose]);

  if (!mounted) return null;
  const current = stack[stack.length - 1] ?? last.current;
  const entity = inv.entities.find((e) => e.id === current);
  const canInvestigate =
    !!onInvestigate && !!entity && entity.type !== "address" && entity.id !== inv.subject_id && entity.record_ids.length > 0;

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label={entity?.name ?? "Entity"}>
      <div
        className={`absolute inset-0 bg-black/25 backdrop-blur-[2px] transition-opacity duration-300 ${visible ? "opacity-100" : "opacity-0"}`}
        onClick={onClose}
      />
      <aside
        className={`material absolute top-0 right-0 flex h-full w-[min(460px,100vw)] flex-col border-l border-black/[0.08] shadow-2xl transition-transform duration-[380ms] [transition-timing-function:var(--ease-fluid)] dark:border-white/[0.1] ${
          visible ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <div className="flex items-center gap-2 border-b border-black/[0.06] px-3 py-2 dark:border-white/[0.08]">
          {stack.length > 1 ? (
            <button className="btn-ghost px-2 py-1 text-xs" onClick={() => setStack((s) => s.slice(0, -1))}>
              <ArrowLeft className="h-3.5 w-3.5" /> Back
            </button>
          ) : (
            <span className="px-2 text-[11px] font-semibold tracking-wide text-slate-500 uppercase">File</span>
          )}
          {canInvestigate && (
            <button className="btn-primary ml-auto py-1 text-xs" onClick={() => onInvestigate!(entity!)}>
              <Search className="h-3.5 w-3.5" /> Investigate {entity!.type === "person" ? "this person" : entity!.type === "wallet" ? "this wallet" : "this company"}
            </button>
          )}
          <button className={`btn-ghost px-2 py-1 ${canInvestigate ? "" : "ml-auto"}`} onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div key={current} className="panel-enter min-h-0 flex-1">
          {current && <EntityPanel investigation={inv} entityId={current} onSelect={(id) => setStack((s) => [...s, id])} />}
        </div>
      </aside>
    </div>
  );
}
