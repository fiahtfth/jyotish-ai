"use client";
import { useState } from "react";
import { api, errMsg, type Place } from "@/lib/api";
import { input } from "@/components/ServiceNav";

export default function PlacePicker({ label, value, onPick }: { label: string; value: Place | null; onPick: (p: Place) => void }) {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<Place[]>([]);
  const [err, setErr] = useState("");
  async function search() {
    setErr("");
    try { setRows(await api.geoSearch(q)); } catch (e) { setErr(errMsg(e)); }
  }
  return (
    <div className="grid gap-2 text-sm">
      <span>{label}{value && <strong> — {value.name}{value.country ? `, ${value.country}` : ""}</strong>}</span>
      <div className="flex gap-2">
        <input className={`${input} flex-1`} value={q} onChange={e => setQ(e.target.value)} placeholder="Search a place" aria-label={label}
          onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); void search(); } }} />
        <button type="button" className="rounded-lg border border-bord px-3" disabled={q.length < 2} onClick={() => { void search(); }}>Search</button>
      </div>
      {err && <p role="alert">{err}</p>}
      {rows.length > 0 && <ul className="rounded-lg border border-bord">{rows.map(r => <li key={`${r.latitude},${r.longitude}`}>
        <button type="button" className="w-full px-3 py-1 text-left hover:bg-accentsoft" onClick={() => { onPick(r); setRows([]); }}>
          {r.label || `${r.name}, ${r.state} ${r.country}`}</button></li>)}</ul>}
    </div>
  );
}
