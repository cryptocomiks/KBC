import {
  BadgeCheck,
  ChevronRight,
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
import { useRef, type ReactNode } from "react";
import { useReveal } from "../lib/reveal";
import type { ConnectorStatus } from "../types";
import DemoVideos from "./DemoVideos";
import Tour from "./Tour";

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
    text: "Registers are read in every country reached: officers, shareholders, beneficial owners, parent companies: up to three levels, with effective ownership computed through every layer.",
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
    text: "Identity and status from the official register, legal form, address, capital, filings and legal notices: with the source of every fact.",
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

/** A centred Apple-style section: eyebrow, large headline, optional intro. */
function Section({
  tag,
  title,
  intro,
  children,
  className = "",
}: {
  tag: string;
  title: ReactNode;
  intro?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`bleed px-4 py-24 sm:py-28 ${className}`}>
      <div className="mx-auto max-w-[1100px]">
        <div className="reveal mx-auto max-w-3xl text-center">
          <div className="eyebrow">{tag}</div>
          <h2 className="headline mt-2 text-[clamp(2rem,4.4vw,3.5rem)]">{title}</h2>
          {intro && <p className="subhead mx-auto mt-4 max-w-2xl text-[clamp(1.05rem,1.6vw,1.3rem)] text-[#6e6e73] dark:text-[#a1a1a6]">{intro}</p>}
        </div>
        <div className="mt-14">{children}</div>
      </div>
    </section>
  );
}

/** Home, in the spirit of apple.com: a large hero with the search, a black film section,
 *  then one idea per band, alternating white and light grey, revealed as you scroll. */
