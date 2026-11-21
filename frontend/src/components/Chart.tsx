"use client";
import { useState, useSyncExternalStore } from "react";
import { useI18n } from "@/lib/i18n";

const ABBR: Record<string, string> = {
  Sun: "Su", Moon: "Mo", Mars: "Ma", Mercury: "Me", Jupiter: "Ju", Venus: "Ve",
  Saturn: "Sa", Rahu: "Ra", Ketu: "Ke", Lagna: "La",
};

// North Indian layout: fixed house regions, sign numbers vary with lagna.
// House centroids in a 200x200 grid (square + diagonals + midpoint diamond).
const CENTROID: Record<number, [number, number]> = {
  1: [100, 30], 2: [50, 16], 3: [16, 50], 4: [33, 100], 5: [16, 150], 6: [50, 183],
  7: [100, 170], 8: [150, 183], 9: [183, 150], 10: [167, 100], 11: [183, 50], 12: [150, 16],
};
const SIGN_NAMES = ["Aries","Taurus","Gemini","Cancer","Leo","Virgo","Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"];
const SIGN_LORDS = ["Mars","Venus","Mercury","Moon","Sun","Mercury","Venus","Mars","Jupiter","Saturn","Saturn","Jupiter"];

// South Indian layout: signs are fixed in a 4x4 grid (centre 2x2 blank), [row, col] per sign index.
const SOUTH_CELL: [number, number][] = [
  [0, 1], [0, 2], [0, 3], [1, 3], [2, 3], [3, 3], [3, 2], [3, 1], [3, 0], [2, 0], [1, 0], [0, 0],
];

// Flags are optional: D1 chart entries may only carry sign/degree.
export type ChartData = Record<string, { sign: number; degree: number; retrograde?: boolean; combust?: boolean }>;
type Style = "north" | "south";
const STYLE_KEY = "jyotish_chart_style";
const styleSubs = new Set<() => void>();
const subStyle = (cb: () => void) => { styleSubs.add(cb); return () => { styleSubs.delete(cb); }; };
const getStyle = (): Style => (localStorage.getItem(STYLE_KEY) === "south" ? "south" : "north");
const getStyleServer = (): Style => "north";

type Occ = { name: string; label: string; retro: boolean; comb: boolean };

// Rahu and Ketu always move backward, so they are never marked retrograde.
const NODES = new Set(["Rahu", "Ketu"]);

