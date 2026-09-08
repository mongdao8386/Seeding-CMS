"use client";

import Link from "next/link";
import { api, type Stats } from "@/lib/api";
import { Empty, ErrorNote, PageTitle, useLoad } from "@/components/ui";

const DAYS = ["Chủ Nhật", "Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy"];

/** Tổng quan — phần 1 mới có "Đội tài khoản". "Cần bạn" và "Hôm nay" vào ở phần 2 và 4. */
export default function Overview() {
  const stats = useLoad(() => api.get<Stats>("/stats"));
  const now = new Date();
  const s = stats.data;

  return (
    <>
      <PageTitle
        title={`${DAYS[now.getDay()]}, ${now.getDate()} tháng ${now.getMonth() + 1}`}
        sub={
          s
            ? s.needs_human > 0
              ? `${s.needs_human} tài khoản đang cần bạn.`
              : "Không có gì cần bạn."
            : "…"
        }
        action={
          <Link href="/tai-khoan?dan=acc" className="btn btn-primary">
            Dán tài khoản
          </Link>
        }
      />
      <ErrorNote message={stats.error} />

      <section className="mb-6 flex flex-col gap-3">
        <div className="flex items-center gap-2.5">
          <span className="label">Cần bạn</span>
          <span className="pill bg-soft text-muted">{s?.needs_human ?? "…"}</span>
        </div>
        {s && s.needs_human === 0 ? (
          <Empty>
            Hàng đợi trống. Checkpoint, phiên chết hay bài không xác nhận được sẽ hiện ở đây trước
            tiên.
          </Empty>
        ) : (
          <Empty>Hàng đợi chờ người vào ở phần 4.</Empty>
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
            <div className="flex justify-between">
              <span>Đang nuôi</span>
              <span className="text-ink">{s?.warming ?? "…"}</span>
            </div>
            <div className="flex justify-between">
              <span>Proxy còn rảnh</span>
              <span className="text-ink">
                {s ? `${s.proxies_free} / ${s.proxies}` : "…"}
              </span>
            </div>
          </div>
          <Link href="/tai-khoan" className="text-sm">
            Xem tài khoản →
          </Link>
        </section>

        <section className="card flex flex-col gap-4 p-5 sm:p-6">
          <span className="label">Hôm nay</span>
          <Empty>Lịch đăng và việc nuôi trong ngày vào ở phần 2 và 3.</Empty>
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
