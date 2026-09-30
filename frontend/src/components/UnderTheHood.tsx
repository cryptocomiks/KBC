import { useQuery } from "@tanstack/react-query";
import {
  Accessibility,
  Bot,
  Check,
  CheckCircle2,
  Copy,
  Database,
  FileLock2,
  FlaskConical,
  GitBranch,
  Loader2,
  Network,
  Play,
  Radar,
  Scale,
  ShieldCheck,
  Workflow,
} from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { Tile } from "./viz";

const BASE = import.meta.env.VITE_API_BASE ?? "/api";

/** Facts measured on the release (re-measured by CI and the audits, see README). */
const MEASURED = { tests: 295, screens: 26, date: "2026-09-30" };

interface McpTool {
  name: string;
  title?: string;
  description: string;
}

async function mcp(method: string, params: Record<string, unknown> = {}) {
  const res = await fetch(`${BASE}/mcp`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: Date.now(), method, params }),
  });
  return res.json();
}

const EXAMPLES: Record<string, { label: string; args: Record<string, unknown> }> = {
  search_entities: { label: "Search a company", args: { query: "Northgate Maritime", type: "company" } },
  screen_names: { label: "Screen payment counterparties", args: { names: ["Ruslan Terekhov", "Gulf Star Trading FZE", "Jane Example"], type: "person" } },
  run_due_diligence: { label: "Full due diligence", args: { query: "Northgate Maritime", depth: 2 } },
  quick_checks: { label: "Check an IBAN", args: { iban: "CH93 0076 2011 6238 5295 7" } },
};

function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      className="btn-ghost shrink-0 px-2 py-1 text-xs"
      aria-label={label}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          setTimeout(() => setDone(false), 1800);
        } catch {
          /* clipboard refused: the text stays selectable */
        }
      }}
    >
      {done ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />} {done ? "Copied" : "Copy"}
    </button>
  );
}

