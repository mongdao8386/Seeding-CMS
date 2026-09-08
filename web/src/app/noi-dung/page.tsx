"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  BASE_URL,
  api,
  qs,
  uploadMedia,
  type AccountRow,
  type Content,
  type Job,
  type Media,
  type Page,
  type Platform,
  type Slot,
} from "@/lib/api";
import { PublishedPosts } from "@/components/posts";
import { Empty, ErrorNote, PLATFORM_LABEL, PLATFORMS, PageTitle, useLoad } from "@/components/ui";

const DAY_SHORT = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];
const DAY_LONG = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"];

function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function monday(d: Date): Date {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7));
  return x;
}
function addDays(d: Date, n: number): Date {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
}
function hhmm(isoTs: string): string {
  const d = new Date(isoTs);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/**
 * Nội dung & Lịch — kiểu C: tuần là trung tâm, mỗi ngày là các mốc giờ vàng.
 * Chọn một bài bên trái, chọn tài khoản, bấm "Lên lịch"; kéo thẻ bài sang ngày khác để dời.
 */
export default function ContentPage() {
  const [platform, setPlatform] = useState<Platform>("tiktok");
  const [weekStart, setWeekStart] = useState(() => monday(new Date()));
  const [selected, setSelected] = useState<Content | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [schedulingFor, setSchedulingFor] = useState<string | null>(null); // ngày YYYY-MM-DD

  const content = useLoad(() => api.get<Content[]>("/content"), []);
  const slots = useLoad(() => api.get<Slot[]>("/slots"), []);
  const jobs = useLoad(
    () => api.get<Job[]>(`/schedule${qs({ start: iso(weekStart), days: 7 })}`),
    [iso(weekStart)],
  );
  const accounts = useLoad(
    () => api.get<Page<AccountRow>>(`/accounts${qs({ limit: 500, platform, ready: true })}`),
    [platform],
  );

  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)), [weekStart]);
  const slotTable = useMemo(() => {
    const t: Record<number, number[]> = {};
    for (const s of slots.data ?? []) {
      if (s.platform !== platform) continue;
      (t[s.weekday] ??= []).push(s.hour);
    }
    for (const k of Object.keys(t)) t[+k].sort((a, b) => a - b);
    return t;
  }, [slots.data, platform]);

  async function move(job: Job, date: string, hour?: number) {
    try {
      await api.patch(`/schedule/${job.id}`, { date, hour });
      jobs.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }
  async function cancel(job: Job) {
    if (!confirm(`Huỷ bài của ${job.handle}?`)) return;
    try {
      await api.del(`/schedule/${job.id}`);
      jobs.reload();
      content.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const today = iso(new Date());

  return (
    <>
      <PageTitle
        title="Nội dung & Lịch"
        sub={`Giờ ${slots.data ? "địa phương" : ""} · kéo thẻ bài sang ngày khác để dời, nó tự bám vào giờ vàng`}
        action={
          <div className="flex gap-1.5 text-sm">
            {PLATFORMS.map((p) => (
              <button
                key={p}
                className={"rounded-lg px-2.5 py-1.5 " + (platform === p ? "bg-soft font-medium text-ink" : "text-muted")}
                onClick={() => setPlatform(p)}
              >
                {PLATFORM_LABEL[p]}
              </button>
            ))}
          </div>
        }
      />
      <ErrorNote message={error ?? content.error ?? jobs.error ?? slots.error} />

      <div className="grid gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
        <ContentPane
          items={content.data ?? []}
          selected={selected}
          onSelect={setSelected}
          onChange={content.reload}
          onError={setError}
          onSchedule={() => setSchedulingFor(today)}
        />

        <section className="flex min-w-0 flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-baseline gap-3">
              <span className="text-lg font-bold tracking-tight">Tuần này</span>
              <span className="text-muted">
                {days[0].getDate()}/{days[0].getMonth() + 1} – {days[6].getDate()}/{days[6].getMonth() + 1}
              </span>
            </div>
            <div className="flex gap-1.5">
              <button className="btn text-xs" onClick={() => setWeekStart(addDays(weekStart, -7))}>‹</button>
              <button className="btn text-xs" onClick={() => setWeekStart(monday(new Date()))}>Hôm nay</button>
              <button className="btn text-xs" onClick={() => setWeekStart(addDays(weekStart, 7))}>›</button>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
            {days.map((d, i) => {
              const key = iso(d);
              const dayJobs = (jobs.data ?? []).filter((j) => iso(new Date(j.scheduled_at)) === key && j.platform === platform);
              const hours = slotTable[i] ?? [];
              return (
                <DayCell
                  key={key}
                  date={d}
                  label={`${DAY_SHORT[i]} ${d.getDate()}`}
                  isToday={key === today}
                  hours={hours}
                  jobs={dayJobs}
                  onDropJob={(job, hour) => move(job, key, hour)}
                  onDropContent={() => setSchedulingFor(key)}
                  onCancel={cancel}
                />
              );
            })}
          </div>

          <div className="card flex flex-wrap items-center gap-4 px-4 py-3 text-xs text-muted">
            <Legend color="bg-accent-soft" border="border-accent" text="sắp đăng" />
            <Legend color="bg-ok-soft" border="border-ok" text="đã lên" />
            <Legend color="bg-warn-soft" border="border-warn" text="cần bạn / hỏng" />
            <span className="ml-auto">Chưa có mốc giờ vàng cho ngày nào? Đặt ở Cài đặt.</span>
          </div>
        </section>
      </div>

      <div className="mt-6">
        <PublishedPosts />
      </div>

      {schedulingFor && (
        <ScheduleDialog
          content={selected}
          contents={content.data ?? []}
          accounts={accounts.data?.items ?? []}
          platform={platform}
          date={schedulingFor}
          onClose={() => setSchedulingFor(null)}
          onDone={() => {
            setSchedulingFor(null);
            jobs.reload();
            content.reload();
          }}
          onPick={setSelected}
        />
      )}
    </>
  );
}

function Legend({ color, border, text }: { color: string; border: string; text: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`h-2.5 w-2.5 rounded-sm border-l-2 ${color} ${border}`} />
      {text}
    </span>
  );
}

function DayCell({
  date,
  label,
  isToday,
  hours,
  jobs,
  onDropJob,
  onDropContent,
  onCancel,
}: {
  date: Date;
  label: string;
  isToday: boolean;
  hours: number[];
  jobs: Job[];
  onDropJob: (job: Job, hour?: number) => void;
  onDropContent: () => void;
  onCancel: (job: Job) => void;
}) {
  const [over, setOver] = useState(false);
  const past = date < new Date(new Date().setHours(0, 0, 0, 0));

  function handleDrop(e: React.DragEvent, hour?: number) {
    e.preventDefault();
    setOver(false);
    const raw = e.dataTransfer.getData("application/json");
    if (!raw) return;
    const data = JSON.parse(raw) as { kind: "job"; job: Job } | { kind: "content" };
    if (data.kind === "job") onDropJob(data.job, hour);
    else onDropContent();
  }

  const byHour = new Map<number | "other", Job[]>();
  for (const j of jobs) {
    const h = new Date(j.scheduled_at).getHours();
    const k = hours.includes(h) ? h : "other";
    byHour.set(k, [...(byHour.get(k) ?? []), j]);
  }

  return (
    <div
      className={
        "card flex min-h-[220px] flex-col gap-2 p-2.5 " +
        (isToday ? "ring-2 ring-ink" : "") +
        (over ? " bg-accent-soft" : "") +
        (past ? " opacity-70" : "")
      }
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => handleDrop(e)}
    >
      <div className="flex items-baseline justify-between">
        <span className="font-bold">{label}</span>
        {isToday && <span className="text-[11px] text-muted">hôm nay</span>}
      </div>

      {hours.length === 0 && jobs.length === 0 && (
        <div className="rounded-lg border border-dashed border-line px-2 py-1.5 text-[11px] text-faint">không có giờ vàng</div>
      )}

      {hours.map((h) => (
        <div
          key={h}
          className="flex flex-col gap-1 rounded-lg border border-dashed border-line px-2 py-1.5"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.stopPropagation();
            handleDrop(e, h);
          }}
        >
          <span className="mono text-[11px] text-faint">{String(h).padStart(2, "0")}:00</span>
          {(byHour.get(h) ?? []).map((j) => (
            <JobChip key={j.id} job={j} onCancel={onCancel} />
          ))}
        </div>
      ))}
      {(byHour.get("other") ?? []).map((j) => (
        <JobChip key={j.id} job={j} onCancel={onCancel} />
      ))}
    </div>
  );
}

