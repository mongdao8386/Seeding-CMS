"use client";

import { useEffect, useState } from "react";
import { api, token } from "@/lib/api";

type Health = { ok: boolean; authenticated: boolean };

/** Chặn toàn bộ giao diện cho tới khi có token dùng được. */
export function TokenGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<"checking" | "need-token" | "ready" | "api-down">("checking");
  const [health, setHealth] = useState<Health | null>(null);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function check() {
    try {
      setHealth(await api.get<Health>("/health"));
    } catch {
      setState("api-down");
      return;
    }
    if (!token.get()) {
      setState("need-token");
      return;
    }
    try {
      await api.get("/stats");
      setState("ready");
    } catch {
      setState("need-token");
    }
  }

  useEffect(() => {
    check();
  }, []);

  if (state === "ready") return <>{children}</>;

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="card w-full max-w-md p-6">
        <div className="mb-1 flex items-center gap-3">
          <div className="h-7 w-7 rounded-lg bg-accent" />
          <div className="text-lg font-bold tracking-tight">Seeding</div>
        </div>

        {state === "checking" && <p className="text-muted">Đang kiểm tra…</p>}

        {state === "api-down" && (
          <>
            <p className="mt-3 font-semibold">Không gọi được API.</p>
            <p className="mt-1 text-muted">
              Chạy <span className="mono">Start.cmd</span> ở thư mục dự án rồi tải lại trang.
            </p>
            <button className="btn mt-4" onClick={() => location.reload()}>
              Thử lại
            </button>
          </>
        )}

        {state === "need-token" && (
          <form
            className="mt-3 flex flex-col gap-3"
            onSubmit={async (e) => {
              e.preventDefault();
              token.set(value.trim());
              try {
                await api.get("/stats");
                setState("ready");
              } catch (err) {
                setError(err instanceof Error ? err.message : "Token không đúng");
              }
            }}
          >
            {health && !health.authenticated ? (
              <p className="text-muted">
                API chưa có token. Chạy{" "}
                <span className="mono">python scripts/gen_api_token.py</span> rồi dán vào{" "}
                <span className="mono">.env</span>.
              </p>
            ) : (
              <p className="text-muted">
                Dán <span className="mono">API_TOKEN</span> — Start.cmd in nó ra màn hình khi bật.
              </p>
            )}
            <input
              autoFocus
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="API_TOKEN"
              className="mono"
            />
            {error && <p className="text-bad-text">{error}</p>}
            <button className="btn btn-primary" type="submit" disabled={!value.trim()}>
              Vào
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

export function SignOut() {
  return (
    <button
      className="btn btn-ghost text-xs text-muted"
      onClick={() => {
        token.clear();
        location.reload();
      }}
    >
      đổi token
    </button>
  );
}
