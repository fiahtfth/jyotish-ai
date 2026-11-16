"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, clearToken, token } from "@/lib/api";
import NorthChart from "@/components/Chart";

type Msg = { id: number; role: string; content: string; kind: string; meta: any; created_at: string };

export default function Chat() {
  const router = useRouter();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [dark, setDark] = useState(false);
  const [menu, setMenu] = useState(false);
  const [me, setMe] = useState<any>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const tempId = useRef(-1);

  useEffect(() => {
    if (!token()) { router.replace("/login"); return; }
    if (localStorage.getItem("jyotish_dark") === "1") { setDark(true); document.documentElement.classList.add("dark"); }
    Promise.all([
      api.me().then(setMe).catch(() => {}),
      api.history().then((h: any) => setMsgs(Array.isArray(h) ? h : h.messages || [])),
    ]).catch((e) => { if (e.message === "profile needed") router.replace("/birth"); })
      .finally(() => setLoading(false));
  }, [router]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, busy]);

  function toggleDark() {
    const d = !dark; setDark(d);
    document.documentElement.classList.toggle("dark", d);
    localStorage.setItem("jyotish_dark", d ? "1" : "0");
  }

  async function send(text: string) {
    if (!text.trim() || busy) return;
    setInput(""); setBusy(true);
    setMsgs(m => [...m, { id: tempId.current--, role: "user", content: text, kind: "text", meta: {}, created_at: "" }]);
    try {
      const added: Msg[] = await api.send(text);
      setMsgs(m => {
        const kept = m.filter(x => x.id >= 0 || x.content !== text);
        return [...kept, ...added];
      });
    } catch (e: any) {
      if (e.message === "profile needed") router.replace("/birth");
      setMsgs(m => [...m, { id: tempId.current--, role: "assistant", content: "Something went wrong — please try again.", kind: "text", meta: {}, created_at: "" }]);
    } finally { setBusy(false); }
  }

  async function reset() {
    setBusy(true);
    try {
      await api.resetChat();
      const h = await api.history();
      setMsgs(Array.isArray(h) ? h : []);
    } catch {} finally { setBusy(false); }
  }

  const lastOptIdx = msgs.reduce((acc, m, i) => (m.kind === "options" && m.meta?.options?.length ? i : acc), -1);
  const optionsActive = lastOptIdx >= 0 && lastOptIdx > msgs.reduce((acc, m, i) => (m.role === "user" ? i : acc), -1);

  return (
    <div className="h-screen flex flex-col max-w-2xl mx-auto">
      <header className="flex items-center justify-between px-4 py-3 border-b border-bord">
        <div>
          <div className="font-serif-astro text-lg leading-tight">Jyotish AI</div>
          <div className="text-xs text-muted">{me ? `for ${me.display_name || me.email}` : ""}</div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={toggleDark} className="text-sm text-muted border border-bord rounded-lg px-3 py-1.5">
            {dark ? "Light" : "Dark"}
          </button>
          <div className="relative">
            <button onClick={() => setMenu(!menu)} className="w-8 h-8 rounded-full bg-accentsoft text-accent font-bold">
              {(me?.display_name || me?.email || "?")[0].toUpperCase()}
            </button>
            {menu && (
              <div className="absolute right-0 mt-2 w-44 bg-card border border-bord rounded-lg shadow-lg text-sm z-20">
                <button onClick={() => router.push("/birth")} className="w-full text-left px-3 py-2 hover:bg-bgsoft">Edit birth details</button>
                <button onClick={() => { setMenu(false); reset(); }} className="w-full text-left px-3 py-2 hover:bg-bgsoft">Restart conversation</button>
                <button onClick={() => { clearToken(); router.replace("/login"); }} className="w-full text-left px-3 py-2 hover:bg-bgsoft text-red-500">Sign out</button>
              </div>
            )}
          </div>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {loading && <div className="text-center text-muted text-sm mt-10">Drawing your chart…</div>}
        {msgs.map((m, i) => {
          if (m.kind === "options") {
            return (
              <div key={m.id}>
                <div className="flex justify-start">
                  <div className="max-w-[85%] rounded-2xl px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap bg-card border border-bord rounded-bl-sm">
                    {m.content}
                  </div>
                </div>
                {i === lastOptIdx && optionsActive && !busy && (
                  <div className="flex flex-wrap gap-2 justify-end mt-2">
                    {m.meta.options.map((o: string) => (
                      <button key={o} onClick={() => send(o)}
                        className="border border-accent text-accent rounded-full px-4 py-1.5 text-sm hover:bg-accent hover:text-white transition">
                        {o}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            );
          }
          const mine = m.role === "user";
          return (
            <div key={m.id} className={`flex ${mine ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap
                ${mine ? "bg-accent text-white rounded-br-sm" : "bg-card border border-bord rounded-bl-sm"}`}>
                {m.content}
                {m.kind === "chart" && m.meta?.chart && (
                  <div className="mt-3 bg-bgsoft rounded-xl p-3">
                    <NorthChart varga={m.meta.varga || m.meta.chart.varga} chart={m.meta.chart.chart || m.meta.chart} />
                  </div>
                )}
                {m.kind === "analysis" && (
                  <div className="mt-2 text-xs text-muted border-t border-bord pt-2">
                    convergence: {m.meta.convergence || "—"} · support {m.meta.support_count ?? "—"}
                  </div>
                )}
              </div>
            </div>
          );
        })}
        {busy && (
          <div className="flex"><div className="bg-card border border-bord rounded-2xl rounded-bl-sm px-4 py-3 text-muted text-sm">
            <span className="animate-pulse">thinking…</span>
          </div></div>
        )}
        <div ref={endRef} />
      </div>

      <div className="border-t border-bord p-3">
        <div className="flex gap-2">
          <input value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === "Enter" && send(input)}
            placeholder="Ask anything…"
            className="flex-1 border border-bord rounded-full px-4 py-2.5 bg-transparent text-[15px] outline-none focus:border-accent" />
          <button onClick={() => send(input)} disabled={busy || !input.trim()}
            className="bg-accent text-white rounded-full px-5 py-2.5 font-medium disabled:opacity-40">Send</button>
        </div>
      </div>
    </div>
  );
}
