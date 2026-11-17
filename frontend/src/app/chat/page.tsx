"use client";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import { api, clearToken, errMsg, streamSend, token, type Me, type Msg } from "@/lib/api";
import type { ChartData } from "@/components/Chart";
import type { PredictionsResponse } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import NorthChart from "@/components/Chart";
import ServiceAgreement from "@/components/ServiceAgreement";
import PredictionOutcome from "@/components/PredictionOutcome";

// chart messages carry either the chart map directly or {varga, chart: map}
const chartOf = (c: unknown) => ((c as { chart?: ChartData }).chart ?? (c as ChartData));
const vargaOf = (m: Msg) => m.meta.varga || (m.meta.chart as { varga?: string }).varga || "";

// dark mode lives in localStorage; read it as an external store (no setState in effects)
const darkSubs = new Set<() => void>();
const subscribeDark = (cb: () => void) => { darkSubs.add(cb); return () => { darkSubs.delete(cb); }; };
const getDark = () => localStorage.getItem("jyotish_dark") === "1";
const getDarkServer = () => false;

export default function Chat() {
  const router = useRouter();
  const { t, lang, setLang } = useI18n();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const dark = useSyncExternalStore(subscribeDark, getDark, getDarkServer);
  const [menu, setMenu] = useState(false);
  const [me, setMe] = useState<Me | null>(null);
  const [live, setLive] = useState<string | null>(null);
  const [bannerOff, setBannerOff] = useState(false);
  const [resendMsg, setResendMsg] = useState("");
  const [predOpen, setPredOpen] = useState(false);
  const [preds, setPreds] = useState<PredictionsResponse | null>(null);
  const [predErr, setPredErr] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const tempId = useRef(-1);
  const sending = useRef(false);
  const loadVersion = useRef(0);
  const [chatError, setChatError] = useState("");
  const [termsAgreed, setTermsAgreed] = useState(false);
  const [termsBusy, setTermsBusy] = useState(false);
  const [termsError, setTermsError] = useState("");

  useEffect(() => { document.documentElement.classList.toggle("dark", dark); }, [dark]);

  useEffect(() => {
    if (!token()) { router.replace("/login"); return; }
    let disposed = false;
    const load = async () => {
      if (sending.current) return;
      const version = ++loadVersion.current;
      try {
        const [account, history] = await Promise.all([api.me(), api.history()]);
        if (disposed || version !== loadVersion.current || sending.current) return;
        setMe(account);
        setMsgs(Array.isArray(history) ? history : history.messages || []);
        setChatError("");
      } catch (e) {
        if (!disposed && version === loadVersion.current) setChatError(errMsg(e));
      } finally {
        if (!disposed) setLoading(false);
      }
    };
    void load();
    const onFocus = () => { if (token()) void load(); else router.replace("/login"); };
    window.addEventListener("focus", onFocus);
    return () => { disposed = true; window.removeEventListener("focus", onFocus); };
  }, [router]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, busy, live]);

  function toggleDark() {
    localStorage.setItem("jyotish_dark", dark ? "0" : "1");
    darkSubs.forEach(cb => cb());
  }

  async function send(text: string) {
    text = text.trim();
    if (!text || sending.current || loading || chatError || me?.ai_terms_required) return;
    sending.current = true;
    ++loadVersion.current;
    setInput(""); setBusy(true); setChatError("");
    const optimisticId = tempId.current--;
    setMsgs(m => [...m, { id: optimisticId, role: "user", content: text, kind: "text", meta: {}, created_at: "" }]);
    try {
      setLive("");
      const added = await streamSend(text, d => setLive(l => (l ?? "") + d));
      setMsgs(m => {
        const ids = new Set(added.map(x => x.id));
        return [...m.filter(x => x.id !== optimisticId && !ids.has(x.id)), ...added];
      });
    } catch (e) {
      // A failed fetch may still have reached the server. Never automatically
      // POST the same turn again; let the user reload the saved conversation.
      setChatError(errMsg(e) || t("somethingWrong"));
    } finally {
      setLive(null); setBusy(false); sending.current = false;
    }
  }

  async function resendVerify() {
    try { await api.resendVerify(); setResendMsg(t("resent")); } catch (e) { setResendMsg(errMsg(e)); }
  }

  async function openPreds() {
    setMenu(false); setPredOpen(true); setPredErr("");
    try { setPreds(await api.predictions()); } catch (e) { setPredErr(errMsg(e)); }
  }

  async function acceptTerms() {
    if (!termsAgreed || termsBusy) return;
    setTermsBusy(true); setTermsError("");
    try {
      const accepted = await api.acceptTerms();
      setMe(m => m ? { ...m, ...accepted } : m);
    } catch (e) { setTermsError(errMsg(e)); }
    finally { setTermsBusy(false); }
  }

  async function downloadData() {
    setMenu(false);
    try {
      const data = await api.exportMe();
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const a = document.createElement("a");
      a.href = url; a.download = "jyotish-ai-my-data.json"; a.click();
      URL.revokeObjectURL(url);
    } catch {}
  }

  async function deleteAccount() {
    setMenu(false);
    if (!confirm(t("confirmDelete"))) return;
    try { await api.deleteMe(); } catch {}
    clearToken(); router.replace("/login");
  }

  async function reset() {
    if (sending.current) return;
    sending.current = true;
    ++loadVersion.current;
    setBusy(true);
    try {
      await api.resetChat();
      const h = await api.history();
      setMsgs(Array.isArray(h) ? h : h.messages || []);
      setChatError("");
    } catch (e) { setChatError(errMsg(e)); }
    finally { setBusy(false); sending.current = false; }
  }

  const lastOptIdx = msgs.reduce((acc, m, i) => (m.kind === "options" && m.meta?.options?.length ? i : acc), -1);
  const optionsActive = lastOptIdx >= 0 && lastOptIdx > msgs.reduce((acc, m, i) => (m.role === "user" ? i : acc), -1);

  return (
    <div className="h-dvh flex flex-col max-w-2xl mx-auto">
      <header className="flex items-center justify-between px-4 py-3 border-b border-bord">
        <div>
          <div className="font-serif-astro text-lg leading-tight">{t("appName")}</div>
          <div className="text-xs text-muted">{me ? t("forName", { name: me.display_name || me.email }) : ""}</div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={toggleDark} className="text-sm text-muted border border-bord rounded-lg px-3 py-1.5">
            {dark ? t("light") : t("dark")}
          </button>
          <div className="relative">
            <button onClick={() => setMenu(!menu)} className="w-8 h-8 rounded-full bg-accentsoft text-accent font-bold">
              {(me?.display_name || me?.email || "?")[0].toUpperCase()}
            </button>
            {menu && (
              <div className="absolute right-0 mt-2 w-56 bg-card border border-bord rounded-lg shadow-lg text-sm z-20">
                <button onClick={() => router.push("/birth")} className="w-full text-left px-3 py-2 hover:bg-bgsoft">{t("editBirth")}</button>
                <button onClick={openPreds} className="w-full text-left px-3 py-2 hover:bg-bgsoft">{t("myPredictions")}</button>
                <button onClick={() => { setLang(lang === "en" ? "hi" : "en"); setMenu(false); }} className="w-full text-left px-3 py-2 hover:bg-bgsoft">{t("language")}</button>
                <button onClick={() => { setMenu(false); reset(); }} className="w-full text-left px-3 py-2 hover:bg-bgsoft">{t("restart")}</button>
                <button onClick={downloadData} className="w-full text-left px-3 py-2 hover:bg-bgsoft">{t("download")}</button>
                <a href="/terms" className="block px-3 py-2 hover:bg-bgsoft">{t("termsLink")}</a>
                <a href="/privacy" className="block px-3 py-2 hover:bg-bgsoft">{t("privacyPolicy")}</a>
                <button onClick={deleteAccount} className="w-full text-left px-3 py-2 hover:bg-bgsoft text-red-500">{t("deleteAccount")}</button>
                <button onClick={() => { clearToken(); router.replace("/login"); }} className="w-full text-left px-3 py-2 hover:bg-bgsoft text-red-500">{t("signOut")}</button>
              </div>
            )}
          </div>
        </div>
      </header>

      {me && me.email_verified === false && !bannerOff && (
        <div className="flex items-center justify-between gap-2 px-4 py-1.5 text-xs bg-accentsoft text-accent" role="status">
          <span>{resendMsg || t("verifyBanner")}</span>
          <span className="flex items-center gap-2">
            <button onClick={resendVerify} className="underline">{t("resend")}</button>
            <button onClick={() => setBannerOff(true)} aria-label={t("dismiss")} className="font-bold">×</button>
          </span>
        </div>
      )}

      <div className="flex-1 min-h-0 overflow-y-auto px-4 py-4 space-y-4">
        {loading && <div className="text-center text-muted text-sm mt-10">{t("drawing")}</div>}
        {msgs.map((m, i) => {
          if (m.kind === "options") {
            return (
              <div key={m.id}>
                <div className="flex justify-start">
                  <div className="max-w-[85%] rounded-2xl px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap bg-card border border-bord rounded-bl-sm">
                    {m.content}
                  </div>
                </div>
                {i === lastOptIdx && optionsActive && !busy && (
                  <div className="flex flex-wrap gap-2 justify-end mt-2">
                    {(m.meta.options ?? []).map(o => (
                      <button key={o} onClick={() => (m.meta.actions?.[o] === "edit_birth" ? router.push("/birth") : send(o))}
                        className="border border-accent text-accent rounded-full px-4 py-1.5 text-sm hover:bg-accent hover:text-white transition">
                        {o}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            );
          }
          const mine = m.role === "user";
          return (
            <div key={m.id} className={`flex ${mine ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap
                ${mine ? "bg-accent text-white rounded-br-sm" : "bg-card border border-bord rounded-bl-sm"}`}>
                {m.content}
                {m.kind === "chart" && !!m.meta?.chart && (
                  <div className="mt-3 bg-bgsoft rounded-xl p-3">
                    <NorthChart varga={vargaOf(m)} chart={chartOf(m.meta.chart)} />
                  </div>
                )}

              </div>
            </div>
          );
        })}
        {busy && live ? (
          <div className="flex justify-start">
            <div className="max-w-[85%] rounded-2xl px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap bg-card border border-bord rounded-bl-sm">
              {live}
            </div>
          </div>
        ) : busy && (
          <div className="flex"><div className="bg-card border border-bord rounded-2xl rounded-bl-sm px-4 py-3 text-muted text-sm">
            <span className="animate-pulse">{t("thinking")}</span>
          </div></div>
        )}
        <div ref={endRef} />
      </div>

      {me?.ai_terms_required && (
        <section className="border-t border-bord bg-card px-4 py-4 space-y-3" aria-label={t("updatedTerms")}>
          <h2 className="font-semibold">{t("updatedTerms")}</h2>
          <p className="text-sm text-muted">{t("updatedTermsNote")}</p>
          <ServiceAgreement checked={termsAgreed} onChange={setTermsAgreed} />
          {termsError && <p role="alert" className="text-sm text-red-500">{termsError}</p>}
          <button onClick={acceptTerms} disabled={!termsAgreed || termsBusy} className="bg-accent text-white rounded-lg px-4 py-2 disabled:opacity-40">
            {termsBusy ? t("loading") : t("acceptContinue")}
          </button>
        </section>
      )}
      {chatError && (
        <div role="alert" className="px-4 py-3 text-sm border-t border-bord">
          <p>{chatError}</p>
          <button onClick={() => window.location.reload()} className="text-accent underline mt-1">
            {t("reloadChat")}
          </button>
        </div>
      )}
      <div className="border-t border-bord p-3">
        <div className="flex gap-2">
          <input value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.nativeEvent.isComposing) { e.preventDefault(); void send(input); } }}
            aria-label={t("askPh")} disabled={loading || !!chatError || !!me?.ai_terms_required}
            placeholder={t("askPh")}
            className="flex-1 border border-bord rounded-full px-4 py-2.5 bg-transparent text-[15px] outline-none focus:border-accent" />
          <button onClick={() => send(input)} disabled={busy || loading || !!chatError || !!me?.ai_terms_required || !input.trim()}
            className="bg-accent text-white rounded-full px-5 py-2.5 font-medium disabled:opacity-40">{t("send")}</button>
        </div>
      </div>

      {predOpen && (
        <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-label={t("predTitle")}
          onClick={() => setPredOpen(false)}>
          <div className="w-full max-w-md max-h-[80vh] overflow-y-auto bg-card border border-bord rounded-2xl p-5 shadow-lg" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-serif-astro text-xl">{t("predTitle")}</h2>
              <button onClick={() => setPredOpen(false)} className="text-sm text-muted border border-bord rounded-lg px-3 py-1">{t("close")}</button>
            </div>
            {predErr ? <div className="text-red-500 text-sm">{predErr}</div>
              : !preds ? <div className="text-muted text-sm">{t("loading")}</div>
              : (
                <>
                  {preds.scorecard && <section aria-label={t("scorecard")} className="mb-4 space-y-2">
                    <h3 className="font-semibold text-sm">{t("scorecard")}</h3>
                    <p className="text-xs text-muted">{t("scorecardNote")}</p>
                    <dl className="grid grid-cols-3 gap-2 text-center text-xs">
                      {([["issued_forecasts", "issuedForecasts"], ["abstentions", "abstentions"], ["scored", "scoredOutcomes"], ["hits", "hits"], ["misses", "misses"], ["unresolved", "pending"]] as const).map(([key, label]) => <div key={key} className="bg-bgsoft rounded-lg p-2"><dt>{t(label)}</dt><dd className="text-lg font-semibold">{preds.scorecard![key]}</dd></div>)}
                    </dl>
                  </section>}
                  <div className="grid grid-cols-3 gap-2 text-center text-xs mb-4">
                    {([["total", "total"], ["happened", "happened"], ["partly", "partly"], ["did_not", "didNot"], ["unsure", "unsure"], ["pending", "pending"]] as const).map(([k, label]) => (
                      <div key={k} className="bg-bgsoft rounded-lg py-2">
                        <div className="text-lg font-semibold">{preds.aggregate[k]}</div>
                        <div className="text-muted">{t(label)}</div>
                      </div>
                    ))}
                  </div>
                  {preds.predictions.length === 0 && <div className="text-muted text-sm">{t("noPredictions")}</div>}
                  <ul className="space-y-2">
                    {preds.predictions.map(r => {
                      const o = r.outcome;
                      const label = o === "happened" ? t("happened") : o === "partly" ? t("partly") : o === "did_not" ? t("didNot") : o === "unsure" ? t("unsure") : o === "outside_window" ? t("outsideWindow") : t("pending");
                      return (
                        <li key={r.id} className="border border-bord rounded-lg p-2.5 text-sm">
                          <div><span className="font-medium capitalize">{r.domain}</span>{r.question ? ` — ${r.question}` : ""}</div>
                          {r.success_criteria && <p className="mt-1 text-xs">{r.success_criteria}</p>}
                          {r.forecast === "abstain" && <p className="text-xs text-muted">{t("abstentions")}</p>}
                          {r.window_start && r.window_end && (
                            <div className="text-xs text-muted">{r.window_start} → {r.window_end}</div>
                          )}
                          <div className="mt-1 text-xs text-muted flex justify-between">
                            <span className="inline-block rounded-md bg-accentsoft text-accent px-2 py-0.5 font-medium">{r.forecast === "abstain" ? t("abstentions") : label}</span>
                            <span>{(r.created_at || "").slice(0, 10)}</span>
                          </div>
                          <PredictionOutcome record={r} onSaved={async () => { setPreds(await api.predictions()); }} />
                        </li>
                      );
                    })}
                  </ul>
                </>
              )}
          </div>
        </div>
      )}
    </div>
  );
}
