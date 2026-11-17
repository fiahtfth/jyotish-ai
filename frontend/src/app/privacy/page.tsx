"use client";
// DRAFT privacy policy — must be reviewed by a lawyer (India DPDP Act 2023,
// and GDPR if serving EU users) and completed with the operator's legal name,
// address, grievance officer and contact email before public launch.
import { useI18n } from "@/lib/i18n";

export default function Privacy() {
  const { t } = useI18n();
  return (
    <main className="min-h-screen flex justify-center p-6">
      <article className="w-full max-w-2xl space-y-4 text-[15px] leading-relaxed">
        <h1 className="font-serif-astro text-3xl">{t("privTitle")}</h1>
        <p className="text-sm text-muted">{t("privNote")}</p>
        <p className="text-sm text-muted">Draft — last updated: [DATE]. Operator: [LEGAL NAME, ADDRESS]. Contact / grievance officer: [EMAIL].</p>

        <h2 className="text-xl font-semibold">{t("privCollect")}</h2>
        <ul className="list-disc pl-6 space-y-1">
          <li>Account details: email address, display name, and a one-way hash of your password.</li>
          <li>Birth details: date, time, place and coordinates of birth, used to calculate your chart.</li>
          <li>Your conversations with the astrologer and your answers to the calibration questions.</li>
        </ul>

        <h2 className="text-xl font-semibold">{t("privWhy")}</h2>
        <p>Only to provide the service: calculating your chart, checking it against your past, and answering your questions. We do not sell your data or use it for advertising.</p>

        <h2 className="text-xl font-semibold">{t("privAI")}</h2>
        <p>{t("aiDisclosure")} External AI replies are included in the service terms accepted at signup. Existing accounts are asked to accept the updated terms before continuing with AI chat. This is not a separate optional setting.</p>

        <h2 className="text-xl font-semibold">{t("privStorage")}</h2>
        <p>Data is stored in our database ([HOSTING PROVIDER, REGION]) for as long as your account exists. Deleting your account removes your account, birth details, calibration answers and conversations.</p>

        <h2 className="text-xl font-semibold">{t("privRights")}</h2>
        <ul className="list-disc pl-6 space-y-1">
          <li>Download everything we hold about you: chat menu → “Download my data”.</li>
          <li>You may stop using AI chat at any time. If you no longer agree to external AI processing, you can download your data and delete your account from the chat menu.</li>
          <li>Delete your account: chat menu → “Delete account”.</li>
          <li>For anything else, contact [EMAIL].</li>
        </ul>

        <h2 className="text-xl font-semibold">{t("privAdvice")}</h2>
        <p>Readings are traditional astrological interpretation, not medical, legal, financial or psychological advice.</p>

        <p><a href="/login" className="underline">{t("back")}</a></p>
      </article>
    </main>
  );
}
