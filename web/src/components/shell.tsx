"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type SystemStatus } from "@/lib/api";
import { SignOut } from "@/components/token-gate";

const NAV = [
  { href: "/", label: "Tổng quan", icon: IconGrid },
  { href: "/tai-khoan", label: "Tài khoản", icon: IconUsers },
  { href: "/noi-dung", label: "Nội dung & Lịch", short: "Lịch", icon: IconCalendar },
  { href: "/cai-dat", label: "Cài đặt", icon: IconSliders },
];

/**
 * Khung: rail trái trên màn rộng, thanh dưới trên điện thoại (hướng B).
 * Nội dung luôn là một cột, tối đa 1180px.
 */
export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));

  return (
    <div className="flex min-h-screen">
      <nav className="sticky top-0 hidden h-screen w-[220px] shrink-0 flex-col gap-1 border-r border-line px-4 py-7 lg:flex">
        <div className="mb-5 flex items-center gap-2.5 px-3">
          <div className="h-7 w-7 rounded-lg bg-accent" />
          <div className="text-[15px] font-bold tracking-tight">Seeding</div>
        </div>
        {NAV.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className={
              "flex items-center gap-2.5 rounded-lg px-3 py-2.5 " +
              (active(href) ? "bg-surface font-semibold text-ink shadow-[0_1px_0_var(--color-line)]" : "text-muted hover:text-ink")
            }
          >
            <Icon />
            <span>{label}</span>
          </Link>
        ))}
        <div className="grow" />
        <SystemPill />
        <div className="px-1 pt-2">
          <SignOut />
        </div>
      </nav>

      <main className="min-w-0 grow px-4 pb-24 pt-6 sm:px-8 lg:px-10 lg:pb-10 lg:pt-9">
        <div className="mx-auto max-w-[1180px]">{children}</div>
      </main>

      <nav className="fixed inset-x-0 bottom-0 z-20 grid grid-cols-4 border-t border-line bg-ground/95 backdrop-blur lg:hidden">
        {NAV.map(({ href, label, short, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className={
              "flex min-h-[56px] flex-col items-center justify-center gap-1 text-[11px] " +
              (active(href) ? "font-semibold text-ink" : "text-muted")
            }
          >
            <Icon />
            <span>{short ?? label}</span>
          </Link>
        ))}
      </nav>
    </div>
  );
}

function SystemPill() {
  const [sys, setSys] = useState<SystemStatus | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => api.get<SystemStatus>("/system").then((s) => alive && setSys(s)).catch(() => alive && setSys(null));
    load();
    const t = setInterval(load, 30_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);
  const Row = ({ ok, text }: { ok: boolean; text: string }) => (
    <div className="flex items-center gap-2 text-xs text-muted">
      <span className={"h-2 w-2 rounded-full " + (ok ? "bg-ok" : "bg-bad")} />
      <span>{text}</span>
    </div>
  );
  return (
    <div className="card flex flex-col gap-1.5 p-3">
      <Row ok={!!sys?.api} text={sys ? "API đang chạy" : "API không trả lời"} />
      <Row ok={!!sys?.database} text="Cơ sở dữ liệu" />
      <Row ok={!!sys?.signer} text={`Signer ${sys?.signer_detail ?? "…"}`} />
    </div>
  );
}

function IconGrid() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="8" height="8" rx="2" /><rect x="13" y="3" width="8" height="8" rx="2" /><rect x="3" y="13" width="8" height="8" rx="2" /><rect x="13" y="13" width="8" height="8" rx="2" />
    </svg>
  );
}
function IconUsers() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="9" cy="8" r="3.5" /><path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6" /><circle cx="17" cy="9" r="2.5" /><path d="M16 14.5c3 0 5.5 2 5.5 5.5" />
    </svg>
  );
}
function IconCalendar() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 9h18M8 4v16M16 4v16" />
    </svg>
  );
}
function IconSliders() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 7h16M4 12h10M4 17h16" /><circle cx="17" cy="12" r="2" />
    </svg>
  );
}
