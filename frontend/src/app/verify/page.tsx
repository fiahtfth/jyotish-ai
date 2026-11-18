"use client";
import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

function VerifyResult() {
  const { t } = useI18n();
  const token = useSearchParams().get("token") || "";
  const [state, setState] = useState<"busy" | "ok" | "fail">(token ? "busy" : "fail");

  useEffect(() => {
    if (!token) return;
    let live = true;
    api.verify(token).then(() => live && setState("ok")).catch(() => live && setState("fail"));
    return () => { live = false; };
  }, [token]);

  return (
    <div className="w-full max-w-sm bg-card border border-bord rounded-2xl p-6 shadow-sm space-y-4">
      <h1 className="font-serif-astro text-2xl">{t("verifyTitle")}</h1>
      <p className="text-sm" role="status">
        {state === "busy" ? t("verifying") : state === "ok" ? t("verifyOk") : t("verifyFail")}
      </p>
      <div className="text-center text-xs">
        <Link href={state === "ok" ? "/chat" : "/login"} className="underline text-muted">
          {state === "ok" ? t("goToChat") : t("backToSignIn")}
        </Link>
      </div>
    </div>
  );
}

export default function Verify() {
  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <Suspense fallback={null}><VerifyResult /></Suspense>
    </main>
  );
}
