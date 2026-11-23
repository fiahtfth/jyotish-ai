"use client";
import { useId, useState } from "react";
import { useI18n, type Key } from "@/lib/i18n";
import type { Confidence, Verdict } from "@/lib/api";

export type Card = {
  topic: string;
  verdict: Verdict;
  window: { start: string; end: string } | null;
  confidence: Confidence;
  why: { text: string; fact_ids?: (string | number)[] }[];
  action: string;
  details?: string;
};

const VERDICT: Record<Verdict, Key> = { likely: "vLikely", mixed: "vMixed", not_indicated: "vNotIndicated", strong: "vStrong", moderate: "vModerate", weak: "vWeak" };
const CONF: Record<Confidence, Key> = { high: "confHigh", medium: "confMedium", low: "confLow" };
const verdictTone: Record<Verdict, string> = {
  likely: "bg-green-500/15 text-green-700 dark:text-green-400", strong: "bg-green-500/15 text-green-700 dark:text-green-400",
  mixed: "bg-amber-500/15 text-amber-700 dark:text-amber-400", moderate: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  not_indicated: "bg-bgsoft text-muted", weak: "bg-bgsoft text-muted",
};

export function formatWindow(w: { start: string; end: string } | null, lang: string): string | null {
  if (!w) return null;
  // date-only strings ("2027-03-01") must parse as local dates — new Date(d)
  // reads them as UTC and shifts the month backward west of UTC. The end is
  // exclusive, so show the last covered month, not the boundary itself.
  const f = (d: string, end = false) => {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d);
    if (!m) return d;
    let dt = new Date(+m[1], +m[2] - 1, +m[3]);
    if (end) dt = new Date(dt.getFullYear(), dt.getMonth(), dt.getDate() - 1);
    return dt.toLocaleDateString(lang === "hi" ? "hi-IN" : "en-GB", { month: "short", year: "numeric" });
  };
  const a = f(w.start), b = f(w.end, true);
  return a === b ? a : `${a} – ${b}`;
}

export function ConfidenceChip({ level }: { level: Confidence }) {
  const { t } = useI18n();
  return <span className="rounded-full border border-bord px-2 py-0.5 text-xs text-muted">{t(CONF[level])}</span>;
}
export function VerdictChip({ verdict }: { verdict: Verdict }) {
  const { t } = useI18n();
  return <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${verdictTone[verdict]}`}>{t(VERDICT[verdict])}</span>;
}

export default function AnswerCard({ card, onSecondOpinion }: { card: Card; onSecondOpinion?: () => void }) {
  const { t, lang } = useI18n();
  const [open, setOpen] = useState(false);
  const id = useId();
  const when = formatWindow(card.window, lang);
  const row = "grid gap-1 sm:grid-cols-[8rem_1fr] sm:gap-3";
  const label = "text-xs font-medium uppercase tracking-wide text-muted";
  return (
    <article aria-label={card.topic} className="space-y-3 rounded-xl border border-bord bg-card p-4 text-sm sm:p-5">
      <h3 className="font-serif-astro text-xl">{card.topic}</h3>
      <div className={row}><div className={label}>{t("acAnswer")}</div><div><VerdictChip verdict={card.verdict} /></div></div>
      <div className={row}><div className={label}>{t("acWhen")}</div><div>{when ?? <span className="text-muted">{t("acNoWindow")}</span>}</div></div>
      <div className={row}><div className={label}>{t("acWhy")}</div>
        <ul className="list-disc space-y-1 pl-4">{card.why.map((w, i) => <li key={i}>{w.text}</li>)}</ul></div>
      <div className={row}><div className={label}>{t("acConfidence")}</div><div><ConfidenceChip level={card.confidence} /></div></div>
      {card.action && <div className={row}><div className={label}>{t("acDo")}</div><div>{card.action}</div></div>}
      <div className="flex flex-wrap gap-2 pt-1">
        {card.details && (
          <button type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}
            className="rounded-lg border border-bord px-3 py-1.5 text-accent">{open ? t("acHideWhy") : t("acWhyBtn")}</button>
        )}
        {onSecondOpinion && (
          <button type="button" onClick={onSecondOpinion} className="rounded-lg border border-bord px-3 py-1.5 text-accent">{t("acSecond")}</button>
        )}
      </div>
      <div id={id} aria-live="polite">
        {open && card.details && <p className="whitespace-pre-line rounded-lg bg-bgsoft p-3 text-muted">{card.details}</p>}
      </div>
    </article>
  );
}
