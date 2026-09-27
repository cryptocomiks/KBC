/** Tiny notification bus: toast("Case saved") from anywhere, rendered by <Toaster />. */
export type ToastKind = "success" | "info" | "error";
export interface ToastItem {
  id: number;
  text: string;
  kind: ToastKind;
}

let next = 1;
export function toast(text: string, kind: ToastKind = "success"): void {
  window.dispatchEvent(new CustomEvent<ToastItem>("kbc-toast", { detail: { id: next++, text, kind } }));
}
