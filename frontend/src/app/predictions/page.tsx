"use client";

import AppNav from "@/components/AppNav";
import { useEffect, useState } from "react";
import { api, errMsg, type OutcomePrediction } from "@/lib/api";
import { useI18n, type Key } from "@/lib/i18n";

const CHOICES: [string, Key][] = [["happened", "happened"], ["partly", "partly"], ["did_not", "didNot"],
  ["outside_window", "outsideWindow"], ["unsure", "unsure"]];
const LABEL: Record<string, Key> = { happened: "happened", partly: "partly", did_not: "didNot", outside_window: "outsideWindow", unsure: "unsure" };

function DueCard({ row, onSaved }: { row: OutcomePrediction; onSaved: () => void }) {
  const { t } = useI18n();
  const [choice, setChoice] = useState("");
  const [date, setDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const needsDate = choice === "happened";
  async function save() {
    setBusy(true); setError("");
    try { await api.predictionOutcome(row.id, choice, date || undefined); onSaved(); }
    catch (e) { setError(errMsg(e)); }
    finally { setBusy(false); }
  }
  return (
    <li className="rounded-xl border border-bord bg-card p-4 space-y-2 text-sm">
      <p className="font-medium">{row.question}</p>
      {row.success_criteria && <p className="text-muted">{row.success_criteria}</p>}
      <p className="text-xs text-muted">{t("windowLabel")}: {row.window_start} – {row.window_end}</p>
      <div className="flex flex-wrap gap-2">
        {CHOICES.map(([value, key]) => (
          <button key={value} onClick={() => setChoice(value)} aria-pressed={choice === value}
            className={`rounded-full border border-accent px-3 py-1 ${choice === value ? "bg-accent text-white" : "text-accent"}`}>{t(key)}</button>
        ))}
      </div>
      {(choice === "happened" || choice === "outside_window") && (
        <label className="flex items-center gap-2">{t("eventDate")}
          <input type="date" value={date} max={new Date().toISOString().slice(0, 10)} onChange={e => setDate(e.target.value)}
            className="rounded border border-bord bg-transparent px-2 py-1" />
        </label>
      )}
      {error && <p role="alert" className="text-red-500">{error}</p>}
      <button onClick={save} disabled={!choice || busy || (needsDate && !date)}
        className="rounded-lg bg-accent px-4 py-1.5 text-white disabled:opacity-40">{t("saveOutcome")}</button>
    </li>
  );
}

export default function PredictionsPage() {
  const { t } = useI18n();
  const [due, setDue] = useState<OutcomePrediction[]>();
  const [answered, setAnswered] = useState<OutcomePrediction[]>([]);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let active = true;
    Promise.all([api.duePredictions(), api.answeredPredictions()])
      .then(([d, a]) => { if (active) { setDue(d.due); setAnswered(a.answered); setError(""); } })
      .catch(e => { if (active) setError(errMsg(e)); });
    return () => { active = false; };
  }, [version]);
  return (
    <main className="mx-auto max-w-2xl space-y-5 px-4 py-7 sm:px-8">
      <AppNav />
      <h1 className="font-serif-astro text-3xl">{t("pastPredictions")}</h1>
      <p className="text-sm text-muted">{t("outcomeNote")}</p>
      {error && <p role="alert" className="text-red-500">{error}</p>}
      {!due && !error && <p role="status">{t("loading")}</p>}
      {saved && <p role="status" className="text-sm">{t("outcomeSaved")}</p>}
      {due && (
        <section className="space-y-3" aria-label={t("duePredictions")}>
          <h2 className="font-semibold">{t("duePredictions")}</h2>
          {due.length === 0 && <p className="text-sm text-muted">{t("nothingDue")}</p>}
          <ul className="space-y-3">{due.map(r => <DueCard key={r.id} row={r} onSaved={() => { setSaved(true); setVersion(v => v + 1); }} />)}</ul>
        </section>
      )}
      {answered.length > 0 && (
        <section className="space-y-2" aria-label={t("answeredPredictions")}>
          <h2 className="font-semibold">{t("answeredPredictions")}</h2>
          <ul className="space-y-2">{answered.map(r => (
            <li key={r.id} className="rounded-lg border border-bord p-3 text-sm">
              <p>{r.question}</p>
              <p className="text-xs text-muted">{r.window_start} – {r.window_end} · {r.outcome ? t(LABEL[r.outcome]) : ""}{r.event_date ? ` · ${r.event_date}` : ""}</p>
            </li>))}</ul>
        </section>
      )}
    </main>
  );
}
