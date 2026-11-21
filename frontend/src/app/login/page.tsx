"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import ServiceAgreement from "@/components/ServiceAgreement";
import { api, errMsg, setToken, token } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function Login() {
  const router = useRouter();
  const { t, lang, setLang } = useI18n();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [adult, setAdult] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (token()) router.replace("/chat"); }, [router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(""); setBusy(true);
    try {
      const r = mode === "login"
        ? await api.login(email, password)
        : await api.register(email, password, name, agreed, adult);
      setToken(r.access_token);
      router.replace(mode === "login" ? "/chat" : "/birth");
    } catch (x) { setErr(errMsg(x)); } finally { setBusy(false); }
  }

  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <button type="button" onClick={() => setLang(lang === "en" ? "hi" : "en")}
        className="absolute top-4 right-4 text-sm text-muted border border-bord rounded-lg px-3 py-1.5">
        {t("language")}
      </button>
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="text-4xl font-serif-astro mb-2">{t("appName")}</div>
          <div className="text-muted text-sm">{t("tagline1")}<br/>{t("tagline2")}</div>
        </div>
        <form onSubmit={submit} className="bg-card border border-bord rounded-2xl p-6 shadow-sm space-y-4">
          <div className="flex rounded-lg overflow-hidden border border-bord text-sm">
            {(["login", "register"] as const).map(m => (
              <button key={m} type="button" onClick={() => setMode(m)}
                className={`flex-1 py-2 capitalize ${mode === m ? "bg-accent text-white" : "text-muted"}`}>
                {m === "login" ? t("signIn") : t("createAccount")}
              </button>
            ))}
          </div>
          {mode === "register" && (
            <input value={name} onChange={e => setName(e.target.value)} placeholder={t("yourName")} required
              className="w-full border border-bord rounded-lg px-3 py-2 bg-transparent" />
          )}
          <input value={email} onChange={e => setEmail(e.target.value)} type="email" placeholder={t("email")} required
            className="w-full border border-bord rounded-lg px-3 py-2 bg-transparent" />
          <input value={password} onChange={e => setPassword(e.target.value)} type="password" placeholder={t("password")} required
            className="w-full border border-bord rounded-lg px-3 py-2 bg-transparent" />
          {mode === "register" && (
            <ServiceAgreement checked={agreed} onChange={setAgreed} />
          )}
          {mode === "register" && (
            <label className="flex gap-2 items-start text-sm text-muted">
              <input type="checkbox" checked={adult} onChange={e => setAdult(e.target.checked)} required className="mt-1" />
              <span>{t("ageConfirm")}</span>
            </label>
          )}
          {err && <div className="text-red-500 text-sm">{err}</div>}
          <button disabled={busy || (mode === "register" && (!agreed || !adult))}
            className="w-full bg-accent text-white rounded-lg py-2.5 font-medium disabled:opacity-50">
            {busy ? "…" : mode === "login" ? t("signIn") : t("createAccount")}
          </button>
          {mode === "login" && (
            <div className="text-center text-xs"><Link href="/forgot" className="underline text-muted">{t("forgotLink")}</Link></div>
          )}
        </form>
        <div className="text-center text-xs text-muted mt-6">
          {t("footer")} · <a href="/privacy" className="underline">{t("privacy")}</a>
        </div>
      </div>
    </main>
  );
}
