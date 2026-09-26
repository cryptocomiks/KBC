const KEY = "kbc-analyst";

/** Name of the analyst using this browser, signed on every workflow step and checklist tick. */
export const analyst = {
  get: (): string => {
    try {
      return localStorage.getItem(KEY) ?? "";
    } catch {
      return "";
    }
  },
  set: (name: string) => {
    try {
      localStorage.setItem(KEY, name.trim());
    } catch {
      /* private mode */
    }
  },
};
