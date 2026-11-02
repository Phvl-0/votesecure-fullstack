// One small client for the FastAPI backend. Nothing here talks to Supabase.
// The token lives in localStorage; injected script could read it, so keep tokens short-lived.

const BASE_URL: string = import.meta.env.VITE_API_URL ?? "/api";
const TOKEN_KEY = "votesecure_token";
export const SESSION_EXPIRED_EVENT = "votesecure:session-expired";
export const AUTH_CHANGED_EVENT = "votesecure:auth-changed";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// --- Token and session ---
export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // storage unavailable: the user will have to log in again
  }
}

export function clearToken(): void {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    // nothing to clear
  }
}

export interface Session {
  userId: string;
  email: string | null;
  role: string | null;
  expiresAt: number | null;
}

// A UI hint only: it reads the token without verifying it. The server decides.
export function getSession(): Session | null {
  const token = getToken();
  if (!token) return null;
  try {
    const payload = token.split(".")[1];
    const claims = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
    const expiresAt = typeof claims.exp === "number" ? claims.exp * 1000 : null;
    if (expiresAt !== null && expiresAt <= Date.now()) {
      clearToken();
      return null;
    }
    if (typeof claims.sub !== "string") return null;
    return {
      userId: claims.sub,
      email: typeof claims.email === "string" ? claims.email : null,
      role: typeof claims.role === "string" ? claims.role : null,
      expiresAt,
    };
  } catch {
    return null;
  }
}

// --- Request helper ---
async function request<T>(
  path: string,
  options: { method?: string; body?: unknown; auth?: boolean } = {}
): Promise<T> {
  const token = options.auth === false ? null : getToken();
  const headers: Record<string, string> = {};
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${BASE_URL}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  if (res.status === 401 && token) {
    clearToken();
    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
  }

  if (!res.ok) {
    let message = res.statusText || "Request failed";
    try {
      const data = await res.json();
      if (typeof data.detail === "string") {
        message = data.detail;
      } else if (Array.isArray(data.detail)) {
        message = data.detail.map((d: { msg?: string }) => d.msg ?? "Invalid input").join("; ");
      }
    } catch {
      // the body was not JSON: keep the status text
    }
    throw new ApiError(res.status, message);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// --- Shapes exactly as the API sends them ---
export interface ApiCandidate {
  id: string;
  election_id?: string;
  name: string;
  party: string | null;
  bio: string | null;
  image: string | null;
}

export interface ApiElection {
  id: string;
  title: string;
  description: string | null;
  start_date: string;
  end_date: string;
  status: "upcoming" | "active" | "ended";
  candidates: ApiCandidate[];
}

export interface ApiResultRow {
  candidate_id: string;
  candidate_name: string;
  party: string | null;
  vote_count: number;
}

export interface ApiResult {
  id: string;
  title: string;
  end_date: string;
  status: "active" | "ended";
  total_votes: number;
  results: ApiResultRow[];
}

export interface ApiMyVote {
  id: string;
  created_at: string;
  election_id: string;
  candidate_id: string;
  elections: { title: string; status: string };
  candidates: { name: string };
}

export interface ApiAuditLog {
  id: string;
  user_id: string;
  action: string;
  details: Record<string, unknown> | null;
  created_at: string;
}

// The API refuses dates without a timezone, and browser date inputs have none.
// new Date() reads such a value as local time; toISOString() makes it explicit.
const toIso = (value: string): string => new Date(value).toISOString();

// --- One function per endpoint ---
export const api = {
  register: (email: string, password: string) =>
    request<Record<string, unknown>>("/register", { method: "POST", body: { email, password }, auth: false }),

  login: async (email: string, password: string): Promise<Session | null> => {
    const data = await request<{ access_token: string }>("/login", {
      method: "POST",
      body: { email, password },
      auth: false,
    });
    setToken(data.access_token);
    window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
    return getSession();
  },

  logout: () => {
    clearToken();
    window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
  },

  listElections: () => request<ApiElection[]>("/elections"),

  createElection: (e: { title: string; description?: string; start_date: string; end_date: string }) =>
    request<ApiElection>("/elections", {
      method: "POST",
      body: { ...e, start_date: toIso(e.start_date), end_date: toIso(e.end_date) },
    }),

  deleteElection: (id: string) =>
    request<void>(`/elections/${encodeURIComponent(id)}`, { method: "DELETE" }),

  addCandidate: (
    electionId: string,
    c: { name: string; party?: string; bio?: string; image?: string }
  ) =>
    request<ApiCandidate>(`/elections/${encodeURIComponent(electionId)}/candidates`, {
      method: "POST",
      body: c,
    }),

  deleteCandidate: (id: string) =>
    request<void>(`/candidates/${encodeURIComponent(id)}`, { method: "DELETE" }),

  castVote: (electionId: string, candidateId: string) =>
    request<{ id: string; election_id: string }>(`/elections/${encodeURIComponent(electionId)}/votes`, {
      method: "POST",
      body: { candidate_id: candidateId },
    }),

  hasVoted: async (electionId: string): Promise<boolean> =>
    (await request<{ has_voted: boolean }>(`/elections/${encodeURIComponent(electionId)}/my-vote`)).has_voted,

  getResults: () => request<ApiResult[]>("/results"),

  myVotes: () => request<ApiMyVote[]>("/me/votes"),

  auditLogs: (limit = 100) => request<ApiAuditLog[]>(`/admin/audit-logs?limit=${limit}`),
};
