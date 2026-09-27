import { type RefObject, useLayoutEffect, useState } from "react";

/** Position of the selected tab inside a tab list, for an indicator that slides between tabs.
 *  Follows resizes; scrolls the selected tab into view in overflowing tab bars. */
export function useTabIndicator(list: RefObject<HTMLElement | null>, key: string): { left: number; width: number } | null {
  const [box, setBox] = useState<{ left: number; width: number } | null>(null);
  useLayoutEffect(() => {
    const el = list.current;
    if (!el) return;
    const measure = () => {
      const tab = el.querySelector<HTMLElement>('[aria-selected="true"]');
      if (tab) setBox({ left: tab.offsetLeft, width: tab.offsetWidth });
    };
    measure();
    el.querySelector<HTMLElement>('[aria-selected="true"]')?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    ro?.observe(el);
    return () => ro?.disconnect();
  }, [list, key]);
  return box;
}
