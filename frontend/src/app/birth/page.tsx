"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, errMsg, token, type Place, type ProfileIn } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function Birth() {
  const router = useRouter();
  const { t } = useI18n();
  const [f, setF] = useState<Pick<ProfileIn, "display_name" | "year" | "month" | "day" | "hour" | "minute" | "second" | "birth_time_precision">>({ display_name: "", year: 1990, month: 1, day: 1, hour: 6, minute: 0, second: 0, birth_time_precision: "exact" });
  const [q, setQ] = useState("");
  const [places, setPlaces] = useState<Place[]>([]);
  const [place, setPlace] = useState<Place | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const deb = useRef<ReturnType<typeof setTimeout>>(null);

  useEffect(() => {
    if (!token()) { router.replace("/login"); return; }
    api.getProfile().then(p => {
      setF(f => ({ ...f, ...p }));
      if (p.place_name) {
        setQ(`${p.place_name}, ${p.place_country}`);
        // normalize profile shape -> geo-search shape used by submit()
        setPlace({ name: p.place_name, state: p.place_state, country: p.place_country,
                   latitude: p.latitude, longitude: p.longitude,
                   timezone_name: p.timezone_name, utc_offset_hours: p.utc_offset_hours });
      }
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
    if (!place) { setErr(t("pickPlace")); return; }
    setBusy(true);
    try {
      await api.putProfile({
        ...f,
        place_name: place.name, place_state: place.state, place_country: place.country,
        latitude: place.latitude, longitude: place.longitude,
      });
      router.replace("/chat");
    } catch (x) { setErr(errMsg(x)); } finally { setBusy(false); }
  }

  const inp = "w-full border border-bord rounded-lg px-3 py-2 bg-transparent";

  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <form onSubmit={submit} className="w-full max-w-md bg-card border border-bord rounded-2xl p-6 shadow-sm space-y-4">
        <h1 className="font-serif-astro text-2xl">{t("birthTitle")}</h1>
        <p className="text-sm text-muted">{t("birthIntro")}</p>
        <input value={f.display_name} onChange={e => setF({ ...f, display_name: e.target.value })}
          placeholder={t("callYou")} className={inp} />
        <div className="grid grid-cols-3 gap-2">
          <input type="number" value={f.day} min={1} max={31} onChange={e => setF({ ...f, day: +e.target.value })} className={inp} placeholder={t("day")} />
          <select value={f.month} onChange={e => setF({ ...f, month: +e.target.value })} className={inp}>
            {t("months").split("|").map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
          </select>
          <input type="number" value={f.year} min={1900} max={2030} onChange={e => setF({ ...f, year: +e.target.value })} className={inp} placeholder={t("year")} />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <label className="text-xs text-muted col-span-2 -mb-2">{t("timeOfBirth")}</label>
          <input type="number" value={f.hour} min={0} max={23} onChange={e => setF({ ...f, hour: +e.target.value })} className={inp} placeholder={t("hour")} />
          <input type="number" value={f.minute} min={0} max={59} onChange={e => setF({ ...f, minute: +e.target.value })} className={inp} placeholder={t("minute")} />
        </div>
        <select value={f.birth_time_precision} onChange={e => setF({ ...f, birth_time_precision: e.target.value as ProfileIn["birth_time_precision"] })} className={inp}>
          <option value="exact">{t("precExact")}</option>
          <option value="approximate">{t("precApprox")}</option>
          <option value="unknown">{t("precUnknown")}</option>
        </select>
        <div className="relative">
          <input value={q} onChange={e => search(e.target.value)} placeholder={t("placePh")} className={inp} />
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
          {busy ? t("computing") : t("continue")}
        </button>
      </form>
    </main>
  );
}
