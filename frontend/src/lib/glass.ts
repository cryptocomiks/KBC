/** Specular highlight of the Liquid Glass surfaces: one delegated pointer listener sets
 *  --mx / --my (pointer position inside the element) on the glass surface under the
 *  pointer, at most once per frame. Nothing runs when reduced motion is requested. */
export function installGlassPointer(): void {
  if (typeof window === "undefined" || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  let frame = 0;
  let last: PointerEvent | null = null;
  const update = () => {
    frame = 0;
    const e = last;
    if (!e) return;
    const el = (e.target as Element | null)?.closest?.<HTMLElement>(".glass-tile, .glass, .glass-panel");
    if (!el) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty("--mx", `${e.clientX - r.left}px`);
    el.style.setProperty("--my", `${e.clientY - r.top}px`);
  };
  window.addEventListener(
    "pointermove",
    (e) => {
      last = e;
      if (!frame) frame = requestAnimationFrame(update);
    },
    { passive: true },
  );
}
