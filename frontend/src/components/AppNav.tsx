"use client";
import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useI18n } from "@/lib/i18n";

const advanced = [["/dashboard", "navDashboard"], ["/varshaphala", "svcVarsha"], ["/prashna", "svcPrashna"]] as const;

export default function AppNav() {
  const { t } = useI18n();
  const path = usePathname() || "";
  const [open, setOpen] = useState(false);
  const main = [["/home", t("navHome")], ["/chat", t("navChat")], ["/matching", t("svcMatching")],
    ["/muhurta", t("svcMuhurta")], ["/predictions", t("myPredictions")]];
  const on = (h: string) => path === h || path.startsWith(h + "/");
  const cls = (a: boolean) => `whitespace-nowrap rounded-lg px-3 py-1.5 text-sm ${a ? "bg-accentsoft text-accent font-medium" : "text-muted hover:text-accent"}`;
  const advActive = advanced.some(([h]) => on(h));
  return (
    <nav aria-label={t("navMain")} className="flex w-full items-center gap-1 overflow-x-auto border-b border-bord bg-card px-2 py-1.5">
      {main.map(([href, label]) => (
        <Link key={href} href={href} aria-current={on(href) ? "page" : undefined} className={cls(on(href))}>{label}</Link>
      ))}
      <div className="relative ml-auto">
        <button type="button" aria-expanded={open} aria-haspopup="true" onClick={() => setOpen(!open)} className={cls(advActive)}>
          {t("navAdvanced")} ▾
        </button>
        {open && (
          <div className="absolute right-0 z-30 mt-1 w-44 rounded-lg border border-bord bg-card text-sm shadow-lg">
            {advanced.map(([href, key]) => (
              <Link key={href} href={href} onClick={() => setOpen(false)} aria-current={on(href) ? "page" : undefined}
                className="block px-3 py-2 hover:bg-bgsoft">{t(key)}</Link>
            ))}
          </div>
        )}
      </div>
    </nav>
  );
}
