"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import AppNav from "@/components/AppNav";
import { ConfidenceChip, VerdictChip, formatWindow } from "@/components/AnswerCard";
import { api, errMsg, getHome, token, type HomeOverview, type HomeYearItem } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

const panel = "rounded-xl border border-bord bg-card p-4 sm:p-6";
const CAUTION = ["not_indicated", "weak"];

// Fallback when /api/home is not available: build the brief from the chart dashboard.
async function briefFromDashboard(): Promise<HomeOverview> {
  const d = await api.chartDashboard();
  const lagnaSign = d.vargas?.D1?.Lagna?.sign;
  const moon = d.planets?.Moon;
  const SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"];
  const today = d.dashas?.date ?? new Date().toISOString().slice(0, 10);
  const cur = d.dashas?.vimshottari?.find(x => x.start <= today && today < x.end);
  return {
    chart_brief: {
      lagna: lagnaSign === undefined ? null : SIGNS[lagnaSign],
      moon_sign: moon?.sign_name ?? "", nakshatra: moon?.nakshatra?.name ?? "",
      current_dasha: cur?.lords?.length ? { maha: cur.lords[0], antar: cur.lords[1] ?? cur.lords[0], until: cur.end } : null,
      time_known: d.time_known !== false,
    },
    year_overview: [], chart_check: { state: "unknown" }, suggested_questions: [],
  };
}

