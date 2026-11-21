"use client";
import { useState } from "react";
import { apiExtra, errMsg, type Place, type PrashnaResult } from "@/lib/api";
import ServiceNav, { button, input, panel } from "@/components/ServiceNav";
import PlacePicker from "@/components/PlacePicker";

const TYPES: [string, string][] = [["general", "General"], ["marriage", "Marriage / relationship"], ["career", "Career / job"], ["money", "Money"],
  ["education", "Education"], ["health", "Health"], ["children", "Children"], ["property", "Property"], ["travel", "Travel"], ["legal", "Legal"]];

export default function Prashna() {
  const [type, setType] = useState("general");
  const [place, setPlace] = useState<Place | null>(null);
  const [geo, setGeo] = useState<{ latitude: number; longitude: number } | null>(null);
  const [res, setRes] = useState<PrashnaResult>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  function locate() {
    navigator.geolocation?.getCurrentPosition(p => { setGeo({ latitude: p.coords.latitude, longitude: p.coords.longitude }); setPlace(null); },
      () => setError("Location permission denied; choose a place instead."));
  }
  async function run(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      const loc = place ? { latitude: place.latitude, longitude: place.longitude, place_name: place.name }
        : geo ? { ...geo, place_name: "Current location" } : {};
      setRes(await apiExtra.prashna({ question_type: type, ...loc }));
    } catch (er) { setError(errMsg(er)); } finally { setBusy(false); }
  }
  const mark = (f: boolean | null) => f === true ? "Favourable" : f === false ? "Unfavourable" : "Informational";

  return (
    <main className="mx-auto max-w-4xl space-y-6 px-4 py-6 sm:px-8 sm:py-10">
      <ServiceNav title="Prashna (horary)" />
      <form onSubmit={run} className={`${panel} space-y-4`}>
        <p className="text-sm">Hold your question in mind and ask it now; the chart is cast for this moment and place.</p>
        <label className="grid max-w-xs gap-2 text-sm">Question type
          <select className={input} value={type} onChange={e => setType(e.target.value)}>{TYPES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <PlacePicker label="Where are you now? (default: residence, else birthplace)" value={place} onPick={p => { setPlace(p); setGeo(null); }} />
        <div className="flex flex-wrap items-center gap-3"><button type="button" className="rounded-lg border border-bord px-3 py-2 text-sm" onClick={locate}>Use my current location</button>
          {geo && <span className="text-sm">Using device location ({geo.latitude.toFixed(2)}, {geo.longitude.toFixed(2)})</span>}</div>
        <button className={button} disabled={busy}>Cast Prashna chart</button>
      </form>
      {error && <p role="alert" className="rounded-lg border border-bord p-3">{error}</p>}
      {res && <>
        <section className={`${panel} space-y-1 text-sm`}>
          <h2 className="font-medium">{res.question_label} · cast {res.cast.local} at {res.cast.place}</h2>
          <p>Prashna Lagna: <strong>{res.lagna.sign} {res.lagna.degree}°</strong> ({res.lagna.nakshatra}); lord {res.lagna.lord} in {res.lagna.lord_sign}, house {res.lagna.lord_house}.</p>
          <p>Moon: {res.moon.sign}, house {res.moon.house}, {res.moon.nakshatra}, {res.moon.waxing ? "waxing" : "waning"}.</p>
          <p>House {res.relevant_house} ({res.relevant.sign}) lord {res.relevant.lord} in house {res.relevant.lord_house}; occupants: {res.relevant.occupants.join(", ") || "none"}.</p>
        </section>
        <section className={panel}><h2 className="mb-2 font-medium">Traditional indicators</h2>
          <ul className="space-y-2 text-sm">{res.indicators.map(i => <li key={i.id}><strong>{mark(i.favourable)}</strong>: {i.label} — {i.detail}
            <span className="block text-xs text-muted">{i.source} · unverified</span></li>)}</ul>
          <p className="mt-3 text-sm">{res.summary.text} {res.summary.label}</p></section>
        {res.rectification.applicable && <section className={panel}><h2 className="mb-2 font-medium">Finding an unknown birth time</h2>
          <p className="text-sm">{res.rectification.heuristic?.text}</p>
          <ul className="mt-2 text-sm">{res.rectification.windows?.map((w, i) => <li key={i}>{w.start}–{w.end}: {w.lagna} Lagna{w.in_prashna_trine ? " (fits the Prashna pattern)" : ""}</li>)}</ul>
          <ul className="mt-2 list-disc pl-5 text-sm">{res.rectification.guidance?.map(g => <li key={g}>{g}</li>)}</ul></section>}
      </>}
    </main>
  );
}
