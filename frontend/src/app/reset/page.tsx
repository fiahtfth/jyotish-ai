"use client";
import { Suspense, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api, errMsg } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

function ResetForm() {
  const { t } = useI18n();
  const token = useSearchParams().get("token") || "";
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [err, setErr] = useState("");
  const [ok, setOk] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    if (!token) { setErr(t("missingToken")); return; }
    if (pw !== pw2) { setErr(t("passwordsMismatch")); return; }
    setBusy(true);
    try { await api.reset(token, pw); setOk(true); }
    catch (x) { setErr(errMsg(x)); } finally { setBusy(false); }
  }

  const inp = "w-full border border-bord rounded-lg px-3 py-2 bg-transparent";
  return (
    <form onSubmit={submit} className="w-full max-w-sm bg-card border border-bord rounded-2xl p-6 shadow-sm space-y-4">
      <h1 className="font-serif-astro text-2xl">{t("resetTitle")}</h1>
      {ok ? (
        <p className="text-sm" role="status">{t("resetDone")}</p>
      ) : (
        <>
          <input value={pw} onChange={e => setPw(e.target.value)} type="password" required autoComplete="new-password"
            placeholder={t("newPassword")} className={inp} />
          <input value={pw2} onChange={e => setPw2(e.target.value)} type="password" required autoComplete="new-password"
            placeholder={t("confirmPassword")} className={inp} />
          {err && <div className="text-red-500 text-sm" role="alert">{err}</div>}
          <button disabled={busy} className="w-full bg-accent text-white rounded-lg py-2.5 font-medium disabled:opacity-50">
            {busy ? "…" : t("setPassword")}
          </button>
        </>
      )}
      <div className="text-center text-xs"><Link href="/login" className="underline text-muted">{t("backToSignIn")}</Link></div>
    </form>
  );
}

export default function Reset() {
  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <Suspense fallback={null}><ResetForm /></Suspense>
    </main>
  );
}