function JobChip({ job, onCancel }: { job: Job; onCancel: (job: Job) => void }) {
  const tone =
    job.status === "succeeded"
      ? "bg-ok-soft border-ok"
      : job.status === "needs_human" || job.status === "failed"
        ? "bg-warn-soft border-warn"
        : job.status === "skipped"
          ? "bg-soft border-line"
          : "bg-accent-soft border-accent";
  const draggable = job.status === "scheduled";
  return (
    <div
      draggable={draggable}
      onDragStart={(e) => {
        e.dataTransfer.setData("application/json", JSON.stringify({ kind: "job", job }));
        e.dataTransfer.effectAllowed = "move";
      }}
      className={`group rounded-lg border-l-[3px] px-2 py-1.5 text-[12px] ${tone} ${draggable ? "cursor-grab" : ""}`}
      title={`${job.title}\n${job.body}${job.last_error ? "\n" + job.last_error : ""}`}
    >
      <div className="flex items-center justify-between gap-1">
        <span className="mono truncate font-medium">{job.handle.replace(/^user/, "u…")}</span>
        <span className="mono text-[10px] text-muted">{hhmm(job.scheduled_at)}</span>
      </div>
      <div className="flex items-center justify-between">
        <span className="truncate text-muted">
          {job.status === "succeeded" ? "đã lên" : job.status === "scheduled" ? "sắp đăng" : job.status === "needs_human" ? "cần bạn" : job.status === "failed" ? "hỏng" : job.status === "running" ? "đang đăng" : job.status}
        </span>
        {job.remote_url ? (
          <a href={job.remote_url} target="_blank" rel="noreferrer" className="text-[11px]">
            mở
          </a>
        ) : job.status === "scheduled" ? (
          <button className="hidden text-[11px] text-bad-text group-hover:inline" onClick={() => onCancel(job)}>
            huỷ
          </button>
        ) : null}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ nội dung

function ContentPane({
  items,
  selected,
  onSelect,
  onChange,
  onError,
  onSchedule,
}: {
  items: Content[];
  selected: Content | null;
  onSelect: (c: Content | null) => void;
  onChange: () => void;
  onError: (m: string) => void;
  onSchedule: () => void;
}) {
  const [adding, setAdding] = useState(false);

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-lg font-bold tracking-tight">Nội dung</span>
        <button className="btn text-xs" onClick={() => setAdding((v) => !v)}>
          {adding ? "đóng" : "Thêm bài"}
        </button>
      </div>

      {adding && (
        <NewContent
          onDone={() => {
            setAdding(false);
            onChange();
          }}
          onError={onError}
        />
      )}

      {items.length === 0 && !adding && <Empty>Chưa có bài nào. Bấm “Thêm bài”: kéo video vào, viết caption.</Empty>}

      <div className="flex flex-col gap-2">
        {items.map((c) => (
          <div
            key={c.id}
            draggable
            onDragStart={(e) => {
              onSelect(c);
              e.dataTransfer.setData("application/json", JSON.stringify({ kind: "content", id: c.id }));
            }}
            onClick={() => onSelect(selected?.id === c.id ? null : c)}
            className={"card flex cursor-pointer gap-3 p-3 " + (selected?.id === c.id ? "ring-2 ring-accent" : "")}
          >
            <Thumb media={c.media} />
            <div className="flex min-w-0 flex-col gap-1">
              <div className="truncate font-semibold">{c.title}</div>
              <div className="line-clamp-2 text-[13px] text-muted">{c.body || "—"}</div>
              <div className="flex flex-wrap gap-x-2 text-xs text-muted">
                {c.media ? <span>{c.media.kind === "video" ? "video" : "ảnh"} {(c.media.size_bytes / 1048576).toFixed(1)} MB</span> : <span className="text-warn-text">chưa có video</span>}
                <span>·</span>
                <span>{c.combinations.toLocaleString("vi")} biến thể</span>
                {c.jobs_total > 0 && (
                  <>
                    <span>·</span>
                    <span>{c.jobs_succeeded} đã lên / {c.jobs_total}</span>
                  </>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="card sticky bottom-16 flex flex-col gap-2 p-3 lg:bottom-4">
        <span className="label">Lên lịch</span>
        <span className="text-sm text-muted">{selected ? `Bài: ${selected.title}` : "Chọn một bài ở trên, hoặc kéo bài thả vào một ngày."}</span>
        <button className="btn btn-primary" disabled={!selected} onClick={onSchedule}>
          Chọn tài khoản và lên lịch
        </button>
      </div>
    </section>
  );
}

function Thumb({ media }: { media: Media | null }) {
  if (!media) return <div className="h-[84px] w-[60px] shrink-0 rounded-lg border border-dashed border-line" />;
  if (media.has_thumbnail) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={`${BASE_URL}/media/${media.id}/thumb?t=${encodeURIComponent(tokenQuery())}`} alt="" className="h-[84px] w-[60px] shrink-0 rounded-lg object-cover" onError={(e) => ((e.target as HTMLImageElement).style.visibility = "hidden")} />;
  }
  return <div className="h-[84px] w-[60px] shrink-0 rounded-lg bg-soft" />;
}
// Anh xem truoc di qua <img>, khong gan header duoc; server chap nhan token o query cho route thumb.
function tokenQuery(): string {
  return typeof window === "undefined" ? "" : (localStorage.getItem("seeding-token") ?? "");
}

function NewContent({ onDone, onError }: { onDone: () => void; onError: (m: string) => void }) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [media, setMedia] = useState<Media | null>(null);
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<{ samples: { title: string; body: string }[]; combinations: number } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!title.trim()) {
      setPreview(null);
      return;
    }
    const t = setTimeout(() => {
      api.post<{ samples: { title: string; body: string }[]; combinations: number }>("/content/preview", { title, body })
        .then(setPreview)
        .catch(() => setPreview(null));
    }, 500);
    return () => clearTimeout(t);
  }, [title, body]);

  async function upload(file: File) {
    setUploading(true);
    try {
      setMedia(await uploadMedia(file));
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
    }
  }

  async function save() {
    setBusy(true);
    try {
      await api.post("/content", { title, body, media_id: media?.id ?? null });
      onDone();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card flex flex-col gap-3 p-3">
      <div
        className={"flex items-center justify-center rounded-lg border border-dashed px-3 py-4 text-center text-sm " + (media ? "border-ok bg-ok-soft text-ok-text" : "border-line bg-softer text-muted")}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          const f = e.dataTransfer.files?.[0];
          if (f) upload(f);
        }}
        onClick={() => fileRef.current?.click()}
      >
        {uploading ? "Đang tải lên…" : media ? `${media.original_name} · ${(media.size_bytes / 1048576).toFixed(1)} MB` : "Kéo video vào đây, hoặc bấm để chọn"}
        <input ref={fileRef} type="file" accept="video/*,image/*" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
      </div>
      <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Caption — dùng {a|b|c} để mỗi acc một câu khác" />
      <textarea value={body} onChange={(e) => setBody(e.target.value)} placeholder={"Dòng dưới (tuỳ chọn) — #hashtag, {chào|hello} cả nhà"} className="min-h-[90px]" />
      {preview && (
        <div className="rounded-lg bg-softer p-2.5 text-xs text-muted">
          <div className="mb-1">
            <b className="text-ink">{preview.combinations.toLocaleString("vi")}</b> biến thể khác nhau. Ví dụ:
          </div>
          {preview.samples.map((s, i) => (
            <div key={i} className="truncate">
              · {s.title}
              {s.body ? ` — ${s.body}` : ""}
            </div>
          ))}
        </div>
      )}
      <button className="btn btn-primary" disabled={busy || !title.trim()} onClick={save}>
        {busy ? "Đang lưu…" : "Lưu bài"}
      </button>
    </div>
  );
}

