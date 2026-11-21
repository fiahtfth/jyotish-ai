"use client";
import { useEffect, useState } from "react";
import { api, apiExtra, errMsg, type MatchResult, type Place, type Profile, type ProfileItem, type PersonRef } from "@/lib/api";
import ServiceNav, { button, input, panel } from "@/components/ServiceNav";
import PlacePicker from "@/components/PlacePicker";

type Source = { kind: "profile"; id: number } | { kind: "entered" };
const verifiedTag = (v: boolean) => (v ? "" : " (not universally accepted)");

export default function Matching() {
  const [profiles, setProfiles] = useState<ProfileItem[]>([]);
  const [active, setActive] = useState<Profile | null>(null);
  const [mine, setMine] = useState<number>(0);
  const [partnerSrc, setPartnerSrc] = useState<Source>({ kind: "entered" });
  const [myRole, setMyRole] = useState<"groom" | "bride">("groom");
  const [name, setName] = useState("");
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [place, setPlace] = useState<Place | null>(null);
  const [consent, setConsent] = useState(false);
  const [res, setRes] = useState<MatchResult>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.listProfiles().then(l => { setProfiles(l); const a = l.find(p => p.is_active) ?? l[0]; if (a) setMine(a.id); }).catch(e => setError(errMsg(e)));
    api.getProfile().then(p => { setActive(p); if (p.gender === "female") setMyRole("bride"); }).catch(() => {});
  }, []);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setError(""); setBusy(true);
    try {
      const me: PersonRef = { profile_id: mine };
      let partner: PersonRef;
      if (partnerSrc.kind === "profile") partner = { profile_id: partnerSrc.id };
      else {
        if (!place) throw new Error("Choose the partner's birth place.");
        const [y, mo, d] = date.split("-").map(Number); const [h, mi] = time.split(":").map(Number);
        partner = { birth: { display_name: name, year: y, month: mo, day: d, hour: h, minute: mi, place_name: place.name,
          latitude: place.latitude, longitude: place.longitude, place_country: place.country } };
      }
      setRes(myRole === "groom" ? await apiExtra.match(me, partner, consent) : await apiExtra.match(partner, me, consent));
    } catch (er) { setError(errMsg(er)); } finally { setBusy(false); }
  }

  return (
    <main className="mx-auto max-w-5xl space-y-6 px-4 py-6 sm:px-8 sm:py-10">
      <ServiceNav title="Kundli matching" />
      <form onSubmit={run} className={`${panel} space-y-4`}>
        <div className="flex flex-wrap gap-4">
          <label className="grid gap-2 text-sm">Your chart
            <select className={input} value={mine} onChange={e => setMine(Number(e.target.value))}>
              {profiles.map(p => <option key={p.id} value={p.id}>{p.display_name || p.relation}</option>)}</select></label>
          <label className="grid gap-2 text-sm">Role in the match
            <select className={input} value={myRole} onChange={e => setMyRole(e.target.value as "groom" | "bride")}>
              <option value="groom">Groom</option><option value="bride">Bride</option></select>
            {active?.gender ? <span className="text-xs text-muted">Profile gender: {active.gender}</span> :
              <span className="text-xs text-muted">No gender saved on the profile; choose the role here.</span>}</label>
          <label className="grid gap-2 text-sm">Partner
            <select className={input} value={partnerSrc.kind === "profile" ? String(partnerSrc.id) : "entered"}
              onChange={e => setPartnerSrc(e.target.value === "entered" ? { kind: "entered" } : { kind: "profile", id: Number(e.target.value) })}>
              <option value="entered">Enter birth details</option>
              {profiles.filter(p => p.id !== mine).map(p => <option key={p.id} value={p.id}>{p.display_name || p.relation}</option>)}</select></label>
        </div>
        {partnerSrc.kind === "entered" && <div className="grid gap-3 sm:grid-cols-3">
          <label className="grid gap-2 text-sm">Name<input className={input} value={name} onChange={e => setName(e.target.value)} /></label>
          <label className="grid gap-2 text-sm">Birth date<input className={input} type="date" required value={date} onChange={e => setDate(e.target.value)} /></label>
          <label className="grid gap-2 text-sm">Birth time<input className={input} type="time" required value={time} onChange={e => setTime(e.target.value)} /></label>
          <div className="sm:col-span-3"><PlacePicker label="Birth place" value={place} onPick={setPlace} /></div>
          <label className="flex items-start gap-2 text-sm sm:col-span-3"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} />
            <span>I have this person&apos;s permission to use their birth details. They are used for this calculation only and are not saved.</span></label>
        </div>}
        <button className={button} disabled={busy || !mine || (partnerSrc.kind === "entered" && !consent)}>Match charts</button>
      </form>
      {error && <p role="alert" className="rounded-lg border border-bord p-3">{error}</p>}
      {res && <>
        <section className={panel}>
          <h2 className="text-xl font-medium">{res.groom_name} (groom) and {res.bride_name} (bride)</h2>
          <p className="mt-2 text-3xl font-serif-astro">{res.total} / {res.max}</p>
          <p className="mt-1 text-sm">{res.band.text}</p>
          {res.adjusted_note && <p className="mt-1 text-sm text-muted">With exceptions applied: {res.adjusted_total} / {res.max}. {res.adjusted_note}</p>}
          <div className="mt-4 overflow-x-auto"><table className="w-full text-left text-sm">
            <thead className="bg-bgsoft"><tr>{["Koota", "Groom", "Bride", "Score", "What it looks at"].map(h => <th key={h} scope="col" className="px-3 py-2">{h}</th>)}</tr></thead>
            <tbody>{res.kootas.map(k => <tr key={k.id} className="border-b border-bord align-top">
              <td className="px-3 py-2 font-medium">{k.name}</td><td className="px-3 py-2">{k.groom}</td><td className="px-3 py-2">{k.bride}</td>
              <td className="px-3 py-2">{k.score} / {k.max}</td>
              <td className="px-3 py-2">{k.explanation}<span className="block text-xs text-muted">{k.rule_id} · {k.source}{k.verified ? "" : " · unverified in part"}{k.verified_note ? ` — ${k.verified_note}` : ""}</span></td></tr>)}</tbody></table></div>
        </section>
        <section className={panel}>
          <h2 className="mb-2 font-medium">Doshas and traditional exceptions</h2>
          {([["Nadi", res.doshas.nadi, res.doshas.nadi.cancelled], ["Bhakoot", res.doshas.bhakoot, res.doshas.bhakoot.cancelled],
            ["Gana", res.doshas.gana, res.doshas.gana.mitigated]] as const).map(([label, d, relieved]) => <div key={label} className="mb-3 text-sm">
            <strong>{label}</strong>: {d.present ? (relieved ? "points lost, but an exception applies" : "points lost, no listed exception applies") : "no dosha"}
            <ul className="ml-4 list-disc">{d.exceptions.map(e => <li key={e.id}>{e.applies ? "Applies" : "Does not apply"}: {e.text}{verifiedTag(e.verified)}</li>)}</ul></div>)}
        </section>
        <section className={panel}>
          <h2 className="mb-2 font-medium">Mangal dosha</h2>
          <div className="grid gap-4 text-sm sm:grid-cols-2">{(["groom", "bride"] as const).map(w => <div key={w}>
            <strong className="capitalize">{w}</strong>: {res.mangal[w].present ? `present (${res.mangal[w].severity})` : "not present"}
            {res.mangal[w].cancelled && " — a cancellation applies"}
            <ul className="ml-4 list-disc">{res.mangal[w].cancellations.filter(c => c.applies).map(c => <li key={c.id}>{c.text}</li>)}</ul>
            <p className="text-xs text-muted">{res.mangal[w].basis}</p></div>)}</div>
          <p className="mt-3 text-sm">{res.mangal.pair.text}</p>
        </section>
        <section className={`${panel} space-y-2 text-sm`}>
          <h2 className="font-medium">Navamsa, 7th house and dasha context</h2>
          {res.navamsa.available ? <p>{res.navamsa.text} (heuristic, unverified)</p> : <p className="text-muted">Navamsa comparison needs both birth times.</p>}
          {res.seventh_house && (["groom", "bride"] as const).map(w => <p key={w} className="capitalize">{w}: 7th house {res.seventh_house![w].sign}, lord {res.seventh_house![w].lord} in house {res.seventh_house![w].lord_house}; {res.seventh_house![w].karaka} in house {res.seventh_house![w].karaka_house}.</p>)}
          {(["groom", "bride"] as const).map(w => res.dasha[w].available && <p key={w} className="capitalize">{w}: running {res.dasha[w].maha}–{res.dasha[w].antar} until {res.dasha[w].until}{res.dasha[w].strongly_adverse ? " (a demanding period by a simple test)" : ""}.</p>)}
        </section>
        <p className="rounded-lg bg-accentsoft p-3 text-sm">{res.disclaimer}</p>
      </>}
    </main>
  );
}
