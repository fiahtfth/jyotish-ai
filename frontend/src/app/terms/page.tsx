"use client";
import { useI18n } from "@/lib/i18n";

export default function Terms() {
  const { t } = useI18n();
  return (
    <main className="min-h-screen flex justify-center p-6">
      <article className="w-full max-w-2xl space-y-5 text-[15px] leading-relaxed">
        <h1 className="font-serif-astro text-3xl">{t("termsTitle")}</h1>
        <p className="text-sm text-muted">{t("termsDate")}</p>
        <p>{t("termsService")}</p>
        <p>{t("aiDisclosure")}</p>
        <p>{t("termsData")}</p>
        <p>{t("termsAccuracy")}</p>
        <p>{t("termsChoice")}</p>
        <p><a href="/privacy" className="underline">{t("privacyPolicy")}</a></p>
        <p><a href="/login" className="underline">{t("back")}</a></p>
      </article>
    </main>
  );
}
