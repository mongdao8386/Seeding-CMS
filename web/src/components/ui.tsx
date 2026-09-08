"use client";

import { useCallback, useEffect, useState } from "react";
import type { AccountRow, AccountStatus, Platform } from "@/lib/api";

/** Gọi API một lần, có reload. */
export function useLoad<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const reload = useCallback(() => {
    setLoading(true);
    loader()
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    reload();
  }, [reload]);
  return { data, error, loading, reload };
}

export function PageTitle({ title, sub, action }: { title: string; sub?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        {sub && <div className="text-muted">{sub}</div>}
      </div>
      {action && <div className="flex flex-wrap gap-2">{action}</div>}
    </div>
  );
}

export function ErrorNote({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="card mb-4 border-l-[3px] border-bad p-3 text-sm text-bad-text">{message}</div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="card border border-dashed border-line p-5 text-muted shadow-none">{children}</div>
  );
}

export const PLATFORM_LABEL: Record<Platform, string> = {
  tiktok: "TikTok",
  instagram: "Instagram",
  x: "X",
  facebook: "Facebook",
  threads: "Threads",
  youtube: "YouTube",
  reddit: "Reddit",
};

export function StatusPill({ account }: { account: AccountRow }) {
  if (account.status === "dead") return <span className="pill bg-bad-soft text-bad-text">Chết</span>;
  if (account.status === "suspended") return <span className="pill bg-bad-soft text-bad-text">Bị khoá</span>;
  if (account.status === "needs_human") return <span className="pill bg-warn-soft text-warn-text">Cần bạn</span>;
  if (account.status === "paused") return <span className="pill bg-soft text-muted">Tạm dừng</span>;
  if (!account.ready) return <span className="pill bg-warn-soft text-warn-text">{blockedShort(account.blocked_reason)}</span>;
  return <span className="pill bg-ok-soft text-ok-text">Sẵn sàng</span>;
}

function blockedShort(reason: string | null): string {
  const r = (reason ?? "").toLowerCase();
  if (r.includes("proxy")) return "Thiếu proxy";
  if (r.includes("signed") || r.includes("cookie")) return "Chưa đăng nhập";
  if (r.includes("profile")) return "Chưa có profile";
  return "Chưa sẵn sàng";
}

export function SessionDot({ alive }: { alive: boolean | null }) {
  const color = alive === null ? "bg-faint" : alive ? "bg-ok" : "bg-bad";
  const text = alive === null ? "chưa kiểm" : alive ? "còn sống" : "phiên chết";
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={"h-2 w-2 rounded-full " + color} />
      <span>{text}</span>
    </span>
  );
}

export const STATUS_LABEL: Record<AccountStatus, string> = {
  warming: "đang nuôi",
  active: "hoạt động",
  paused: "tạm dừng",
  needs_human: "cần bạn",
  suspended: "bị khoá",
  dead: "chết",
};

/** Hai chữ đầu của handle làm avatar. */
/** Nen tang co adapter, theo thu tu uu tien. Reddit va Facebook it dung hon nhung khong bo. */
export const PLATFORMS: Platform[] = ["tiktok", "instagram", "x", "reddit", "facebook"];

export function Avatar({ handle, tone = "ok" }: { handle: string; tone?: "ok" | "warn" | "muted" }) {
  const initials = handle.replace(/^user/, "").slice(0, 2).toUpperCase() || handle.slice(0, 2).toUpperCase();
  const cls = tone === "ok" ? "bg-ok-soft text-ok-text" : tone === "warn" ? "bg-warn-soft text-warn-text" : "bg-soft text-muted";
  return (
    <div className={"flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold " + cls}>
      {initials}
    </div>
  );
}

export function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const ms = Date.now() - new Date(iso).getTime();
  const m = Math.round(ms / 60000);
  if (m < 1) return "vừa xong";
  if (m < 60) return `${m} phút trước`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} giờ trước`;
  const d = Math.round(h / 24);
  return `${d} ngày trước`;
}
