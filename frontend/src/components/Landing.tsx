import {
  ArrowRight,
  BadgeCheck,
  Building2,
  ClipboardCheck,
  FileText,
  Fingerprint,
  Gauge,
  Globe2,
  Lock,
  Network,
  Newspaper,
  Scale,
  Search,
  ShieldAlert,
  Users,
} from "lucide-react";
import type { ReactNode } from "react";
import type { ConnectorStatus } from "../types";
import DemoVideos from "./DemoVideos";

interface Props {
  /** The search form, shown in the hero: the tool starts right here. */
  search: ReactNode;
  connectors?: ConnectorStatus[];
  onCases: () => void;
}

const STEPS = [
  {
    Icon: Search,
    title: "Search",
    text: "A company, a person, an identifier (SIREN, LEI, Swiss UID, UK number, CIK) or a crypto address. Homonyms are shown side by side with dates of birth and linked companies, so you pick the right one.",
  },
  {
    Icon: Network,
    title: "Map",
    text: "Registers are read in every country reached: officers, shareholders, beneficial owners, parent companies — up to three levels, with effective ownership computed through every layer.",
  },
  {
    Icon: ShieldAlert,
    title: "Screen",
    text: "Every company and person of the network is checked against sanctions, PEP, law-enforcement and regulator lists, offshore leaks, courts and the press. Each hit is triaged: likely match, to check, or namesake.",
  },
  {
    Icon: ClipboardCheck,
    title: "Decide & document",
    text: "An explained risk score, the documents to request, the KYC questionnaire and vigilance level, a checklist, four-eyes validation, a PDF report and daily monitoring of the case.",
  },
];

const WHAT = [
  {
    Icon: Fingerprint,
    title: "Know your client",
    text: "Identity and status from the official register, legal form, address, capital, filings and legal notices — with the source of every fact.",
  },
  {
    Icon: Users,
    title: "Who is really behind",
    text: "Ultimate beneficial owners over 25 %, compared with the owners the client declared. Circular holdings, long chains and nominees are flagged.",
  },
  {
    Icon: Globe2,
    title: "Where the risk is",
    text: "Countries of the network against FATF, EU and offshore lists, the Basel AML Index and corruption indicators.",
  },
  {
    Icon: Gauge,
    title: "Why it scores that way",
    text: "No black box: each point of the score comes from a named factor, its weight and its distance to the client.",
  },
];

const CATEGORY: Record<string, { label: string; Icon: typeof Building2 }> = {
  registry: { label: "Company registers", Icon: Building2 },
  screening: { label: "Sanctions, PEP & watchlists", Icon: ShieldAlert },
  leaks: { label: "Leaks & investigations", Icon: Newspaper },
  documents: { label: "Courts, regulators, filings", Icon: Scale },
  chain: { label: "Blockchains", Icon: Network },
  media: { label: "Press", Icon: Newspaper },
  archive: { label: "Websites & archives", Icon: Globe2 },
};
const WATCHLISTS = 297; // 120 core + 172 extended bulk lists + OFAC SDN + UN + 3 crypto address lists

function Section({ tag, title, children }: { tag: string; title: string; children: ReactNode }) {
  return (
    <section className="mx-auto max-w-6xl px-1">
      <div className="tag">{tag}</div>
      <h2 className="mt-2 mb-6 text-[26px] font-semibold tracking-tight text-slate-900 dark:text-white">{title}</h2>
      {children}
    </section>
  );
}

