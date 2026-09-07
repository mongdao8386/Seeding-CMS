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

  /** Gui multipart tu dung. Dung khi khong phai la mot file. */
  postForm: async <T>(path: string, form: FormData): Promise<T> => {
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
   * Upload multipart. Khong dat content-type de trinh duyet tu them boundary.
   *
   * `file` nhan ca File lan chuoi: dan thang vao o nhap nhanh hon han viec mo Excel,
   * luu file, roi di tim xem vua luu vao dau.
   */
  upload: async <T>(path: string, file: File | string): Promise<T> => {
    const form = new FormData();
    if (typeof file === "string") {
      form.append("text", file);
    } else {
      form.append("file", file);
    }
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

/**
 * Mot trang ket qua.
 *
 * `total` la so ban ghi KHOP DIEU KIEN LOC, khong phai so ban ghi trong trang. Thieu
 * no thi giao dien khong ve duoc "51-100 cua 213", va nguoi dung khong bao gio biet
 * minh dang nhin mot phan hay toan bo.
 */
export type Page<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
};

/** Ghep query string, bo qua cac gia tri rong. */
export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

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
  /** Dang bai duoc chua. false = thieu profile, proxy, hoac phien dang nhap. */
  ready: boolean;
  /** Thieu gi, neu chua san sang. */
  blocked_reason: string | null;
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

export type OpenedProfile = {
  profile_id: string;
  handle: string;
  pid: number;
  url: string | null;
  detail: string;
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
  last_error: string | null;
  /** Khong phai bi mat. Mat khau thi khong bao gio di nguoc ra khoi API. */
  username: string | null;
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
  /** 0 = thu Hai ... 6 = Chu nhat, khop voi date.weekday() cua Python. */
  weekday: number;
  active_from_hour: number;
  /** 24 = nua dem ket thuc ngay. */
  active_to_hour: number;
  note: string | null;
};

export type PostSlot = {
  id: string;
  platform: string;
  /** 0 = thu Hai ... 6 = Chu nhat. */
  weekday: number;
  /** Gio dia phuong cua khan gia (SlotMeta.timezone), khong phai UTC. */
  hour: number;
  minute: number;
  note: string | null;
};

export type SlotMeta = { timezone: string; jitter_max_seconds: number };

export type GraphAudit = {
  accounts: number;
  edges: number;
  density: number;
  mutual_pairs: number;
  mutual_rate: number;
  max_following: number;
  isolated: number;
  max_density: number;
  safe: boolean;
  warnings: string[];
};

export type GraphEdge = {
  id: string;
  follower: string;
  target: string;
  platform: string;
  status: "planned" | "done" | "failed";
  created_at: string;
  done_at: string | null;
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
  /** Chi CO hay KHONG. Chuoi cookie la mot phien dang nhap song. */
  has_cookie: boolean;
  /** Vi sao cookie khong dung duoc, neu co. */
  cookie_note: string | null;
};

export type ImportReport = {
  ok: boolean;
  ready: number;
  /** So dong co cookie DUNG DUOC - da thu doc va co ca cookie phien. */
  with_cookies: number;
  /** So dong co cookie nhung doc khong ra, hoac thieu cookie phien. */
  cookie_problems: number;
  /** So dong ma phan bi cat nham da duoc noi lai vao cot cuoi. */
  rejoined_rows: number;
  unknown_columns: string[];
  /** Cot cua nguoi ban da duoc doi sang ten cua he thong. */
  renamed_columns: Record<string, string>;
  rows: ImportRow[];
  problems: ImportProblem[];
};

export type ImportResult = {
  created: number;
  handles?: string[];
  skipped?: number;
  detail?: string;
  profiles_with_session?: number;
  warnings?: string[];
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

export type Device = {
  id: string;
  serial: string;
  label: string;
  os: "android" | "ios";
  model: string | null;
  os_version: string | null;
  status: "offline" | "ready" | "busy" | "unauthorized" | "error";
  last_seen_at: string | null;
  last_error: string | null;
  account_id: string | null;
  handle: string | null;
  proxy_label: string | null;
  note: string | null;
};

export type DevicePreflight = {
  ready: boolean;
  problems: string[];
  adb: string | null;
  note: string;
};

export type WorkspaceDetail = {
  id: string;
  name: string;
  personas: number;
  accounts: number;
  campaigns: number;
  content: number;
};

export type ProxyImportResult = {
  created: number;
  labels: string[];
  tested: number;
  passed: number;
  /** Hai proxy ra cung mot IP la MOT loi ra duoc dem thanh hai. */
  duplicate_exit_ips: string[];
  results: { label: string; ok: boolean; exit_ip: string | null; error: string | null }[];
  skipped: { line: number; raw: string; detail: string }[];
  problems: { line: number; raw: string; detail: string }[];
};
