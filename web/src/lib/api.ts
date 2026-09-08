const BASE = process.env.NEXT_PUBLIC_API ?? "http://127.0.0.1:8000";
const TOKEN_KEY = "seeding-token";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

/** Token nằm trong localStorage của trình duyệt, không bao giờ gửi đi đâu khác. */
export const token = {
  get: () => (typeof window === "undefined" ? null : localStorage.getItem(TOKEN_KEY)),
  set: (value: string) => localStorage.setItem(TOKEN_KEY, value),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

async function parseError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
  } catch {
    return res.statusText;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const bearer = token.get();
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        ...(init?.body instanceof FormData ? {} : { "content-type": "application/json" }),
        ...(bearer ? { authorization: `Bearer ${bearer}` } : {}),
        ...(init?.headers ?? {}),
      },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(`Không gọi được API ở ${BASE}. Start.cmd đã bật chưa?`, 0);
  }
  if (res.status === 401) {
    token.clear();
    throw new ApiError("Token bị từ chối. Nhập lại.", 401);
  }
  if (!res.ok) throw new ApiError(await parseError(res), res.status);
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body === undefined ? "{}" : JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  /** Form: dùng cho các ô dán (text lớn) — server đọc bằng Form(...). */
  form: <T>(path: string, fields: Record<string, string | boolean | number>) => {
    const fd = new FormData();
    for (const [k, v] of Object.entries(fields)) fd.append(k, String(v));
    return request<T>(path, { method: "POST", body: fd });
  },
};

export function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const out = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") out.set(k, String(v));
  }
  const s = out.toString();
  return s ? `?${s}` : "";
}

// ---------------------------------------------------------------- kiểu dữ liệu

export type Platform = "tiktok" | "instagram" | "x" | "facebook" | "threads" | "youtube" | "reddit";
export type AccountStatus = "warming" | "active" | "paused" | "needs_human" | "suspended" | "dead";
export type AccountRole = "channel" | "booster";

export type Page<T> = { items: T[]; total: number; limit: number; offset: number };

export type AccountRow = {
  id: string;
  platform: Platform;
  handle: string;
  status: AccountStatus;
  role: AccountRole;
  daily_cap: number;
  warmup_started_at: string | null;
  last_posted_at: string | null;
  proxy_label: string | null;
  session_alive: boolean | null;
  ready: boolean;
  blocked_reason: string | null;
  warm_day: number | null;
};

export type AccountDetail = AccountRow & {
  proxy_host: string | null;
  proxy_exit_ip: string | null;
  cookie_count: number;
  session_cookie: boolean;
  user_agent: string | null;
  timezone: string | null;
  last_login_at: string | null;
  last_health_at: string | null;
  profile_id: string | null;
};

export type AccountSecrets = {
  fields: Record<string, string>;
  totp_code: string | null;
  known: string[];
};

export type Proxy = {
  id: string;
  label: string;
  kind: string;
  scheme: string;
  host: string;
  port: number;
  region: string | null;
  status: "untested" | "ok" | "failing" | "retired";
  last_exit_ip: string | null;
  last_error: string | null;
  username: string | null;
  bound_handle: string | null;
};

export type Stats = {
  channels: number;
  boosters: number;
  accounts: number;
  ready: number;
  blocked: number;
  dead: number;
  needs_human: number;
  warming: number;
  proxies: number;
  proxies_free: number;
};

export type SystemStatus = {
  api: boolean;
  database: boolean;
  signer: boolean;
  signer_detail: string | null;
  x_library: boolean | null;
  x_library_detail: string | null;
};

export type ImportCheck = {
  ok: boolean;
  ready: number;
  with_cookies: number;
  cookie_problems: number;
  rejoined_rows: number;
  unknown_columns: string[];
  renamed_columns: Record<string, string>;
  rows: {
    line: number;
    platform: string;
    handle: string;
    daily_cap: number;
    secret_count: number;
    has_cookie: boolean;
    cookie_note: string | null;
  }[];
  problems: { line: number; handle: string | null; detail: string }[];
};

export type ImportResult = {
  created: number;
  handles: string[];
  profiles_with_session: number;
  skipped: number;
  warnings: string[];
  problems: { line: number; handle: string | null; detail: string }[];
};

export type ProxyImportResult = {
  created: number;
  labels: string[];
  tested: number;
  passed: number;
  duplicate_exit_ips: string[];
  results: { label: string; ok: boolean; exit_ip: string | null; error: string | null }[];
  skipped: { line: number; raw: string; detail: string }[];
  problems: { line: number; raw: string; detail: string }[];
};

