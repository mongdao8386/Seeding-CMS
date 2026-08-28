"use client";

import { useState } from "react";
import {
  api,
  type Account,
  type Profile,
  type Proxy,
  type ProxyTestAll,
} from "@/lib/api";
import { NewAccount } from "@/components/new-account";
import { ImportAccounts } from "@/components/import-accounts";
import { ProfileRow } from "@/components/profile-row";
import { AccountRow, ProxyRow } from "@/components/rows";
import {
  Command,
  Empty,
  ErrorBox,
  Field,
  Loading,
  PageHead,
  Platform,
  Status,
  useLoad,
  when,
} from "@/components/ui";

type Tab = "accounts" | "profiles" | "proxies";

export default function Accounts() {
  const [tab, setTab] = useState<Tab>("accounts");
  const [rowError, setRowError] = useState<unknown>(null);
  const [testingAll, setTestingAll] = useState(false);
  const [testAll, setTestAll] = useState<ProxyTestAll | null>(null);
  const accounts = useLoad<Account[]>(() => api.get("/accounts"));
  const profiles = useLoad<Profile[]>(() => api.get("/profiles"));
  const proxies = useLoad<Proxy[]>(() => api.get("/proxies"));

  const withoutProfile = (accounts.data ?? []).filter(
    (a) => a.platform !== "reddit" && !(profiles.data ?? []).some((p) => p.account_id === a.id),
  );

  return (
    <>
      <PageHead
        title="Accounts"
        hint="One account ↔ one profile ↔ one proxy, bound for good and never rotated. Reddit goes through its API, so it needs no profile."
      />

      <ErrorBox error={rowError ?? accounts.error ?? profiles.error ?? proxies.error} />

      <div className="mb-5 flex gap-1">
        {(
          [
            ["accounts", `Accounts (${accounts.data?.length ?? 0})`],
            ["profiles", `Profiles (${profiles.data?.length ?? 0})`],
            ["proxies", `Proxies (${proxies.data?.length ?? 0})`],
          ] as [Tab, string][]
        ).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className="btn btn-ghost text-sm"
            style={
              tab === key
                ? { borderColor: "var(--a)", color: "var(--a)" }
                : { color: "var(--ink-2)" }
            }
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "accounts" && (
        <>
          {/* Dong khi ca hai cung dong; mo ra thi panel chiem tron hang. */}
          <div className="flex flex-wrap items-start gap-3 [&>div]:w-full">
            <NewAccount onDone={accounts.reload} />
            <ImportAccounts onDone={accounts.reload} />
          </div>
          {withoutProfile.length > 0 && (
            <div className="card mb-4 p-3" style={{ borderLeft: "3px solid var(--warn)" }}>
              <span className="label" style={{ color: "var(--warn)" }}>
                No profile yet
              </span>
              <p className="muted mt-1 text-sm">
                {withoutProfile.map((a) => a.handle).join(", ")} — these accounts cannot post yet.
                Create a profile in the next tab.
              </p>
            </div>
          )}

          <div className="card overflow-x-auto">
            {accounts.loading && <Loading />}
            {accounts.data?.length ? (
              <table className="grid">
                <thead>
                  <tr>
                    <th>Handle</th>
                    <th>Platform</th>
                    <th>Status</th>
                    <th>Daily cap</th>
                    <th>Warming since</th>
                    <th>Last posted</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {accounts.data.map((a) => (
                    <AccountRow
                      key={a.id}
                      account={a}
                      onChange={accounts.reload}
                      onError={setRowError}
                    />
                  ))}
                </tbody>
              </table>
            ) : (
              !accounts.loading && <Empty>No accounts yet.</Empty>
            )}
          </div>
        </>
      )}

      {tab === "profiles" && (
        <>
          <NewProfile
            accounts={withoutProfile}
            proxies={proxies.data ?? []}
            onDone={() => (profiles.reload(), accounts.reload())}
          />

          <div className="card mt-5 overflow-x-auto">
            {profiles.data?.length ? (
              <table className="grid">
                <thead>
                  <tr>
                    <th>Handle</th>
                    <th>Platform</th>
                    <th>Session</th>
                    <th>Proxy</th>
                    <th>Fingerprint</th>
                    <th>Last checked</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {profiles.data.map((p) => (
                    <ProfileRow
                      key={p.id}
                      profile={p}
                      proxies={proxies.data ?? []}
                      onChange={() => (profiles.reload(), accounts.reload())}
                      onError={setRowError}
                    />
                  ))}
                </tbody>
              </table>
            ) : (
              <Empty>No profiles yet.</Empty>
            )}
          </div>

          {(profiles.data ?? []).some((p) => !p.last_login_at) && (
            <div className="card mt-4 p-3">
              <span className="label">Sign in by hand</span>
              <p className="muted mb-2 mt-1 text-sm">
                The dashboard cannot open a browser on your machine — run this in a terminal. Do it
                once, then the session is kept for good.
              </p>
              <div className="flex flex-col gap-2">
                {(profiles.data ?? [])
                  .filter((p) => !p.last_login_at)
                  .map((p) => (
                    <Command key={p.id}>
                      {`.venv/Scripts/python scripts/login_profile.py ${p.platform} ${p.handle}`}
                    </Command>
                  ))}
              </div>
            </div>
          )}
        </>
      )}

      {tab === "proxies" && (
        <>
          {testAll && (
            <div
              className="card mb-4 p-3 text-sm"
              style={{
                borderLeft: `3px solid ${
                  testAll.duplicate_exit_ips.length
                    ? "var(--bad)"
                    : testAll.passed === testAll.tested
                      ? "var(--ok)"
                      : "var(--warn)"
                }`,
              }}
            >
              <span className="label">Test all</span>
              <p className="mt-1">
                {testAll.passed} of {testAll.tested} proxies reachable.
              </p>
              {testAll.duplicate_exit_ips.length > 0 && (
                <p className="mt-1" style={{ color: "var(--bad)" }}>
                  Two or more proxies came out of the same IP:{" "}
                  <span className="mono">{testAll.duplicate_exit_ips.join(", ")}</span>. That is one
                  exit, not several — accounts bound to them are sharing an address without knowing.
                </p>
              )}
            </div>
          )}
          <NewProxy onDone={proxies.reload} />
          <div className="card mt-5 overflow-x-auto">
            {proxies.data?.length ? (
              <table className="grid">
                <thead>
                  <tr>
                    <th>Label</th>
                    <th>Kind</th>
                    <th>Address</th>
                    <th>Region</th>
                    <th>Sticky</th>
                    <th>Status</th>
                    <th>Exit IP</th>
                    <th style={{ textAlign: "right" }}>
                      <button
                        className="btn btn-ghost text-xs"
                        disabled={testingAll}
                        onClick={async () => {
                          setTestingAll(true);
                          setTestAll(null);
                          try {
                            setTestAll(await api.post<ProxyTestAll>("/proxies/test-all"));
                            proxies.reload();
                          } catch (e) {
                            setRowError(e);
                          } finally {
                            setTestingAll(false);
                          }
                        }}
                      >
                        {testingAll ? "testing all…" : "test all"}
                      </button>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {proxies.data.map((p) => (
                    <ProxyRow
                      key={p.id}
                      proxy={p}
                      onChange={proxies.reload}
                      onError={setRowError}
                    />
                  ))}
                </tbody>
              </table>
            ) : (
              <Empty>No proxies yet.</Empty>
            )}
          </div>
        </>
      )}
    </>
  );
}

