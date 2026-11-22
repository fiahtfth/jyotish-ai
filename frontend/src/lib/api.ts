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
  notice?: string;                 // short non-conversational note shown above a reply
  followup_id?: number | string;   // prediction follow-up options
  actions?: Record<string, "edit_birth">; // option label -> client-side action instead of sending text
  varga?: string;
  chart?: unknown;                 // chart payload, shape differs per sender (see chat page)
  chandra_lagna?: boolean;         // birth time unknown: the chart is the Moon chart
  convergence?: string;
  support_count?: number;
  classical?: ClassicalAudit;
  career_sources?: { attribution?: string; database?: string; license?: string };
  career_result?: {
    leader: string | null;
    india_reference?: string;
    roles: { title: string; code?: string; matched: string[]; preferred: string[]; blockers: string[]; unknown: string[] }[];
  };
  report?: { domains?: { domain: string; analysis?: { classical?: ClassicalAudit } }[] };
  expanded?: boolean;
  followup?: { id: number; options: string[]; question?: string; success_criteria?: string | null };
  card?: unknown;                  // core-engine answer card; shaped like components/AnswerCard Card
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
  age_confirmed?: boolean; ai_processing_enabled?: boolean;
};
export type Place = {
  name: string; state: string; country: string; latitude: number; longitude: number;
  label?: string; timezone_name?: string; utc_offset_hours?: number;
};
export type Profile = {
  id?: number; relation?: string; permission_confirmed?: boolean;
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
  // optional extras
  gender?: "female" | "male" | "other" | "prefer_not_to_say" | null;
  residence_name?: string; residence_state?: string; residence_country?: string;
  residence_latitude?: number | null; residence_longitude?: number | null;
  residence_timezone_name?: string; is_minor?: boolean;
};
export type ProfileIn = Omit<Profile, "timezone_name" | "utc_offset_hours" | "offset_source" | "tz_warnings" | "tzdb_version" | "residence_timezone_name" | "is_minor">;
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
export type OutcomePrediction = {
  id: number; domain: string; event_type: string | null; question: string; success_criteria: string | null;
  window_start: string | null; window_end: string | null;
  outcome: PredictionRecord["outcome"]; event_date: string | null;
};
export type PredictionsResponse = {
  predictions: PredictionRecord[];
  followups_enabled?: boolean;
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
  register: (email: string, password: string, display_name: string, terms_accepted: boolean, age_confirmed: boolean) =>
    req<TokenOut>("/api/auth/register", { method: "POST", body: JSON.stringify({ email, password, display_name, terms_accepted, age_confirmed }) }),
  withdrawConsent: () => req<{ ai_processing_enabled: boolean }>("/api/auth/me/withdraw-consent", { method: "POST" }),
  resumeConsent: () => req<{ ai_processing_enabled: boolean }>("/api/auth/me/resume-consent", {
    method: "POST", body: JSON.stringify({ terms_accepted: true }) }),
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
  createProfile: (p: ProfileIn) => req<Profile>("/api/profiles", { method: "POST", body: JSON.stringify(p) }),
  listProfiles: () => req<ProfileItem[]>("/api/profiles"),
  activateProfile: (id: number) => req<ProfileItem>(`/api/profiles/${id}/activate`, { method: "POST" }),
  profilePermission: (id: number, permission_confirmed: boolean) => req<ProfileItem>(`/api/profiles/${id}/permission`, {
    method: "PUT", body: JSON.stringify({ permission_confirmed }) }),
  history: () => req<Msg[] | { messages: Msg[] }>("/api/chat/history"),
  send: (text: string) => req<Msg[]>("/api/chat/send", { method: "POST", body: JSON.stringify({ text }) }),
  resetChat: () => req("/api/chat/reset", { method: "POST" }),
  chart: (v: string) => req(`/api/chart/${v}`),
  chartDashboard: (date = "") => req<ChartDashboard>(`/api/chart-dashboard${date ? `?as_of=${encodeURIComponent(date)}` : ""}`),
  chartTransits: (start: string, end: string, planet: string) => req<ChartTransits>(
    `/api/chart-transits?${new URLSearchParams({ start, end, planet })}`),
  kpChart: () => req<KpChart>("/api/kp"),
  degreeTable: (text: string, source_program: string, ayanamsa_id: string) =>
    req<DegreeTable>("/api/tools/degree-table", { method: "POST", body: JSON.stringify({ text, source_program, ayanamsa_id }) }),
  coverage: () => req<Coverage>("/api/coverage"),
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
  duePredictions: () => req<{ due: OutcomePrediction[]; count: number }>("/api/predictions/due"),
  answeredPredictions: () => req<{ answered: OutcomePrediction[] }>("/api/predictions/history"),
  predictions: (): Promise<PredictionsResponse> => req<PredictionsResponse>("/api/predictions"),
  predictionFollowups: (enabled: boolean) =>
    req<{ followups_enabled: boolean }>("/api/predictions/followups", { method: "PUT", body: JSON.stringify({ enabled }) }),
};