export default function Landing({ search, connectors, onCases }: Props) {
  const root = useRef<HTMLDivElement>(null);
  useReveal(root);
  const live = (connectors ?? []).filter((c) => !c.demo);
  const byKind = new Map<string, ConnectorStatus[]>();
  for (const c of live) byKind.set(c.kind, [...(byKind.get(c.kind) ?? []), c]);
  const enabled = live.filter((c) => c.enabled).length;
  const toSearch = () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
    document.getElementById("q")?.focus();
  };
  const toFilm = () => document.getElementById("film")?.scrollIntoView({ behavior: "smooth", block: "start" });

  return (
    <div ref={root} className="-mt-5 -mb-5">
      <Tour />
      {/* Hero */}
      <section className="bleed bg-white px-4 pt-20 pb-16 text-center sm:pt-28 dark:bg-black">
        <div className="reveal mx-auto max-w-4xl">
          <div className="text-[clamp(1.1rem,1.8vw,1.5rem)] font-semibold tracking-[-0.02em]">KYC 1 CLICK</div>
          <h1 className="headline mt-2 text-[clamp(2.75rem,7.2vw,5.5rem)]">
            Due diligence.
            <br />
            <span className="text-glow">In one click.</span>
          </h1>
          <p className="subhead mx-auto mt-5 max-w-2xl text-[clamp(1.1rem,2vw,1.6rem)] text-[#6e6e73] dark:text-[#a1a1a6]">
            Who owns the company, who runs it, whether anyone is sanctioned or exposed: and the KYC file, ready.
          </p>
          <div className="mt-7 flex flex-wrap items-center justify-center gap-x-6 gap-y-3 text-[17px]">
            <button className="btn-primary !px-6 !py-2.5 !text-[17px]" onClick={toSearch}>
              Start a search
            </button>
            <button className="link-more" onClick={toFilm} data-tour="film">
              Watch the film <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
        <div className="reveal mx-auto mt-14 max-w-5xl text-left" style={{ ["--d" as string]: 2 }}>
          {search}
        </div>
        <p className="reveal mx-auto mt-6 flex max-w-3xl items-center justify-center gap-2 text-[12px] text-[#6e6e73] dark:text-[#86868b]" style={{ ["--d" as string]: 3 }}>
          <BadgeCheck className="h-3.5 w-3.5 shrink-0" /> Public and official sources only. Every fact carries its source.
        </p>
      </section>

      {/* Film */}
      <section id="film" className="dark bleed scroll-mt-12 bg-black px-4 py-24 text-[#f5f5f7] sm:py-28">
        <div className="mx-auto max-w-[1100px]">
          <div className="reveal mx-auto max-w-3xl text-center">
            <div className="eyebrow">See it in action</div>
            <h2 className="headline mt-2 text-[clamp(2rem,4.4vw,3.5rem)]">From a name to a decision. In 90 seconds.</h2>
          </div>
          <div className="reveal mt-14" style={{ ["--d" as string]: 1 }}>
            <DemoVideos />
          </div>
        </div>
      </section>

      {/* How it works */}
      <Section
        tag="How it works"
        title="Four steps. One file."
        intro="Search, map, screen, decide: every step sourced, every decision recorded."
        className="bg-slate-50 dark:bg-[#0a0a0a]"
      >
        <ol className="grid gap-5 md:grid-cols-2">
          {STEPS.map((s, i) => (
            <li key={s.title} className="reveal rounded-[28px] bg-white p-8 sm:p-10 dark:bg-[#1c1c1e]" style={{ ["--d" as string]: i % 2 }}>
              <s.Icon className="h-8 w-8 text-brand-500 dark:text-[#2997ff]" strokeWidth={1.6} />
              <div className="mt-6 text-[13px] font-semibold text-[#6e6e73] dark:text-[#a1a1a6]">Step {i + 1}</div>
              <h3 className="headline mt-1 text-[28px]">{s.title}</h3>
              <p className="mt-3 text-[15px] leading-relaxed text-[#6e6e73] dark:text-[#a1a1a6]">{s.text}</p>
            </li>
          ))}
        </ol>
      </Section>

      {/* What you get */}
      <Section
        tag="What you get"
        title="The answers a compliance officer needs."
        className="bg-white dark:bg-black"
      >
        <div className="grid gap-x-10 gap-y-14 sm:grid-cols-2">
          {WHAT.map((w, i) => (
            <div key={w.title} className="reveal text-center sm:text-left" style={{ ["--d" as string]: i % 2 }}>
              <w.Icon className="mx-auto h-9 w-9 text-[#1d1d1f] sm:mx-0 dark:text-[#f5f5f7]" strokeWidth={1.4} />
              <h3 className="headline mt-4 text-[24px]">{w.title}</h3>
              <p className="mt-2 text-[16px] leading-relaxed text-[#6e6e73] dark:text-[#a1a1a6]">{w.text}</p>
            </div>
          ))}
        </div>
      </Section>

      {/* Sources */}
      <Section
        tag="Sources"
        title={
          <>
            <span className="tabular-nums">{live.length || 60}</span> public sources.
            <br />
            <span className="tabular-nums">{WATCHLISTS}</span> watchlists. Live.
          </>
        }
        intro="Registers, sanctions and PEP lists, courts, regulators, leaks and the press: queried as you search."
        className="bg-slate-50 dark:bg-[#0a0a0a]"
      >
        <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          {[...byKind.entries()]
            .sort((a, b) => b[1].length - a[1].length)
            .map(([kind, list], i) => {
              const cat = CATEGORY[kind] ?? { label: kind, Icon: FileText };
              return (
                <div key={kind} className="reveal rounded-[28px] bg-white p-7 dark:bg-[#1c1c1e]" style={{ ["--d" as string]: i % 3 }}>
                  <cat.Icon className="h-6 w-6 text-brand-500 dark:text-[#2997ff]" strokeWidth={1.6} />
                  <div className="mt-4 flex items-baseline justify-between gap-2">
                    <h3 className="text-[19px] font-semibold tracking-[-0.02em]">{cat.label}</h3>
                    <span className="headline text-[28px] text-[#86868b]">{list.length}</span>
                  </div>
                  <ul className="mt-3 space-y-1.5">
                    {list.slice(0, 6).map((c) => (
                      <li key={c.name} className="text-[13px] leading-snug text-[#6e6e73] dark:text-[#a1a1a6]">
                        {c.label}
                        {!c.enabled && c.message.startsWith("Offline") && <span className="ml-1 text-amber-600">(offline)</span>}
                      </li>
                    ))}
                    {list.length > 6 && <li className="text-[13px] text-[#86868b]">and {list.length - 6} more</li>}
                  </ul>
                </div>
              );
            })}
        </div>
        <p className="reveal mx-auto mt-10 max-w-3xl text-center text-[13px] leading-relaxed text-[#6e6e73] dark:text-[#86868b]">
          {enabled > 0 && `${enabled} sources active on this server. `}The full list, with the status of each source, is under{" "}
          <b className="font-semibold">Sources</b> in the top bar. Watchlists include the EU, UN, US (OFAC), UK, Swiss, French and Monaco asset
          freezes, regulators' enforcement actions and warnings, and law-enforcement notices.
        </p>
      </Section>

      {/* Method, limits & privacy */}
      <Section
        tag="Method & limits"
        title="An analytical aid. Not a verdict."
        intro={
          <a href="#/validation" className="link-more">
            Read the matching validation report <ChevronRight className="h-4 w-4" />
          </a>
        }
        className="bg-white dark:bg-black"
      >
        <div className="grid gap-10 md:grid-cols-3">
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
          ].map((m, i) => (
            <div key={m.title} className="reveal text-center" style={{ ["--d" as string]: i }}>
              <m.Icon className="mx-auto h-9 w-9 text-[#1d1d1f] dark:text-[#f5f5f7]" strokeWidth={1.4} />
              <h3 className="headline mt-4 text-[22px]">{m.title}</h3>
              <p className="mt-2 text-[15px] leading-relaxed text-[#6e6e73] dark:text-[#a1a1a6]">{m.text}</p>
            </div>
          ))}
        </div>
      </Section>

      {/* Call to action */}
      <section className="bleed bg-slate-50 px-4 py-24 text-center dark:bg-[#0a0a0a]">
        <div className="reveal mx-auto max-w-3xl">
          <h2 className="headline text-[clamp(2rem,4.4vw,3.5rem)]">Follow your clients over time.</h2>
          <p className="subhead mx-auto mt-4 max-w-2xl text-[clamp(1.05rem,1.6vw,1.3rem)] text-[#6e6e73] dark:text-[#a1a1a6]">
            Save an investigation as a case: questionnaire, checklist, four-eyes validation and daily monitoring.
          </p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-x-6 gap-y-3 text-[17px]">
            <button className="btn-primary !px-6 !py-2.5 !text-[17px]" onClick={onCases}>
              Open cases
            </button>
            <button className="link-more" onClick={toSearch}>
              Start a search <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