export type OpenedProfile = { profile_id: string; handle: string; pid: number; detail: string };

// ------------------------------------------------------------- noi dung & lich

export type Media = {
  id: string;
  created_at: string;
  filename: string;
  original_name: string;
  kind: "image" | "video";
  size_bytes: number;
  width: number | null;
  height: number | null;
  duration_seconds: number | null;
  has_thumbnail: boolean;
  used_by: number;
};

export type Content = {
  id: string;
  created_at: string;
  title: string;
  body: string;
  media: Media | null;
  jobs_total: number;
  jobs_succeeded: number;
  jobs_scheduled: number;
  combinations: number;
};

export type JobStatus = "pending" | "scheduled" | "running" | "succeeded" | "failed" | "needs_human" | "skipped";

export type Job = {
  id: string;
  campaign_id: string;
  content_id: string | null;
  account_id: string;
  handle: string;
  platform: Platform;
  status: JobStatus;
  scheduled_at: string;
  title: string;
  body: string;
  remote_url: string | null;
  last_error: string | null;
  attempt_count: number;
};

export type Slot = { platform: Platform; weekday: number; hour: number; minute: number };
export type SlotMeta = { timezone: string; weekdays: string[] };

// ---------------------------------------------------------------- nuôi

export type TimelineItem = {
  at: string;
  kind: "post" | "like" | "follow" | "comment" | "repost" | "browse" | "session" | "identity" | "delete" | "edit" | "reply" | "dm";
  status: JobStatus | null;
  title: string;
  detail: string | null;
  url: string | null;
};

export type Takeover = {
  id: string;
  created_at: string;
  account_id: string;
  profile_id: string | null;
  handle: string;
  platform: Platform;
  reason: string;
  status: "open" | "resolved" | "abandoned";
  has_stuck_job: boolean;
  alerted: boolean;
};

export type Settings = {
  warmup_quiet_days: number;
  warmup_days: number;
  default_daily_cap: number;
  health_check_interval_hours: number;
  health_fail_threshold: number;
  schedule_timezone: string;
  alert_kind: string;
  alert_configured: boolean;
  tiktok_post_via_http: boolean;
  tiktok_interact_via_http: boolean;
  instagram_enabled: boolean;
  x_enabled: boolean;
  reddit_enabled: boolean;
  facebook_enabled: boolean;
  chatbot_enabled: boolean;
  chatbot_comments: boolean;
  chatbot_dms: boolean;
  chatbot_model: string;
  chatbot_llm_configured: boolean;
  chatbot_max_per_hour: number;
  chatbot_interval_minutes: number;
  chatbot_last: { at: string; handle: string; replier: string; replied: number; dm_replied: number; stopped: string | null } | null;
  warm_comment_style: string;
  warm_keywords: string[];
  tiktok_actions: string;
};

export type Post = {
  attempt_id: string;
  job_id: string;
  account_id: string;
  handle: string;
  platform: Platform;
  title: string;
  caption: string;
  remote_id: string | null;
  remote_url: string | null;
  posted_at: string;
  deleted_at: string | null;
  edited_at: string | null;
  pending: "delete" | "edit" | null;
  can_delete: string | null;
  can_edit: string | null;
};

export type Identity = {
  handle: string;
  platform: Platform;
  supported: boolean;
  why_not: string | null;
  min_days: number;
  last_username_change_at: string | null;
  next_username_change_at: string | null;
  pending: { id: string; scheduled_at: string; status: JobStatus; plan: string } | null;
  suggestions: { names: string[]; usernames: string[] };
};

export type KindCount = { planned: number; done: number; failed: number };
export type ActivitySummary = {
  date: string;
  likes: KindCount;
  follows: KindCount;
  comments: KindCount;
  replies: KindCount;
  dms: KindCount;
  accounts_warming: number;
};

export const BASE_URL = BASE;

/** Upload một file (multipart). */
export async function uploadMedia(file: File): Promise<Media> {
  const fd = new FormData();
  fd.append("file", file);
  const bearer = token.get();
  let res: Response;
  try {
    res = await fetch(`${BASE}/media`, {
      method: "POST",
      body: fd,
      headers: bearer ? { authorization: `Bearer ${bearer}` } : {},
    });
  } catch {
    throw new ApiError(`Không gọi được API ở ${BASE}.`, 0);
  }
  if (!res.ok) throw new ApiError(await parseError(res), res.status);
  return (await res.json()) as Media;
}
