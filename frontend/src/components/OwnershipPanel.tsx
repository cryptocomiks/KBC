import { AlertOctagon, Check, ChevronRight, Copy, Crown, HelpCircle, Info, Layers, ShieldAlert, UserCheck, UserX } from "lucide-react";
import { useState } from "react";
import { toast } from "../lib/toast";
import type { Investigation, OwnershipAnalysis, OwnershipOwner, OwnershipRoute } from "../types";
import { Meter, Tile, type Tone } from "./viz";

const pct = (v: number | null | undefined) => (v == null ? "-" : `${Number(v.toFixed(2))} %`);

const STATUS: Record<OwnershipOwner["status"], { label: string; tone: string }> = {
  ubo_both: { label: "UBO · declared", tone: "bg-[#248a3d]/10 text-[#248a3d] dark:text-[#30d158]" },
  ubo_ownership: { label: "UBO · not declared", tone: "bg-[#d70015]/10 text-[#d70015] dark:text-[#ff453a]" },
  ubo_declared: { label: "Declared UBO", tone: "bg-brand-500/10 text-brand-600 dark:text-[#2997ff]" },
  below_threshold: { label: "Below threshold", tone: "bg-slate-500/10 text-slate-600 dark:text-slate-300" },
  dead_end: { label: "Chain stops here", tone: "bg-amber-500/15 text-amber-800 dark:text-amber-300" },
};

