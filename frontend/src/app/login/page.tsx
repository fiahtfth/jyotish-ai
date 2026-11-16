"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, setToken, token } from "@/lib/api";

export default function Login() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (token()) router.replace("/chat"); }, [router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(""); setBusy(true);
    try {
      const r = mode === "login"
        ? await api.login(email, password)
        : await api.register(email, password, name);
      setToken(r.access_token);
      router.replace(mode === "login" ? "/chat" : "/birth");
    } catch (x: any) { setErr(x.message); } finally { setBusy(false); }
  }

  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="text-4xl font-serif-astro mb-2">Jyotish AI</div>
          <div className="text-muted text-sm">A Vedic astrologer that proves itself on your past<br/>before reading your future.</div>
        </div>
        <form onSubmit={submit} className="bg-card border border-bord rounded-2xl p-6 shadow-sm space-y-4">
          <div className="flex rounded-lg overflow-hidden border border-bord text-sm">
            {(["login", "register"] as const).map(m => (
              <button key={m} type="button" onClick={() => setMode(m)}
                className={`flex-1 py-2 capitalize ${mode === m ? "bg-accent text-white" : "text-muted"}`}>
                {m === "login" ? "Sign in" : "Create account"}
              </button>
            ))}
          </div>
          {mode === "register" && (
            <input value={name} onChange={e => setName(e.target.value)} placeholder="Your name" required
              className="w-full border border-bord rounded-lg px-3 py-2 bg-transparent" />
          )}
          <input value={email} onChange={e => setEmail(e.target.value)} type="email" placeholder="Email" required
            className="w-full border border-bord rounded-lg px-3 py-2 bg-transparent" />
          <input value={password} onChange={e => setPassword(e.target.value)} type="password" placeholder="Password" required
            className="w-full border border-bord rounded-lg px-3 py-2 bg-transparent" />
          {err && <div className="text-red-500 text-sm">{err}</div>}
          <button disabled={busy}
            className="w-full bg-accent text-white rounded-lg py-2.5 font-medium disabled:opacity-50">
            {busy ? "…" : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>
        <div className="text-center text-xs text-muted mt-6">Personalized readings grounded in your actual birth chart.</div>
      </div>
    </main>
  );
}
