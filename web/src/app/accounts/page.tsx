"use client";

import { useState } from "react";
import {
  api,
  qs,
  type Account,
  type Page,
  type Profile,
  type Proxy,
  type ProxyTestAll,
} from "@/lib/api";
import { NewAccount } from "@/components/new-account";
import { ImportAccounts } from "@/components/import-accounts";
import { Devices } from "@/components/devices";
import { ImportProxies } from "@/components/import-proxies";
import { useWorkspace } from "@/components/workspace";
import { ProfileRow } from "@/components/profile-row";
import { AccountRow, ProxyRow } from "@/components/rows";
import {
  Command,
  Empty,
  ErrorBox,
  Field,
  Loading,
  PageHead,
  Pager,
  Platform,
  SearchBox,
  Status,
  useLoad,
  usePaged,
  when,
} from "@/components/ui";

const PLATFORMS = ["reddit", "threads", "x", "youtube", "instagram", "facebook", "tiktok"];
const ACCOUNT_STATUSES = ["new", "warming", "active", "needs_human", "suspended", "dead"];

type Tab = "accounts" | "profiles" | "proxies" | "devices";

export default function Accounts() {
  const [tab, setTab] = useState<Tab>("accounts");
  const [rowError, setRowError] = useState<unknown>(null);
  const [testingAll, setTestingAll] = useState(false);
  const [testAll, setTestAll] = useState<ProxyTestAll | null>(null);
  const workspace = useWorkspace();
  const [platform, setPlatform] = useState("");
  const [status, setStatus] = useState("");

  const accounts = usePaged<Account>("/accounts", ({ limit, offset, q }) =>
    `/accounts${qs({ limit, offset, q, platform, status, workspace_id: workspace.id })}`,
  );
  const profiles = usePaged<Profile>("/profiles", ({ limit, offset, q }) =>
    `/profiles${qs({ limit, offset, q })}`,
  );
  const proxies = usePaged<Proxy>("/proxies", ({ limit, offset, q }) =>
    `/proxies${qs({ limit, offset, q })}`,
  );

  // Ba danh sach duoi day KHONG phan trang - chung la hang doi viec phai lam, va mot
  // hang doi chi hien trang dau thi khong con la hang doi. Server tra ve day du.
  const needProfile = useLoad<Account[]>(() => api.get("/accounts/without-profile"));
  const needLogin = useLoad<Page<Profile>>(() =>
    api.get("/profiles?logged_in=false&limit=500"),
  );
  // Proxy cho o chon trong form: phai la TOAN BO, khong phai trang dang xem.
  const allProxies = useLoad<Page<Proxy>>(() => api.get("/proxies?limit=500"));

  const proxyChoices = allProxies.data?.items ?? [];
  const withoutProfile = needProfile.data ?? [];

  function reloadAll() {
    accounts.reload();
    profiles.reload();
    proxies.reload();
    needProfile.reload();
    needLogin.reload();
    allProxies.reload();
  }

  return (
    <>
      <PageHead
        title="Accounts"
        hint="One account ↔ one profile ↔ one proxy, bound for good and never rotated. Reddit goes through its API, so it needs no profile."
      />

      <ErrorBox
        error={
          rowError ?? accounts.error ?? profiles.error ?? proxies.error ?? needProfile.error
        }
      />

      <div className="mb-5 flex gap-1">
        {(
          [
            ["accounts", `Accounts (${accounts.total})`],
            ["profiles", `Profiles (${profiles.total})`],
            ["proxies", `Proxies (${proxies.total})`],
            ["devices", "Devices"],
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
            <NewAccount onDone={reloadAll} />
            <ImportAccounts onDone={reloadAll} />
          </div>
          {withoutProfile.length > 0 && (
            <div className="card mb-4 p-3" style={{ borderLeft: "3px solid var(--warn)" }}>
              <span className="label" style={{ color: "var(--warn)" }}>
                No profile yet ({withoutProfile.length})
              </span>
              <p className="muted mt-1 text-sm">
                {withoutProfile
                  .slice(0, 12)
                  .map((a) => a.handle)
                  .join(", ")}
                {withoutProfile.length > 12 ? ` and ${withoutProfile.length - 12} more` : ""} — these
                accounts cannot post yet. Create a profile in the next tab.
              </p>
            </div>
          )}

          <div className="mb-3 flex flex-wrap items-center gap-2">
            <SearchBox
              value={accounts.query}
              onChange={accounts.setQuery}
              placeholder="search handle…"
            />
            <select
              value={platform}
              onChange={(e) => {
                setPlatform(e.target.value);
                accounts.resetPage();
              }}
              className="text-sm"
            >
              <option value="">all platforms</option>
              {PLATFORMS.map((x) => (
                <option key={x} value={x}>
                  {x}
                </option>
              ))}
            </select>
            <select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                accounts.resetPage();
              }}
              className="text-sm"
            >
              <option value="">all statuses</option>
              {ACCOUNT_STATUSES.map((x) => (
                <option key={x} value={x}>
                  {x.replace("_", " ")}
                </option>
              ))}
            </select>
            <div className="ml-auto">
              <Pager
                total={accounts.total}
                offset={accounts.offset}
                pageSize={accounts.pageSize}
                onGoto={accounts.goto}
                noun="account"
              />
            </div>
          </div>

          <div className="card overflow-x-auto">
            {accounts.loading && <Loading />}
            {accounts.items.length ? (
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
                  {accounts.items.map((a) => (
                    <AccountRow key={a.id} account={a} onChange={reloadAll} onError={setRowError} />
                  ))}
                </tbody>
              </table>
            ) : (
              !accounts.loading && (
                <Empty>
                  {accounts.query || platform || status
                    ? "Nothing matches those filters."
                    : "No accounts yet."}
                </Empty>
              )
            )}
          </div>
        </>
      )}

      {tab === "profiles" && (
        <>
          <NewProfile accounts={withoutProfile} proxies={proxyChoices} onDone={reloadAll} />

          <div className="mb-3 mt-5 flex flex-wrap items-center gap-2">
            <SearchBox
              value={profiles.query}
              onChange={profiles.setQuery}
              placeholder="search handle…"
            />
            <div className="ml-auto">
              <Pager
                total={profiles.total}
                offset={profiles.offset}
                pageSize={profiles.pageSize}
                onGoto={profiles.goto}
                noun="profile"
              />
            </div>
          </div>

          <div className="card overflow-x-auto">
            {profiles.loading && <Loading />}
            {profiles.items.length ? (
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
                  {profiles.items.map((p) => (
                    <ProfileRow
                      key={p.id}
                      profile={p}
                      proxies={proxyChoices}
                      onChange={reloadAll}
                      onError={setRowError}
                    />
                  ))}
                </tbody>
              </table>
            ) : (
              !profiles.loading && (
                <Empty>
                  {profiles.query ? "Nothing matches that search." : "No profiles yet."}
                </Empty>
              )
            )}
          </div>

          {(needLogin.data?.items.length ?? 0) > 0 && (
            <div className="card mt-4 p-3">
              <span className="label">
                Sign in by hand ({needLogin.data?.total ?? 0})
              </span>
              <p className="muted mb-2 mt-1 text-sm">
                The dashboard cannot open a browser on your machine — run this in a terminal. Do it
                once, then the session is kept for good.
              </p>
              <div className="flex flex-col gap-2">
                {(needLogin.data?.items ?? []).slice(0, 20).map((p) => (
                  <Command key={p.id}>
                    {`.venv/Scripts/python scripts/login_profile.py ${p.platform} ${p.handle}`}
                  </Command>
                ))}
              </div>
              {(needLogin.data?.total ?? 0) > 20 && (
                <p className="faint mt-2 text-xs">
                  Showing 20 of {needLogin.data?.total}. The rest appear as these are done.
                </p>
              )}
            </div>
          )}
        </>
      )}

      {tab === "devices" && (
        <Devices accounts={accounts.items} proxies={proxyChoices} onError={setRowError} />
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
          <div className="mb-4 flex flex-wrap items-start gap-3 [&>div]:w-full">
            <ImportProxies onDone={reloadAll} />
          </div>
          <NewProxy onDone={reloadAll} />

          <div className="mb-3 mt-5 flex flex-wrap items-center gap-2">
            <SearchBox
              value={proxies.query}
              onChange={proxies.setQuery}
              placeholder="search label or host…"
            />
            <div className="ml-auto">
              <Pager
                total={proxies.total}
                offset={proxies.offset}
                pageSize={proxies.pageSize}
                onGoto={proxies.goto}
                noun="proxy"
              />
            </div>
          </div>

          <div className="card overflow-x-auto">
            {proxies.loading && <Loading />}
            {proxies.items.length ? (
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
                  {proxies.items.map((p) => (
                    <ProxyRow key={p.id} proxy={p} onChange={reloadAll} onError={setRowError} />
                  ))}
                </tbody>
              </table>
            ) : (
              !proxies.loading && (
                <Empty>{proxies.query ? "Nothing matches that search." : "No proxies yet."}</Empty>
              )
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
