"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, token } from "@/lib/api";

type Place = { name: string; state: string; country: string; latitude: number; longitude: number; timezone_name: string; utc_offset_hours: number };

export default function Birth() {
  const router = useRouter();
  const [f, setF] = useState({ display_name: "", year: 1990, month: 1, day: 1, hour: 6, minute: 0, second: 0, birth_time_precision: "exact" });
  const [q, setQ] = useState("");
  const [places, setPlaces] = useState<Place[]>([]);
  const [place, setPlace] = useState<Place | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const deb = useRef<ReturnType<typeof setTimeout>>(null);

  useEffect(() => {
    if (!token()) { router.replace("/login"); return; }
    api.getProfile().then((p: any) => {
      setF(f => ({ ...f, ...p }));
      if (p.place_name) { setQ(`${p.place_name}, ${p.place_country}`); setPlace(p); }
    }).catch(() => {});
  }, [router]);

  function search(v: string) {
    setQ(v); setPlace(null);
    if (deb.current) clearTimeout(deb.current);
    if (v.trim().length < 2) { setPlaces([]); return; }
    deb.current = setTimeout(() => api.geoSearch(v.trim()).then(setPlaces).catch(() => {}), 300);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    if (!place) { setErr("Please pick your birth place from the suggestions."); return; }
    setBusy(true);
    try {
      await api.putProfile({
        ...f,
        place_name: place.name, place_state: place.state, place_country: place.country,
        latitude: place.latitude, longitude: place.longitude,
      });
      router.replace("/chat");
    } catch (x: any) { setErr(x.message); } finally { setBusy(false); }
  }

  const inp = "w-full border border-bord rounded-lg px-3 py-2 bg-transparent";

  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <form onSubmit={submit} className="w-full max-w-md bg-card border border-bord rounded-2xl p-6 shadow-sm space-y-4">
        <h1 className="font-serif-astro text-2xl">Your birth details</h1>
        <p className="text-sm text-muted">The astrologer needs this to draw your chart. All calculations happen on the server and are locked — the AI only interprets, never computes.</p>
        <input value={f.display_name} onChange={e => setF({ ...f, display_name: e.target.value })}
          placeholder="What should we call you?" className={inp} />
        <div className="grid grid-cols-3 gap-2">
          <input type="number" value={f.day} min={1} max={31} onChange={e => setF({ ...f, day: +e.target.value })} className={inp} placeholder="Day" />
          <select value={f.month} onChange={e => setF({ ...f, month: +e.target.value })} className={inp}>
            {["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"].map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
          </select>
          <input type="number" value={f.year} min={1900} max={2030} onChange={e => setF({ ...f, year: +e.target.value })} className={inp} placeholder="Year" />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <label className="text-xs text-muted col-span-2 -mb-2">Time of birth</label>
          <input type="number" value={f.hour} min={0} max={23} onChange={e => setF({ ...f, hour: +e.target.value })} className={inp} placeholder="Hour (0–23)" />
          <input type="number" value={f.minute} min={0} max={59} onChange={e => setF({ ...f, minute: +e.target.value })} className={inp} placeholder="Minute" />
        </div>
        <select value={f.birth_time_precision} onChange={e => setF({ ...f, birth_time_precision: e.target.value })} className={inp}>
          <option value="exact">Time is exact (birth certificate / hospital record)</option>
          <option value="approximate">Approximate (±15 min or so)</option>
          <option value="unknown">Time is unknown</option>
        </select>
        <div className="relative">
          <input value={q} onChange={e => search(e.target.value)} placeholder="Birth place — start typing a city" className={inp} />
          {places.length > 0 && !place && (
            <div className="absolute z-10 mt-1 w-full bg-card border border-bord rounded-lg shadow-lg max-h-56 overflow-auto">
              {places.map((p, i) => (
                <button key={i} type="button"
                  onClick={() => { setPlace(p); setQ(`${p.name}${p.state ? `, ${p.state}` : ""}, ${p.country}`); setPlaces([]); }}
                  className="w-full text-left px-3 py-2 text-sm hover:bg-bgsoft">
                  {p.name}{p.state ? `, ${p.state}` : ""}, {p.country}
                </button>
              ))}
            </div>
          )}
          {place && <div className="text-xs text-muted mt-1">{place.latitude.toFixed(2)}° / {place.longitude.toFixed(2)}° · {place.timezone_name}</div>}
        </div>
        {err && <div className="text-red-500 text-sm">{err}</div>}
        <button disabled={busy} className="w-full bg-accent text-white rounded-lg py-2.5 font-medium disabled:opacity-50">
          {busy ? "Computing your chart…" : "Continue"}
        </button>
      </form>
    </main>
  );
}
