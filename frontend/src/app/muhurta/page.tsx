"use client";
import { useState } from "react";
import { apiExtra, errMsg, type MuhurtaResult, type Place } from "@/lib/api";
import ServiceNav, { button, input, panel } from "@/components/ServiceNav";
import PlacePicker from "@/components/PlacePicker";

const EVENTS: [string, string][] = [["vivah", "Vivah (marriage)"], ["griha_pravesh", "Griha pravesh"], ["vehicle", "Vehicle purchase"],
  ["business", "Business start"], ["property", "Property purchase"], ["travel", "Travel"], ["namkaran", "Namkaran"]];
const iso = (d: Date) => d.toISOString().slice(0, 10);

export default function Muhurta() {
  const today = new Date();
  const [event, setEvent] = useState("vivah");
  const [start, setStart] = useState(iso(today));
  const [end, setEnd] = useState(iso(new Date(today.getTime() + 14 * 864e5)));
  const [place, setPlace] = useState<Place | null>(null);
  const [direction, setDirection] = useState("");
  const [res, setRes] = useState<MuhurtaResult>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      setRes(await apiExtra.muhurta({ event, start, end, direction: direction || undefined,
        ...(place ? { latitude: place.latitude, longitude: place.longitude, place_name: place.name } : {}) }));
    } catch (er) { setError(errMsg(er)); } finally { setBusy(false); }
  }

  return (
    <main className="mx-auto max-w-5xl space-y-6 px-4 py-6 sm:px-8 sm:py-10">
      <ServiceNav title="Muhurta" />
      <form onSubmit={run} className={`${panel} space-y-4`}>
        <div className="flex flex-wrap gap-4">
          <label className="grid gap-2 text-sm">Event<select className={input} value={event} onChange={e => setEvent(e.target.value)}>
            {EVENTS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label className="grid gap-2 text-sm">From<input type="date" className={input} value={start} onChange={e => setStart(e.target.value)} required /></label>
          <label className="grid gap-2 text-sm">Until (max 45 days)<input type="date" className={input} value={end} onChange={e => setEnd(e.target.value)} required /></label>
          {event === "travel" && <label className="grid gap-2 text-sm">Direction<select className={input} value={direction} onChange={e => setDirection(e.target.value)}>
            <option value="">Not specified</option>{["east", "west", "north", "south"].map(d => <option key={d}>{d}</option>)}</select></label>}
        </div>
        <PlacePicker label="Location (default: your current residence, else birthplace)" value={place} onPick={setPlace} />
        <button className={button} disabled={busy}>{busy ? "Scanning…" : "Find muhurta windows"}</button>
      </form>
      {error && <p role="alert" className="rounded-lg border border-bord p-3">{error}</p>}
      {res && <>
        <p className="text-sm text-muted">{res.event_label} at {res.location.name || `${res.location.latitude}, ${res.location.longitude}`}
          {res.location.source ? ` (${res.location.source.replace("_", " ")})` : ""} · {res.accepted_steps} of {res.scanned_steps} 15-minute steps passed every exclusion
          {res.native_moon ? ` · Tara and Chandra bala from your Moon (${res.native_moon})` : ""}</p>
        <p className="text-sm">{res.event_rules.note} Lagna: {res.event_rules.lagna}.</p>
        {!res.slots.length && <p role="status" className="rounded-lg bg-accentsoft p-3">No window passes all exclusions in this range. See the reasons below and try other dates.</p>}
        {res.slots.map((s, i) => <section key={i} className={panel}>
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="font-medium">{s.weekday} {s.date}, {s.start}–{s.end} · Lagna {s.lagna}</h2>
            <span className="rounded-full bg-accentsoft px-3 py-1 text-sm">{s.badge}</span></div>
          <p className="mt-1 text-sm text-muted">{s.paksha} {s.tithi} · {s.nakshatra} · {s.yoga} · {s.karana}</p>
          {s.bonus.map(b => <p key={b} className="text-sm">Bonus: {b}</p>)}
          {s.warnings.map(w => <p key={w} className="text-sm">{w}</p>)}
          <details className="mt-2 text-sm"><summary className="cursor-pointer">Factors</summary>
            <ul className="mt-2 grid gap-1 sm:grid-cols-2">{s.factors.map(f => <li key={f.id}>{f.ok ? "Met" : "Not met"}: {f.label}{f.verified === true ? "" : " (unverified list)"}</li>)}</ul></details>
        </section>)}
        <section className={panel}><h2 className="mb-2 font-medium">Excluded steps ({res.excluded.steps})</h2>
          <ul className="grid gap-1 text-sm sm:grid-cols-2">{Object.entries(res.excluded.by_reason).map(([k, v]) => <li key={k}>{k}: {v} steps</li>)}</ul></section>
        <details className={panel}><summary className="cursor-pointer font-medium">Rules used</summary>
          <ul className="mt-2 space-y-1 text-sm">{res.rules.map(r => <li key={r.id}>{r.id}: {r.label} — {r.source}{r.verified === true ? "" : " (unverified)"}</li>)}</ul></details>
        <p className="text-sm text-muted">{res.disclaimer}</p>
      </>}
    </main>
  );
}
