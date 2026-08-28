const BASE = process.env.NEXT_PUBLIC_API ?? "http://127.0.0.1:8000";
const TOKEN_KEY = "seeding-cms-token";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

/** Token nam trong localStorage cua trinh duyet, khong bao gio gui sang server nao khac. */
export const token = {
  get: () => (typeof window === "undefined" ? null : localStorage.getItem(TOKEN_KEY)),
  set: (value: string) => localStorage.setItem(TOKEN_KEY, value),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const bearer = token.get();
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        "content-type": "application/json",
        ...(bearer ? { authorization: `Bearer ${bearer}` } : {}),
        ...(init?.headers ?? {}),
      },
      cache: "no-store",
    });
  } catch {
    // Loi mang, gan nhu luon la chua chay uvicorn. Noi thang thay vi de "Failed to fetch".
    throw new ApiError(
      `Can't reach the API at ${BASE}. Is uvicorn running?`,
      0,
    );
  }

  // Token sai hoac het han: xoa di de cua dang nhap hien lai thay vi loi lap vo tan.
  if (res.status === 401) {
    token.clear();
    throw new ApiError("That token was rejected. Please enter it again.", 401);
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* giữ statusText */
    }
    throw new ApiError(detail, res.status);
  }

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

  /** Upload multipart. Khong dat content-type de trinh duyet tu them boundary. */
  upload: async <T>(path: string, file: File): Promise<T> => {
    const form = new FormData();
    form.append("file", file);
    const bearer = token.get();
    const res = await fetch(`${BASE}${path}`, {
      method: "POST",
      body: form,
      headers: bearer ? { authorization: `Bearer ${bearer}` } : {},
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      } catch {
        /* giữ statusText */
      }
      throw new ApiError(detail, res.status);
    }
    return (await res.json()) as T;
  },

  /**
   * Anh nam sau token, ma the <img> thi khong gui duoc header. Nen tai bang fetch
   * roi doi thanh blob URL - khong bao gio dat token vao query string.
   */
  blobUrl: async (path: string): Promise<string> => {
    const bearer = token.get();
    const res = await fetch(`${BASE}${path}`, {
      headers: bearer ? { authorization: `Bearer ${bearer}` } : {},
    });
    if (!res.ok) throw new ApiError("Could not load the image", res.status);
    return URL.createObjectURL(await res.blob());
  },
};

// ---- Kieu du lieu, khop voi schemas.py ----

export type Stats = {
  accounts: number;
  accounts_needing_human: number;
  profiles_alive: number;
  profiles_total: number;
  jobs_scheduled: number;
  jobs_succeeded: number;
  jobs_failed: number;
  activity_scheduled_today: number;
};

export type Named = { id: string; name: string };

export type Account = {
  id: string;
  platform: string;
  handle: string;
  status: string;
  daily_cap: number;
  warmup_started_at: string | null;
  last_posted_at: string | null;
};

export type Profile = {
  id: string;
  account_id: string;
  handle: string;
  platform: string;
  engine: string;
  fingerprint: string;
  proxy_label: string | null;
  session_alive: boolean;
  last_login_at: string | null;
  last_health_at: string | null;
  consecutive_health_failures: number;
};

export type Proxy = {
  id: string;
  label: string;
  kind: string;
  scheme: string;
  host: string;
  port: number;
  region: string | null;
  sticky: boolean;
  status: string;
  last_exit_ip: string | null;
};

export type ContentItem = {
  id: string;
  created_at: string;
  title_template: string;
  body_template: string;
  media_ref: string | null;
  approved: boolean;
};

export type PreviewSample = { title: string; body: string; content_hash: string };

export type Preview = {
  samples: PreviewSample[];
  combinations: number;
  hashtag_combinations: number;
  unique_in_sample: number;
  collision_risk: number;
  warning: string | null;
  unknown_pools: string[];
};

export type CampaignSummary = {
  id: string;
  name: string;
  starts_at: string;
  stagger_window_seconds: number;
  repeat: "none" | "daily" | "weekly";
  repeat_until: string | null;
  /** Co cha nghia la ban sao cua mot ky, khong phai chien dich nguoi tao tay. */
  repeat_parent_id: string | null;
  next_run: string | null;
  total_jobs: number;
  succeeded: number;
  failed: number;
  needs_human: number;
};

export type Group = {
  id: string;
  name: string;
  platform: string;
  post_kind: "post" | "comment";
  target: { subreddit?: string; url?: string } & Record<string, unknown>;
  account_count: number;
  total_jobs: number;
  succeeded: number;
  failed: number;
  needs_human: number;
};

export type Job = {
  id: string;
  group_id: string;
  status: string;
  scheduled_at: string;
  handle: string;
  title: string;
  content_hash: string;
  attempt_count: number;
  last_error: string | null;
  remote_url: string | null;
};

export type Takeover = {
  id: string;
  created_at: string;
  handle: string;
  platform: string;
  reason: string;
  status: string;
  has_stuck_job: boolean;
};

export type ActivityJob = {
  id: string;
  kind: string;
  status: string;
  scheduled_at: string;
  duration_seconds: number;
  detail: string | null;
};

export type MediaAsset = {
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

export type HashtagSet = {
  id: string;
  name: string;
  platform: string | null;
  tags: string[];
  note: string | null;
  placeholder: string;
};

export type ProxyTestAll = {
  tested: number;
  passed: number;
  results: (ProxyTest & { id: string; label: string })[];
  duplicate_exit_ips: string[];
};

export type ProxyTest = {
  ok: boolean;
  exit_ip: string | null;
  latency_ms: number | null;
  error: string | null;
};

export type PlatformWindow = {
  id: string;
  platform: string;
  active_from_hour: number;
  active_to_hour: number;
  note: string | null;
};

export type ImportProblem = { line: number; handle: string; detail: string };

export type ImportRow = {
  line: number;
  platform: string;
  handle: string;
  persona: string | null;
  daily_cap: number;
  start_warmup: boolean;
  /** Chi SO luong. Bi mat khong bao gio di nguoc ra khoi API. */
  secret_count: number;
};

export type ImportReport = {
  ok: boolean;
  ready: number;
  unknown_columns: string[];
  rows: ImportRow[];
  problems: ImportProblem[];
};

export type ImportResult = {
  created: number;
  handles?: string[];
  skipped?: number;
  detail?: string;
  problems: ImportProblem[];
};

export type Cohort = {
  label: string;
  n: number;
  alive: number;
  gone: number;
  needs_human: number;
  survival: number;
  takeovers_per_account: number;
  median_days_lived: number | null;
  /** false nghia la nhom qua nho de rut ket luan. */
  trustworthy: boolean;
};

export type Survival = {
  total: number;
  min_cohort: number;
  detail?: string;
  overall?: Cohort;
  by_proxy_kind: Cohort[];
  by_proxy_label: Cohort[];
  by_warmup_length: Cohort[];
  by_posting_rate: Cohort[];
};