export type ProfileItem = { id: number; display_name: string; relation: string; is_active: boolean; permission_confirmed: boolean };

type Window = { start_s: number; end_s: number; margin_before_s: number; margin_after_s: number; status: string; open_ended: boolean };
type Dasha = { lords?: string[]; signs?: string[]; start: string; end: string };
type Position = { sign: number; degree: number; sign_name: string; house: number; dignity: string[];
  retrograde: boolean; combust: boolean; gandanta: boolean; sandhi: boolean; vargottama: boolean; nakshatra: { name: string; pada: number } };
export type ChartDashboard = {
  settings: { calc_settings: Record<string, string | number>; varga_rule_version: string; varga_schemes: Record<string, string>;
    ayanamsa: { id: string; dms: string }; ephemeris: string; warnings: string[]; tzdb_version: string;
    dasha_year: { mode: string; days: number }; utc_offset_hours: number; birth_datetime_local: string; place: string };
  time_known?: boolean; chandra_lagna?: boolean;   // false/true when the birth time is unknown (Moon chart)
  vargas: Record<string, import("@/components/Chart").ChartData>;
  planets: Record<string, Position>;
  aspects: { from: string; to: string; distance: number }[];
  yogas: { id: string; name: string; level: string; source: string; conditions_fired: string[]; note?: string }[];
  ashtakavarga: { signs: string[]; planets: string[]; sav: number[] | null; bav: number[][] | null };
  sensitivity: Record<string, Window>;
  moon_pada: Window & { pada: number };
  dashas: { date: string; dasha_year: string; date_convention: string; vimshottari: Dasha[]; yogini: Dasha[]; chara: Dasha[] };
};
export type ChartTransits = {
  time_zone: string; rule_version: string; reduced_precision: boolean;
  events: { at: string; kind: string; from?: string; to: string }[];
  kakshya_slices: { sign: string; lord: string; start: string; end: string; bindu_active: boolean }[];
  sade_sati?: { phase: string; sign: string; start: string; end: string; start_clipped: boolean; end_clipped: boolean }[];
};
export type DegreeTable = { warnings: string[]; unavailable: string[];
  planets: Record<string, { source_text: string; error_arcsec: number; nakshatra_padas: { name: string; pada: number }[] }>;
  vargas: Record<string, Record<string, { possible_signs: number[]; status: string }>>;
};
export type KpChart = {
  frame: { ayanamsa: string; dms: string; houses: string; rule_version: string; source: string };
  cusps: { house: number; sign: string; degree: number; star_lord: string; sub_lord: string; segment: number }[];
  significators: { house: number; stars_of_occupants: string[]; occupants: string[]; stars_of_owner: string[]; owner: string }[];
  ruling_planets: Record<string, string | null>;
  segments: { number: number; start_arcsec: number; end_arcsec: number; nakshatra: string; sub_lord: string }[];
  limitations: string[];
};
export type Coverage = { version: string; counts: Record<string, number>;
  intents: { intent_id: string; phase: number; domain: string; status: string; sample_questions: string[];
    specificity: { status: string; chart_windows: number; supportive_chart_rate: number | null; mean_supportive_window_share: number | null } | null }[];
};

