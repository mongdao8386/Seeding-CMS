"use client";

import { useState } from "react";
import { api, type Account, type Proxy, type ProxyTest } from "@/lib/api";
import { ConfirmButton, Field, Platform, Status, when } from "@/components/ui";

const ACCOUNT_STATUSES = ["new", "warming", "active", "needs_human", "suspended", "dead"];
const SCHEMES = ["http", "https", "socks5"];

/** Mot dong tai khoan, sua duoc tai cho. */
export function AccountRow({
  account,
  onChange,
  onError,
}: {
  account: Account;
  onChange: () => void;
  onError: (e: unknown) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [handle, setHandle] = useState(account.handle);
  const [cap, setCap] = useState(account.daily_cap);
  const [status, setStatus] = useState(account.status);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    try {
      await api.patch(`/accounts/${account.id}`, {
        handle,
        daily_cap: cap,
        status,
        ...(password ? { secrets: { password } } : {}),
      });
      setPassword("");
      setEditing(false);
      onChange();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }

  if (editing) {
    return (
      <tr>
        <td colSpan={7}>
          <div className="flex flex-wrap items-end gap-3 py-1">
            <Field label="Handle">
              <input
                value={handle}
                onChange={(e) => setHandle(e.target.value)}
                className="mono text-sm"
                style={{ width: 180 }}
              />
            </Field>
            <Field label="Daily cap">
              <input
                type="number"
                min={1}
                max={100}
                value={cap}
                onChange={(e) => setCap(Number(e.target.value) || 1)}
                style={{ width: 90 }}
              />
            </Field>
            <Field label="Status">
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                style={{ width: 150 }}
              >
                {ACCOUNT_STATUSES.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="New password (blank keeps it)">
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                style={{ width: 190 }}
              />
            </Field>
            <button className="btn" disabled={busy} onClick={save}>
              Save
            </button>
            <button className="btn btn-ghost" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
          <p className="faint mt-1 text-xs">
            Leaving the password blank keeps the stored one — and the TOTP seed is kept either way.
          </p>
        </td>
      </tr>
    );
  }

  return (
    <tr>
      <td className="mono font-medium">{account.handle}</td>
      <td>
        <Platform value={account.platform} />
      </td>
      <td>
        <Status value={account.status} />
      </td>
      <td className="mono tabular-nums">{account.daily_cap}</td>
      <td className="mono whitespace-nowrap text-xs">{when(account.warmup_started_at)}</td>
      <td className="mono whitespace-nowrap text-xs">{when(account.last_posted_at)}</td>
      <td>
        <div className="flex justify-end gap-2">
          <button className="btn btn-ghost text-xs" onClick={() => setEditing(true)}>
            edit
          </button>
          <ConfirmButton
            onConfirm={async () => {
              try {
                await api.del(`/accounts/${account.id}`);
                onChange();
              } catch (e) {
                onError(e);
              }
            }}
          >
            delete
          </ConfirmButton>
        </div>
      </td>
    </tr>
  );
}

/** Mot dong proxy, sua duoc tai cho va thu duoc ket noi that. */
export function ProxyRow({
  proxy,
  onChange,
  onError,
}: {
  proxy: Proxy;
  onChange: () => void;
  onError: (e: unknown) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({
    label: proxy.label,
    host: proxy.host,
    port: proxy.port,
    scheme: proxy.scheme,
    region: proxy.region ?? "",
    password: "",
  });
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<ProxyTest | null>(null);
  const [busy, setBusy] = useState(false);

  const set = (k: string, v: string | number) => setForm({ ...form, [k]: v });

  if (editing) {
    return (
      <tr>
        <td colSpan={8}>
          <div className="flex flex-wrap items-end gap-3 py-1">
            <Field label="Label">
              <input
                value={form.label}
                onChange={(e) => set("label", e.target.value)}
                className="mono text-sm"
                style={{ width: 150 }}
              />
            </Field>
            <Field label="Scheme">
              <select
                value={form.scheme}
                onChange={(e) => set("scheme", e.target.value)}
                style={{ width: 110 }}
              >
                {SCHEMES.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Host">
              <input
                value={form.host}
                onChange={(e) => set("host", e.target.value)}
                className="mono text-sm"
                style={{ width: 160 }}
              />
            </Field>
            <Field label="Port">
              <input
                type="number"
                value={form.port}
                onChange={(e) => set("port", Number(e.target.value) || 0)}
                style={{ width: 100 }}
              />
            </Field>
            <Field label="Region">
              <input
                value={form.region}
                onChange={(e) => set("region", e.target.value)}
                style={{ width: 100 }}
              />
            </Field>
            <Field label="New password">
              <input
                type="password"
                value={form.password}
                onChange={(e) => set("password", e.target.value)}
                style={{ width: 150 }}
              />
            </Field>
            <button
              className="btn"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await api.patch(`/proxies/${proxy.id}`, {
                    label: form.label,
                    host: form.host,
                    port: form.port,
                    scheme: form.scheme,
                    region: form.region || null,
                    ...(form.password ? { password: form.password } : {}),
                  });
                  setEditing(false);
                  onChange();
                } catch (e) {
                  onError(e);
                } finally {
                  setBusy(false);
                }
              }}
            >
              Save
            </button>
            <button className="btn btn-ghost" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </td>
      </tr>
    );
  }

  return (
    <tr>
      <td className="mono font-medium">{proxy.label}</td>
      <td>
        <span className={`pill ${proxy.kind === "datacenter" ? "pill-bad" : "pill-n"}`}>
          {proxy.kind}
        </span>
      </td>
      <td className="mono text-xs">
        {proxy.scheme}://{proxy.host}:{proxy.port}
      </td>
      <td className="mono text-xs">{proxy.region ?? "—"}</td>
      <td className="mono text-xs">{proxy.sticky ? "yes" : "NO"}</td>
      <td>
        <Status value={proxy.status} />
      </td>
      <td className="mono text-xs">
        {result ? (
          result.ok ? (
            <span style={{ color: "var(--ok)" }}>
              {result.exit_ip} · {result.latency_ms}ms
            </span>
          ) : (
            <span style={{ color: "var(--bad)" }} title={result.error ?? ""}>
              failed
            </span>
          )
        ) : (
          (proxy.last_exit_ip ?? "—")
        )}
      </td>
      <td>
        <div className="flex justify-end gap-2">
          <button
            className="btn btn-ghost text-xs"
            disabled={testing}
            onClick={async () => {
              setTesting(true);
              try {
                setResult(await api.post<ProxyTest>(`/proxies/${proxy.id}/test`));
                onChange();
              } catch (e) {
                onError(e);
              } finally {
                setTesting(false);
              }
            }}
          >
            {testing ? "testing" : "test"}
          </button>
          <button className="btn btn-ghost text-xs" onClick={() => setEditing(true)}>
            edit
          </button>
          <ConfirmButton
            onConfirm={async () => {
              try {
                await api.del(`/proxies/${proxy.id}`);
                onChange();
              } catch (e) {
                onError(e);
              }
            }}
          >
            delete
          </ConfirmButton>
        </div>
      </td>
    </tr>
  );
}
