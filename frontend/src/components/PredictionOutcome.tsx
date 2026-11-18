"use client";
import { useState } from "react";
import { api, errMsg, type PredictionRecord } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function PredictionOutcome({ record, onSaved }: { record: PredictionRecord; onSaved: () => Promise<void> }) {
  const { t } = useI18n();
  const [outcome, setOutcome] = useState("unsure");
  const [eventDate, setEventDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (record.forecast !== "event_indicated" || !record.window_end || record.window_end >= new Date().toISOString().slice(0, 10)) return null;
  async function save() {
    setBusy(true); setError("");
    try { await api.predictionOutcome(record.id, outcome, outcome === "happened" || outcome === "outside_window" ? eventDate || undefined : undefined); await onSaved(); }
    catch (e) { setError(errMsg(e)); }
    finally { setBusy(false); }
  }
  return (
    <div className="mt-3 space-y-2 border-t border-bord pt-2">
      <label className="block text-xs">{t("recordOutcome")}
        <select value={outcome} onChange={e => setOutcome(e.target.value)} className="block w-full border border-bord rounded bg-card p-2 mt-1">
          <option value="happened">{t("happened")}</option><option value="partly">{t("partly")}</option>
          <option value="did_not">{t("didNot")}</option><option value="outside_window">{t("outsideWindow")}</option><option value="unsure">{t("unsure")}</option>
        </select>
      </label>
      {(outcome === "happened" || outcome === "outside_window") && <label className="block text-xs">{t("eventDate")}
        <input type="date" value={eventDate} onChange={e => setEventDate(e.target.value)} max={new Date().toISOString().slice(0, 10)} className="block border border-bord rounded bg-transparent p-2 mt-1" />
      </label>}
      <button onClick={save} disabled={busy || outcome === "happened" && !eventDate} className="text-accent underline text-xs disabled:opacity-40">{busy ? t("loading") : t("saveOutcome")}</button>
      {error && <p role="alert" className="text-xs text-red-500">{error}</p>}
    </div>
  );
}
