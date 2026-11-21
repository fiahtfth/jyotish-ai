"use client";
// DRAFT privacy policy — must be reviewed by a lawyer (India DPDP Act 2023,
// and GDPR if serving EU users). Operator details come from environment
// variables (NEXT_PUBLIC_LEGAL_NAME, NEXT_PUBLIC_GRIEVANCE_OFFICER,
// NEXT_PUBLIC_HOSTING_REGION, NEXT_PUBLIC_RETENTION_PERIOD) and show a clear
// "to be filled" text until the operator sets them.
import { useEffect, useState } from "react";
import { api, errMsg, token, type Me } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

const TBD = "— to be filled by operator";
const LEGAL_NAME = process.env.NEXT_PUBLIC_LEGAL_NAME || TBD;
const GRIEVANCE = process.env.NEXT_PUBLIC_GRIEVANCE_OFFICER || TBD;
const HOSTING = process.env.NEXT_PUBLIC_HOSTING_REGION || TBD;
const BACKUPS = process.env.NEXT_PUBLIC_RETENTION_PERIOD || TBD;

function AiConsent() {
  const { t } = useI18n();
  const [me, setMe] = useState<Me | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    if (token()) api.me().then(setMe).catch(() => {});
  }, []);
  if (!me) return null;
  const on = me.ai_processing_enabled !== false;
  async function toggle() {
    setErr("");
    try {
      if (on) await api.withdrawConsent(); else await api.resumeConsent();
      setMe(m => m ? { ...m, ai_processing_enabled: !on } : m);
    } catch (e) { setErr(errMsg(e)); }
  }
  return (
    <div id="ai-consent" className="border border-bord rounded-lg p-3 space-y-2 text-sm">
      <div>{t(on ? "aiStatusOn" : "aiStatusOff")}</div>
      <button type="button" onClick={toggle} className="border border-bord rounded-lg px-3 py-1.5">
        {t(on ? "aiWithdraw" : "aiResume")}
      </button>
      {err && <div className="text-red-500">{err}</div>}
    </div>
  );
}

export default function Privacy() {
  const { t } = useI18n();
  return (
    <main className="min-h-screen flex justify-center p-6">
      <article className="w-full max-w-2xl space-y-4 text-[15px] leading-relaxed">
        <h1 className="font-serif-astro text-3xl">{t("privTitle")}</h1>
        <p className="text-sm text-muted">{t("privNote")}</p>
        <p className="text-sm text-muted">Draft policy. Operator: {LEGAL_NAME}. Grievance officer / contact: {GRIEVANCE}.</p>

        <h2 className="text-xl font-semibold">{t("privCollect")}</h2>
        <ul className="list-disc pl-6 space-y-1">
          <li>Account details: email address, display name, and a one-way hash of your password.</li>
          <li>Birth details: date, time, place and coordinates of birth, used to calculate your chart.</li>
          <li>Your conversations, answers to birth-time checks and key details the chat remembers from what you share. Those details are stored with the conversation for the selected birth profile.</li>
          <li>Optional gender and current city of residence, if you add them (residence is used for today&apos;s panchang and timing context; gender only for compatibility matching).</li>
          <li>Birth profiles of family members and friends are stored under your account on your assurance that you have their permission. If they are under 18, you confirm you are their parent or guardian. Accounts are for people aged 18 or older.</li>
          <li>Shared birth profiles require your confirmation that you have permission to use those details. The optional forecast follow-up setting controls whether the chat asks you to report outcomes.</li>
        </ul>

        <h2 className="text-xl font-semibold">{t("privWhy")}</h2>
        <p>Only to provide the service: calculating your chart, checking it against your past, and answering your questions. We do not sell your data or use it for advertising.</p>

        <h2 className="text-xl font-semibold">{t("privAI")}</h2>
        <p>{t("aiDisclosure")} External AI replies are included in the service terms accepted at signup.</p>
        <p>To write a reply, your date and place of birth (and current city, if set), a summary of your chart, and the text of your recent chat messages are sent to Google (Gemini), Groq and/or OpenRouter, depending on which are configured. These providers may process data on servers outside India. We send what is needed for the reply and do not send your email or password.</p>
        <p>You can withdraw consent for AI processing at any time without deleting your account. Chat then gives computed chart facts only, and nothing is sent to these providers.</p>
        <AiConsent />

        <h2 className="text-xl font-semibold">{t("privStorage")}</h2>
        <p>Data is stored in our database (hosting region: {HOSTING}) for as long as your account exists. Deleting your account removes your account, birth details, calibration answers and conversations right away. Backups and logs are kept for a limited period after deletion: {BACKUPS}. Data held by AI providers is governed by their own terms.</p>
        <h2 className="text-xl font-semibold">Security incidents</h2>
        <p>If a breach of personal data affects you, we will tell you and the Data Protection Board of India without undue delay, as the law requires, saying what happened and what you can do.</p>

        <h2 className="text-xl font-semibold">{t("privRights")}</h2>
        <ul className="list-disc pl-6 space-y-1">
          <li>Download everything we hold about you: chat menu → “Download my data”.</li>
          <li>Ask “What do you remember about me?” to see key details saved from your current conversation. Restarting the conversation clears those notes with the messages.</li>
          <li>Withdraw consent for AI processing without deleting your account: the button above, or chat menu → “Withdraw AI consent”.</li>
          <li>Delete your account: chat menu → “Delete account”.</li>
          <li>For complaints or anything else, contact the grievance officer: {GRIEVANCE}.</li>
        </ul>

        <h2 className="text-xl font-semibold">{t("privAdvice")}</h2>
        <p>Readings are traditional astrological interpretation, not medical, legal, financial or psychological advice.</p>

        <p><a href="/login" className="underline">{t("back")}</a></p>
      </article>
    </main>
  );
}
