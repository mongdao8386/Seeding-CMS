"use client";

import { useEffect, useState } from "react";
import { api, type Platform, type Settings, type Slot, type SlotMeta, type SystemStatus } from "@/lib/api";
import { ErrorNote, PLATFORM_LABEL, PLATFORMS, PageTitle, useLoad } from "@/components/ui";

/** Cài đặt: giờ vàng (sửa được), nhịp nuôi và trạng thái hệ thống (đọc từ .env). */
export default function SettingsPage() {
  const [platform, setPlatform] = useState<Platform>("tiktok");
  const slots = useLoad(() => api.get<Slot[]>("/slots"), []);
  const meta = useLoad(() => api.get<SlotMeta>("/slots/meta"), []);
  const settings = useLoad(() => api.get<Settings>("/settings"), []);
  const sys = useLoad(() => api.get<SystemStatus>("/system"), []);
  const [alertNote, setAlertNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  return (
    <>
      <PageTitle title="Cài đặt" />
      <ErrorNote message={error ?? slots.error} />

      <section className="card flex flex-col gap-4 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-[15px] font-semibold">Giờ vàng — {PLATFORM_LABEL[platform]}</div>
            <div className="text-[13px] text-muted">
              Bài được bám vào mốc gần nhất, mỗi tài khoản một mốc khác nhau trong ngày.
              {meta.data ? ` Múi giờ ${meta.data.timezone}.` : ""}
            </div>
          </div>
          <div className="flex gap-1.5 text-sm">
            {PLATFORMS.map((p) => (
              <button key={p} className={"rounded-lg px-2.5 py-1.5 " + (platform === p ? "bg-soft font-medium" : "text-muted")} onClick={() => setPlatform(p)}>
                {PLATFORM_LABEL[p]}
              </button>
            ))}
          </div>
        </div>

        {meta.data && (
          <SlotEditor platform={platform} slots={(slots.data ?? []).filter((s) => s.platform === platform)} weekdays={meta.data.weekdays} onChange={slots.reload} onError={setError} />
        )}
      </section>

      <div className="mt-5 grid gap-5 md:grid-cols-2">
        <section className="card flex flex-col gap-3 p-5">
          <div className="text-[15px] font-semibold">Nuôi tài khoản</div>
          <div className="text-[13px] text-muted">Đọc từ <span className="mono">.env</span> — đổi ở đó rồi bật lại.</div>
          {settings.data ? (
            <dl className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-2">
              <dt className="text-muted">Ngày im lặng — chỉ tương tác, không đăng</dt>
              <dd className="mono">{settings.data.warmup_quiet_days}</dd>
              <dt className="text-muted">Ngày tăng nhịp — từ 1 bài lên trần</dt>
              <dd className="mono">{settings.data.warmup_days}</dd>
              <dt className="text-muted">Trần bài / ngày</dt>
              <dd className="mono">{settings.data.default_daily_cap}</dd>
              <dt className="text-muted">Kiểm phiên mỗi</dt>
              <dd className="mono">{settings.data.health_check_interval_hours} giờ</dd>
              <dt className="text-muted">Hỏng liên tiếp bao lần thì gọi người</dt>
              <dd className="mono">{settings.data.health_fail_threshold}</dd>
              <dt className="text-muted">Múi giờ lịch</dt>
              <dd className="mono">{settings.data.schedule_timezone}</dd>
            </dl>
          ) : (
            <p className="text-muted">…</p>
          )}
          <p className="text-xs text-faint">Thả tim 4–8, follow 1–3, bình luận 0–2 mỗi ngày; ngày đầu một nửa. Chung cho TikTok, Instagram và X — sửa trong platforms/outreach.py.</p>
        </section>

        <section className="card flex flex-col gap-3 p-5">
          <div className="text-[15px] font-semibold">Hệ thống</div>
          <Row ok={!!sys.data?.api} text={sys.data ? "API đang chạy" : "API không trả lời"} />
          <Row ok={!!sys.data?.database} text="Cơ sở dữ liệu" />
          <Row ok={!!sys.data?.signer} text={`Signer TikTok · ${sys.data?.signer_detail ?? "…"}`} />
          <Row ok={!!settings.data?.tiktok_post_via_http} text={settings.data?.tiktok_post_via_http ? "Đăng TikTok qua HTTP" : "Đăng TikTok qua HTTP: tắt"} />
          <Row ok={!!settings.data?.tiktok_interact_via_http} text={settings.data?.tiktok_interact_via_http ? "Nuôi TikTok qua HTTP" : "Nuôi TikTok qua HTTP: tắt"} />
          <Row ok={!!settings.data?.instagram_enabled} text={settings.data?.instagram_enabled ? "Instagram qua API app (aiograpi)" : "Instagram: tắt"} />
          <Row ok={!!settings.data?.x_enabled} text={settings.data?.x_enabled ? "X qua twifork" : "X: tắt"} />
          <Row ok={!!settings.data?.reddit_enabled} text={settings.data?.reddit_enabled ? "Reddit qua API (script app)" : "Reddit: tắt"} />
          <Row ok={!!settings.data?.facebook_enabled} text={settings.data?.facebook_enabled ? "Facebook bằng trình duyệt (chậm, không nuôi tự động)" : "Facebook: tắt"} />
          {settings.data?.x_enabled && (
            <Row
              ok={sys.data?.x_library !== false}
              text={
                sys.data?.x_library === null || sys.data?.x_library === undefined
                  ? "Thư viện X: chưa kiểm (chưa có tài khoản X hoặc worker chưa quét)"
                  : sys.data.x_library
                    ? "Thư viện X khớp với X"
                    : `Thư viện X lệch — chạy: pip install -U twifork · ${sys.data.x_library_detail ?? ""}`
              }
            />
          )}
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <Row ok={!!settings.data?.alert_configured} text={settings.data?.alert_configured ? `Cảnh báo ${settings.data.alert_kind} khi cần bạn` : "Cảnh báo chưa bật — đặt ALERT_WEBHOOK_URL trong .env"} />
            {settings.data?.alert_configured && (
              <button
                className="btn text-xs"
                onClick={async () => {
                  try {
                    await api.post("/alerts/test");
                    setAlertNote("Đã gửi tin thử.");
                  } catch (e) {
                    setAlertNote(e instanceof Error ? e.message : String(e));
                  }
                }}
              >
                Gửi thử
              </button>
            )}
          </div>
          {alertNote && <p className="text-xs text-muted">{alertNote}</p>}
        </section>
      </div>
    </>
  );
}

function SlotEditor({
  platform,
  slots,
  weekdays,
  onChange,
  onError,
}: {
  platform: Platform;
  slots: Slot[];
  weekdays: string[];
  onChange: () => void;
  onError: (m: string) => void;
}) {
  const [draft, setDraft] = useState<Record<number, number[]>>({});
  const [dirty, setDirty] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const t: Record<number, number[]> = {};
    for (let d = 0; d < 7; d++) t[d] = [];
    for (const s of slots) t[s.weekday].push(s.hour);
    for (const d of Object.keys(t)) t[+d].sort((a, b) => a - b);
    setDraft(t);
    setDirty(new Set());
  }, [slots, platform]);

  function toggle(day: number, hour: number) {
    const hours = draft[day] ?? [];
    const next = hours.includes(hour) ? hours.filter((h) => h !== hour) : [...hours, hour].sort((a, b) => a - b);
    setDraft({ ...draft, [day]: next });
    setDirty(new Set(dirty).add(day));
  }

  async function save() {
    setBusy(true);
    try {
      for (const day of dirty) {
        await api.put("/slots", { platform, weekdays: [day], times: (draft[day] ?? []).map((h) => ({ hour: h, minute: 0 })) });
      }
      onChange();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-2">
        {weekdays.map((name, day) => (
          <div key={day} className="grid grid-cols-[80px_minmax(0,1fr)] items-center gap-3 sm:grid-cols-[90px_minmax(0,1fr)]">
            <span className="text-muted">{name}</span>
            <div className="flex flex-wrap gap-1">
              {Array.from({ length: 24 }, (_, h) => h).map((h) => {
                const on = (draft[day] ?? []).includes(h);
                return (
                  <button
                    key={h}
                    className={"mono min-h-[30px] min-w-[38px] rounded-md px-1.5 text-[12px] " + (on ? "bg-accent-soft font-medium text-accent-dark ring-1 ring-accent" : "bg-softer text-faint hover:bg-soft")}
                    onClick={() => toggle(day, h)}
                  >
                    {String(h).padStart(2, "0")}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <div className="flex items-center gap-3">
        <button className="btn btn-primary" disabled={busy || dirty.size === 0} onClick={save}>
          {busy ? "Đang lưu…" : dirty.size ? `Lưu ${dirty.size} ngày` : "Không có gì đổi"}
        </button>
        <span className="text-xs text-muted">Bấm vào giờ để bật/tắt. Mỗi ngày nên 2–4 mốc; nhiều hơn là rải loãng.</span>
      </div>
    </div>
  );
}

function Row({ ok, text }: { ok: boolean; text: string }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className={"h-2 w-2 rounded-full " + (ok ? "bg-ok" : "bg-bad")} />
      <span>{text}</span>
    </div>
  );
}
