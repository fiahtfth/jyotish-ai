"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, errMsg, type Coverage } from "@/lib/api";

export default function CoveragePage() {
  const [data, setData] = useState<Coverage>();
  const [error, setError] = useState("");
  const [phaseOne, setPhaseOne] = useState(true);
  useEffect(() => {
    let active = true;
    api.coverage().then(result => { if (active) setData(result); })
      .catch(e => { if (active) setError(errMsg(e)); });
    return () => { active = false; };
  }, []);
  return (
    <main className="mx-auto max-w-5xl space-y-5 px-4 py-7 sm:px-8">
      <Link href="/dashboard" className="text-sm text-accent hover:underline">Back to chart dashboard</Link>
      <h1 className="font-serif-astro text-3xl sm:text-4xl">Calculation coverage</h1>
      {error && <p role="alert">{error}</p>}
      {!data && !error && <p role="status">Loading coverage…</p>}
      {data && <>
        <p className="text-sm text-muted">Intent registry {data.version} · {data.intents.length} intents</p>
        <dl className="grid grid-cols-3 gap-2 sm:gap-4">{Object.entries(data.counts).map(([status, count]) =>
          <div key={status} className="rounded-xl border border-bord bg-card p-3 sm:p-4">
            <dt className="text-xs capitalize text-muted sm:text-sm">{status}</dt><dd className="text-xl">{count}</dd>
          </div>)}</dl>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={phaseOne} onChange={e => setPhaseOne(e.target.checked)} /> Phase 1 only</label>
        <div className="overflow-x-auto rounded-xl border border-bord bg-card">
          <table className="w-full text-left text-sm">
            <thead className="bg-bgsoft"><tr>{["Intent", "Status", "Supportive chart rate"].map(h => <th scope="col" key={h} className="px-3 py-2">{h}</th>)}</tr></thead>
            <tbody>{data.intents.filter(row => !phaseOne || row.phase === 1).map(row =>
              <tr key={row.intent_id} className="border-t border-bord">
                <td className="px-3 py-2"><p>{row.sample_questions[0]}</p><p className="capitalize text-muted">{row.domain}</p></td>
                <td className="px-3 py-2 capitalize">{row.status}</td>
                <td className="px-3 py-2">{row.specificity === null ? "—" : row.specificity.supportive_chart_rate === null ?
                  "Specificity test pending" : `${(row.specificity.supportive_chart_rate * 100).toFixed(1)}% of synthetic chart windows`}</td>
              </tr>)}</tbody>
          </table>
        </div>
      </>}
    </main>
  );
}
