import { useCallback, useEffect, useState } from "react";

/** Every screen has its own address (hash-based: works on any static host, no server rewrite):
 *  #/                                  home
 *  #/search?q=…&type=…&depth=…&n=…     search results
 *  #/investigate?ids=a,b&depth=…&n=…   investigation
 *  #/cases                             cases dashboard
 *  #/cases/<id>[/<tab>]                a case (tab: kyc | investigation | history)
 */
export type SearchType = "any" | "person" | "company";
export type CaseTab = "kyc" | "investigation" | "history";
export type Route =
  | { name: "home" }
  | { name: "search"; q: string; type: SearchType; depth: number; maxNodes: number }
  | { name: "investigate"; ids: string[]; depth: number; maxNodes: number }
  | { name: "cases" }
  | { name: "case"; id: string; tab: CaseTab };

const TABS: CaseTab[] = ["kyc", "investigation", "history"];
const int = (v: string | null, fallback: number, min: number, max: number) => {
  const n = Number(v);
  return Number.isFinite(n) && n >= min && n <= max ? Math.round(n) : fallback;
};

export function parseRoute(hash: string): Route {
  const raw = hash.replace(/^#/, "") || "/";
  const [path, query = ""] = raw.split("?");
  const qs = new URLSearchParams(query);
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  if (parts[0] === "search" && (qs.get("q") ?? "").trim().length >= 2) {
    const type = qs.get("type");
    return {
      name: "search",
      q: qs.get("q")!.trim(),
      type: type === "person" || type === "company" ? type : "any",
      depth: int(qs.get("depth"), 2, 1, 3),
      maxNodes: int(qs.get("n"), 60, 5, 250),
    };
  }
  if (parts[0] === "investigate") {
    const ids = (qs.get("ids") ?? "").split(",").filter(Boolean).slice(0, 20);
    if (ids.length) return { name: "investigate", ids, depth: int(qs.get("depth"), 2, 1, 3), maxNodes: int(qs.get("n"), 60, 5, 250) };
  }
  if (parts[0] === "cases") {
    if (parts[1]) return { name: "case", id: parts[1], tab: TABS.includes(parts[2] as CaseTab) ? (parts[2] as CaseTab) : "kyc" };
    return { name: "cases" };
  }
  return { name: "home" };
}

export function formatRoute(r: Route): string {
  switch (r.name) {
    case "search":
      return `#/search?${new URLSearchParams({ q: r.q, type: r.type, depth: String(r.depth), n: String(r.maxNodes) })}`;
    case "investigate":
      return `#/investigate?${new URLSearchParams({ ids: r.ids.join(","), depth: String(r.depth), n: String(r.maxNodes) })}`;
    case "cases":
      return "#/cases";
    case "case":
      return `#/cases/${encodeURIComponent(r.id)}${r.tab === "kyc" ? "" : `/${r.tab}`}`;
    default:
      return "#/";
  }
}

/** Current route + navigate(route, {replace}) — the browser's back / forward buttons just work. */
export function useRoute(): [Route, (r: Route, opts?: { replace?: boolean }) => void] {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash));
  useEffect(() => {
    const onChange = () => {
      setRoute(parseRoute(window.location.hash));
      window.scrollTo({ top: 0 });
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  const navigate = useCallback((r: Route, opts?: { replace?: boolean }) => {
    const hash = formatRoute(r);
    if (hash === window.location.hash || (hash === "#/" && !window.location.hash)) return;
    if (opts?.replace) {
      window.history.replaceState(null, "", hash);
      setRoute(parseRoute(hash));
    } else {
      window.location.hash = hash;
    }
  }, []);
  return [route, navigate];
}