// -------------------------------------------------------------- lên lịch

function ScheduleDialog({
  content,
  contents,
  accounts,
  platform,
  date,
  onClose,
  onDone,
  onPick,
}: {
  content: Content | null;
  contents: Content[];
  accounts: AccountRow[];
  platform: Platform;
  date: string;
  onClose: () => void;
  onDone: () => void;
  onPick: (c: Content) => void;
}) {
  const [picked, setPicked] = useState<Set<string>>(() => new Set(accounts.map((a) => a.id)));
  const [start, setStart] = useState(date);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Job[] | null>(null);

  async function run() {
    if (!content) return;
    setBusy(true);
    setError(null);
    try {
      const jobs = await api.post<Job[]>("/schedule", {
        content_id: content.id,
        account_ids: [...picked],
        start_date: start,
      });
      setResult(jobs);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-30 flex items-end justify-center bg-ink/30 p-0 sm:items-center sm:p-6" onClick={onClose}>
      <div className="card flex max-h-[92vh] w-full max-w-lg flex-col gap-4 overflow-auto rounded-b-none p-5 sm:rounded-b-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <span className="text-lg font-bold">Lên lịch</span>
          <button className="btn btn-ghost text-xs" onClick={onClose}>đóng</button>
        </div>

        {!content ? (
          <div className="flex flex-col gap-2">
            <span className="text-muted">Chọn bài:</span>
            {contents.map((c) => (
              <button key={c.id} className="card p-3 text-left" onClick={() => onPick(c)}>
                {c.title}
              </button>
            ))}
          </div>
        ) : result ? (
          <div className="flex flex-col gap-2">
            <div className="rounded-lg bg-ok-soft p-3 text-ok-text">
              Đã lên lịch <b>{result.length}</b> bài. Mỗi tài khoản một câu caption khác nhau, bám giờ vàng.
            </div>
            <ul className="text-sm text-muted">
              {result.slice(0, 8).map((j) => (
                <li key={j.id}>
                  <span className="mono">{j.handle}</span> · {new Date(j.scheduled_at).toLocaleString("vi", { weekday: "short", hour: "2-digit", minute: "2-digit", day: "numeric", month: "numeric" })}
                </li>
              ))}
              {result.length > 8 && <li>…và {result.length - 8} bài nữa</li>}
            </ul>
            <button className="btn btn-primary" onClick={onDone}>Xong</button>
          </div>
        ) : (
          <>
            <div className="rounded-lg bg-softer p-3">
              <div className="font-semibold">{content.title}</div>
              <div className="text-xs text-muted">{content.media ? "có video" : "chưa có video — TikTok không đăng được bài chỉ có chữ"}</div>
            </div>
            <label className="flex items-center gap-3">
              <span className="w-24 text-muted">Bắt đầu</span>
              <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
            </label>
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <span className="text-muted">
                  Tài khoản {PLATFORM_LABEL[platform]} sẵn sàng · đã chọn {picked.size}/{accounts.length}
                </span>
                <button className="btn btn-ghost text-xs" onClick={() => setPicked(picked.size === accounts.length ? new Set() : new Set(accounts.map((a) => a.id)))}>
                  {picked.size === accounts.length ? "bỏ chọn hết" : "chọn hết"}
                </button>
              </div>
              {accounts.length === 0 && <Empty>Không có tài khoản {PLATFORM_LABEL[platform]} nào sẵn sàng.</Empty>}
              <div className="flex flex-wrap gap-1.5">
                {accounts.map((a) => (
                  <button
                    key={a.id}
                    className="chip mono"
                    data-on={picked.has(a.id)}
                    onClick={() => {
                      const n = new Set(picked);
                      if (n.has(a.id)) n.delete(a.id);
                      else n.add(a.id);
                      setPicked(n);
                    }}
                  >
                    {a.handle}
                  </button>
                ))}
              </div>
            </div>
            {error && <p className="text-bad-text">{error}</p>}
            <button className="btn btn-primary" disabled={busy || picked.size === 0 || !content.media} onClick={run}>
              {busy ? "Đang lên lịch…" : `Lên lịch ${picked.size} bài`}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
