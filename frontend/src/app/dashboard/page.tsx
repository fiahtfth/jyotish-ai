"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, errMsg, type ChartDashboard, type ChartTransits, type DegreeTable, type KpChart, type ProfileItem } from "@/lib/api";
import NorthChart from "@/components/Chart";

const tabs = ["Chart", "Timeline", "Sensitivity", "Ashtakavarga", "Transits", "KP", "Paste degrees"] as const;
type Tab = typeof tabs[number];
const input = "rounded-lg border border-bord bg-card px-3 py-2";
const button = "rounded-lg bg-accent px-4 py-2 text-white disabled:opacity-50";
const panel = "rounded-xl border border-bord bg-card p-4 sm:p-6";
const signs = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"];

function Table({ headings, rows }: { headings: string[]; rows: (string | number)[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="bg-bgsoft"><tr>{headings.map(h => <th key={h} scope="col" className="px-3 py-2">{h}</th>)}</tr></thead>
        <tbody>{rows.map((row, i) => <tr key={i} className="border-b border-bord last:border-0">
          {row.map((cell, j) => <td key={j} className="px-3 py-2 align-top">{cell}</td>)}
        </tr>)}</tbody>
      </table>
    </div>
  );
}

function markdown(data: ChartDashboard) {
  const lines = ["# Jyotish chart", "", data.settings.birth_datetime_local, data.settings.place,
    "", "## Calculation settings", "", `Ayanamsa: ${data.settings.ayanamsa.id} ${data.settings.ayanamsa.dms}`,
    `UTC offset: ${data.settings.utc_offset_hours} hours`, `tzdb: ${data.settings.tzdb_version || "Unavailable"}`,
    `Varga rules: ${data.settings.varga_rule_version}`, `Ephemeris: ${data.settings.ephemeris}`,
    ...Object.entries(data.settings.calc_settings).map(([key, value]) => `- ${key}: ${value}`),
    "", "## Planetary positions", "",
    ...Object.entries(data.planets).map(([name, p]) => `- ${name} in ${p.sign_name} ${p.degree}°, house ${p.house}, ${p.nakshatra.name} pada ${p.nakshatra.pada}`),
    "", "## Traditional yogas", "",
    ...data.yogas.map(y => `- ${y.name} (${y.level}). ${y.source}. ${y.conditions_fired.join(", ")}`)];
  const href = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = href;
  link.download = "jyotish-chart.md";
  link.click();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

export default function Dashboard() {
  const [data, setData] = useState<ChartDashboard>();
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("Chart");
  const [varga, setVarga] = useState("D1");
  const [day, setDay] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [planet, setPlanet] = useState("Saturn");
  const [transits, setTransits] = useState<ChartTransits>();
  const [paste, setPaste] = useState("");
  const [source, setSource] = useState("jagannatha_hora");
  const [ayanamsa, setAyanamsa] = useState("");
  const [pasted, setPasted] = useState<DegreeTable>();
  const [kp, setKp] = useState<KpChart>();
  const [busy, setBusy] = useState(false);
  const [profiles, setProfiles] = useState<ProfileItem[]>([]);
  const activeProfile = profiles.find(p => p.is_active);

  useEffect(() => {
    let active = true;
    api.chartDashboard().then(result => {
      if (active) {
        setData(result);
        setDay(result.dashas.date);
      }
    }).catch(e => { if (active) setError(errMsg(e)); });
    api.listProfiles().then(result => { if (active) setProfiles(result); }).catch(() => {});
    return () => { active = false; };
  }, []);

  async function load(action: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try { await action(); } catch (e) { setError(errMsg(e)); }
    finally { setBusy(false); }
  }

  async function selectProfile(id: number) {
    setData(undefined);
    setTransits(undefined);
    setKp(undefined);
    setVarga("D1");
    await load(async () => {
      await api.activateProfile(id);
      setProfiles(await api.listProfiles());
      const result = await api.chartDashboard();
      setData(result);
      setDay(result.dashas.date);
    });
  }

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-4 py-6 sm:px-8 sm:py-10">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Link href="/chat" className="text-sm text-accent hover:underline">Back to chat</Link>
          <h1 className="mt-2 font-serif-astro text-3xl sm:text-4xl">Chart dashboard</h1>
          {data && <p className="mt-1 text-sm text-muted">{data.settings.birth_datetime_local} · {data.settings.place}</p>}
        </div>
        <div className="flex gap-4 text-sm">
          <Link href="/coverage" className="text-accent hover:underline">Coverage</Link>
          <Link href="/birth?new=1" className="text-accent hover:underline">Add profile</Link>
          {data && <button onClick={() => markdown(data)} className="text-accent hover:underline">Download Markdown</button>}
        </div>
      </header>
      {!!profiles.length && <div className="flex flex-wrap items-end gap-3">
        <label className="grid gap-2 text-sm">Birth profile
          <select className={input} disabled={busy} value={activeProfile?.id} onChange={e => { void selectProfile(Number(e.target.value)); }}>
            {profiles.map(p => <option key={p.id} value={p.id}>{p.display_name || p.relation}</option>)}
          </select>
        </label>
        {activeProfile && activeProfile.relation !== "self" && !activeProfile.permission_confirmed &&
          <button type="button" className={button} disabled={busy} onClick={() => {
            void load(async () => {
              await api.profilePermission(activeProfile.id, true);
              setProfiles(await api.listProfiles());
              const result = await api.chartDashboard();
              setData(result);
              setDay(result.dashas.date);
            });
          }}>I have permission to use these birth details</button>}
      </div>}
      <nav className="flex flex-wrap gap-2" aria-label="Chart views">
        {tabs.map(name => <button key={name} aria-pressed={tab === name} onClick={() => { setTab(name); setError(""); }}
          className={`rounded-lg border border-bord px-3 py-2 text-sm ${tab === name ? "bg-accentsoft text-accent" : "bg-card"}`}>{name}</button>)}
      </nav>
      {error && <p role="alert" className="rounded-lg border border-bord p-3">{error}</p>}
      {!data && !error && tab !== "Paste degrees" && <p role="status">Loading chart…</p>}
      {data?.settings.warnings.map(w => <p key={w} role="status" className="rounded-lg bg-accentsoft p-3 text-sm">{w}</p>)}
      {data && tab === "Chart" && <>
        <section className={`${panel} grid gap-6 lg:grid-cols-[250px_1fr]`}>
          <div className="space-y-4">
            <label className="grid gap-2 text-sm">Divisional chart
              <select className={input} value={varga} onChange={e => setVarga(e.target.value)}>
                {Object.keys(data.vargas).map(name => <option key={name}>{name}</option>)}
              </select>
            </label>
            <NorthChart varga={varga} chart={data.vargas[varga]} />
            <p className="text-sm text-muted">{data.settings.varga_schemes[varga]}</p>
          </div>
          <Table headings={["Planet", "D1 sign", "House", "Nakshatra", "Dignity and flags"]}
            rows={Object.entries(data.planets).map(([name, p]) => [name, `${p.sign_name} ${p.degree.toFixed(4)}°`, p.house,
              `${p.nakshatra.name} · ${p.nakshatra.pada}`,
              [...p.dignity, ...(p.retrograde ? ["Retrograde"] : []), ...(p.combust ? ["Combust"] : []),
                ...(p.vargottama ? ["Vargottama"] : []), ...(p.gandanta ? ["Gandanta"] : []), ...(p.sandhi ? ["Sandhi"] : [])].join(" · ") || "—"])} />
        </section>
        <details className={panel}><summary className="cursor-pointer font-medium">Calculation settings</summary>
          <p className="my-3 text-sm">{data.settings.ayanamsa.id} {data.settings.ayanamsa.dms} · tzdb {data.settings.tzdb_version || "unavailable"} · {data.settings.ephemeris}</p>
          <Table headings={["Setting", "Value"]} rows={Object.entries(data.settings.calc_settings)} />
        </details>
        <details className={panel}><summary className="cursor-pointer font-medium">Parashari aspects and yogas</summary>
          <Table headings={["Planet", "Aspects sign", "Distance"]} rows={data.aspects.map(a => [a.from, a.to, a.distance])} />
          <div className="mt-5 space-y-3">{data.yogas.map(y => <div key={y.id} className="text-sm">
            <strong>{y.name}</strong> · {y.level} <p>{y.note}</p>
            <p className="break-words text-muted">{y.source} · {y.conditions_fired.join(", ")}</p>
          </div>)}</div>
        </details>
      </>}
      {data && tab === "Timeline" && <section className={panel}>
        <form onSubmit={e => { e.preventDefault(); void load(() => api.chartDashboard(day).then(setData)); }} className="flex flex-wrap items-end gap-3">
          <label className="grid gap-2 text-sm">Inspect active dashas on<input className={input} type="date" value={day} required onChange={e => setDay(e.target.value)} /></label>
          <button className={button} disabled={busy}>Inspect</button>
        </form>
        <p className="my-4 text-sm text-muted">{data.dashas.date} · {data.settings.dasha_year.days} days per dasha year. {data.dashas.date_convention}</p>
        <div className="grid gap-4 xl:grid-cols-3">{(["vimshottari", "yogini", "chara"] as const).map(system =>
          <div key={system} className="min-w-0"><h2 className="mb-2 font-medium capitalize">{system}</h2>
            <Table headings={["Lords or signs", "From", "Until"]} rows={data.dashas[system].map(p => [(p.lords ?? p.signs ?? []).join(" → "), p.start, p.end])} />
          </div>)}</div>
      </section>}
      {data && tab === "Sensitivity" && <section className={panel}>
        <h2 className="mb-3 font-medium">Stable windows around the recorded time</h2>
        <Table headings={["Position", "Seconds before", "Seconds after", "Boundary status"]}
          rows={[...Object.entries(data.sensitivity), ["Moon pada", data.moon_pada] as const].map(([name, w]) =>
            [name, w.margin_before_s, w.margin_after_s, w.status === "cusp_sensitive" ? "Cusp-sensitive" : w.open_ended ? "No nearby boundary on at least one side" : "Stable"])} />
      </section>}
      {data && tab === "Ashtakavarga" && <section className={panel}>
        {data.ashtakavarga.sav && data.ashtakavarga.bav ? <Table headings={["Points", ...data.ashtakavarga.signs]}
          rows={[["SAV", ...data.ashtakavarga.sav], ...data.ashtakavarga.planets.map((p, i) => [p, ...data.ashtakavarga.bav![i]])]} /> :
          <p>Ashtakavarga is unavailable for this chart.</p>}
      </section>}
      {tab === "Transits" && <section className={panel}>
        <form onSubmit={e => { e.preventDefault(); void load(() => api.chartTransits(start, end, planet).then(setTransits)); }} className="flex flex-wrap items-end gap-3">
          <label className="grid gap-2 text-sm">Planet<select className={input} value={planet} onChange={e => setPlanet(e.target.value)}>
            {["Saturn", "Jupiter", "Mars", "Sun"].map(p => <option key={p}>{p}</option>)}</select></label>
          <label className="grid gap-2 text-sm">From (UTC)<input type="date" required className={input} value={start} onChange={e => setStart(e.target.value)} /></label>
          <label className="grid gap-2 text-sm">Until (UTC)<input type="date" required className={input} value={end} onChange={e => setEnd(e.target.value)} /></label>
          <button className={button} disabled={busy}>Find transitions</button>
        </form>
        {transits && <div className="mt-5 space-y-3">
          {transits.reduced_precision && <p role="status">Reduced precision · Moshier ephemeris</p>}
          {transits.sade_sati && <><h2 className="font-medium">Sade Sati phases</h2>
            {transits.sade_sati.length ? <Table headings={["Phase", "Sign", "From", "Until"]}
              rows={transits.sade_sati.map(p => [p.phase, p.sign, p.start + (p.start_clipped ? " (range start)" : ""), p.end + (p.end_clipped ? " (range end)" : "")])} /> :
              <p className="text-sm text-muted">No Sade Sati phase in this range.</p>}</>}
          {transits.events.length ? <Table headings={["Time (UTC)", "Transition", "From", "To"]}
            rows={transits.events.map(e => [e.at, e.kind.replaceAll("_", " "), e.from ?? "—", e.to])} /> : <p>No transitions in this range.</p>}
          <details className="rounded-lg border border-bord p-3">
            <summary className="cursor-pointer font-medium">Bindu-active kakshyas</summary>
            <Table headings={["Sign", "Kakshya lord", "From (UTC)", "Until (UTC)"]}
              rows={transits.kakshya_slices.filter(slice => slice.bindu_active)
                .map(slice => [slice.sign, slice.lord, slice.start, slice.end])} />
          </details>
        </div>}
      </section>}
      {tab === "KP" && <section className={panel}>
        {!kp ? <button className={button} disabled={busy} onClick={() => { void load(() => api.kpChart().then(setKp)); }}>Calculate KP chart</button> :
          <div className="space-y-5">
            <p>{kp.frame.ayanamsa} {kp.frame.dms} · {kp.frame.houses} · {kp.frame.rule_version}</p>
            <Table headings={["Cusp", "Position", "Star lord", "Sub-lord", "Segment"]}
              rows={kp.cusps.map(c => [c.house, `${c.sign} ${c.degree.toFixed(4)}°`, c.star_lord, c.sub_lord, c.segment])} />
            <details><summary className="cursor-pointer font-medium">Significators and ruling planets</summary>
              <Table headings={["House", "Stars of occupants", "Occupants", "Stars of owner", "Owner"]}
                rows={kp.significators.map(s => [s.house, s.stars_of_occupants.join(", "), s.occupants.join(", "), s.stars_of_owner.join(", "), s.owner])} />
              <dl className="mt-4 grid gap-2 text-sm sm:grid-cols-2">{Object.entries(kp.ruling_planets).map(([key, value]) =>
                <div key={key}><dt className="capitalize text-muted">{key.replaceAll("_", " ")}</dt><dd>{value ?? "Unavailable"}</dd></div>)}</dl>
            </details>
            <details><summary className="cursor-pointer font-medium">249 sub-lord segments</summary>
              <Table headings={["Number", "Start arcseconds", "End arcseconds", "Nakshatra", "Sub-lord"]}
                rows={kp.segments.map(s => [s.number, s.start_arcsec, s.end_arcsec, s.nakshatra, s.sub_lord])} />
            </details>
            {kp.limitations.map(line => <p key={line} className="text-sm text-muted">{line}</p>)}
          </div>}
      </section>}
      {tab === "Paste degrees" && <section className={panel}>
        <form onSubmit={e => { e.preventDefault(); void load(() => api.degreeTable(paste, source, ayanamsa).then(setPasted)); }} className="space-y-4">
          <div className="flex flex-wrap gap-4">
            <label className="grid gap-2 text-sm">Source program<select className={input} value={source} onChange={e => setSource(e.target.value)}>
              <option value="jagannatha_hora">Jagannatha Hora</option><option value="drik_panchang">Drik Panchang</option>
              <option value="astrosage">AstroSage</option><option value="other">Other</option></select></label>
            <label className="grid gap-2 text-sm">Ayanamsa<select className={input} value={ayanamsa} required onChange={e => setAyanamsa(e.target.value)}>
              <option value="">Select the source frame</option>
              {["LAHIRI", "LAHIRI_ICRC", "LAHIRI_1940", "LAHIRI_VP285", "TRUE_CITRA"].map(a => <option key={a}>{a}</option>)}</select></label>
          </div>
          <label className="grid gap-2 text-sm">Original degree table
            <textarea className={input} value={paste} onChange={e => setPaste(e.target.value)} required maxLength={4000} rows={8}
              placeholder={"Lagna 18°08′ Leo\nMoon 27°58′ Sagittarius"} /></label>
          <button className={button} disabled={busy}>Check pasted degrees</button>
        </form>
        {pasted && <div className="mt-5 space-y-4">
          {pasted.warnings.map(w => <p key={w} className="text-sm">{w}</p>)}
          <Table headings={["Original entry", "Uncertainty (arcsec)", "Nakshatra/pada", "D9", "D60"]}
            rows={Object.entries(pasted.planets).map(([name, p]) => [p.source_text, p.error_arcsec,
              p.nakshatra_padas.map(n => `${n.name} ${n.pada}`).join(" or "),
              pasted.vargas.D9[name].possible_signs.map(s => signs[s]).join(" or "),
              pasted.vargas.D60[name].possible_signs.map(s => signs[s]).join(" or ")])} />
          <p className="text-sm text-muted">Requires birth details: {pasted.unavailable.join(", ")}.</p>
        </div>}
      </section>}
    </main>
  );
}