/** Home: what the tool does, how it works, its sources and limits — with the search right in the hero. */
export default function Landing({ search, connectors, onCases }: Props) {
  const live = (connectors ?? []).filter((c) => !c.demo);
  const byKind = new Map<string, ConnectorStatus[]>();
  for (const c of live) byKind.set(c.kind, [...(byKind.get(c.kind) ?? []), c]);
  const enabled = live.filter((c) => c.enabled).length;

  return (
    <div className="space-y-20 pb-10">
      {/* Hero */}
      <div className="mx-auto max-w-5xl pt-12 text-center">
        <div className="chip mx-auto mb-6">
          <BadgeCheck className="h-4 w-4 text-brand-600 dark:text-brand-500" />
          Public & official sources only · every fact sourced
        </div>
        <h1 className="display text-[clamp(2.1rem,4.6vw,3.4rem)]">
          Due diligence on any company,
          <br />
          <span className="text-glow">in one click.</span>
        </h1>
        <p className="mx-auto mt-5 max-w-2xl text-[16px] leading-relaxed text-slate-600 dark:text-slate-400">
          KYC 1 CLICK maps who owns and runs a company, screens every party against sanctions, PEP and watchlists, and
          prepares the KYC file: risk score, documents to request, vigilance level and report.
        </p>
        <div className="mx-auto mt-8 max-w-5xl text-left">{search}</div>
      </div>

      {/* Demo videos */}
      <Section tag="See it in action" title="From a name to a decision, in 90 seconds">
        <DemoVideos />
      </Section>

      {/* How it works */}
      <Section tag="How it works" title="From a name to a documented decision">
        <ol className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {STEPS.map((s, i) => (
            <li key={s.title} className="card relative p-5">
              <div className="flex items-center gap-3">
                <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-500/10 text-brand-700 ring-1 ring-brand-500/25 dark:text-brand-300">
                  <s.Icon className="h-[18px] w-[18px]" />
                </span>
                <span className="font-mono text-[11px] text-slate-400">0{i + 1}</span>
              </div>
              <h3 className="mt-4 text-[15px] font-semibold">{s.title}</h3>
              <p className="mt-1.5 text-[13px] leading-relaxed text-slate-600 dark:text-slate-400">{s.text}</p>
            </li>
          ))}
        </ol>
      </Section>

      {/* What you get */}
      <Section tag="What you get" title="The answers a compliance officer needs">
        <div className="grid gap-4 sm:grid-cols-2">
          {WHAT.map((w) => (
            <div key={w.title} className="card flex gap-4 p-5">
              <w.Icon className="mt-0.5 h-5 w-5 shrink-0 text-brand-600 dark:text-brand-500" />
              <div>
                <h3 className="text-[15px] font-semibold">{w.title}</h3>
                <p className="mt-1 text-[13px] leading-relaxed text-slate-600 dark:text-slate-400">{w.text}</p>
              </div>
            </div>
          ))}
        </div>
      </Section>

      {/* Sources */}
      <Section tag="Sources" title={`${live.length || 40} public sources and ${WATCHLISTS} watchlists, queried live`}>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {[...byKind.entries()]
            .sort((a, b) => b[1].length - a[1].length)
            .map(([kind, list]) => {
              const cat = CATEGORY[kind] ?? { label: kind, Icon: FileText };
              return (
                <div key={kind} className="card p-5">
                  <div className="flex items-center gap-2">
                    <cat.Icon className="h-4 w-4 text-brand-600 dark:text-brand-500" />
                    <h3 className="text-[14px] font-semibold">{cat.label}</h3>
                    <span className="ml-auto font-mono text-[11px] text-slate-500">{list.length}</span>
                  </div>
                  <ul className="mt-3 space-y-1.5">
                    {list.slice(0, 7).map((c) => (
                      <li key={c.name} className="flex items-start gap-2 text-[12.5px] leading-snug text-slate-600 dark:text-slate-400">
                        <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${c.enabled ? "bg-brand-500" : "bg-slate-400"}`} />
                        <span>
                          {c.label}
                          {!c.enabled && c.message.startsWith("Offline") && <span className="ml-1 text-amber-600">(offline)</span>}
                        </span>
                      </li>
                    ))}
                    {list.length > 7 && <li className="text-[12px] text-slate-500">+ {list.length - 7} more</li>}
                  </ul>
                </div>
              );
            })}
        </div>
        <p className="mt-4 text-[12px] text-slate-500">
          {enabled > 0 && `${enabled} sources active on this server. `}The full list, with the status of each source, is under{" "}
          <b>Sources</b> in the top bar. Watchlists include the EU, UN, US (OFAC), UK, Swiss, French and Monaco asset freezes, regulators'
          enforcement actions and warnings, and law-enforcement notices.
        </p>
      </Section>

      {/* Method, limits & privacy */}
      <Section tag="Method & limits" title="An analytical aid, not a verdict">
        <div className="grid gap-4 md:grid-cols-3">
          {[
            {
              Icon: Scale,
              title: "Human decision",
              text: "Name matches can be false positives or negatives. Every hit shows why it matched (date of birth, nationality, identifiers) and must be confirmed by an analyst, whose decision is kept in the audit trail.",
            },
            {
              Icon: FileText,
              title: "Traceable",
              text: "Each entity, link and hit carries its source, record id, link and retrieval date. Reports list the sources consulted and the methodology.",
            },
            {
              Icon: Lock,
              title: "Privacy by design",
              text: "Public and lawfully accessible sources only; private individuals are never profiled beyond their role in a company. Client documents are read in memory and never stored. Cases are password-protected.",
            },
          ].map((m) => (
            <div key={m.title} className="card p-5">
              <m.Icon className="h-5 w-5 text-brand-600 dark:text-brand-500" />
              <h3 className="mt-3 text-[15px] font-semibold">{m.title}</h3>
              <p className="mt-1.5 text-[13px] leading-relaxed text-slate-600 dark:text-slate-400">{m.text}</p>
            </div>
          ))}
        </div>
      </Section>

      {/* Call to action */}
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 rounded-2xl border border-slate-200 bg-white px-6 py-5 dark:border-white/[0.07] dark:bg-[#0e1115]">
        <div>
          <div className="text-[15px] font-semibold">Follow your clients over time</div>
          <p className="text-[13px] text-slate-500">Save an investigation as a case: questionnaire, checklist, validation and daily monitoring.</p>
        </div>
        <div className="flex gap-2">
          <button
            className="btn-outline"
            onClick={() => {
              window.scrollTo({ top: 0, behavior: "smooth" });
              document.getElementById("q")?.focus();
            }}
          >
            <Search className="h-4 w-4" /> Start a search
          </button>
          <button className="btn-primary" onClick={onCases}>
            Open cases <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