function Badge({ className, children }: { className: string; children: React.ReactNode }) {
  return <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${className}`}>{children}</span>;
}

function RouteLine({ route, onSelect }: { route: OwnershipRoute; onSelect: (id: string) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-x-1 gap-y-1 text-[12px]">
      {route.names.map((n, i) => (
        <span key={route.ids[i]} className="inline-flex items-center gap-1">
          <button onClick={() => onSelect(route.ids[i])} className="rounded-md bg-black/[0.04] px-1.5 py-0.5 hover:bg-black/[0.08] dark:bg-white/[0.06] dark:hover:bg-white/[0.12]">
            {n}
          </button>
          {i < route.pcts.length && (
            <span className="inline-flex items-center text-slate-400">
              <ChevronRight className="h-3 w-3" />
              <span className="font-semibold text-slate-600 tabular-nums dark:text-slate-300">{route.pcts[i] == null ? "?" : `${route.pcts[i]} %`}</span>
              <ChevronRight className="h-3 w-3" />
            </span>
          )}
        </span>
      ))}
      <span className="ml-1 text-slate-500">= {route.effective == null ? "unknown (a percentage is missing)" : pct(route.effective)}</span>
    </div>
  );
}

function OwnerCard({ o, threshold, onSelect }: { o: OwnershipOwner; threshold: number; onSelect: (id: string) => void }) {
  const [open, setOpen] = useState(o.routes.length <= 2);
  const st = STATUS[o.status];
  const gap = o.declared && o.declared_pct != null && o.effective_pct != null && Math.abs(o.declared_pct - o.effective_pct) >= 5;
  return (
    <li className="px-5 py-4">
      <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <button onClick={() => onSelect(o.id)} className="text-[15px] font-semibold hover:text-brand-600">
              {o.name}
            </button>
            <Badge className={st.tone}>{st.label}</Badge>
            {o.sanctioned && (
              <Badge className="bg-[#d70015] text-white">
                <ShieldAlert className="h-3 w-3" /> Sanctions list
              </Badge>
            )}
            {o.pep && <Badge className="bg-violet-500/15 text-violet-700 dark:text-violet-300">PEP</Badge>}
            {!o.natural_person && <Badge className="bg-slate-500/10 text-slate-600 dark:text-slate-300">{o.type}</Badge>}
          </div>
          <div className="mt-1 text-[12px] text-slate-500">
            {o.layers === 0 ? "Direct holding" : `${o.layers} intermediate compan${o.layers > 1 ? "ies" : "y"}`}
            {o.countries.length > 0 && ` · through ${o.countries.join(" → ")}`}
            {o.roles.length > 0 && ` · also ${o.roles.join(", ")}`}
          </div>
        </div>
        <div className="w-full sm:w-56">
          <div className="flex items-baseline justify-between">
            <span className="text-[11px] text-slate-500">Effective interest</span>
            <span className="text-[20px] font-semibold tracking-tight tabular-nums">{pct(o.effective_pct)}</span>
          </div>
          <div className="relative mt-1">
            <Meter value={o.effective_pct ?? 0} max={100} tone={(o.effective_pct ?? 0) >= threshold ? "accent" : "neutral"} />
            <span className="absolute -top-1 h-[14px] w-px bg-slate-500/70" style={{ left: `${threshold}%` }} title={`Threshold ${threshold} %`} />
          </div>
          <div className="mt-1 flex justify-between text-[11px] text-slate-500">
            <span>direct {pct(o.direct_pct)}</span>
            <span>declared {o.declared ? pct(o.declared_pct) : "no"}</span>
          </div>
        </div>
      </div>
      {gap && (
        <p className="mt-2 flex items-start gap-1.5 text-[12px] text-amber-700 dark:text-amber-300">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" /> Declared {pct(o.declared_pct)} vs computed {pct(o.effective_pct)}: options, voting rights, a nominee or an outdated declaration?
        </p>
      )}
      {o.partly_unknown && <p className="mt-1 text-[12px] text-slate-500">One route has no published percentage: the effective interest may be higher.</p>}
      {o.routes.length > 0 && (
        <div className="mt-2">
          <button onClick={() => setOpen(!open)} className="text-[12px] font-medium text-brand-600 hover:underline">
            {open ? "Hide" : "Show"} {o.routes.length} ownership route{o.routes.length > 1 ? "s" : ""}
          </button>
          {open && (
            <div className="mt-1.5 space-y-1.5">
              {o.routes.map((r) => (
                <RouteLine key={r.ids.join(">")} route={r} onSelect={onSelect} />
              ))}
            </div>
          )}
        </div>
      )}
    </li>
  );
}

/** "Who really owns this, how sure are we, and what do we still need to ask?" */
export default function OwnershipPanel({ investigation: inv, onSelect }: { investigation: Investigation; onSelect: (id: string) => void }) {
  const a: OwnershipAnalysis | null | undefined = inv.ownership;
  if (!a) {
    return <div className="card p-6 text-sm text-slate-500">Run the investigation again to compute the beneficial ownership analysis.</div>;
  }
  const subject = inv.entities.find((e) => e.id === inv.subject_id);
  const ubos = a.owners.filter((o) => o.status.startsWith("ubo"));
  const blockedSubject = a.sanctions.find((s) => s.id === a.subject_id && s.blocked);
  const blocked = a.sanctions.filter((s) => s.blocked);
  const exposure = a.sanctions.filter((s) => !s.blocked);
  const enhanced = a.threshold_applied < a.threshold;
  const sanctionsTone: Tone = blocked.length ? "critical" : exposure.length ? "serious" : "good";

  const copy = async () => {
    const text = [`Questions for ${subject?.name ?? "the client"}:`, ...a.questions.map((q, i) => `${i + 1}. ${q}`)].join("\n");
    await navigator.clipboard?.writeText(text).catch(() => undefined);
    toast("Questions copied");
  };

  if (!a.subject_is_company) {
    return (
      <div className="panel-enter space-y-4">
        <section className="card overflow-hidden">
          <header className="px-5 pt-5">
            <h2 className="text-[19px] font-semibold tracking-[-0.02em]">What {subject?.name} owns</h2>
            <p className="text-[13px] text-slate-500">Direct and indirect interests (product of the percentages along each route, summed over routes).</p>
          </header>
          <ul className="mt-3 divide-y divide-slate-200/70 dark:divide-white/[0.06]">
            {a.holdings.length === 0 && <li className="px-5 py-4 text-sm text-slate-500">No shareholding found in the sources consulted.</li>}
            {a.holdings.map((h) => (
              <li key={h.id} className="grid items-center gap-3 px-5 py-3 sm:grid-cols-[1fr_200px_80px]">
                <button onClick={() => onSelect(h.id)} className="text-left">
                  <div className="text-[14px] font-medium hover:text-brand-600">{h.name}</div>
                  <div className="text-[12px] text-slate-500">
                    {h.jurisdiction ?? "?"} · {h.direct ? "direct" : `${h.layers} intermediate compan${h.layers > 1 ? "ies" : "y"}`}
                  </div>
                </button>
                <Meter value={h.effective_pct ?? 0} max={100} />
                <div className="text-right text-[14px] font-semibold tabular-nums">{pct(h.effective_pct)}</div>
              </li>
            ))}
          </ul>
        </section>
        <SanctionsSection a={a} onSelect={onSelect} />
        <ActionsSection actions={a.actions} />
      </div>
    );
  }

  return (
    <div className="panel-enter space-y-4">
      {blockedSubject && (
        <div className="flex items-start gap-3 rounded-2xl bg-[#d70015] px-5 py-4 text-white">
          <AlertOctagon className="mt-0.5 h-5 w-5 shrink-0" />
          <div className="text-[14px]">
            <b>Blocked by ownership.</b> {subject?.name} is owned {pct(blockedSubject.aggregate_pct)} in aggregate by sanctioned persons (OFAC 50 % rule; EU ownership
            criterion). No funds or economic resources may be made available to it: escalate to sanctions compliance.
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile
          label="Traced to natural persons"
          value={pct(a.traced_pct)}
          sub="share of the capital explained"
          tone={(a.traced_pct ?? 0) >= 75 ? "good" : (a.traced_pct ?? 0) >= 25 ? "warning" : "serious"}
          meter={{ value: a.traced_pct ?? 0, max: 100, tone: (a.traced_pct ?? 0) >= 75 ? "good" : "warning" }}
        />
        <Tile
          label="Beneficial owners"
          value={ubos.length}
          sub={`threshold ${a.threshold_applied} %${enhanced ? " (enhanced: high risk)" : ""}`}
          tone={ubos.some((o) => o.status === "ubo_ownership") ? "serious" : ubos.length ? "good" : "warning"}
        />
        <Tile label="Unexplained capital" value={pct(a.unexplained_pct)} sub={a.depth_limited ? `partly beyond the search depth (${a.max_depth})` : "not traced to a person"} tone={(a.unexplained_pct ?? 0) > 25 ? "warning" : "neutral"} />
        <Tile
          label="Sanctions by ownership"
          value={blocked.length ? "Blocked" : exposure.length ? "Exposure" : "None"}
          sub={blocked.length ? `${blocked.length} entit${blocked.length > 1 ? "ies" : "y"} ≥ 50 %` : exposure.length ? "minority owner or officer" : "OFAC 50 % rule · EU control"}
          tone={sanctionsTone}
        />
      </div>

      {a.smo_reason && (
        <section className="card flex items-start gap-3 p-5">
          <UserX className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
          <div>
            <h3 className="text-[15px] font-semibold">No beneficial owner by ownership: senior managing official</h3>
            <p className="mt-1 text-[13px] text-slate-600 dark:text-slate-300">{a.smo_reason}</p>
            {a.smo.length > 0 ? (
              <ul className="mt-2 flex flex-wrap gap-2">
                {a.smo.map((s) => (
                  <li key={s.id}>
                    <button onClick={() => onSelect(s.id)} className="rounded-full bg-black/[0.05] px-3 py-1 text-[12px] hover:bg-black/[0.08] dark:bg-white/[0.08]">
                      <b>{s.name}</b> · {s.role}
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-[12px] text-slate-500">No senior manager found in the sources: ask the client for the list of directors.</p>
            )}
          </div>
        </section>
      )}

      <section className="card overflow-hidden">
        <header className="flex flex-wrap items-end gap-2 px-5 pt-5">
          <div className="mr-auto">
            <h2 className="flex items-center gap-2 text-[19px] font-semibold tracking-[-0.02em]">
              <Crown className="h-4 w-4 text-amber-500" /> Who owns {subject?.name}
            </h2>
            <p className="text-[13px] text-slate-500">
              Effective interest = product of the percentages along each route, summed over all routes. Threshold {a.threshold} % (EU AMLD), {a.enhanced_threshold} % applied
              when the case is high or critical risk. The vertical mark on each bar is the threshold applied.
            </p>
          </div>
        </header>
        <ul className="mt-2 divide-y divide-slate-200/70 dark:divide-white/[0.06]">
          {a.owners.length === 0 && <li className="px-5 py-4 text-sm text-slate-500">No owner found above the subject in the sources consulted.</li>}
          {a.owners.map((o) => (
            <OwnerCard key={o.id} o={o} threshold={a.threshold_applied} onSelect={onSelect} />
          ))}
        </ul>
      </section>

      <section className="card overflow-hidden">
        <header className="px-5 pt-5">
          <h2 className="flex items-center gap-2 text-[19px] font-semibold tracking-[-0.02em]">
            <Layers className="h-4 w-4 text-slate-400" /> Ownership coverage, level by level
          </h2>
          <p className="text-[13px] text-slate-500">Share capital of each company in the chain accounted for by the shareholders identified: where the chain goes dark.</p>
        </header>
        <ul className="mt-3 divide-y divide-slate-200/70 dark:divide-white/[0.06]">
          {a.coverage.map((c) => (
            <li key={c.id} className="grid items-center gap-3 px-5 py-3 sm:grid-cols-[minmax(0,1fr)_220px_110px]">
              <div className="min-w-0">
                <button onClick={() => onSelect(c.id)} className="text-left text-[14px] font-medium hover:text-brand-600">
                  {c.name}
                </button>
                <div className="text-[12px] text-slate-500">
                  {c.jurisdiction ?? "?"}
                  {c.offshore && " · offshore"} · {c.holders} shareholder{c.holders === 1 ? "" : "s"} known
                  {c.holders_without_pct > 0 && ` (${c.holders_without_pct} without %)`}
                </div>
                {c.reason && (
                  <div className={`mt-0.5 text-[12px] ${c.depth_limited ? "text-slate-500" : "text-amber-700 dark:text-amber-300"}`}>
                    {c.dead_end && !c.depth_limited ? "Dead end: " : ""}
                    {c.reason}
                  </div>
                )}
              </div>
              <Meter value={c.identified_pct} max={100} tone={c.identified_pct >= 99.5 ? "good" : c.depth_limited ? "neutral" : "warning"} />
              <div className="text-right text-[13px] tabular-nums">
                <b>{pct(c.identified_pct)}</b>
                {c.unexplained_pct > 0 && <div className="text-[11px] text-slate-500">{pct(c.unexplained_pct)} unknown</div>}
              </div>
            </li>
          ))}
        </ul>
      </section>

      <SanctionsSection a={a} onSelect={onSelect} />

      <ActionsSection actions={a.actions} />

      <section className="card overflow-hidden">
        <header className="flex flex-wrap items-center gap-2 px-5 pt-5">
          <h2 className="mr-auto flex items-center gap-2 text-[19px] font-semibold tracking-[-0.02em]">
            <HelpCircle className="h-4 w-4 text-brand-500" /> Questions for the client
          </h2>
          {a.questions.length > 0 && (
            <button onClick={copy} className="btn-outline h-8 text-xs">
              <Copy className="h-3.5 w-3.5" /> Copy all
            </button>
          )}
        </header>
        {a.questions.length === 0 ? (
          <p className="flex items-center gap-2 px-5 py-4 text-sm text-slate-500">
            <Check className="h-4 w-4 text-[#248a3d]" /> The ownership is fully explained by the sources: nothing to ask on this point.
          </p>
        ) : (
          <ol className="mt-3 list-decimal space-y-2 px-5 pb-5 pl-10 text-[14px] marker:text-slate-400">
            {a.questions.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ol>
        )}
        {a.depth_limited && (
          <p className="border-t border-slate-200/70 px-5 py-3 text-[12px] text-slate-500 dark:border-white/[0.06]">
            Part of the chain lies at the edge of the search (depth {a.max_depth}): run a deeper investigation before asking the client about those levels.
          </p>
        )}
      </section>
    </div>
  );
}

function ActionsSection({ actions }: { actions?: string[] }) {
  if (!actions?.length) return null;
  return (
    <section className="card overflow-hidden border-l-4 border-l-[#d70015]">
      <header className="px-5 pt-5">
        <h2 className="flex items-center gap-2 text-[19px] font-semibold tracking-[-0.02em]">
          <AlertOctagon className="h-4 w-4 text-[#d70015]" /> Internal actions
        </h2>
        <p className="text-[13px] text-slate-500">For the compliance team only: never share with the client (tipping-off).</p>
      </header>
      <ul className="mt-3 space-y-2 px-5 pb-5 text-[14px]">
        {actions.map((x) => (
          <li key={x} className="flex items-start gap-2">
            <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-[#d70015]" />
            {x}
          </li>
        ))}
      </ul>
    </section>
  );
}

function SanctionsSection({ a, onSelect }: { a: OwnershipAnalysis; onSelect: (id: string) => void }) {
  return (
    <section className="card overflow-hidden">
      <header className="px-5 pt-5">
        <h2 className="flex items-center gap-2 text-[19px] font-semibold tracking-[-0.02em]">
          <ShieldAlert className="h-4 w-4 text-[#d70015]" /> Sanctions by ownership and control
        </h2>
        <p className="text-[13px] text-slate-500">
          OFAC 50 % rule and EU ownership criterion: holdings of sanctioned persons are added up; an entity owned 50 % or more is blocked, and so are the entities it owns 50 % or
          more. A sanctioned person on the board is flagged for the EU control test.
        </p>
      </header>
      {a.sanctions.length === 0 ? (
        <p className="flex items-center gap-2 px-5 py-4 text-sm text-slate-500">
          <UserCheck className="h-4 w-4 text-[#248a3d]" /> No entity in the network is owned or run by a person on a sanctions list (confirmed matches only).
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-slate-200/70 dark:divide-white/[0.06]">
          {a.sanctions.map((s) => (
            <li key={s.id} className="grid items-center gap-3 px-5 py-3 sm:grid-cols-[minmax(0,1fr)_200px_110px]">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <button onClick={() => onSelect(s.id)} className="text-left text-[14px] font-medium hover:text-brand-600">
                    {s.name}
                  </button>
                  {s.blocked ? <Badge className="bg-[#d70015] text-white">Blocked (≥ 50 %)</Badge> : <Badge className="bg-amber-500/15 text-amber-800 dark:text-amber-300">Exposure</Badge>}
                </div>
                <div className="text-[12px] text-slate-500">
                  {s.owners.map((o) => `${o.name}${o.listed ? "" : " (blocked by ownership)"} ${pct(o.pct)}`).join(" · ")}
                  {s.control.length > 0 && `${s.owners.length ? " · " : ""}sanctioned officer: ${s.control.join(", ")}`}
                </div>
              </div>
              <div className="relative">
                <Meter value={s.aggregate_pct} max={100} tone={s.blocked ? "critical" : "serious"} />
                <span className="absolute -top-1 left-1/2 h-[14px] w-px bg-slate-500/70" title="50 %" />
              </div>
              <div className="text-right text-[14px] font-semibold tabular-nums">{pct(s.aggregate_pct)}</div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
