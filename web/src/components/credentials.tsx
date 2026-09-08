"use client";

import { useState } from "react";
import { api, type AccountSecrets } from "@/lib/api";
import { useLoad } from "@/components/ui";

/** Thông tin đăng nhập dán vào lúc nhập acc: xem, chép, sửa. Mật khẩu ẩn cho tới khi bấm Hiện. */

const LABEL: Record<string, string> = {
  username: "Tên đăng nhập",
  password: "Mật khẩu",
  recovery_email: "Email",
  recovery_password: "Mật khẩu email",
  totp_seed: "2FA (seed)",
  client_id: "Client ID",
  client_secret: "Client secret",
};
const HIDDEN = new Set(["password", "recovery_password", "totp_seed", "client_secret"]);
const ORDER = ["username", "password", "recovery_email", "recovery_password", "totp_seed", "client_id", "client_secret"];

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // clipboard bị chặn (http không phải localhost): người dùng vẫn chọn tay được
  }
}

function Value({ k, v, shown }: { k: string; v: string; shown: boolean }) {
  const [copied, setCopied] = useState(false);
  const masked = HIDDEN.has(k) && !shown;
  return (
    <span className="flex min-w-0 items-center gap-2">
      <span className="mono truncate" title={masked ? undefined : v}>
        {masked ? "•".repeat(Math.min(v.length, 12)) : v}
      </span>
      <button
        type="button"
        className="btn btn-ghost px-1.5 py-0 text-xs"
        onClick={async () => {
          await copy(v);
          setCopied(true);
          setTimeout(() => setCopied(false), 1200);
        }}
      >
        {copied ? "đã chép" : "Chép"}
      </button>
    </span>
  );
}

/** Thẻ đầy đủ trên trang tài khoản: xem + sửa. */
export function CredentialsCard({ accountId }: { accountId: string }) {
  const data = useLoad(() => api.get<AccountSecrets>(`/accounts/${accountId}/secrets`), [accountId]);
  const [shown, setShown] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fields = data.data?.fields ?? {};
  const keys = ORDER.filter((k) => data.data?.known.includes(k) ?? false);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api.put(`/accounts/${accountId}/secrets`, { fields: draft });
      setEditing(false);
      data.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card flex flex-col gap-3 p-5">
      <div className="flex items-center justify-between gap-2">
        <span className="label">Thông tin đăng nhập</span>
        <div className="flex gap-2">
          {!editing && (
            <button type="button" className="btn text-xs" onClick={() => setShown((s) => !s)}>
              {shown ? "Ẩn" : "Hiện"}
            </button>
          )}
          {!editing ? (
            <button
              type="button"
              className="btn text-xs"
              onClick={() => {
                setDraft(Object.fromEntries(keys.map((k) => [k, fields[k] ?? ""])));
                setEditing(true);
              }}
            >
              Sửa
            </button>
          ) : (
            <>
              <button type="button" className="btn text-xs" disabled={busy} onClick={() => setEditing(false)}>
                Huỷ
              </button>
              <button type="button" className="btn btn-primary text-xs" disabled={busy} onClick={save}>
                {busy ? "…" : "Lưu"}
              </button>
            </>
          )}
        </div>
      </div>
      {error && <div className="text-sm text-bad-text">{error}</div>}
      {data.loading && <div className="text-sm text-muted">Đang mở két…</div>}
      {!data.loading && !editing && Object.keys(fields).length === 0 && (
        <div className="text-sm text-muted">Chưa có gì. Bấm Sửa để ghi tên đăng nhập, mật khẩu, email, 2FA.</div>
      )}
      <dl className="grid grid-cols-[120px_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
        {editing
          ? keys.map((k) => (
              <div key={k} className="contents">
                <dt className="self-center text-muted">{LABEL[k] ?? k}</dt>
                <dd>
                  <input
                    value={draft[k] ?? ""}
                    onChange={(e) => setDraft((d) => ({ ...d, [k]: e.target.value }))}
                    className="mono w-full px-2 py-1"
                    autoComplete="off"
                    spellCheck={false}
                  />
                </dd>
              </div>
            ))
          : keys
              .filter((k) => fields[k])
              .map((k) => (
                <div key={k} className="contents">
                  <dt className="text-muted">{LABEL[k] ?? k}</dt>
                  <dd className="min-w-0">
                    <Value k={k} v={fields[k]} shown={shown} />
                  </dd>
                </div>
              ))}
        {!editing && data.data?.totp_code && (
          <div className="contents">
            <dt className="text-muted">Mã 2FA lúc này</dt>
            <dd>
              <Value k="totp_code" v={data.data.totp_code} shown />
            </dd>
          </div>
        )}
      </dl>
      <p className="text-xs text-faint">Lưu mã hoá trong két, dùng khi phải đăng nhập lại trong trình duyệt của profile.</p>
    </section>
  );
}

/** Dòng gọn trên thẻ tiếp quản: chỉ tải khi bấm, để đăng nhập lại chỉ cần chép dán. */
export function CredentialsInline({ accountId }: { accountId: string }) {
  const [data, setData] = useState<AccountSecrets | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [shown, setShown] = useState(false);

  if (!data) {
    return (
      <span className="flex items-center gap-2">
        <button
          type="button"
          className="btn text-xs"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              setData(await api.get<AccountSecrets>(`/accounts/${accountId}/secrets`));
            } catch (e) {
              setError(e instanceof Error ? e.message : String(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "…" : "Thông tin đăng nhập"}
        </button>
        {error && <span className="text-xs text-bad-text">{error}</span>}
      </span>
    );
  }
  const keys = ORDER.filter((k) => data.fields[k]);
  if (keys.length === 0) {
    return <span className="text-xs text-muted">Chưa lưu thông tin đăng nhập cho acc này (sửa ở trang tài khoản).</span>;
  }
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
      {keys.map((k) => (
        <span key={k} className="flex items-center gap-1">
          <span className="text-muted">{LABEL[k] ?? k}:</span>
          <Value k={k} v={data.fields[k]} shown={shown} />
        </span>
      ))}
      {data.totp_code && (
        <span className="flex items-center gap-1">
          <span className="text-muted">2FA:</span>
          <Value k="totp_code" v={data.totp_code} shown />
        </span>
      )}
      <button type="button" className="btn btn-ghost px-1.5 py-0 text-xs" onClick={() => setShown((s) => !s)}>
        {shown ? "Ẩn" : "Hiện"}
      </button>
    </div>
  );
}
