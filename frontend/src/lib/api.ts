// API base: same-origin ("") anywhere that isn't localhost, so a dev
// NEXT_PUBLIC_API_URL left in .env.local can never leak into a prod build.
// Only on localhost do we consult the env / fall back to the dev backend.
const API = (typeof window !== "undefined" &&
             window.location.hostname !== "localhost" &&
             window.location.hostname !== "127.0.0.1")
  ? ""
  : (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000");

export function token() {
  return typeof window === "undefined" ? "" : localStorage.getItem("jyotish_token") || "";
}
export function setToken(t: string) { localStorage.setItem("jyotish_token", t); }
export function clearToken() { localStorage.removeItem("jyotish_token"); }

function authHeaders(): Record<string, string> {
  return token() ? { authorization: `Bearer ${token()}` } : {};
}

// shared status handling: 401 -> login, 428 -> birth details, other non-2xx -> Error(detail)
export type MsgMeta = {
  options?: string[];
  followup_id?: number | string;   // prediction follow-up options
  actions?: Record<string, "edit_birth">; // option label -> client-side action instead of sending text
  varga?: string;
  chart?: unknown;                 // chart payload, shape differs per sender (see chat page)
  convergence?: string;
  support_count?: number;
  analysis?: { convergence?: string };
};
export type Msg = {
  id: number; role: string; content: string; kind: string;
  meta: MsgMeta;
  created_at: string;
};
export type Me = {
  id: number; email: string; display_name: string; has_profile: boolean;
  llm_consent: boolean; email_verified: boolean;
};
export type Place = {
  name: string; state: string; country: string; latitude: number; longitude: number;
  label?: string; timezone_name?: string; utc_offset_hours?: number;
};
export type Profile = {
  display_name: string; year: number; month: number; day: number;
  hour: number; minute: number; second: number;
  place_name: string; place_state: string; place_country: string;
  latitude: number; longitude: number;
  birth_time_precision: "exact" | "approximate" | "unknown";
  timezone_name: string; utc_offset_hours: number;
};
export type ProfileIn = Omit<Profile, "timezone_name" | "utc_offset_hours">;

export type TokenOut = { access_token: string; token_type: string; needs_birth_profile: boolean };

export function errMsg(e: unknown): string { return e instanceof Error ? e.message : String(e); }

async function failIfBad(r: Response) {
  if (r.status === 401) {
    // a failed login shouldn't bounce the page — show the server's message
    if (typeof window !== "undefined" && location.pathname !== "/login") {
      clearToken(); location.href = "/login";
    }
    const e = await r.json().catch(() => ({}));
    throw new Error(e.detail || "unauthorized");
  }
  if (r.status === 428) { if (typeof window !== "undefined") location.href = "/birth"; throw new Error("profile needed"); }
  if (!r.ok) {
    const e = await r.json().catch(() => ({}));
    const detail = Array.isArray(e.detail)
      ? e.detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join("; ")
      : e.detail;
    throw new Error(detail || `error ${r.status}`);
  }
}

async function req<T = unknown>(path: string, opts: RequestInit = {}): Promise<T> {
  const r = await fetch(API + path, {
    cache: "no-store",
    ...opts,
    headers: {
      "content-type": "application/json",
      ...authHeaders(),
      ...(opts.headers || {}),
    },
  });
  await failIfBad(r);
  return r.json();
}

// Thrown when the stream breaks AFTER the server accepted the request: the turn
// is already persisted server-side, so callers must reload history, not resend.
export class StreamBroken extends Error {}
// The server reported a failed turn via an "error" event (connection is fine):
// the user's message is kept server-side but the turn produced no reply.
export class StreamServerError extends Error {}

export type PredictionRecord = {
  id: number; domain: string; question: string;
  window_start: string | null; window_end: string | null;
  convergence: string; created_at: string | null;
  outcome: "happened" | "partly" | "did_not" | "unsure" | null;
  outcome_at: string | null;
};
export type PredictionsResponse = {
  predictions: PredictionRecord[];
  aggregate: { total: number; happened: number; partly: number; did_not: number; unsure: number; pending: number };
};

// POST /api/chat/stream — SSE over fetch. Calls onDelta for each text delta and
// resolves with the authoritative messages from the final "done" event.
export async function streamSend(text: string, onDelta: (t: string) => void): Promise<Msg[]> {
  const r = await fetch(API + "/api/chat/stream", {
    method: "POST",
    cache: "no-store",
    headers: { "content-type": "application/json", accept: "text/event-stream", ...authHeaders() },
    body: JSON.stringify({ text }),
  });
  await failIfBad(r);
  if (!r.body) throw new Error("streaming unsupported");
  // from here on the server has accepted the turn
  try {
    return await readStream(r.body, onDelta);
  } catch (e) {
    throw e instanceof StreamBroken || e instanceof StreamServerError ? e : new StreamBroken(e instanceof Error ? e.message : "stream broken");
  }
}

async function readStream(body: ReadableStream<Uint8Array>, onDelta: (t: string) => void): Promise<Msg[]> {
  const reader = body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  let done: Msg[] | null = null;

  const handle = (block: string) => {
    const data = block.split(/\r?\n/)
      .filter(l => l.startsWith("data:"))
      .map(l => l.slice(5).replace(/^ /, ""))
      .join("\n");
    if (!data) return;
    let ev: { type?: string; text?: unknown; messages?: Msg[]; detail?: string };
    try { ev = JSON.parse(data); } catch { return; }
    if (ev.type === "delta" && typeof ev.text === "string") onDelta(ev.text);
    else if (ev.type === "done") done = ev.messages || [];
    else if (ev.type === "error") throw new StreamServerError(ev.detail || "stream error");
  };

  for (;;) {
    const { value, done: fin } = await reader.read();
    buf += dec.decode(value, { stream: !fin });
    // events are separated by a blank line; a chunk may end mid-event
    const parts = buf.split(/\r?\n\r?\n/);
    buf = parts.pop() ?? "";
    for (const p of parts) handle(p);
    if (fin) break;
  }
  if (buf.trim()) handle(buf);
  if (done === null) throw new Error("stream ended without a result");
  return done;
}

export const api = {
  register: (email: string, password: string, display_name: string, llm_consent: boolean) =>
    req<TokenOut>("/api/auth/register", { method: "POST", body: JSON.stringify({ email, password, display_name, llm_consent }) }),
  setConsent: (llm_consent: boolean) =>
    req<{ llm_consent: boolean }>("/api/auth/consent", { method: "PUT", body: JSON.stringify({ llm_consent }) }),
  exportMe: () => req("/api/auth/me/export"),
  login: (email: string, password: string) =>
    req<TokenOut>("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  me: () => req<Me>("/api/auth/me"),
  deleteMe: () => req("/api/auth/me", { method: "DELETE" }),
  geoSearch: (q: string) => req<Place[]>(`/api/geo/search?q=${encodeURIComponent(q)}`),
  getProfile: () => req<Profile>("/api/profile"),
  putProfile: (p: ProfileIn) => req<Profile>("/api/profile", { method: "PUT", body: JSON.stringify(p) }),
  history: () => req<Msg[] | { messages: Msg[] }>("/api/chat/history"),
  send: (text: string) => req<Msg[]>("/api/chat/send", { method: "POST", body: JSON.stringify({ text }) }),
  resetChat: () => req("/api/chat/reset", { method: "POST" }),
  chart: (v: string) => req(`/api/chart/${v}`),
  calibration: () => req("/api/calibration"),
  forgot: (email: string) =>
    req("/api/auth/forgot", { method: "POST", body: JSON.stringify({ email }) }),
  reset: (token: string, password: string) =>
    req("/api/auth/reset", { method: "POST", body: JSON.stringify({ token, password }) }),
  verify: (token: string) =>
    req("/api/auth/verify", { method: "POST", body: JSON.stringify({ token }) }),
  resendVerify: () => req("/api/auth/verify/resend", { method: "POST" }),
  predictions: (): Promise<PredictionsResponse> => req<PredictionsResponse>("/api/predictions"),
};
