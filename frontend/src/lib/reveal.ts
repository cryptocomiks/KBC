import { useEffect, type RefObject } from "react";

/** Apple-style entrance: elements with the `reveal` class fade and rise into place the first
 *  time they scroll into view — including elements rendered later (data loaded afterwards).
 *  Everything is shown at once when reduced motion is requested. */
export function useReveal(root: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const pending = () => Array.from(el.querySelectorAll<HTMLElement>(".reveal:not(.in)"));
    if (typeof IntersectionObserver === "undefined" || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      const showAll = () => pending().forEach((i) => i.classList.add("in"));
      showAll();
      const mo = new MutationObserver(showAll);
      mo.observe(el, { childList: true, subtree: true });
      return () => mo.disconnect();
    }
    const watched = new WeakSet<Element>();
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            e.target.classList.add("in");
            io.unobserve(e.target);
          }
        }
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.12 },
    );
    const watch = () =>
      pending().forEach((i) => {
        if (!watched.has(i)) {
          watched.add(i);
          io.observe(i);
        }
      });
    watch();
    const mo = new MutationObserver(watch);
    mo.observe(el, { childList: true, subtree: true });
    return () => {
      io.disconnect();
      mo.disconnect();
    };
  }, [root]);
}
