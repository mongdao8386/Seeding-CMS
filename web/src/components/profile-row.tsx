"use client";

import { useState } from "react";
import { api, type Profile, type Proxy } from "@/lib/api";
import { ConfirmButton, Field, Platform, when } from "@/components/ui";

const ENGINES = ["camoufox", "patchright"];
const LOCALES = ["en-US", "en-GB", "vi-VN", "th-TH", "id-ID", "ja-JP", "ko-KR"];

/** Mot dong profile: doi proxy, doi engine, hoac xoa han. */
export function ProfileRow({
  profile,
  proxies,
  onChange,
  onError,
}: {
  profile: Profile;
  proxies: Proxy[];
  onChange: () => void;
  onError: (e: unknown) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [proxyId, setProxyId] = useState("");
  const [engine, setEngine] = useState(profile.engine);
  const [locale, setLocale] = useState("en-US");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [needsForce, setNeedsForce] = useState(false);

  async function save(force: boolean) {
    setBusy(true);
    try {
      await api.patch(`/profiles/${profile.id}`, {
        engine,
        locale,
        ...(proxyId ? { proxy_id: proxyId, force_rebind: force, rebind_reason: reason } : {}),
      });
      setEditing(false);
      setNeedsForce(false);
      setProxyId("");
      setReason("");
      onChange();
    } catch (e) {
      // Doi proxy bi chan la ket qua co y, khong phai su co - hien nut xac nhan
      // thay vi bat nguoi dung tu doan.
      const message = e instanceof Error ? e.message : "";
      if (message.includes("one-account-one-IP")) {
        setNeedsForce(true);
      } else {
        onError(e);
      }
    } finally {
      setBusy(false);
    }
  }

  if (editing) {
    return (
      <tr>
        <td colSpan={7}>
          <div className="flex flex-wrap items-end gap-3 py-1">
            <Field label="Proxy">
              <select
                value={proxyId}
                onChange={(e) => {
                  setProxyId(e.target.value);
                  setNeedsForce(false);
                }}
                style={{ width: 190 }}
              >
                <option value="">keep {profile.proxy_label ?? "none"}</option>
                {proxies.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Engine">
              <select
                value={engine}
                onChange={(e) => setEngine(e.target.value)}
                style={{ width: 140 }}
              >
                {ENGINES.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Locale">
              <select
                value={locale}
                onChange={(e) => setLocale(e.target.value)}
                style={{ width: 120 }}
              >
                {LOCALES.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </Field>
            {proxyId && (
              <Field label="Why rebind?">
                <input
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="old proxy is dead"
                  style={{ width: 190 }}
                />
              </Field>
            )}

            {needsForce ? (
              <button className="btn btn-danger" disabled={busy} onClick={() => save(true)}>
                Rebind anyway
              </button>
            ) : (
              <button className="btn" disabled={busy} onClick={() => save(false)}>
                Save
              </button>
            )}
            <button
              className="btn btn-ghost"
              onClick={() => {
                setEditing(false);
                setNeedsForce(false);
              }}
            >
              Cancel
            </button>
          </div>

          {needsForce && (
            <p className="mt-1 text-xs" style={{ color: "var(--bad)" }}>
              This profile is already bound to a proxy. Rotating IPs between sessions of the same
              account does more harm than a slow but fixed residential IP — only do this if the old
              proxy is genuinely dead.
            </p>
          )}
          <p className="faint mt-1 text-xs">
            The fingerprint is deliberately not editable — it is the account&apos;s identity, not a
            setting.
          </p>
        </td>
      </tr>
    );
  }

  return (
    <tr>
      <td className="mono font-medium">{profile.handle}</td>
      <td>
        <Platform value={profile.platform} />
      </td>
      <td>
        {profile.session_alive ? (
          <span className="pill pill-ok">alive</span>
        ) : profile.last_login_at ? (
          <span className="pill pill-bad">dead</span>
        ) : (
          <span className="pill pill-warn">never signed in</span>
        )}
        {profile.consecutive_health_failures > 0 && (
          <span className="faint mono ml-1 text-xs">
            {profile.consecutive_health_failures} failed
          </span>
        )}
      </td>
      <td className="mono text-xs">{profile.proxy_label ?? "— none —"}</td>
      <td className="mono max-w-xs truncate text-xs" title={profile.fingerprint}>
        {profile.fingerprint}
      </td>
      <td className="mono whitespace-nowrap text-xs">{when(profile.last_health_at)}</td>
      <td>
        <div className="flex justify-end gap-2">
          <button className="btn btn-ghost text-xs" onClick={() => setEditing(true)}>
            edit
          </button>
          <ConfirmButton
            confirmLabel={profile.last_login_at ? "lose session?" : "sure?"}
            onConfirm={async () => {
              try {
                // Profile con phien thi backend chan; force vi nguoi dung da xac nhan
                // qua nut hai nhip, va nhan nut da noi ro se mat phien.
                await api.del(`/profiles/${profile.id}?force=true`);
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
