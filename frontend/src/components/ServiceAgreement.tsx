"use client";
import { useI18n } from "@/lib/i18n";

export default function ServiceAgreement({ checked, onChange }: {
  checked: boolean; onChange: (checked: boolean) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="space-y-2 text-sm text-muted">
      <p>{t("aiDisclosure")}</p>
      <label className="flex gap-2 items-start">
        <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} required className="mt-1" />
        <span>{t("agreePrefix")} <a href="/terms" target="_blank" rel="noopener noreferrer" className="underline">{t("termsLink")}</a> {t("and")} <a href="/privacy" target="_blank" rel="noopener noreferrer" className="underline">{t("privacyPolicy")}</a>. {t("agreeSuffix")}</span>
      </label>
    </div>
  );
}