// moonChart: the birth time is unknown, so the Moon sign is drawn as Lagna (Chandra Lagna).
export default function NorthChart({ varga, chart, moonChart = false }: { varga: string; chart: ChartData; moonChart?: boolean }) {
  const { t } = useI18n();
  const style = useSyncExternalStore(subStyle, getStyle, getStyleServer);
  const [sel, setSel] = useState<number | null>(null); // selected sign index
  function pick(s: Style) { localStorage.setItem(STYLE_KEY, s); styleSubs.forEach(cb => cb()); }

  const lagnaSign: number = chart?.Lagna?.sign ?? 0;
  const houseSign = (h: number) => (lagnaSign + h - 1) % 12;
  const signHouse = (sign: number) => ((sign - lagnaSign + 12) % 12) + 1;

  // occupants by sign index (Lagna included as a marker, listed first)
  const bySign: Record<number, Occ[]> = {};
  for (const [name, p] of Object.entries(chart || {})) {
    (bySign[p.sign] = bySign[p.sign] || []).push({
      name, label: ABBR[name] || name.slice(0, 2), retro: !!p.retrograde && !NODES.has(name), comb: !!p.combust && !NODES.has(name),
    });
  }
  const occText = (o: Occ) => o.label + (o.retro ? " R" : "") + (o.comb ? " c" : "");
  const occFull = (o: Occ) => o.name + (o.retro ? ` (${t("retro")})` : "") + (o.comb ? ` (${t("combust")})` : "");

  const lagnaWord = moonChart ? t("chandraLagna") : t("lagna");
  const summary = `${varga} ${lagnaWord} ${SIGN_NAMES[lagnaSign]}. ` +
    Array.from({ length: 12 }, (_, i) => i).map(sign => {
      const o = (bySign[sign] || []).filter(x => x.name !== "Lagna");
      return o.length ? `${o.map(occFull).join(", ")} — ${SIGN_NAMES[sign]}, ${t("house")} ${signHouse(sign)}` : "";
    }).filter(Boolean).join("; ");

  const stroke = { stroke: "var(--accent)", fill: "none" } as const;
  const hit = (sign: number) => ({
    role: "button" as const, tabIndex: 0, style: { cursor: "pointer", outline: "none" },
    "aria-label": `${t("house")} ${signHouse(sign)}, ${SIGN_NAMES[sign]}`,
    "aria-pressed": sel === sign,
    onClick: () => setSel(sel === sign ? null : sign),
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSel(sel === sign ? null : sign); }
    },
  });
  const hl = (sign: number) => sel === sign ? "var(--accent-soft)" : "transparent";

  const selOcc = sel != null ? (bySign[sel] || []).filter(o => o.name !== "Lagna") : [];

  return (
    <div className="w-full max-w-[240px] mx-auto">
      <div className="flex justify-center gap-1 mb-2 text-[11px]" role="group" aria-label={t("chartStyle")}>
        {(["north", "south"] as const).map(s => (
          <button key={s} type="button" onClick={() => pick(s)} aria-pressed={style === s}
            className={`px-2 py-0.5 rounded-full border border-bord ${style === s ? "bg-accent text-white" : "text-muted"}`}>
            {t(s === "north" ? "northIndian" : "southIndian")}
          </button>
        ))}
      </div>
      <svg viewBox="0 0 200 200" className="w-full" role="group" aria-label={summary}>
        <title>{`${varga} — ${t(style === "north" ? "northIndian" : "southIndian")}`}</title>
        <desc>{`${t("chartDesc")} ${summary}`}</desc>
        {style === "north" ? (
          <>
            <rect x="0" y="0" width="200" height="200" {...stroke} strokeWidth="1.5" />
            <line x1="0" y1="0" x2="200" y2="200" {...stroke} strokeWidth="1" />
            <line x1="200" y1="0" x2="0" y2="200" {...stroke} strokeWidth="1" />
            <polygon points="100,0 200,100 100,200 0,100" {...stroke} strokeWidth="1" />
            {Object.entries(CENTROID).map(([h, [x, y]]) => {
              const hi = +h;
              const sign = houseSign(hi);
              const occ = (bySign[sign] || []).filter(o => o.name !== "Lagna");
              return (
                <g key={h} {...hit(sign)}>
                  <circle cx={x} cy={y} r="22" fill={hl(sign)} opacity="0.7" />
                  <text x={x - 16} y={y - 5} fontSize="8" fill="var(--muted)">{sign + 1}</text>
                  {hi === 1 && <text x={x + 8} y={y - 5} fontSize="8" fontWeight="700" fill="var(--accent)">{ABBR.Lagna}</text>}
                  {occ.map((o, i) => (
                    <text key={o.name} x={x - 14 + (i % 3) * 15} y={y + 7 + Math.floor(i / 3) * 10}
                      fontSize="9" fontWeight="600" fill="var(--fg)">{occText(o)}</text>
                  ))}
                </g>
              );
            })}
          </>
        ) : (
          <>
            {Array.from({ length: 12 }, (_, sign) => {
              const [r, c] = SOUTH_CELL[sign];
              const x = c * 50, y = r * 50;
              const occ = (bySign[sign] || []).filter(o => o.name !== "Lagna");
              const isLagna = sign === lagnaSign;
              return (
                <g key={sign} {...hit(sign)}>
                  <rect x={x} y={y} width="50" height="50" fill={sel === sign ? "var(--accent-soft)" : "none"}
                    stroke="var(--accent)" strokeWidth="1" />
                  {isLagna && <line x1={x} y1={y} x2={x + 14} y2={y} stroke="var(--accent)" strokeWidth="3" />}
                  {isLagna && <line x1={x} y1={y} x2={x} y2={y + 14} stroke="var(--accent)" strokeWidth="3" />}
                  <text x={x + 3} y={y + 47} fontSize="7" fill="var(--muted)">{SIGN_NAMES[sign].slice(0, 3)}</text>
                  {isLagna && <text x={x + 5} y={y + 14} fontSize="8" fontWeight="700" fill="var(--accent)">{ABBR.Lagna}</text>}
                  {occ.map((o, i) => (
                    <text key={o.name} x={x + 5 + (i % 2) * 22} y={y + 24 + Math.floor(i / 2) * 10}
                      fontSize="9" fontWeight="600" fill="var(--fg)">{occText(o)}</text>
                  ))}
                </g>
              );
            })}
            <text x="100" y="98" textAnchor="middle" fontSize="9" fill="var(--muted)">{varga}</text>
            <text x="100" y="110" textAnchor="middle" fontSize="8" fill="var(--muted)">{lagnaWord} {SIGN_NAMES[lagnaSign]}</text>
          </>
        )}
      </svg>
      <div className="text-center text-xs text-muted mt-1">
        {varga} · {lagnaWord} {SIGN_NAMES[lagnaSign]}
      </div>
      {sel != null && (
        <div className="mt-2 text-xs border border-bord rounded-lg p-2 bg-card" role="status">
          <div><span className="text-muted">{t("house")}:</span> {signHouse(sel)}</div>
          <div><span className="text-muted">{t("sign")}:</span> {SIGN_NAMES[sel]}</div>
          <div><span className="text-muted">{t("signLord")}:</span> {SIGN_LORDS[sel]}</div>
          <div><span className="text-muted">{t("occupants")}:</span> {selOcc.length ? selOcc.map(occFull).join(", ") : t("none")}</div>
        </div>
      )}
    </div>
  );
}
