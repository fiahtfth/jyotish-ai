"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, errMsg, token, TzError, type Place, type Profile, type ProfileIn, type TzReject } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function Birth() {
  const router = useRouter();
  const { t } = useI18n();
  const [f, setF] = useState<ProfileIn>({ display_name: "", year: 1990, month: 1, day: 1, hour: 6, minute: 0, second: 0, birth_time_precision: "exact",
    place_name: "", place_state: "", place_country: "", latitude: 0, longitude: 0,
    time_basis: "zone", utc_offset_manual: null, dst_fold: null, calc_preset: "default" });
  const [q, setQ] = useState("");
  const [places, setPlaces] = useState<Place[]>([]);
  const [place, setPlace] = useState<Place | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [ambig, setAmbig] = useState<TzReject | null>(null);
  const [resolved, setResolved] = useState<Profile | null>(null);
  const [adding, setAdding] = useState(false);
  const [created, setCreated] = useState(false);
  const [manualCoords, setManualCoords] = useState(false);
  const deb = useRef<ReturnType<typeof setTimeout>>(null);

  useEffect(() => {
    if (!token()) { router.replace("/login"); return; }
    if (new URLSearchParams(window.location.search).get("new") === "1") {
      Promise.resolve().then(() => setAdding(true));
      return;
    }
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

  async function submit(e: React.FormEvent, fold?: 0 | 1) {
    e.preventDefault();
    setErr("");
    const location = manualCoords ? {
      name: q.trim() || t("manualCoords"), state: f.place_state, country: f.place_country,
      latitude: f.latitude, longitude: f.longitude,
    } : place;
    if (!location) { setErr(t("pickPlace")); return; }
    setBusy(true);
    try {
      const save = adding && !created ? api.createProfile : api.putProfile;
      const p = await save({
        ...f,
        dst_fold: fold ?? f.dst_fold,
        place_name: location.name, place_state: location.state, place_country: location.country,
        latitude: location.latitude, longitude: location.longitude,
      });
      setAmbig(null);
      if (adding) setCreated(true);
      // Confirm the resolved offset only when it could surprise the user:
      // tz warnings, or a non-tzdb resolution (lmt/manual/fallback). A clean
      // tzdb lookup is unambiguous — go straight to the chat.
      if ((p.tz_warnings?.length ?? 0) > 0 || p.offset_source !== "tzdb") {
        setResolved(p);
      } else {
        router.replace("/chat");
      }
    } catch (x) {
      if (x instanceof TzError) {
        if (x.detail.code === "ambiguous_time") setAmbig(x.detail);
        else { setAmbig(null); setErr(`${t("dstGap")} ${x.message}`); }
      } else setErr(errMsg(x));
    } finally { setBusy(false); }
  }

  const inp = "w-full border border-bord rounded-lg px-3 py-2 bg-transparent";
  const offFmt = (h: number) => {
    const arc = Math.round(Math.abs(h) * 3600);
    const parts = [Math.floor(arc / 3600), Math.floor((arc % 3600) / 60)];
    if (arc % 60) parts.push(arc % 60);
    return `UTC${h < 0 ? "-" : "+"}${parts.map(p => String(p).padStart(2, "0")).join(":")}`;
  };

  if (resolved) return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <div className="w-full max-w-md bg-card border border-bord rounded-2xl p-6 shadow-sm space-y-4">
        <h1 className="font-serif-astro text-2xl">{t("confirmOffset")}</h1>
        <div className="text-sm">
          {t("offsetUsed")}: <strong>{offFmt(resolved.utc_offset_hours)}</strong>
          <span className="text-muted"> ({t("offsetVia")} {resolved.offset_source}{resolved.timezone_name ? ` · ${resolved.timezone_name}` : ""}{resolved.tzdb_version ? ` · tzdata ${resolved.tzdb_version}` : ""})</span>
        </div>
        {(resolved.tz_warnings?.length ?? 0) > 0 && (
          <div className="text-sm border border-bord rounded-lg p-3 space-y-1">
            <div className="font-medium">{t("tzWarningsTitle")}</div>
            {resolved.tz_warnings!.map((w, i) => <div key={i} className="text-muted">· {w}</div>)}
          </div>
        )}
        <div className="flex gap-2">
          <button onClick={() => setResolved(null)} className="flex-1 border border-bord rounded-lg py-2.5">{t("changeTime")}</button>
          <button onClick={() => router.replace("/chat")} className="flex-1 bg-accent text-white rounded-lg py-2.5 font-medium">{t("confirmContinue")}</button>
        </div>
      </div>
    </main>
  );

  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <form onSubmit={e => submit(e)} className="w-full max-w-md bg-card border border-bord rounded-2xl p-6 shadow-sm space-y-4">
        <h1 className="font-serif-astro text-2xl">{t("birthTitle")}</h1>
        <p className="text-sm text-muted">{t("birthIntro")}</p>
        {adding && <label className="grid gap-2 text-sm">
          {t("profileRelation")}
          <select value={f.relation ?? "self"} onChange={e => setF({ ...f, relation: e.target.value, permission_confirmed: false })} className={inp}>
            {["self", "spouse", "mother", "father", "son", "daughter", "brother", "sister", "friend", "other"].map(relation =>
              <option key={relation} value={relation}>{relation}</option>)}
          </select>
        </label>}
        {f.relation && f.relation !== "self" && <label className="flex gap-2 text-sm">
          <input type="checkbox" required checked={!!f.permission_confirmed} onChange={e => setF({ ...f, permission_confirmed: e.target.checked })} />
          {t("profilePermission")}
        </label>}
        <input value={f.display_name} onChange={e => setF({ ...f, display_name: e.target.value })}
          placeholder={t("callYou")} className={inp} />
        <div className="grid grid-cols-3 gap-2">
          <input type="number" value={f.day} min={1} max={31} onChange={e => setF({ ...f, day: +e.target.value })} className={inp} placeholder={t("day")} />
          <select value={f.month} onChange={e => setF({ ...f, month: +e.target.value })} className={inp}>
            {t("months").split("|").map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
          </select>
          <input type="number" value={f.year} min={1850} max={2030} onChange={e => setF({ ...f, year: +e.target.value })} className={inp} placeholder={t("year")} />
        </div>
        <div className="grid grid-cols-3 gap-2">
          <label className="text-xs text-muted col-span-3 -mb-2">{t("timeOfBirth")}</label>
          <input type="number" value={f.hour} min={0} max={23} onChange={e => setF({ ...f, hour: +e.target.value })} className={inp} placeholder={t("hour")} />
          <input type="number" value={f.minute} min={0} max={59} onChange={e => setF({ ...f, minute: +e.target.value })} className={inp} placeholder={t("minute")} />
          <input type="number" value={f.second} min={0} max={59} onChange={e => setF({ ...f, second: +e.target.value })}
            className={inp} aria-label={t("second")} placeholder={t("second")} />
        </div>
        <select value={f.birth_time_precision} onChange={e => setF({ ...f, birth_time_precision: e.target.value as ProfileIn["birth_time_precision"] })} className={inp}>
          <option value="exact">{t("precExact")}</option>
          <option value="approximate">{t("precApprox")}</option>
          <option value="unknown">{t("precUnknown")}</option>
        </select>
        <div>
          <label className="text-xs text-muted">{t("timeBasis")}</label>
          <select value={f.time_basis} onChange={e => setF({ ...f, time_basis: e.target.value as ProfileIn["time_basis"], dst_fold: null })} className={inp}>
            <option value="zone">{t("tbZone")}</option>
            <option value="lmt">{t("tbLmt")}</option>
            <option value="manual">{t("tbManual")}</option>
          </select>
        </div>
        {f.time_basis === "manual" && (
          <input type="number" step="0.25" min={-14} max={14}
            value={f.utc_offset_manual ?? ""}
            onChange={e => setF({ ...f, utc_offset_manual: e.target.value === "" ? null : +e.target.value })}
            placeholder={t("manualOffsetPh")} className={inp} />
        )}
        <div>
          <label className="text-xs text-muted">{t("calcPreset")}</label>
          <select value={f.calc_preset} onChange={e => setF({ ...f, calc_preset: e.target.value })} className={inp}>
            <option value="default">{t("presetDefault")}</option>
            {f.calc_preset === "legacy_tropical" && <option value="legacy_tropical">{t("presetLegacy")}</option>}
            <option value="drik">{t("presetDrik")}</option>
            <option value="jh">{t("presetJh")}</option>
            <option value="iae">{t("presetIae")}</option>
          </select>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={manualCoords} onChange={e => setManualCoords(e.target.checked)} /> {t("manualCoords")}
        </label>
        {manualCoords ? <div className="space-y-2">
          <input value={q} onChange={e => setQ(e.target.value)} className={inp} placeholder={t("placeLabel")} />
          <div className="grid grid-cols-2 gap-2">
            <label className="text-sm">{t("latitude")}<input type="number" required min={-90} max={90} step="any"
              value={f.latitude} onChange={e => setF({ ...f, latitude: +e.target.value })} className={inp} /></label>
            <label className="text-sm">{t("longitude")}<input type="number" required min={-180} max={180} step="any"
              value={f.longitude} onChange={e => setF({ ...f, longitude: +e.target.value })} className={inp} /></label>
            <input value={f.place_state} onChange={e => setF({ ...f, place_state: e.target.value })} placeholder={t("placeState")} className={inp} />
            <input value={f.place_country} onChange={e => setF({ ...f, place_country: e.target.value })} placeholder={t("placeCountry")} className={inp} />
          </div>
        </div> : <div className="relative">
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
        </div>}
        {ambig && (
          <div className="text-sm border border-bord rounded-lg p-3 space-y-2">
            <div>{t("dstChoose")}</div>
            {ambig.offsets.map((o, i) => (
              <button key={i} type="button" disabled={busy} onClick={e => submit(e as unknown as React.FormEvent, i as 0 | 1)}
                className="w-full border border-bord rounded-lg py-2 hover:bg-bgsoft disabled:opacity-50">
                {offFmt(o)} — {i === 0 ? t("dstEarlier") : t("dstLater")}
              </button>
            ))}
          </div>
        )}
        {err && <div className="text-red-500 text-sm">{err}</div>}
        <button disabled={busy} className="w-full bg-accent text-white rounded-lg py-2.5 font-medium disabled:opacity-50">
          {busy ? t("computing") : t("continue")}
        </button>
      </form>
    </main>
  );
}
