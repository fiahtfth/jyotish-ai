"use client";
import { useI18n } from "@/lib/i18n";
import AppNav from "@/components/AppNav";

export const input = "rounded-lg border border-bord bg-card px-3 py-2";
export const button = "rounded-lg bg-accent px-4 py-2 text-white disabled:opacity-50";
export const panel = "rounded-xl border border-bord bg-card p-4 sm:p-6";

export default function ServiceNav({ title }: { title: string }) {
  const { t } = useI18n();
  return (
    <header className="space-y-2">
      <AppNav />
      <h1 className="font-serif-astro text-3xl sm:text-4xl">{title}</h1>
      <p className="text-sm text-muted">{t("svcNote")}</p>
    </header>
  );
}
