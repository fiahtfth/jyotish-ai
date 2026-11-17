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

async function req(path: string, opts: RequestInit = {}) {
  const r = await fetch(API + path, {
    cache: "no-store",
    ...opts,
    headers: {
      "content-type": "application/json",
      ...(token() ? { authorization: `Bearer ${token()}` } : {}),
      ...(opts.headers || {}),
    },
  });
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
      ? e.detail.map((d: any) => d.msg || JSON.stringify(d)).join("; ")
      : e.detail;
    throw new Error(detail || `error ${r.status}`);
  }
  return r.json();
}

export const api = {
  register: (email: string, password: string, display_name: string) =>
    req("/api/auth/register", { method: "POST", body: JSON.stringify({ email, password, display_name }) }),
  login: (email: string, password: string) =>
    req("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  me: () => req("/api/auth/me"),
  deleteMe: () => req("/api/auth/me", { method: "DELETE" }),
  geoSearch: (q: string) => req(`/api/geo/search?q=${encodeURIComponent(q)}`),
  getProfile: () => req("/api/profile"),
  putProfile: (p: any) => req("/api/profile", { method: "PUT", body: JSON.stringify(p) }),
  history: () => req("/api/chat/history"),
  send: (text: string) => req("/api/chat/send", { method: "POST", body: JSON.stringify({ text }) }),
  resetChat: () => req("/api/chat/reset", { method: "POST" }),
  chart: (v: string) => req(`/api/chart/${v}`),
  calibration: () => req("/api/calibration"),
};
