"use client";

import Link from "next/link";
import { useState } from "react";
import { api, type OpenedProfile, type Takeover } from "@/lib/api";
import { Empty, PLATFORM_LABEL, timeAgo } from "@/components/ui";

/** Hàng đợi chờ người — thứ nổi nhất trên Tổng quan. Mỗi dòng: vì sao, và ba nút. */
export function TakeoverList({ items, onChange, onError }: { items: Takeover[]; onChange: () => void; onError: (m: string) => void }) {
  if (items.length === 0) {
    return <Empty>Hàng đợi trống. Checkpoint, phiên chết hay bài không xác nhận được sẽ hiện ở đây trước tiên.</Empty>;
  }
  return (
    <div className="card overflow-hidden">
      {items.map((t) => (
        <TakeoverRow key={t.id} t={t} onChange={onChange} onError={onError} />
      ))}
    </div>
  );
}

function TakeoverRow({ t, onChange, onError }: { t: Takeover; onChange: () => void; onError: (m: string) => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [totp, setTotp] = useState<string | null>(null);
  const [note, setNote] = useState("");

  async function run(label: string, fn: () => Promise<unknown>) {
    setBusy(label);
    try {
      await fn();
      onChange();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-2 border-b border-line border-l-[3px] border-l-warn px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Link href={`/tai-khoan/${t.account_id}`} className="mono font-semibold text-ink">
          {t.handle}
        </Link>
        <span className="text-muted">{PLATFORM_LABEL[t.platform]}</span>
        <span className="text-muted">· {timeAgo(t.created_at)}</span>
        {t.has_stuck_job && <span className="pill bg-soft text-muted">có bài đang kẹt</span>}
        {totp && (
          <span className="mono rounded-md bg-accent-soft px-2 py-0.5 text-accent-dark">
            2FA {totp}
          </span>
        )}
      </div>
      <div className="text-sm text-warn-text">{t.reason}</div>
      <div className="flex flex-wrap items-center gap-2">
        <button
          className="btn text-xs"
          disabled={!t.profile_id || busy !== null}
          onClick={() =>
            run("open", async () => {
              const r = await api.post<OpenedProfile>(`/profiles/${t.profile_id}/open`, {});
              onError(r.detail);
            })
          }
        >
          Mở trình duyệt
        </button>
        <button
          className="btn text-xs"
          disabled={busy !== null}
          onClick={async () => {
            try {
              const r = await api.get<{ code: string | null; note: string }>(`/takeovers/${t.id}/totp`);
              setTotp(r.code ?? "—");
            } catch (e) {
              onError(e instanceof Error ? e.message : String(e));
            }
          }}
        >
          Mã 2FA
        </button>
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="ghi chú (đã giải captcha…)"
          className="min-h-[34px] grow px-2 py-1 text-sm sm:max-w-[260px]"
        />
        <button
          className="btn btn-primary text-xs"
          disabled={busy !== null}
          onClick={() => run("resolve", () => api.post(`/takeovers/${t.id}/resolve`, { by: "dashboard", note: note || null }))}
        >
          {busy === "resolve" ? "…" : "Đã giải"}
        </button>
        <button
          className="btn btn-ghost text-xs text-bad-text"
          disabled={busy !== null}
          onClick={() => {
            if (!confirm(`Bỏ ${t.handle}? Tài khoản chuyển sang "chết".`)) return;
            run("abandon", () => api.post(`/takeovers/${t.id}/abandon`, { by: "dashboard", note: note || "bỏ từ dashboard" }));
          }}
        >
          Bỏ tài khoản
        </button>
      </div>
    </div>
  );
}
