import type { ClassicalAudit } from "@/lib/api";

export default function ClassicalEvidence({ audit, expanded, label = "Chart calculations and timing evidence" }: { audit: ClassicalAudit; expanded: boolean; label?: string }) {
  return (
    <details open={expanded} className="mb-2 min-w-0 whitespace-normal">
      <summary className="cursor-pointer font-medium text-accent">{label}</summary>
      {audit.tables.map((table, index) => (
        <div key={index} className="my-3 max-w-full overflow-x-auto" tabIndex={0}>
          <table className="w-full border-collapse text-left text-sm">
            <caption className="mb-1 text-left font-semibold">{table.title}</caption>
            <thead><tr>{table.columns.map(col => <th scope="col" key={col} className="border-b border-bord p-2">{col}</th>)}</tr></thead>
            <tbody>{table.rows.map((row, i) => (
              <tr key={i}>{row.map((cell, j) => (
                <td key={j} className="min-w-24 border-b border-bord p-2 align-top">{cell}</td>
              ))}</tr>
            ))}</tbody>
          </table>
        </div>
      ))}
      <p className="text-sm text-muted">{audit.note}</p>
    </details>
  );
}
