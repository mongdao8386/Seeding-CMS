"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api, type AccountDetail, type OpenedProfile } from "@/lib/api";
import { Avatar, Empty, ErrorNote, PLATFORM_LABEL, StatusPill, useLoad } from "@/components/ui";

/** Chi tiết — phần 1: danh tính + mở trình duyệt. Dòng thời gian vào ở phần 2–3. */
export default function AccountPage() {
  const { id } = useParams<{ id: string }>();
  const acc = useLoad(() => api.get<AccountDetail>(`/accounts/${id}`), [id]);
  const [opened, setOpened] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const a = acc.data;

  async function open() {
    if (!a?.profile_id) return;
    setBusy(true);
    setOpened(null);
    try {
      const r = await api.post<OpenedProfile>(`/profiles/${a.profile_id}/open`, {});
      setOpened(r.detail);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function setStatus(status: "paused" | "warming") {
    if (!a) return;
    try {
      await api.patch(`/accounts/${a.id}`, { status });
      acc.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <>
      <div className="mb-5 flex items-center gap-2 text-sm text-muted">
        <Link href="/tai-khoan">Tài khoản</Link>
        <span>›</span>
        <span className="mono text-ink">{a?.handle ?? "…"}</span>
      </div>
      <ErrorNote message={acc.error ?? error} />

      {a && (
        <>
          <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-4">
              <Avatar handle={a.handle} tone={a.ready ? "ok" : "warn"} />
              <div className="flex flex-col gap-1">
                <div className="flex flex-wrap items-center gap-2.5">
                  <span className="mono text-xl font-semibold tracking-tight">{a.handle}</span>
                  <StatusPill account={a} />
                </div>
                <div className="flex flex-wrap gap-x-3 text-muted">
                  <span>{PLATFORM_LABEL[a.platform]}</span>
                  <span>·</span>
                  <span>
                    proxy <span className="mono">{a.proxy_label ?? "chưa có"}</span>
                  </span>
                  <span>·</span>
                  <span>{a.warm_day ? `nuôi ngày ${a.warm_day}` : "chưa nuôi"}</span>
                </div>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {a.status === "paused" ? (
                <button className="btn" onClick={() => setStatus("warming")}>
                  Chạy lại
                </button>
              ) : (
                <button className="btn" onClick={() => setStatus("paused")}>
                  Tạm dừng
                </button>
              )}
              <button className="btn btn-primary" disabled={busy || !a.profile_id || !a.proxy_label} onClick={open}>
                {busy ? "Đang mở…" : "Mở trình duyệt"}
              </button>
            </div>
          </div>
          {!a.ready && a.blocked_reason && (
            <div className="card mb-5 border-l-[3px] border-warn p-3 text-sm text-warn-text">{a.blocked_reason}</div>
          )}
          {opened && <div className="card mb-5 border-l-[3px] border-ok p-3 text-sm text-ok-text">{opened}</div>}

          <div className="grid gap-5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
            <section className="card p-5">
              <span className="label">Dòng thời gian</span>
              <div className="mt-3">
                <Empty>Đăng bài, thả tim, follow, bình luận, checkpoint sẽ hiện ở đây từ phần 2.</Empty>
              </div>
            </section>

            <section className="card flex flex-col gap-3 p-5">
              <span className="label">Danh tính</span>
              <dl className="grid grid-cols-[110px_minmax(0,1fr)] gap-x-4 gap-y-2.5">
                <dt className="text-muted">Proxy</dt>
                <dd className="mono truncate">{a.proxy_host ? `${a.proxy_label} · ${a.proxy_host}` : "chưa có"}</dd>
                <dt className="text-muted">IP ra</dt>
                <dd className="mono">{a.proxy_exit_ip ?? "—"}</dd>
                <dt className="text-muted">Múi giờ</dt>
                <dd>{a.timezone ?? "theo IP proxy"}</dd>
                <dt className="text-muted">Cookie</dt>
                <dd>
                  {a.cookie_count} · {a.session_cookie ? "có phiên" : "không có phiên"}
                </dd>
                <dt className="text-muted">Trình duyệt</dt>
                <dd className="truncate" title={a.user_agent ?? ""}>
                  {a.user_agent ? shortUa(a.user_agent) : "—"}
                </dd>
                <dt className="text-muted">Trần / ngày</dt>
                <dd>{a.daily_cap} bài</dd>
              </dl>
              <p className="text-xs text-faint">Fingerprint không sửa được — nó là danh tính, không phải cài đặt.</p>
            </section>
          </div>
        </>
      )}
    </>
  );
}

function shortUa(ua: string): string {
  const ff = ua.match(/Firefox\/(\d+)/);
  const os = /Windows/.test(ua) ? "Windows" : /Mac/.test(ua) ? "macOS" : /Linux/.test(ua) ? "Linux" : "";
  return ff ? `Firefox ${ff[1]} / ${os}` : ua.slice(0, 40);
}
