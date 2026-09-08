"use client";

import Link from "next/link";
import { api, qs, type ActivitySummary, type Job, type Stats } from "@/lib/api";
import { Empty, ErrorNote, PageTitle, useLoad } from "@/components/ui";

const DAYS = ["Chủ Nhật", "Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy"];

/** Tổng quan: cái gì cần tôi? đội thế nào? hôm nay đăng gì? */
export default function Overview() {
  const now = new Date();
  const todayIso = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  const stats = useLoad(() => api.get<Stats>("/stats"));
  const warm = useLoad(() => api.get<ActivitySummary>("/activity/summary"));
  const today = useLoad(() => api.get<Job[]>(`/schedule${qs({ start: todayIso, days: 1 })}`));
  const s = stats.data;
  const w = warm.data;
  const posted = (today.data ?? []).filter((j) => j.status === "succeeded").length;
  const upcoming = (today.data ?? []).filter((j) => j.status === "scheduled" || j.status === "running").length;

  return (
    <>
      <PageTitle
        title={`${DAYS[now.getDay()]}, ${now.getDate()} tháng ${now.getMonth() + 1}`}
        sub={s ? (s.needs_human > 0 ? `${s.needs_human} tài khoản đang cần bạn.` : "Không có gì cần bạn.") : "…"}
        action={
          <Link href="/tai-khoan?dan=acc" className="btn btn-primary">
            Dán tài khoản
          </Link>
        }
      />
      <ErrorNote message={stats.error ?? warm.error ?? today.error} />

      <section className="mb-6 flex flex-col gap-3">
        <div className="flex items-center gap-2.5">
          <span className="label">Cần bạn</span>
          <span className="pill bg-soft text-muted">{s?.needs_human ?? "…"}</span>
        </div>
        {s && s.needs_human === 0 ? (
          <Empty>Hàng đợi trống. Checkpoint, phiên chết hay bài không xác nhận được sẽ hiện ở đây trước tiên.</Empty>
        ) : (
          <Empty>
            {s?.needs_human ?? 0} tài khoản đang cần bạn — mở{" "}
            <Link href="/tai-khoan">Tài khoản</Link>, lọc “Cần bạn”. Hàng đợi chi tiết vào ở phần 4.
          </Empty>
        )}
      </section>

      <div className="grid gap-5 md:grid-cols-2">
        <section className="card flex flex-col gap-4 p-5 sm:p-6">
          <span className="label">Đội tài khoản</span>
          <div className="grid grid-cols-3 gap-3">
            <Big n={s?.ready} label="sẵn sàng" tone="ok" />
            <Big n={s?.blocked} label="chưa sẵn sàng" tone="warn" />
            <Big n={s?.dead} label="chết" tone="bad" />
          </div>
          <div className="h-px bg-line" />
          <div className="flex flex-col gap-2 text-muted">
            <div className="flex flex-col gap-1">
              <div className="flex justify-between">
                <span>Đang nuôi</span>
                <span className="text-ink">{s?.warming ?? "…"} tài khoản</span>
              </div>
              {w && (
                <div className="text-xs">
                  hôm nay: {w.likes.done}/{w.likes.planned} thả tim · {w.follows.done}/{w.follows.planned} follow ·{" "}
                  {w.comments.done}/{w.comments.planned} bình luận
                </div>
              )}
            </div>
            <div className="flex justify-between">
              <span>Proxy còn rảnh</span>
              <span className="text-ink">{s ? `${s.proxies_free} / ${s.proxies}` : "…"}</span>
            </div>
          </div>
          <Link href="/tai-khoan" className="text-sm">
            Xem tài khoản →
          </Link>
        </section>

        <section className="card flex flex-col gap-3 p-5 sm:p-6">
          <div className="flex items-center justify-between">
            <span className="label">Hôm nay</span>
            <span className="text-xs text-muted">
              <b className="text-ink">{posted}</b> đã đăng · <b className="text-ink">{upcoming}</b> sắp đăng
            </span>
          </div>
          {(today.data ?? []).length === 0 ? (
            <Empty>Hôm nay không có bài nào trong lịch.</Empty>
          ) : (
            <div className="flex flex-col">
              {(today.data ?? []).slice(0, 8).map((j) => (
                <div key={j.id} className="flex items-center gap-3 border-b border-line py-2">
                  <span className="mono w-11 text-muted">
                    {new Date(j.scheduled_at).toLocaleTimeString("vi", { hour: "2-digit", minute: "2-digit" })}
                  </span>
                  <span className="mono min-w-0 grow truncate">{j.handle}</span>
                  <span
                    className={
                      "pill " +
                      (j.status === "succeeded" ? "bg-ok-soft text-ok-text" : j.status === "needs_human" || j.status === "failed" ? "bg-warn-soft text-warn-text" : "bg-soft text-muted")
                    }
                  >
                    {j.status === "succeeded" ? "đã lên" : j.status === "scheduled" ? "sắp đăng" : j.status === "needs_human" ? "cần bạn" : j.status === "failed" ? "hỏng" : j.status}
                  </span>
                </div>
              ))}
            </div>
          )}
          <Link href="/noi-dung" className="text-sm">
            Xem cả tuần →
          </Link>
        </section>
      </div>
    </>
  );
}

function Big({ n, label, tone }: { n: number | undefined; label: string; tone: "ok" | "warn" | "bad" }) {
  const color = tone === "ok" ? "text-ok" : tone === "warn" ? "text-warn" : "text-bad";
  return (
    <div className="flex flex-col">
      <div className={"text-[34px] font-bold leading-none tracking-tight " + color}>{n ?? "…"}</div>
      <div className="mt-1 text-muted">{label}</div>
    </div>
  );
}