// ---------------------------------------------------------------- extra services (matching, muhurta, varshaphala, prashna, report views)
export type Exception = { id: string; text: string; applies: boolean; verified: boolean; source: string };
export type Koota = { id: string; name: string; max: number; score: number; groom: string; bride: string;
  explanation: string; rule_id: string; source: string; verified: boolean; verified_note?: string };
export type MangalSide = { present: boolean; severity: string; houses_from: Record<string, number | null>; mars_sign: string;
  cancellations: Exception[]; cancelled: boolean; basis: string; source: string; verified: boolean };
export type MatchResult = {
  groom_name: string; bride_name: string; partner_data_stored: boolean;
  kootas: Koota[]; total: number; max: number; adjusted_total: number; adjusted_note: string | null;
  band: { key: string; text: string };
  doshas: { nadi: { present: boolean; cancelled: boolean; exceptions: Exception[] };
    bhakoot: { present: boolean; cancelled: boolean; exceptions: Exception[] };
    gana: { present: boolean; mitigated: boolean; exceptions: Exception[] } };
  mangal: { groom: MangalSide; bride: MangalSide; pair: { verdict: string; text: string; verified: boolean } };
  navamsa: { available: boolean; text?: string; groom_d9_lagna?: string; bride_d9_lagna?: string };
  seventh_house: null | Record<"groom" | "bride", { sign: string; lord: string; lord_house: number; occupants: string[]; karaka: string; karaka_house: number }>;
  dasha: Record<"groom" | "bride", { available: boolean; maha?: string; antar?: string; until?: string; strongly_adverse?: boolean }>;
  disclaimer: string;
};
export type PartnerBirthIn = { display_name: string; year: number; month: number; day: number; hour: number; minute: number;
  place_name: string; latitude: number; longitude: number; place_country: string; gender?: "male" | "female" };
export type PersonRef = { profile_id?: number; birth?: PartnerBirthIn };
export type MuhurtaSlot = { date: string; weekday: string; start: string; end: string; lagna: string; k: number; n: number; badge: string;
  tithi: string; paksha: string; nakshatra: string; yoga: string; karana: string; reasons: string[]; not_met: string[];
  bonus: string[]; warnings: string[]; factors: { id: string; label: string; ok: boolean; verified: boolean | string }[] };
export type MuhurtaResult = { event_label: string; location: { name: string; latitude: number; longitude: number; source?: string };
  slots: MuhurtaSlot[]; scanned_steps: number; accepted_steps: number; native_moon: string | null;
  excluded: { steps: number; by_reason: Record<string, number>; examples: { date: string; time: string; reasons: string[] }[] };
  rules: { id: string; label: string; source: string; verified: boolean | string }[];
  event_rules: { lagna: string; verified: boolean; source: string; note: string }; disclaimer: string };
export type Varshaphala = { year: number; year_of_life: number; return_local: string; status: string;
  varsha_lagna: { sign_name: string }; muntha: { sign_name: string; house_from_varsha_lagna: number };
  year_lord: { planet?: string; lord?: string; [k: string]: unknown } | null;
  office_bearers: Record<string, unknown> | null;
  positions: { planet: string; sign: string; degree: number; house: number }[];
  tajika_yogas: { name: string; planets?: number[]; note?: string; detail?: string; [k: string]: unknown }[];
  mudda: { scheme: string; periods: { lords: string[]; start: string; end: string | null; duration_years: number }[] } | null;
  sahams: { name: string; sign: string; degree: number; house: number; lord: string }[]; sahams_note: string;
  chart: import("@/components/Chart").ChartData };
