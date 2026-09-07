"use client";

import { useEffect, useState } from "react";
import { api, token } from "@/lib/api";

/**
 * Bao cho phan con lai cua trang biet da co token dung duoc.
 *
 * WorkspaceProvider nam ngoai TokenGate (vi o chon workspace o tren header), nen no
 * khong the doi TokenGate render xong roi moi goi API. Thieu tin hieu nay thi lan goi
 * dau tien cua no roi vao luc chua co token, that bai, va o chon nam trong mai cho
 * toi khi nguoi dung tai lai trang.
 */
export const AUTH_READY = "seeding:authenticated";

function announceReady() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(AUTH_READY));
  }
}

type Health = { ok: boolean; authenticated: boolean };

/** Chan toan bo dashboard cho toi khi co token dung duoc. */
export function TokenGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<"checking" | "need-token" | "ready" | "api-down">(
    "checking",
  );
  const [health, setHealth] = useState<Health | null>(null);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function check() {
    try {
      const h = await api.get<Health>("/health");
      setHealth(h);
    } catch {
      setState("api-down");
      return;
    }

    if (!token.get()) {
      setState("need-token");
      return;
    }

    try {
      await api.get("/stats"); // route that, de biet token co dung duoc khong
      setState("ready");
      announceReady();
    } catch {
      setState("need-token");
    }
  }

  useEffect(() => {
    check();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (state === "checking") {
    return <p className="faint py-16 text-center text-sm">Checking…</p>;
  }

  if (state === "api-down") {
    return (
      <Panel title="Can't reach the API">
        <p className="muted text-sm">Start it in another terminal window:</p>
        <code
          className="mono mt-2 block rounded px-2 py-1.5 text-xs"
          style={{ background: "var(--surface-2)", border: "1px solid var(--rule)" }}
        >
          .venv/Scripts/uvicorn seeding.api.main:app --reload
        </code>
        <button className="btn mt-4" onClick={check}>
          Try again
        </button>
      </Panel>
    );
  }

  if (state === "need-token") {
    return (
      <Panel title="Enter token">
        {health && !health.authenticated ? (
          <>
            <p className="text-sm" style={{ color: "var(--bad)" }}>
              The API has no <span className="mono">API_TOKEN</span> set, so it is refusing every
              request.
            </p>
            <p className="muted mt-2 text-sm">
              Generate one, paste it into .env, then restart the API:
            </p>
            <code
              className="mono mt-2 block rounded px-2 py-1.5 text-xs"
              style={{ background: "var(--surface-2)", border: "1px solid var(--rule)" }}
            >
              .venv/Scripts/python scripts/gen_api_token.py
            </code>
          </>
        ) : (
          <p className="muted text-sm">
            The token is the <span className="mono">API_TOKEN</span> line in your{" "}
            <span className="mono">.env</span> file. It is stored in this browser only and never
            sent anywhere else.
          </p>
        )}

        <form
          className="mt-4 flex flex-col gap-2"
          onSubmit={async (e) => {
            e.preventDefault();
            setError(null);
            token.set(value.trim());
            try {
              await api.get("/stats");
              setState("ready");
              announceReady();
            } catch (err) {
              token.clear();
              setError(err instanceof Error ? err.message : "That token doesn't work");
            }
          }}
        >
          <input
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="paste your token here"
            className="mono text-sm"
            autoFocus
          />
          {error && (
            <p className="text-sm" style={{ color: "var(--bad)" }}>
              {error}
            </p>
          )}
          <button className="btn" type="submit" disabled={!value.trim()}>
            Continue
          </button>
        </form>
      </Panel>
    );
  }

  return <>{children}</>;
}

export function SignOut() {
  // Doc localStorage trong luc render lam server va client ra hai ket qua khac nhau,
  // va React vut ca cay di de dung lai tu dau - loi hydration tren MOI trang. Doi den
  // sau khi gan xong thi ca hai lan render dau tien deu la "khong co gi".
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  if (!mounted || !token.get()) return null;
  return (
    <button
      className="label hover:opacity-70"
      style={{ background: "none", border: "none", cursor: "pointer" }}
      onClick={() => {
        token.clear();
        location.reload();
      }}
    >
      sign out
    </button>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mx-auto mt-16 max-w-md">
      <div className="card p-6">
        <h1 className="mb-3 text-lg font-semibold">{title}</h1>
        {children}
      </div>
    </div>
  );
}