/** Live JSON-RPC console: what an AI agent sends to the MCP server, and what it gets back. */
function AgentConsole({ tools }: { tools: McpTool[] }) {
  const [tool, setTool] = useState("screen_names");
  const [running, setRunning] = useState(false);
  const [ms, setMs] = useState<number | null>(null);
  const [out, setOut] = useState<string>("");
  const request = { jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: tool, arguments: EXAMPLES[tool]?.args ?? {} } };

  const run = async () => {
    setRunning(true);
    setOut("");
    const t = performance.now();
    try {
      const res = await mcp("tools/call", request.params);
      const data = res.result?.structuredContent ?? res.result ?? res.error;
      setOut(JSON.stringify(data, null, 2));
    } catch (e) {
      setOut(String(e));
    } finally {
      setMs(Math.round(performance.now() - t));
      setRunning(false);
    }
  };

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-black/[0.06] px-5 py-3 dark:border-white/[0.08]">
        <Bot className="h-4 w-4 text-brand-600" aria-hidden />
        <h3 className="text-sm font-semibold">Try it: what an agent sends, what it gets back</h3>
        <label className="ml-auto flex items-center gap-2 text-xs">
          <span className="text-slate-500">Tool</span>
          <select className="input py-1 text-xs" value={tool} onChange={(e) => (setTool(e.target.value), setOut(""), setMs(null))}>
            {tools.map((t) => (
              <option key={t.name} value={t.name}>
                {EXAMPLES[t.name]?.label ?? t.title ?? t.name}
              </option>
            ))}
          </select>
        </label>
        <button className="btn-primary py-1.5 text-xs" onClick={run} disabled={running}>
          {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />} Run on the live server
        </button>
      </div>
      <div className="grid md:grid-cols-2">
        <div className="min-w-0 border-b border-black/[0.06] p-4 md:border-r md:border-b-0 dark:border-white/[0.08]">
          <div className="tag mb-2">Request (JSON-RPC 2.0, POST {BASE}/mcp)</div>
          <pre className="max-h-80 overflow-auto rounded-xl bg-black/[0.04] p-3 text-[12px] leading-relaxed dark:bg-white/[0.06]" tabIndex={0} aria-label="Request">
            {JSON.stringify(request, null, 2)}
          </pre>
        </div>
        <div className="min-w-0 p-4" aria-live="polite">
          <div className="tag mb-2">Response{ms != null && <span className="font-normal text-slate-500"> · {ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`}</span>}</div>
          <pre className="max-h-80 overflow-auto rounded-xl bg-black/[0.04] p-3 text-[12px] leading-relaxed dark:bg-white/[0.06]" tabIndex={0} aria-label="Response">
            {running ? (tool === "run_due_diligence" ? "Mapping the network and screening everyone… (up to a few minutes on live sources)" : "Running…") : out || "Press Run."}
          </pre>
        </div>
      </div>
    </div>
  );
}

const PRACTICES = [
  { Icon: GitBranch, title: "CI on every push", text: "Lint, type checks, the backend test suite and the production build must pass before anything ships." },
  { Icon: Radar, title: "Smoke test after every deployment", text: "The live site is searched, an investigation is run and a PDF is generated as soon as Vercel deploys." },
  { Icon: Database, title: "Every source checked every day", text: "A scheduled job queries each registry and list with a known reference (Putin on the EU, UK and Swiss lists, Huawei on the US Entity List…)." },
  { Icon: FlaskConical, title: "Matching measured, not assumed", text: "A labelled set of name pairs (transliterations, homonyms, generic company words) gives the detection and false-alert rates." },
  { Icon: Accessibility, title: "Accessible to everyone", text: "Every page and tab audited with axe-core against WCAG 2.1 AA, light and dark, desktop and mobile, keyboard only." },
  { Icon: Scale, title: "Every alert has a legal basis", text: "Each red flag is mapped to LBA, OBA-FINMA, CDB 20, EU AMLD, sanctions regulations and FATF Recommendations, with a ready-to-paste justification." },
  { Icon: FileLock2, title: "Privacy by design", text: "Client documents and bank statements are read in memory and never stored. Cached answers can be wiped in one click." },
  { Icon: ShieldCheck, title: "Licences tracked per source", text: "A commercial mode switches off every source whose licence forbids commercial reuse: screening then relies on official lists only." },
];

const PIPELINE = [
  { Icon: Database, title: "Sources", text: "Registries, official sanctions lists, PEPs, leaks, courts, press, blockchains" },
  { Icon: Workflow, title: "Connectors", text: "Cache, retries, rate limits, circuit breaker, licence gate" },
  { Icon: Network, title: "Network", text: "Entity resolution across countries, owners of owners, effective interest" },
  { Icon: ShieldCheck, title: "Screening", text: "Transliteration-aware matching, namesake triage, analyst memory" },
  { Icon: Scale, title: "Risk & law", text: "Explained score, OFAC 50 % rule, legal basis, actions" },
  { Icon: Bot, title: "Outputs", text: "Web app, PDF report, SAR draft, KYC case, MCP for AI agents" },
];

/** How the product is built and verified: for a compliance buyer, an engineer or a recruiter. */
export default function UnderTheHood() {
  const connectors = useQuery({ queryKey: ["connectors"], queryFn: api.connectors });
  const validation = useQuery({ queryKey: ["validation"], queryFn: api.validation });
  const tools = useQuery({ queryKey: ["mcp-tools"], queryFn: async () => ((await mcp("tools/list")).result?.tools ?? []) as McpTool[] });

  const all = connectors.data ?? [];
  const active = all.filter((c) => c.enabled);
  const screening = active.filter((c) => c.kind === "screening").length;
  const v = validation.data?.overall;
  const url = BASE.startsWith("http") ? `${BASE}/mcp` : `${window.location.origin}${BASE}/mcp`;
  const claudeCmd = `claude mcp add --transport http kyc-1-click ${url}`;
  const jsonCfg = JSON.stringify({ mcpServers: { "kyc-1-click": { type: "http", url } } }, null, 2);

  return (
    <div className="panel-enter mx-auto max-w-[1100px] space-y-12 pb-12">
      <div className="pt-6 text-center">
        <div className="eyebrow">Under the hood</div>
        <h1 className="headline mt-2 text-[clamp(2rem,4.4vw,3.2rem)]">Built like a compliance product.</h1>
        <p className="subhead mx-auto mt-3 max-w-2xl text-[17px] text-slate-500">
          Sourced answers, measured accuracy, audited accessibility, and an open door for AI agents. The figures below are live.
        </p>
      </div>

      <section aria-label="Live figures" className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile label="Data sources active" value={connectors.data ? `${active.length} / ${all.length}` : "…"} sub="checked every day" tone="good" />
        <Tile label="Sanctions, PEP and watchlist sources" value={connectors.data ? screening : "…"} sub="OFAC, UN, EU, UK, CH, US export lists, France…" tone="accent" />
        <Tile
          label="Matching: true matches caught"
          value={v?.detection_rate != null ? `${v.detection_rate} %` : "…"}
          sub={v ? `${v.pairs} labelled pairs · ${v.false_positive_rate ?? 0} % false alerts` : "validation set"}
          tone="good"
        />
        <Tile label="WCAG 2.1 AA violations" value={0} sub={`${MEASURED.screens} screens, light and dark · ${MEASURED.tests} automated tests`} tone="good" />
      </section>

      <section className="space-y-4" aria-labelledby="agents">
        <div className="text-center">
          <div className="eyebrow">For AI agents</div>
          <h2 id="agents" className="headline mt-2 text-[clamp(1.6rem,3vw,2.3rem)]">Plug it into any AI agent.</h2>
          <p className="mx-auto mt-2 max-w-2xl text-[15px] text-slate-500">
            KYC 1 CLICK is also a <b className="font-semibold text-slate-700 dark:text-slate-200">Model Context Protocol</b> server. An assistant such as Claude, or a bank's
            internal compliance copilot, can search a name, run a full due diligence or screen a list of counterparties, and gets the same sourced, explained results as
            this site.
          </p>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <div className="card p-4">
            <div className="flex items-center gap-2">
              <span className="tag">Claude Code</span>
              <span className="ml-auto" />
              <CopyButton text={claudeCmd} label="Copy the Claude Code command" />
            </div>
            <pre className="mt-2 overflow-x-auto rounded-xl bg-black/[0.04] p-3 text-[12px] dark:bg-white/[0.06]" tabIndex={0} aria-label="Claude Code command">
              {claudeCmd}
            </pre>
          </div>
          <div className="card p-4">
            <div className="flex items-center gap-2">
              <span className="tag">Any MCP client (JSON config)</span>
              <span className="ml-auto" />
              <CopyButton text={jsonCfg} label="Copy the JSON configuration" />
            </div>
            <pre className="mt-2 overflow-x-auto rounded-xl bg-black/[0.04] p-3 text-[12px] dark:bg-white/[0.06]" tabIndex={0} aria-label="JSON configuration">
              {jsonCfg}
            </pre>
          </div>
        </div>
        {tools.data && tools.data.length > 0 && (
          <>
            <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {tools.data.map((t) => (
                <li key={t.name} className="card p-4">
                  <code className="text-[12px] font-semibold text-brand-600">{t.name}</code>
                  <p className="mt-1 text-[12.5px] leading-snug text-slate-500">{t.description.split(". ")[0].replace(/\.$/, "")}.</p>
                </li>
              ))}
            </ul>
            <AgentConsole tools={tools.data} />
          </>
        )}
      </section>

      <section className="space-y-4" aria-labelledby="pipeline">
        <div className="text-center">
          <div className="eyebrow">Architecture</div>
          <h2 id="pipeline" className="headline mt-2 text-[clamp(1.6rem,3vw,2.3rem)]">From a name to a decision.</h2>
        </div>
        <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
          {PIPELINE.map((s, i) => (
            <li key={s.title} className="card relative p-4">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-brand-500 text-[11px] font-semibold text-white">{i + 1}</span>
                <s.Icon className="h-4 w-4 text-brand-600" aria-hidden />
              </div>
              <div className="mt-2 text-[14px] font-semibold">{s.title}</div>
              <p className="mt-1 text-[12.5px] leading-snug text-slate-500">{s.text}</p>
            </li>
          ))}
        </ol>
        <p className="text-center text-[12.5px] text-slate-500">
          FastAPI and Python on the server, React and TypeScript in the browser, deployed on Vercel. The full API is documented at{" "}
          <a className="text-brand-600 underline underline-offset-2" href={`${BASE}/docs`}>
            {BASE}/docs
          </a>
          .
        </p>
      </section>

      <section className="space-y-4" aria-labelledby="practices">
        <div className="text-center">
          <div className="eyebrow">Engineering</div>
          <h2 id="practices" className="headline mt-2 text-[clamp(1.6rem,3vw,2.3rem)]">Verified, every day.</h2>
        </div>
        <ul className="grid gap-3 sm:grid-cols-2">
          {PRACTICES.map((p) => (
            <li key={p.title} className="card flex gap-3 p-4">
              <p.Icon className="mt-0.5 h-5 w-5 shrink-0 text-brand-600" aria-hidden />
              <div>
                <div className="flex items-center gap-1.5 text-[14px] font-semibold">
                  {p.title} <CheckCircle2 className="h-3.5 w-3.5 text-[#1b7331] dark:text-[#30d158]" aria-hidden />
                </div>
                <p className="mt-0.5 text-[13px] leading-snug text-slate-500">{p.text}</p>
              </div>
            </li>
          ))}
        </ul>
        <p className="text-center text-[11px] text-slate-500">Test and accessibility figures measured on {MEASURED.date}; source and matching figures are read live from the server.</p>
      </section>
    </div>
  );
}
