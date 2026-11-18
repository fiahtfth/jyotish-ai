// The exported app and API are served together, including local previews.
// Only the Next development server needs a separate backend address.
const API = process.env.NODE_ENV === "development"
  ? (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000")
  : "";

export function token() {
  return typeof window === "undefined" ? "" : localStorage.getItem("jyotish_token") || "";
}
export function setToken(t: string) { localStorage.setItem("jyotish_token", t); }
export function clearToken() { localStorage.removeItem("jyotish_token"); }

function authHeaders(): Record<string, string> {
  return token() ? { authorization: `Bearer ${token()}` } : {};
}

// shared status handling: 401 -> login, 428 -> birth details, other non-2xx -> Error(detail)
export type ClassicalAudit = {
  note: string;
  tables: { title: string; columns: string[]; rows: string[][] }[];
};
export type MsgMeta = {
  options?: string[];
  followup_id?: number | string;   // prediction follow-up options
  actions?: Record<string, "edit_birth">; // option label -> client-side action instead of sending text
  varga?: string;
  chart?: unknown;                 // chart payload, shape differs per sender (see chat page)
  convergence?: string;
  support_count?: number;
  classical?: ClassicalAudit;
  report?: { domains?: { domain: string; analysis?: { classical?: ClassicalAudit } }[] };
  expanded?: boolean;
  analysis?: { convergence?: string; classical?: ClassicalAudit; decision?: { event?: unknown } };
};
export type Msg = {
  id: number; role: string; content: string; kind: string;
  meta: MsgMeta;
  created_at: string;
};
export type Me = {
  id: number; email: string; display_name: string; has_profile: boolean;
  llm_consent: boolean; email_verified: boolean; ai_terms_required: boolean; terms_version: string | null;
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
  time_basis: "zone" | "lmt" | "manual";
  utc_offset_manual: number | null;
  dst_fold: 0 | 1 | null;
  calc_preset: string;
  timezone_name: string; utc_offset_hours: number;
  offset_source?: string; tz_warnings?: string[]; tzdb_version?: string;
};
export type ProfileIn = Omit<Profile, "timezone_name" | "utc_offset_hours" | "offset_source" | "tz_warnings" | "tzdb_version">;
export type TzReject = { code: "ambiguous_time" | "nonexistent_time"; message: string; offsets: number[] | [number, number]; timezone_name?: string };
export class TzError extends Error { detail: TzReject; constructor(d: TzReject) { super(d.message); this.detail = d; } }

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
    if (e.detail && typeof e.detail === "object" && !Array.isArray(e.detail)
        && (e.detail.code === "ambiguous_time" || e.detail.code === "nonexistent_time")) {
      throw new TzError(e.detail as TzReject);
    }
    const detail = Array.isArray(e.detail)
      ? e.detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join("; ")
      : typeof e.detail === "object" && e.detail ? e.detail.message : e.detail;
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
  forecast?: "event_indicated" | "abstain" | null;
  success_criteria?: string | null;
  window_start: string | null; window_end: string | null;
  convergence: string; created_at: string | null;
  outcome: "happened" | "partly" | "did_not" | "unsure" | "outside_window" | null;
  outcome_at: string | null;
};
export type PredictionsResponse = {
  predictions: PredictionRecord[];
  scorecard?: { total_analyses: number; issued_forecasts: number; abstentions: number; prospective_forecasts: number;
    matured: number; scored: number; hits: number; misses: number; partial: number; unresolved: number; note: string };
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
  if (!r.body) throw new StreamBroken("No response stream. Reload the conversation to check your message.");
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

  try {
    for (;;) {
      const { value, done: fin } = await reader.read();
      buf += dec.decode(value, { stream: !fin });
      const parts = buf.split(/\r?\n\r?\n/);
      buf = parts.pop() ?? "";
      for (const p of parts) {
        handle(p);
        if (done !== null) return done;
      }
      if (fin) break;
    }
    if (buf.trim()) handle(buf);
    if (done === null) throw new Error("Connection interrupted. Reload the conversation to check your message.");
    return done;
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export const api = {
  register: (email: string, password: string, display_name: string, terms_accepted: boolean) =>
    req<TokenOut>("/api/auth/register", { method: "POST", body: JSON.stringify({ email, password, display_name, terms_accepted }) }),
  acceptTerms: () => req<{ llm_consent: boolean; ai_terms_required: boolean; terms_version: string }>(
    "/api/auth/terms", { method: "POST", body: JSON.stringify({ terms_accepted: true }) }),
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
  predictionOutcome: (id: number, outcome: string, event_date?: string) => req(`/api/predictions/${id}/outcome`, {
    method: "POST", body: JSON.stringify({ outcome, event_date }) }),
  predictions: (): Promise<PredictionsResponse> => req<PredictionsResponse>("/api/predictions"),
};
