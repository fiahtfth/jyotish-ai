"use client";
import { useEffect, useState } from "react";
import { apiExtra, errMsg, type Varshaphala } from "@/lib/api";
import ServiceNav, { input, panel } from "@/components/ServiceNav";
import NorthChart from "@/components/Chart";

export default function VarshaPage() {
  const [year, setYear] = useState<number>(new Date().getFullYear());
  const [data, setData] = useState<Varshaphala>();
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    apiExtra.varshaphala(year).then(d => { if (live) { setData(d); setError(""); } }).catch(e => { if (live) { setData(undefined); setError(errMsg(e)); } });
    return () => { live = false; };
  }, [year]);
  const lord = data?.year_lord ? String(data.year_lord.planet ?? data.year_lord.lord ?? "") : "";
  return (
    <main className="mx-auto max-w-5xl space-y-6 px-4 py-6 sm:px-8 sm:py-10">
      <ServiceNav title="Varshaphala (annual chart)" />
      <label className="grid max-w-xs gap-2 text-sm">Year
        <input type="number" className={input} value={year} min={1900} max={2150} onChange={e => setYear(Number(e.target.value))} /></label>
      {error && <p role="alert" className="rounded-lg border border-bord p-3">{error}</p>}
      {!data && !error && <p role="status">Loading…</p>}
      {data && <>
        <section className={`${panel} grid gap-6 md:grid-cols-[250px_1fr]`}>
          <NorthChart varga="Varsha" chart={data.chart} />
          <div className="space-y-2 text-sm">
            <p>Solar return: {data.return_local} · year {data.year_of_life} of life</p>
            <p>Varsha Lagna: <strong>{data.varsha_lagna.sign_name}</strong></p>
            <p>Muntha: <strong>{data.muntha.sign_name}</strong> in house {data.muntha.house_from_varsha_lagna} of the annual chart</p>
            <p>Year lord (Varsheshwara): <strong>{lord || "unavailable"}</strong></p>
            {data.status !== "applied" && <p role="status">Some sections are partial.</p>}
          </div>
        </section>
        <section className={panel}><h2 className="mb-2 font-medium">Positions in the annual chart</h2>
          <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="bg-bgsoft"><tr>
            {["Planet", "Sign", "Degree", "House"].map(h => <th key={h} scope="col" className="px-3 py-2">{h}</th>)}</tr></thead>
            <tbody>{data.positions.map(p => <tr key={p.planet} className="border-b border-bord"><td className="px-3 py-1">{p.planet}</td><td className="px-3 py-1">{p.sign}</td>
              <td className="px-3 py-1">{p.degree}°</td><td className="px-3 py-1">{p.house}</td></tr>)}</tbody></table></div></section>
        <section className={panel}><h2 className="mb-2 font-medium">Tajika yogas</h2>
          {data.tajika_yogas.length ? <ul className="space-y-1 text-sm">{data.tajika_yogas.map((y, i) => <li key={i}><strong>{y.name}</strong> {y.detail ?? y.note ?? ""}</li>)}</ul> : <p className="text-sm">None found.</p>}</section>
        {data.mudda && <section className={panel}><h2 className="mb-1 font-medium">Mudda dasha</h2><p className="mb-2 text-xs text-muted">{data.mudda.scheme}</p>
          <ul className="text-sm">{data.mudda.periods.map((p, i) => <li key={i}>{p.lords.join(" – ")}: {p.start} to {p.end ?? "year end"}</li>)}</ul></section>}
        <section className={panel}><h2 className="mb-1 font-medium">Sahams</h2><p className="mb-2 text-xs text-muted">{data.sahams_note}</p>
          <ul className="grid gap-1 text-sm sm:grid-cols-3">{data.sahams.map(s => <li key={s.name}>{s.name}: {s.sign} {s.degree}° (house {s.house})</li>)}</ul></section>
      </>}
    </main>
  );
}