function NewProfile({
  accounts,
  proxies,
  onDone,
}: {
  accounts: Account[];
  proxies: Proxy[];
  onDone: () => void;
}) {
  const [accountId, setAccountId] = useState("");
  const [proxyId, setProxyId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  if (accounts.length === 0) return null;

  return (
    <div className="card p-4">
      <span className="label">Create profile</span>
      <p className="muted mb-3 mt-1 text-sm">
        Only once per account — creating it again would mint a new fingerprint, which is exactly
        the anomaly this system exists to avoid.
      </p>
      <ErrorBox error={error} />
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-48 flex-1">
          <Field label="Account">
            <select value={accountId} onChange={(e) => setAccountId(e.target.value)}>
              <option value="">— pick one —</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.handle} ({a.platform})
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div className="min-w-48 flex-1">
          <Field label="Proxy">
            <select value={proxyId} onChange={(e) => setProxyId(e.target.value)}>
              <option value="">— none (testing only) —</option>
              {proxies.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <button
          className="btn"
          disabled={!accountId || busy}
          onClick={async () => {
            setBusy(true);
            setError(null);
            try {
              await api.post("/profiles", {
                account_id: accountId,
                proxy_id: proxyId || null,
              });
              setAccountId("");
              onDone();
            } catch (e) {
              setError(e);
            } finally {
              setBusy(false);
            }
          }}
        >
          Create
        </button>
      </div>
    </div>
  );
}

function NewProxy({ onDone }: { onDone: () => void }) {
  const [form, setForm] = useState({
    label: "",
    host: "",
    port: 8080,
    username: "",
    password: "",
    region: "",
    kind: "residential",
    scheme: "http",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const set = (k: string, v: string | number) => setForm({ ...form, [k]: v });

  return (
    <div className="card p-4">
      <span className="label">Add proxy</span>
      <p className="muted mb-3 mt-1 text-sm">
        Use sticky residential proxies. Datacenter ones are detected almost every time, and
        rotating ones break the one-account-one-IP rule.
      </p>
      <ErrorBox error={error} />
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Label">
          <input
            value={form.label}
            onChange={(e) => set("label", e.target.value)}
            className="mono text-sm"
          />
        </Field>
        <Field label="Host">
          <input
            value={form.host}
            onChange={(e) => set("host", e.target.value)}
            className="mono text-sm"
          />
        </Field>
        <Field label="Port">
          <input
            value={String(form.port)}
            onChange={(e) => set("port", Number(e.target.value) || 0)}
            className="mono text-sm"
          />
        </Field>
        <Field label="Scheme">
          <select value={form.scheme} onChange={(e) => set("scheme", e.target.value)}>
            <option value="http">http</option>
            <option value="https">https</option>
            <option value="socks5">socks5</option>
          </select>
        </Field>
        <Field label="Username">
          <input
            value={form.username}
            onChange={(e) => set("username", e.target.value)}
            className="mono text-sm"
          />
        </Field>
        <Field label="Password">
          <input
            type="password"
            value={form.password}
            onChange={(e) => set("password", e.target.value)}
            className="mono text-sm"
          />
        </Field>
        <Field label="Region">
          <input
            value={form.region}
            onChange={(e) => set("region", e.target.value)}
            className="mono text-sm"
          />
        </Field>
      </div>
      <div className="mt-3 flex items-center gap-3">
        <select
          value={form.kind}
          onChange={(e) => set("kind", e.target.value)}
          style={{ width: "auto" }}
        >
          <option value="residential">residential</option>
          <option value="mobile">mobile</option>
          <option value="datacenter">datacenter (testing only)</option>
        </select>
        <button
          className="btn"
          disabled={!form.label || !form.host || busy}
          onClick={async () => {
            setBusy(true);
            setError(null);
            try {
              await api.post("/proxies", {
                ...form,
                username: form.username || null,
                password: form.password || null,
                region: form.region || null,
              });
              setForm({ ...form, label: "", host: "", username: "", password: "" });
              onDone();
            } catch (e) {
              setError(e);
            } finally {
              setBusy(false);
            }
          }}
        >
          Add
        </button>
      </div>
    </div>
  );
}
