"use client";

import { useEffect, useState } from "react";
import { api, type Takeover } from "@/lib/api";
import { Command, ErrorBox, Loading, PageHead, useLoad, when } from "@/components/ui";

export default function Takeovers() {
  const { data, error, loading, reload } = useLoad<Takeover[]>(() => api.get("/takeovers"));

  return (
    <>
      <PageHead
        title="Takeover queue"
        hint="When an account hits a checkpoint the system stops and waits for you — no retrying, no automatic re-login. This is what separates a system that works from a demo."
      />

      <ErrorBox error={error} />
      {loading && <Loading />}

      {data?.length === 0 && (
        <div className="card p-6 text-center" style={{ borderLeft: "3px solid var(--ok)" }}>
          <p className="text-sm font-medium" style={{ color: "var(--ok)" }}>
            Queue is clear
          </p>
          <p className="muted mt-1 text-sm">No account is waiting on you.</p>
        </div>
      )}

      <div className="flex flex-col gap-4">
        {(data ?? []).map((t) => (
          <TakeoverCard key={t.id} item={t} onDone={reload} />
        ))}
      </div>
    </>
  );
}

function TakeoverCard({ item, onDone }: { item: Takeover; onDone: () => void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [totp, setTotp] = useState<{ code: string | null; note: string } | null>(null);

  // Ma 2FA doi moi 30 giay nen phai lam moi, khong lay mot lan roi thoi.
  useEffect(() => {
    let alive = true;
    const fetchCode = () =>
      api
        .get<{ code: string | null; note: string }>(`/takeovers/${item.id}/totp`)
        .then((d) => alive && setTotp(d))
        .catch(() => {});
    fetchCode();
    const timer = setInterval(fetchCode, 15_000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [item.id]);

  async function act(action: "resolve" | "abandon") {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/takeovers/${item.id}/${action}`, {
        by: "dashboard",
        note: note || (action === "abandon" ? "not recoverable" : "resolved"),
      });
      onDone();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card p-4" style={{ borderLeft: "3px solid var(--b)" }}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="mono text-base font-semibold">{item.handle}</span>
        <span className="pill pill-b">{item.platform}</span>
        <span className="faint mono text-xs">stuck since {when(item.created_at)}</span>
        {item.has_stuck_job && <span className="pill pill-warn">a post is stuck</span>}
        {totp?.code && (
          <span className="ml-auto flex items-baseline gap-2">
            <span className="label">2fa code</span>
            <span className="mono text-lg font-semibold tracking-widest tabular-nums">
              {totp.code}
            </span>
          </span>
        )}
      </div>

      <p className="muted mt-2 text-sm">{item.reason}</p>

      <div className="mt-3">
        <span className="label mb-1 block">1 · Open the browser and solve it</span>
        <Command>
          {`.venv/Scripts/python scripts/takeover.py open ${item.platform} ${item.handle}`}
        </Command>
      </div>

      <div className="mt-3">
        <span className="label mb-1 block">2 · Close it out here</span>
        <ErrorBox error={error} />
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="entered the verification code"
            className="min-w-48 flex-1 text-sm"
          />
          <button className="btn" disabled={busy} onClick={() => act("resolve")}>
            Resolved
          </button>
          <button className="btn btn-danger" disabled={busy} onClick={() => act("abandon")}>
            Abandon account
          </button>
        </div>
        <p className="faint mt-2 text-xs">
          Once resolved the account goes back to warming up rather than straight to active, and the
          stuck post is rescheduled six hours out — posting right after clearing a checkpoint is
          exactly the rhythm being watched.
        </p>
      </div>
    </div>
  );
}
