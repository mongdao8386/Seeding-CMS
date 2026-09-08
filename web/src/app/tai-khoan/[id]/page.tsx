"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api, type AccountDetail, type OpenedProfile, type TimelineItem } from "@/lib/api";
import { CredentialsCard } from "@/components/credentials";
import { IdentityCard } from "@/components/identity";
import { Avatar, Empty, ErrorNote, PLATFORM_LABEL, StatusPill, useLoad } from "@/components/ui";

/** Chi tiết tài khoản: danh tính, mở trình duyệt, dòng thời gian (đăng + nuôi). */
export default function AccountPage() {
  const { id } = useParams<{ id: string }>();
  const acc = useLoad(() => api.get<AccountDetail>(`/accounts/${id}`), [id]);
  const timeline = useLoad(() => api.get<TimelineItem[]>(`/accounts/${id}/timeline`), [id]);
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

  async function setRole(role: "channel" | "booster") {
    if (!a) return;
    const msg =
      role === "booster"
        ? "Chuyển sang tương tác chéo? Acc này sẽ không đăng bài, không nuôi ra ngoài, chỉ đẩy bài của các acc xây kênh (không cần proxy)."
        : "Chuyển sang xây kênh? Acc này sẽ cần proxy, đăng bài và nuôi ra ngoài như bình thường.";
    if (!confirm(msg)) return;
    try {
      await api.patch(`/accounts/${a.id}`, { role });
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
                  <span className={a.role === "booster" ? "text-accent-dark" : ""}>{a.role === "booster" ? "tương tác chéo" : "xây kênh"}</span>
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
              <button className="btn" onClick={() => setRole(a.role === "booster" ? "channel" : "booster")}>
                {a.role === "booster" ? "Chuyển sang xây kênh" : "Chuyển sang tương tác chéo"}
              </button>
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
                <Timeline items={timeline.data ?? []} loading={timeline.loading} />
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

            <div className="lg:col-start-2">
              <CredentialsCard accountId={a.id} />
            </div>

            <div className="lg:col-start-2">
              <IdentityCard
                accountId={a.id}
                onChanged={() => {
                  acc.reload();
                  timeline.reload();
                }}
              />
            </div>
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

const KIND_VI: Record<TimelineItem["kind"], string> = {
  post: "Đăng bài",
  like: "Thả tim",
  follow: "Follow",
  comment: "Bình luận",
  repost: "Đăng lại",
  browse: "Xem feed",
  session: "Phiên",
  identity: "Danh tính",
  delete: "Xoá bài",
  edit: "Sửa bài",
  reply: "Trả lời bình luận",
  dm: "Nhắn tin",
};

function statusVi(s: TimelineItem["status"]): { text: string; cls: string } {
  switch (s) {
    case "succeeded":
      return { text: "xong", cls: "text-ok-text" };
    case "scheduled":
      return { text: "sắp tới", cls: "text-muted" };
    case "running":
      return { text: "đang chạy", cls: "text-accent-dark" };
    case "needs_human":
      return { text: "cần bạn", cls: "text-warn-text" };
    case "failed":
      return { text: "hỏng", cls: "text-warn-text" };
    case "skipped":
      return { text: "bỏ qua", cls: "text-muted" };
    default:
      return { text: "", cls: "text-muted" };
  }
}

function Timeline({ items, loading }: { items: TimelineItem[]; loading: boolean }) {
  if (loading && items.length === 0) return <p className="text-muted">Đang tải…</p>;
  if (items.length === 0) return <Empty>Chưa có gì. Việc nuôi và bài đăng sẽ hiện ở đây.</Empty>;
  let lastDay = "";
  return (
    <div className="flex flex-col">
      {items.map((it, i) => {
        const d = new Date(it.at);
        const day = d.toLocaleDateString("vi", { weekday: "long", day: "numeric", month: "numeric" });
        const showDay = day !== lastDay;
        lastDay = day;
        const st = statusVi(it.status);
        const handle = it.title.includes("@") ? it.title.slice(it.title.indexOf("@")) : "";
        return (
          <div key={i}>
            {showDay && <div className="pb-1 pt-3 text-xs font-semibold text-muted">{day}</div>}
            <div className={"flex items-start gap-3 border-b border-line py-2.5 " + (it.kind === "post" ? "-mx-2 rounded-lg bg-softer px-2" : "")}>
              <span className="mono w-11 shrink-0 text-muted">
                {String(d.getHours()).padStart(2, "0")}:{String(d.getMinutes()).padStart(2, "0")}
              </span>
              <span className="min-w-0 grow">
                <span className={it.kind === "post" ? "font-semibold" : ""}>{KIND_VI[it.kind]}</span>
                {it.kind === "post" ? (
                  <span className="text-muted"> “{it.title}”</span>
                ) : it.kind === "identity" ? (
                  <span className="text-muted"> {it.title.replace(/^Đổi danh tính: /, "")}</span>
                ) : it.kind === "reply" || it.kind === "dm" ? (
                  <span className="text-muted"> {it.detail ?? ""}</span>
                ) : it.kind === "delete" || it.kind === "edit" ? (
                  <span className="text-muted"> {it.detail && it.status === "succeeded" ? it.detail : ""}</span>
                ) : (
                  <span className="mono text-muted"> {handle}</span>
                )}
                {it.url && it.status === "succeeded" && (
                  <>
                    {" "}
                    <a href={it.url} target="_blank" rel="noreferrer" className="text-xs">
                      mở
                    </a>
                  </>
                )}
                {it.detail && it.status !== "succeeded" && <div className="truncate text-xs text-muted">{it.detail}</div>}
              </span>
              <span className={"shrink-0 text-xs font-semibold " + st.cls}>{st.text}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
