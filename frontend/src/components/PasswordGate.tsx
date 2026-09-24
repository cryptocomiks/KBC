import { Lock } from "lucide-react";
import { useState } from "react";
import { auth } from "../api";

interface Props {
  onUnlock: () => void;
  wrong?: boolean;
}

/** Asked once per browser: cases and the dashboard are protected by APP_PASSWORD. */
export default function PasswordGate({ onUnlock, wrong }: Props) {
  const [pw, setPw] = useState("");
  return (
    <form
      className="card mx-auto mt-10 max-w-sm space-y-3 p-6"
      onSubmit={(e) => {
        e.preventDefault();
        auth.set(pw);
        onUnlock();
      }}
    >
      <div className="flex items-center gap-2 text-base font-semibold">
        <Lock className="h-4 w-4 text-brand-600" /> Cases are protected
      </div>
      <p className="text-sm text-slate-500">
        Saved cases, analyst decisions and monitoring are private. Enter the password set in <code>APP_PASSWORD</code>.
      </p>
      {wrong && <p className="text-sm text-red-600">Wrong password.</p>}
      <input type="password" className="input w-full" placeholder="Password" value={pw} onChange={(e) => setPw(e.target.value)} autoFocus />
      <button className="btn-primary w-full justify-center" disabled={!pw}>
        Unlock
      </button>
      <p className="text-[11px] text-slate-500">Kept in this browser only. Use “Lock” in the Cases page to forget it.</p>
    </form>
  );
}
