"use client";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import { api, clearToken, errMsg, streamSend, StreamBroken, StreamServerError, token, type Me, type Msg } from "@/lib/api";
import type { ChartData } from "@/components/Chart";
import type { PredictionsResponse } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import NorthChart from "@/components/Chart";

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

  useEffect(() => { document.documentElement.classList.toggle("dark", dark); }, [dark]);

  useEffect(() => {
    if (!token()) { router.replace("/login"); return; }
    const load = () => Promise.all([
      api.me().then(setMe).catch(() => {}),
      api.history().then(h => setMsgs(Array.isArray(h) ? h : h.messages || [])),
    ]).catch((e) => { if (e.message === "profile needed") router.replace("/birth"); })
      .finally(() => setLoading(false));
    load();
    // token may have been replaced in another tab — reload the right account's chat
    const onFocus = () => { if (token()) load(); };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [router]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, busy, live]);

  function toggleDark() {
    localStorage.setItem("jyotish_dark", dark ? "0" : "1");
    darkSubs.forEach(cb => cb());
  }

  async function send(text: string) {
    if (!text.trim() || busy) return;
    setInput(""); setBusy(true);
    setMsgs(m => [...m, { id: tempId.current--, role: "user", content: text, kind: "text", meta: {}, created_at: "" }]);
    const apply = (added: Msg[]) => setMsgs(m => {
      // done messages are authoritative: replace the optimistic user message
      const kept = m.filter(x => x.id >= 0 || x.content !== text);
      return [...kept, ...added];
    });
    try {
      setLive("");
      let added: Msg[] | null = null;
      try {
        added = await streamSend(text, d => setLive(l => (l ?? "") + d));
      } catch (e) {
        if (errMsg(e) === "profile needed" || errMsg(e) === "unauthorized") throw e;
        setLive(null);
        // server-reported failure: keep the optimistic message, show the error text
        if (e instanceof StreamServerError) throw e;
        if (e instanceof StreamBroken) {
          // server already persisted the turn (it finishes even if we disconnect):
          // reload history instead of resending, which would duplicate it
          const h = await api.history();
          setMsgs(Array.isArray(h) ? h : h.messages || []);
        } else {
          added = await api.send(text); // never accepted: safe to use the non-streaming endpoint
        }
      }
      if (added) apply(added);
    } catch (e) {
      if (errMsg(e) === "profile needed") router.replace("/birth");
      setMsgs(m => [...m, { id: tempId.current--, role: "assistant", content: t("somethingWrong"), kind: "text", meta: {}, created_at: "" }]);
    } finally { setLive(null); setBusy(false); }
  }

  async function resendVerify() {
    try { await api.resendVerify(); setResendMsg(t("resent")); } catch (e) { setResendMsg(errMsg(e)); }
  }

  async function openPreds() {
    setMenu(false); setPredOpen(true); setPredErr("");
    try { setPreds(await api.predictions()); } catch (e) { setPredErr(errMsg(e)); }
  }

  async function toggleConsent() {
    setMenu(false);
    try {
      const r = await api.setConsent(!me?.llm_consent);
      setMe(m => (m ? { ...m, llm_consent: r.llm_consent } : m));
    } catch {}
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
    setBusy(true);
    try {
      await api.resetChat();
      const h = await api.history();
      setMsgs(Array.isArray(h) ? h : []);
    } catch {} finally { setBusy(false); }
  }

  const lastOptIdx = msgs.reduce((acc, m, i) => (m.kind === "options" && m.meta?.options?.length ? i : acc), -1);
  const optionsActive = lastOptIdx >= 0 && lastOptIdx > msgs.reduce((acc, m, i) => (m.role === "user" ? i : acc), -1);

  return (
    <div className="h-screen flex flex-col max-w-2xl mx-auto">
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
                <button onClick={toggleConsent} className="w-full text-left px-3 py-2 hover:bg-bgsoft">
                  {me?.llm_consent ? t("stopAI") : t("allowAI")}
                </button>
                <button onClick={downloadData} className="w-full text-left px-3 py-2 hover:bg-bgsoft">{t("download")}</button>
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

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
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
                {m.kind === "analysis" && (
                  <div className="mt-2 text-xs text-muted border-t border-bord pt-2">
                    {t("convergence")}: {m.meta.convergence || "—"} · {t("support")} {m.meta.support_count ?? "—"}
                  </div>
                )}
                {m.meta?.analysis?.convergence && (
                  <div className="mt-2 text-xs text-muted border-t border-bord pt-2">
                    <span className="inline-block rounded-md bg-accentsoft text-accent px-2 py-0.5 font-medium">
                      {m.meta.analysis.convergence}
                    </span>
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

      <div className="border-t border-bord p-3">
        <div className="flex gap-2">
          <input value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === "Enter" && send(input)}
            placeholder={t("askPh")}
            className="flex-1 border border-bord rounded-full px-4 py-2.5 bg-transparent text-[15px] outline-none focus:border-accent" />
          <button onClick={() => send(input)} disabled={busy || !input.trim()}
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
                      const label = o === "happened" ? t("happened") : o === "partly" ? t("partly") : o === "did_not" ? t("didNot") : o === "unsure" ? t("unsure") : t("pending");
                      return (
                        <li key={r.id} className="border border-bord rounded-lg p-2.5 text-sm">
                          <div><span className="font-medium capitalize">{r.domain}</span>{r.question ? ` — ${r.question}` : ""}</div>
                          {r.window_start && r.window_end && (
                            <div className="text-xs text-muted">{r.window_start} → {r.window_end}</div>
                          )}
                          <div className="mt-1 text-xs text-muted flex justify-between">
                            <span className="inline-block rounded-md bg-accentsoft text-accent px-2 py-0.5 font-medium">{label}</span>
                            <span>{(r.created_at || "").slice(0, 10)}</span>
                          </div>
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