export type PrashnaResult = {
  question_label: string; relevant_house: number; karakas: string[];
  cast: { local: string; place: string; location_source: string };
  lagna: { sign: string; degree: number; lord: string; lord_house: number; lord_sign: string; modality: string; nakshatra: string };
  moon: { sign: string; house: number; nakshatra: string; waxing: boolean };
  relevant: { sign: string; lord: string; lord_house: number; occupants: string[] };
  indicators: { id: string; label: string; favourable: boolean | null; detail: string; source: string; verified: boolean }[];
  summary: { favourable: number; unfavourable: number; text: string; leaning: string; label: string };
  kp_lite: { available: boolean; note?: string };
  rectification: { applicable: boolean; windows?: { lagna: string; start: string; end: string; in_prashna_trine: boolean }[];
    heuristic?: { text: string }; guidance?: string[] };
};
export type Tree = { lord?: string; sign?: string; start: string; end: string | null; running: boolean; antars?: Tree[]; pratyantars?: Tree[] };
export type ReportViews = {
  time_known: boolean; settings_line: string;
  dasha: { vimshottari: Tree[] | { unavailable: string }; yogini: Tree[] | { unavailable: string }; chara: Tree[] | { unavailable: string } };
  panchang: { tithi: { name: string; paksha: string }; vaara: string; nakshatra: { name: string; pada: number };
    yoga: { name: string }; karana: { name: string }; basis: string } | { unavailable: string };
  avakahada: { items: Record<string, string | number>; notes: string[] };
  shadbala: null | { planets: { planet: string; components: Record<string, number>; total_virupas: number; rupas: number;
    required_rupas: number; ratio: number; meets_minimum: boolean }[]; bhava_bala: { house: number; rupas: number; ratio: number }[] | null; note: string };
  chalit: null | { chart: import("@/components/Chart").ChartData; rows: { planet: string; rasi_house: number; chalit_house: number; shifted: boolean }[]; note: string };
  planets: { planet: string; sign: string; house: number; longitude_dms: string; nakshatra: string; pada: number; nakshatra_lord: string;
    dignity: string[]; compound_dignity: string | null; avastha: string | null; flags: string[] }[];
  ashtakavarga: { signs: string[]; planets: string[]; bav: number[][] | null; sav: number[] | null };
};
export const apiExtra = {
  match: (groom: PersonRef, bride: PersonRef, partner_consent: boolean) =>
    req<MatchResult>("/api/matching", { method: "POST", body: JSON.stringify({ groom, bride, partner_consent }) }),
  muhurta: (b: { event: string; start: string; end: string; latitude?: number; longitude?: number; place_name?: string; direction?: string }) =>
    req<MuhurtaResult>("/api/muhurta", { method: "POST", body: JSON.stringify(b) }),
  varshaphala: (year?: number) => req<Varshaphala>(`/api/varshaphala${year ? `?year=${year}` : ""}`),
  prashna: (b: { question_type: string; latitude?: number; longitude?: number; place_name?: string }) =>
    req<PrashnaResult>("/api/prashna", { method: "POST", body: JSON.stringify(b) }),
  reportViews: () => req<ReportViews>("/api/report-views"),
  downloadPdf: async () => {
    const r = await fetch(API + "/api/report.pdf", { cache: "no-store", headers: authHeaders() });
    await failIfBad(r);
    const href = URL.createObjectURL(await r.blob());
    const a = document.createElement("a");
    a.href = href; a.download = "kundli.pdf"; a.click();
    setTimeout(() => URL.revokeObjectURL(href), 1000);
  },
};

// ---- Simplified Home (GET /api/home) ----
export type Verdict = "likely" | "mixed" | "not_indicated" | "strong" | "moderate" | "weak";
export type Confidence = "high" | "medium" | "low";
export type HomeYearItem = {
  topic: string; label: string; verdict: Verdict;
  window: { start: string; end: string } | null;
  confidence: Confidence; why: { text: string }[]; action: string;
};
export type HomeOverview = {
  chart_brief: { lagna: string | null; moon_sign: string; nakshatra: string;
    current_dasha: { maha: string; antar: string; until: string } | string | null; time_known: boolean };
  year_overview: HomeYearItem[];
  chart_check: { state: string; personal_fit?: string | null };
  suggested_questions: string[];
};
// resolves to null when the endpoint does not exist yet (404)
export async function getHome(): Promise<HomeOverview | null> {
  const r = await fetch(API + "/api/home", { cache: "no-store", headers: authHeaders() });
  if (r.status === 404) return null;
  await failIfBad(r);
  return r.json();
}
