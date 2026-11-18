"use client";
import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function Forgot() {
  const { t } = useI18n();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    // always show the same message — never reveal whether the account exists
    try { await api.forgot(email); } catch {} finally { setBusy(false); setSent(true); }
  }

  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <form onSubmit={submit} className="w-full max-w-sm bg-card border border-bord rounded-2xl p-6 shadow-sm space-y-4">
        <h1 className="font-serif-astro text-2xl">{t("forgotTitle")}</h1>
        {sent ? (
          <p className="text-sm" role="status">{t("forgotDone")}</p>
        ) : (
          <>
            <p className="text-sm text-muted">{t("forgotIntro")}</p>
            <input value={email} onChange={e => setEmail(e.target.value)} type="email" required
              placeholder={t("email")} className="w-full border border-bord rounded-lg px-3 py-2 bg-transparent" />
            <button disabled={busy} className="w-full bg-accent text-white rounded-lg py-2.5 font-medium disabled:opacity-50">
              {busy ? "…" : t("sendLink")}
            </button>
          </>
        )}
        <div className="text-center text-xs"><Link href="/login" className="underline text-muted">{t("backToSignIn")}</Link></div>
      </form>
    </main>
  );
}