export default function Home() {
  const router = useRouter();
  const { t, lang } = useI18n();
  const [data, setData] = useState<HomeOverview | null>(null);
  const [partial, setPartial] = useState(false);   // /api/home missing: brief only
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);
  const retry = useCallback(() => { setLoading(true); setError(""); setVersion(v => v + 1); }, []);

  useEffect(() => {
    if (!token()) { router.replace("/login"); return; }
    let active = true;
    (async () => {
      try {
        const h = await getHome();
        if (!active) return;
        if (h) { setData(h); setPartial(false); }
        else {
          setPartial(true);
          setData(await briefFromDashboard().catch(() => null));
        }
      } catch (e) { if (active) setError(errMsg(e)); }
      finally { if (active) setLoading(false); }
    })();
    return () => { active = false; };
  }, [router, version]);

  const ask = (q: string) => router.push(`/chat?q=${encodeURIComponent(q)}`);
  const fmtDate = (d: string) => {
    const dt = new Date(d);
    return isNaN(dt.getTime()) ? d : dt.toLocaleDateString(lang === "hi" ? "hi-IN" : "en-GB", { month: "long", year: "numeric" });
  };

  const brief = data?.chart_brief;
  const dasha = brief?.current_dasha;
  const dashaText = !dasha ? "" : typeof dasha === "string" ? dasha
    : t("homeDashaText", { maha: dasha.maha, antar: dasha.antar, until: fmtDate(dasha.until) });

  const items = data?.year_overview ?? [];
  const caution = items.find(i => CAUTION.includes(i.verdict));
  const top = items.filter(i => i !== caution).slice(0, 3);

  const topicCard = (i: HomeYearItem, warn = false) => {
    const w = formatWindow(i.window, lang);
    return (
      <li key={i.topic}>
        <button type="button" onClick={() => ask(i.label)} aria-label={`${i.label}. ${t("homeAskTopic")}`}
          className={`h-full w-full space-y-2 rounded-xl border bg-card p-4 text-left hover:border-accent ${warn ? "border-amber-500/60" : "border-bord"}`}>
          {warn && <div className="text-xs font-medium text-amber-700 dark:text-amber-400">{t("homeCaution")}</div>}
          <div className="font-serif-astro text-lg">{i.label}</div>
          <div className="flex flex-wrap items-center gap-2"><VerdictChip verdict={i.verdict} /><ConfidenceChip level={i.confidence} /></div>
          <div className="text-xs text-muted">{t("homeWhen")}: {w ?? t("homeNoWindow")}</div>
          {i.why[0] && <p className="text-sm">{i.why[0].text}</p>}
        </button>
      </li>
    );
  };

  const cc = data?.chart_check;
  const checked = !!cc && ["checked", "verified", "done", "good", "ok"].includes(cc.state);

  return (
    <div className="mx-auto flex min-h-dvh max-w-3xl flex-col">
      <AppNav />
      <main className="space-y-6 px-4 py-6 sm:px-8">
        <h1 className="font-serif-astro text-3xl sm:text-4xl">{t("homeTitle")}</h1>
        {loading && <p role="status">{t("loading")}</p>}
        {error && (
          <div role="alert" className={panel}>
            <p className="text-red-500">{error}</p>
            <button type="button" onClick={retry} className="mt-3 rounded-lg bg-accent px-4 py-2 text-white">{t("homeRetry")}</button>
          </div>
        )}
        {!loading && !error && (
          <>
            {brief && (
              <section aria-labelledby="h-brief" className={`${panel} space-y-3`}>
                <h2 id="h-brief" className="font-serif-astro text-xl">{t("homeBrief")}</h2>
                <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
                  {[["homeLagna", brief.lagna], ["homeMoon", brief.moon_sign], ["homeNakshatra", brief.nakshatra]].map(([k, v]) => (
                    <div key={k as string}><dt className="text-xs text-muted">{t(k as "homeLagna")}</dt><dd className="text-base font-medium">{v || "—"}</dd></div>
                  ))}
                </dl>
                {dashaText && <p className="text-sm"><span className="text-muted">{t("homeDasha")}: </span>{dashaText}</p>}
                {!brief.time_known && <p role="status" className="rounded-lg bg-accentsoft p-3 text-sm">{t("homeTimeUnknown")}</p>}
              </section>
            )}
            {partial && (
              <div role="status" className={`${panel} space-y-3 text-sm`}>
                <p>{t("homeComingSoon")}</p>
                <button type="button" onClick={() => router.push("/chat")} className="rounded-lg bg-accent px-4 py-2 text-white">{t("homeOpenChat")}</button>
              </div>
            )}
            {!partial && !brief && <p className="text-muted">{t("homeEmpty")}</p>}
            {!partial && (
              <>
                <section aria-labelledby="h-year" className="space-y-3">
                  <h2 id="h-year" className="font-serif-astro text-xl">{t("homeThisYear")}</h2>
                  {items.length === 0 ? <p className="text-sm text-muted">{t("homeEmpty")}</p> : (
                    <ul className="grid gap-3 sm:grid-cols-2">{top.map(i => topicCard(i))}{caution && topicCard(caution, true)}</ul>
                  )}
                </section>
                {cc && (
                  <section aria-labelledby="h-check" className={`${panel} space-y-2`}>
                    <h2 id="h-check" className="font-serif-astro text-xl">{t("homeChartCheck")}</h2>
                    <p className="text-sm" role="status">{checked ? t("ccGood") : t("ccNot")}{cc.personal_fit ? ` (${cc.personal_fit})` : ""}</p>
                    {!checked && <button type="button" onClick={() => ask(t("ccQuestion"))} className="rounded-lg bg-accent px-4 py-2 text-white">{t("ccButton")}</button>}
                  </section>
                )}
                {!!data?.suggested_questions?.length && (
                  <section aria-labelledby="h-q" className="space-y-3">
                    <h2 id="h-q" className="font-serif-astro text-xl">{t("homeSuggested")}</h2>
                    <ul className="flex flex-wrap gap-2">
                      {data.suggested_questions.slice(0, 6).map(q => (
                        <li key={q}><button type="button" onClick={() => ask(q)} className="rounded-full border border-bord bg-card px-3 py-1.5 text-sm hover:border-accent">{q}</button></li>
                      ))}
                    </ul>
                  </section>
                )}
              </>
            )}
          </>
        )}
      </main>
    </div>
  );
}
