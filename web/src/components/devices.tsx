"use client";

import { useState } from "react";
import { api, qs, type Account, type Device, type DevicePreflight, type Proxy } from "@/lib/api";
import { ConfirmButton, Empty, Field, Loading, Pager, SearchBox, Status, useLoad, usePaged, when } from "@/components/ui";

/**
 * Duong thiet bi that: dien thoai chay app that, thay cho trinh duyet.
 *
 * Man hinh nay co mot viec quan trong hon ca CRUD: noi ro cai gi con thieu. Chuoi cong
 * cu Android co bon manh (adb, driver USB, go loi USB tren may, Appium), va thieu manh
 * nao cung ra mot loi khong lien quan gi den nguyen nhan that.
 */
export function Devices({
  accounts,
  proxies,
  onError,
}: {
  accounts: Account[];
  proxies: Proxy[];
  onError: (e: unknown) => void;
}) {
  const devices = usePaged<Device>("/devices", ({ limit, offset, q }) =>
    `/devices${qs({ limit, offset, q })}`,
  );
  const preflight = useLoad<DevicePreflight>(() => api.get("/devices/preflight"));
  const [syncing, setSyncing] = useState(false);
  const [sync, setSync] = useState<{
    ok: boolean;
    detail?: string;
    attached: number;
    unknown: { serial: string; state: string; model: string | null }[];
  } | null>(null);
  const [adding, setAdding] = useState(false);

  async function runSync() {
    setSyncing(true);
    try {
      setSync(await api.post("/devices/sync"));
      devices.reload();
      preflight.reload();
    } catch (e) {
      onError(e);
    } finally {
      setSyncing(false);
    }
  }

  const pf = preflight.data;

  return (
    <>
      {pf && !pf.ready && (
        <div className="card mb-4 p-3 text-sm" style={{ borderLeft: "3px solid var(--warn)" }}>
          <span className="label" style={{ color: "var(--warn)" }}>
            Not ready yet
          </span>
          <ul className="muted mt-1 flex flex-col gap-1">
            {pf.problems.map((problem, i) => (
              <li key={i}>{problem}</li>
            ))}
          </ul>
          <p className="faint mt-2 text-xs">{pf.note}</p>
        </div>
      )}

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <button className="btn" onClick={() => setAdding((v) => !v)}>
          {adding ? "close" : "Add device"}
        </button>
        <button className="btn btn-ghost" disabled={syncing} onClick={runSync}>
          {syncing ? "Checking…" : "Scan for phones"}
        </button>
        <SearchBox value={devices.query} onChange={devices.setQuery} placeholder="search…" />
        <div className="ml-auto">
          <Pager
            total={devices.total}
            offset={devices.offset}
            pageSize={devices.pageSize}
            onGoto={devices.goto}
            noun="device"
          />
        </div>
      </div>

      {sync && (
        <div
          className="card mb-4 p-3 text-sm"
          style={{ borderLeft: `3px solid ${sync.ok ? "var(--ok)" : "var(--bad)"}` }}
        >
          {sync.ok ? (
            <>
              <p>{sync.attached} phone(s) attached.</p>
              {sync.unknown.length > 0 && (
                <p className="muted mt-1">
                  Not registered yet:{" "}
                  <span className="mono">
                    {sync.unknown.map((u) => `${u.serial} (${u.state})`).join(", ")}
                  </span>
                  . Add them above — they are not added automatically, because a phone plugged in
                  to charge shows up here too.
                </p>
              )}
            </>
          ) : (
            <p>{sync.detail}</p>
          )}
        </div>
      )}

      {adding && (
        <NewDevice
          accounts={accounts}
          proxies={proxies}
          onDone={() => {
            setAdding(false);
            devices.reload();
          }}
          onError={onError}
        />
      )}

      <div className="card overflow-x-auto">
        {devices.loading && <Loading />}
        {devices.items.length ? (
          <table className="grid">
            <thead>
              <tr>
                <th>Label</th>
                <th>Serial</th>
                <th>OS</th>
                <th>Model</th>
                <th>State</th>
                <th>Account</th>
                <th>Proxy</th>
                <th>Last seen</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {devices.items.map((d) => (
                <tr key={d.id}>
                  <td className="text-sm">{d.label}</td>
                  <td className="mono text-xs">{d.serial}</td>
                  <td>
                    <span className="pill pill-b">{d.os}</span>
                  </td>
                  <td className="mono text-xs">{d.model ?? "—"}</td>
                  <td>
                    <Status
                      value={
                        d.status === "ready"
                          ? "active"
                          : d.status === "busy"
                            ? "running"
                            : d.status === "offline"
                              ? "skipped"
                              : "failed"
                      }
                    />
                    {d.status === "unauthorized" && (
                      <span className="faint ml-2 text-xs">allow USB debugging on the phone</span>
                    )}
                  </td>
                  <td className="mono text-xs">{d.handle ?? <span className="faint">—</span>}</td>
                  <td className="mono text-xs">{d.proxy_label ?? <span className="faint">—</span>}</td>
                  <td className="faint text-xs">{when(d.last_seen_at)}</td>
                  <td style={{ textAlign: "right" }}>
                    <ConfirmButton
                      onConfirm={async () => {
                        try {
                          await api.del(`/devices/${d.id}`);
                          devices.reload();
                        } catch (e) {
                          onError(e);
                        }
                      }}
                    >
                      delete
                    </ConfirmButton>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          !devices.loading && (
            <Empty>
              {devices.query
                ? "Nothing matches that search."
                : "No devices yet. Plug a phone in, turn on USB debugging, then Scan."}
            </Empty>
          )
        )}
      </div>

      <div className="card mt-4 p-4 text-sm">
        <span className="label">Why a real phone rather than a faked one</span>
        <p className="muted mt-2">
          A real app sends signals a browser has no way to fake — sensors, tilt, device id, the
          rhythm of a finger on glass. Spoofing a mobile user-agent in a desktop browser gives you
          none of that. It gives you a string, and a fingerprint that <em>contradicts itself</em>:
          the UA claims a phone while WebGL reports your graphics card. That is easier to catch
          than an honest desktop profile, not harder.
        </p>
        <p className="muted mt-2">
          The same rule as browser profiles applies here: one account, one device, one proxy, never
          rotated. Running one account on the web in the morning and on the phone at night from two
          different addresses is a clearer signal than anything else this system avoids.
        </p>
      </div>
    </>
  );
}

function NewDevice({
  accounts,
  proxies,
  onDone,
  onError,
}: {
  accounts: Account[];
  proxies: Proxy[];
  onDone: () => void;
  onError: (e: unknown) => void;
}) {
  const [serial, setSerial] = useState("");
  const [label, setLabel] = useState("");
  const [accountId, setAccountId] = useState("");
  const [proxyId, setProxyId] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <div className="card mb-4 p-4">
      <span className="label">New device</span>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <Field label="Serial (from adb devices)">
          <input
            value={serial}
            onChange={(e) => setSerial(e.target.value)}
            placeholder="R3CT90ABCDE"
            className="mono text-sm"
          />
        </Field>
        <Field label="Label">
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Samsung A52 — máy 1"
          />
        </Field>
        <Field label="Account (optional for now)">
          <select value={accountId} onChange={(e) => setAccountId(e.target.value)}>
            <option value="">— not bound yet —</option>
            {accounts
              .filter((a) => a.platform !== "reddit" && a.status !== "dead")
              .map((a) => (
                <option key={a.id} value={a.id}>
                  {a.handle} ({a.platform})
                </option>
              ))}
          </select>
        </Field>
        <Field label="Proxy">
          <select value={proxyId} onChange={(e) => setProxyId(e.target.value)}>
            <option value="">— none —</option>
            {proxies.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <button
        className="btn mt-4"
        disabled={!serial.trim() || !label.trim() || busy}
        onClick={async () => {
          setBusy(true);
          try {
            await api.post("/devices", {
              serial: serial.trim(),
              label: label.trim(),
              account_id: accountId || null,
              proxy_id: proxyId || null,
            });
            onDone();
          } catch (e) {
            onError(e);
          } finally {
            setBusy(false);
          }
        }}
      >
        Add
      </button>
    </div>
  );
}
