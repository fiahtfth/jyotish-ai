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

export default function NorthChart({ varga, chart }: { varga: string; chart: Record<string, { sign: number; degree: number }> }) {
  const lagnaSign: number = chart?.Lagna?.sign ?? 0;
  const houseSign = (h: number) => (lagnaSign + h - 1) % 12;
  const signHouse: Record<number, number> = {};
  for (let h = 1; h <= 12; h++) signHouse[houseSign(h)] = h;
  const occupants: Record<number, string[]> = {};
  for (const [name, p] of Object.entries(chart || {})) {
    const h = signHouse[p.sign];
    if (h == null) continue;
    (occupants[h] = occupants[h] || []).push(ABBR[name] || name.slice(0, 2));
  }

  return (
    <div className="w-full max-w-[240px] mx-auto">
      <svg viewBox="0 0 200 200" className="w-full">
        <rect x="0" y="0" width="200" height="200" fill="none" stroke="var(--accent)" strokeWidth="1.5" />
        <line x1="0" y1="0" x2="200" y2="200" stroke="var(--accent)" strokeWidth="1" />
        <line x1="200" y1="0" x2="0" y2="200" stroke="var(--accent)" strokeWidth="1" />
        <polygon points="100,0 200,100 100,200 0,100" fill="none" stroke="var(--accent)" strokeWidth="1" />
        {Object.entries(CENTROID).map(([h, [x, y]]) => {
          const hi = +h;
          return (
            <g key={h}>
              <text x={x - 16} y={y - 5} fontSize="8" fill="var(--muted)">{houseSign(hi) + 1}</text>
              {(occupants[hi] || []).map((t, i) => (
                <text key={i} x={x - 14 + (i % 3) * 15} y={y + 7 + Math.floor(i / 3) * 10}
                  fontSize="9" fontWeight="600" fill="var(--fg)">{t}</text>
              ))}
            </g>
          );
        })}
      </svg>
      <div className="text-center text-xs text-muted mt-1">
        {varga} · Lagna {SIGN_NAMES[lagnaSign]}
      </div>
    </div>
  );
}
