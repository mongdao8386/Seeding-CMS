"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

export function PageHead({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="mb-6">
      <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
      {hint && <p className="muted mt-1 max-w-2xl text-sm">{hint}</p>}
    </div>
  );
}

/** Loi phai noi duoc phai lam gi tiep, khong chi bao la hong. */
export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  const offline = error instanceof ApiError && error.status === 0;

  return (
    <div
      className="card mb-4 p-3 text-sm"
      style={{ borderLeft: "3px solid var(--bad)", color: "var(--ink)" }}
    >
      <span className="label" style={{ color: "var(--bad)" }}>
        Error
      </span>
      <p className="mt-1">{message}</p>
      {offline && (
        <p className="faint mono mt-2 text-xs">
          .venv/Scripts/uvicorn seeding.api.main:app --reload
        </p>
      )}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="faint px-1 py-8 text-center text-sm">{children}</p>;
}

export function Loading() {
  return <p className="faint px-1 py-8 text-center text-sm">Loading…</p>;
}

const STATUS_STYLE: Record<string, string> = {
  succeeded: "pill-ok",
  active: "pill-ok",
  ok: "pill-ok",
  scheduled: "pill-n",
  pending: "pill-n",
  untested: "pill-n",
  running: "pill-a",
  warming: "pill-warn",
  new: "pill-warn",
  needs_human: "pill-b",
  failed: "pill-bad",
  suspended: "pill-bad",
  dead: "pill-bad",
  failing: "pill-bad",
  skipped: "pill-n",
};

const STATUS_LABEL: Record<string, string> = {
  succeeded: "posted",
  scheduled: "waiting",
  running: "running",
  failed: "failed",
  needs_human: "needs you",
  skipped: "skipped",
  pending: "not planned",
  new: "new",
  warming: "warming up",
  active: "active",
  suspended: "suspended",
  dead: "abandoned",
};

export function Status({ value }: { value: string }) {
  return (
    <span className={`pill ${STATUS_STYLE[value] ?? "pill-n"}`}>
      {STATUS_LABEL[value] ?? value}
    </span>
  );
}

/** Lane API va lane automation la hai the gioi khac nhau, nen to khac nhau. */
export function Platform({ value }: { value: string }) {
  return <span className={`pill ${value === "reddit" ? "pill-a" : "pill-b"}`}>{value}</span>;
}

export function when(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-GB", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Goi API mot lan khi mo trang, kem ham tai lai. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fn()
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e) => alive && setError(e))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonce, ...deps]);

  return { data, error, loading, reload: () => setNonce((n) => n + 1) };
}

/** Lenh CLI kem nut chep - UI khong tu mo duoc trinh duyet tren may ban. */
export function Command({ children }: { children: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-center gap-2">
      <code
        className="mono flex-1 overflow-x-auto whitespace-nowrap rounded px-2 py-1.5 text-xs"
        style={{ background: "var(--surface-2)", border: "1px solid var(--rule)" }}
      >
        {children}
      </code>
      <button
        className="btn btn-ghost shrink-0 text-xs"
        onClick={() => {
          navigator.clipboard.writeText(children);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
      >
        {copied ? "copied" : "copy"}
      </button>
    </div>
  );
}

/** Nhan cho input, dung chung o cac form. */
export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="label mb-1 block">{label}</label>
      {children}
    </div>
  );
}

/** Anh nam sau token, nen phai tai bang fetch roi doi thanh blob URL. */
export function AuthedImage({
  path,
  alt,
  className,
  style,
}: {
  path: string;
  alt: string;
  className?: string;
  style?: React.CSSProperties;
}) {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let url: string | null = null;
    let alive = true;
    api
      .blobUrl(path)
      .then((u) => {
        url = u;
        if (alive) setSrc(u);
        else URL.revokeObjectURL(u);
      })
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [path]);

  if (failed) {
    return (
      <div
        className={className}
        style={{ ...style, background: "var(--surface-2)", display: "grid", placeItems: "center" }}
      >
        <span className="faint text-xs">no preview</span>
      </div>
    );
  }
  if (!src) {
    return <div className={className} style={{ ...style, background: "var(--surface-2)" }} />;
  }
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={src} alt={alt} className={className} style={style} />;
}

/** Nut xoa hai nhip: bam lan dau la hoi lai, bam lan hai moi that su xoa. */
export function ConfirmButton({
  onConfirm,
  children,
  confirmLabel = "sure?",
  className = "btn btn-danger text-xs",
}: {
  onConfirm: () => void | Promise<void>;
  children: React.ReactNode;
  confirmLabel?: string;
  className?: string;
}) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!armed) return;
    const timer = setTimeout(() => setArmed(false), 4000);
    return () => clearTimeout(timer);
  }, [armed]);

  return (
    <button
      className={className}
      disabled={busy}
      onClick={async () => {
        if (!armed) {
          setArmed(true);
          return;
        }
        setBusy(true);
        try {
          await onConfirm();
        } finally {
          setBusy(false);
          setArmed(false);
        }
      }}
    >
      {armed ? confirmLabel : children}
    </button>
  );
}

export function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function humanDuration(seconds: number | null): string {
  if (!seconds) return "";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m ? `${m}:${String(s).padStart(2, "0")}` : `${s}s`;
}
