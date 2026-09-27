import { Play, Volume2, VolumeX } from "lucide-react";
import { useEffect, useRef, useState } from "react";

const CHAPTERS = [
  { t: 12, label: "Search a name or an identifier" },
  { t: 18, label: "Homonyms side by side" },
  { t: 24, label: "The verdict first: risk and red flags" },
  { t: 33, label: "Documents to request" },
  { t: 42, label: "Ownership graph" },
  { t: 48, label: "KYC case, questionnaire, risk map" },
  { t: 70, label: "Decision memo" },
  { t: 77, label: "One-click PDF report" },
];

const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/** Showreel (muted loop, plays only while visible) and the full product demo with chapters. */
export default function DemoVideos() {
  const reel = useRef<HTMLVideoElement>(null);
  const demo = useRef<HTMLVideoElement>(null);
  const [muted, setMuted] = useState(true);
  const [started, setStarted] = useState(false);
  const [time, setTime] = useState(0);

  useEffect(() => {
    const v = reel.current;
    if (!v || typeof IntersectionObserver === "undefined") return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const io = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting) v.play().catch(() => undefined);
        else v.pause();
      },
      { threshold: 0.35 },
    );
    io.observe(v);
    return () => io.disconnect();
  }, []);

  const toggleSound = () => {
    const v = reel.current;
    if (!v) return;
    v.muted = !v.muted;
    setMuted(v.muted);
    if (!v.muted) v.play().catch(() => undefined);
  };

  const playDemo = (at?: number) => {
    const v = demo.current;
    if (!v) return;
    if (at !== undefined) v.currentTime = at;
    setStarted(true);
    v.play().catch(() => undefined);
  };

  const current = CHAPTERS.reduce((acc, c, i) => (time >= c.t ? i : acc), -1);

  return (
    <div className="space-y-6">
      {/* Showreel */}
      <div className="glass rounded-[26px] p-2">
        <div className="relative overflow-hidden rounded-[20px] bg-black">
          <video
            ref={reel}
            className="block aspect-video w-full"
            src="/media/showreel.mp4"
            poster="/media/showreel-poster.jpg"
            muted
            loop
            playsInline
            preload="none"
            aria-label="KYC 1 CLICK showreel (15 seconds)"
          />
          <button
            onClick={toggleSound}
            className="absolute right-3 bottom-3 flex items-center gap-1.5 rounded-full border border-white/20 bg-black/40 px-3 py-1.5 text-xs font-medium text-white backdrop-blur-md transition-colors hover:bg-black/60"
            aria-label={muted ? "Turn the sound on" : "Mute"}
          >
            {muted ? <VolumeX className="h-3.5 w-3.5" /> : <Volume2 className="h-3.5 w-3.5" />}
            {muted ? "Sound on" : "Mute"}
          </button>
          <span className="absolute top-3 left-3 rounded-full bg-black/40 px-2.5 py-1 font-mono text-[10px] tracking-[0.14em] text-white/80 uppercase backdrop-blur-md">
            Showreel · 15 s
          </span>
        </div>
      </div>

      {/* Full demo with chapters */}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="glass rounded-[26px] p-2">
          <div className="relative overflow-hidden rounded-[20px] bg-black">
            <video
              ref={demo}
              className="block aspect-video w-full"
              src="/media/demo.mp4"
              poster="/media/demo-poster.jpg"
              controls={started}
              playsInline
              preload="none"
              onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
              onPlay={() => setStarted(true)}
              aria-label="Product demo (1 min 30): search, investigation, KYC case, decision memo, PDF report"
            />
            {!started && (
              <button onClick={() => playDemo()} className="group absolute inset-0 flex items-center justify-center bg-black/25" aria-label="Play the demo">
                <span className="glass-panel flex items-center gap-3 rounded-full py-3 pr-6 pl-3 text-slate-900 shadow-2xl transition-transform group-hover:scale-105 dark:text-white">
                  <span className="flex h-11 w-11 items-center justify-center rounded-full bg-brand-500 text-white">
                    <Play className="ml-0.5 h-5 w-5 fill-current" />
                  </span>
                  <span className="text-left">
                    <span className="block text-sm font-semibold">Watch the demo</span>
                    <span className="block text-xs text-slate-500 dark:text-slate-400">1 min 30 · fictitious data</span>
                  </span>
                </span>
              </button>
            )}
          </div>
        </div>
        <div className="card p-4">
          <div className="label mb-2">Chapters</div>
          <ol className="space-y-0.5">
            {CHAPTERS.map((c, i) => (
              <li key={c.t}>
                <button
                  onClick={() => playDemo(c.t)}
                  className={`flex w-full items-center gap-3 rounded-lg px-2 py-1.5 text-left text-sm transition-colors hover:bg-slate-100 dark:hover:bg-white/[0.05] ${
                    i === current ? "bg-brand-500/10 text-brand-700 dark:text-brand-300" : "text-slate-700 dark:text-slate-300"
                  }`}
                >
                  <span className="w-9 shrink-0 font-mono text-xs text-slate-500">{fmt(c.t)}</span>
                  {c.label}
                </button>
              </li>
            ))}
          </ol>
          <p className="mt-3 text-[11px] leading-relaxed text-slate-500">Demo data is fictitious. Every figure in a real case links to its public source.</p>
        </div>
      </div>
    </div>
  );
}
