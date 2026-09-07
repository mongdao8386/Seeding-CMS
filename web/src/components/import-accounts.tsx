"use client";

import { useEffect, useRef, useState } from "react";
import {
  api,
  qs,
  type ImportReport,
  type ImportResult,
  type Named,
  token,
} from "@/lib/api";
import { ErrorBox, Field } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";

const BASE = process.env.NEXT_PUBLIC_API ?? "http://127.0.0.1:8000";

const PLATFORMS = ["facebook", "threads", "x", "instagram", "tiktok", "youtube", "reddit"];

/**
 * Nhap tai khoan hang loat tu CSV, hai lua.
 *
 * Lua mot chi KIEM va hien ket qua; khong tao gi ca. Nhap thang mot file 200 dong ma
 * dong 173 hong thi 172 dong da nam trong database va nguoi dung khong biet sua tu dau.
 */
export function ImportAccounts({ onDone }: { onDone: () => void }) {
  const workspace = useWorkspace();
  const [open, setOpen] = useState(false);
  const [workspaces, setWorkspaces] = useState<Named[]>([]);
  const [workspaceId, setWorkspaceId] = useState("");
  const [personas, setPersonas] = useState<Named[]>([]);
  const [personaId, setPersonaId] = useState("");
  const [newPersona, setNewPersona] = useState("");
  const [platform, setPlatform] = useState("facebook");
  const [attachProxies, setAttachProxies] = useState(true);

  const [file, setFile] = useState<File | null>(null);
  const [pasted, setPasted] = useState("");
  const [report, setReport] = useState<ImportReport | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    api
      .get<Named[]>("/workspaces")
      .then((w) => {
        setWorkspaces(w);
        if (w.length) setWorkspaceId((current) => current || workspace.id || w[0].id);
      })
      .catch(setError);
  }, [open]);

  // Persona phai theo workspace dang chon. Nap tat ca nghia la o chon workspace
  // khong dieu khien gi, va mot dong CSV khong ghi persona se roi vao workspace khac.
  useEffect(() => {
    if (!workspaceId) {
      setPersonas([]);
      return;
    }
    api
      .get<Named[]>(`/personas?workspace_id=${workspaceId}`)
      .then((rows) => {
        setPersonas(rows);
        setPersonaId((current) => (rows.some((x) => x.id === current) ? current : ""));
      })
      .catch(setError);
  }, [workspaceId]);

  /** Nguon du lieu: uu tien o dan, roi moi den file. */
  const source: File | string | null = pasted.trim() ? pasted : file;

  async function check(picked: File | string) {
    if (typeof picked === "string") {
      setFile(null);
    } else {
      setFile(picked);
      setPasted("");
    }
    setResult(null);
    setError(null);
    setBusy(true);
    try {
      setReport(
        await api.upload<ImportReport>(`/accounts/import/check${qs({ platform })}`, picked),
      );
    } catch (e) {
      setError(e);
      setReport(null);
    } finally {
      setBusy(false);
    }
  }

  async function run(partial: boolean) {
    if (!source) return;
    setBusy(true);
    setError(null);
    try {
      // Tao persona moi truoc, neu nguoi dung go ten thay vi chon.
      let fallback = personaId;
      if (newPersona.trim()) {
        const made = await api.post<{ id: string }>("/personas", {
          workspace_id: workspaceId,
          name: newPersona.trim(),
        });
        fallback = made.id;
      }

      const query = new URLSearchParams({ workspace_id: workspaceId, platform });
      if (fallback) query.set("persona_id", fallback);
      if (partial) query.set("partial", "true");
      if (attachProxies) query.set("attach_proxies", "true");
      const outcome = await api.upload<ImportResult>(`/accounts/import?${query}`, source);
      setResult(outcome);
      setNewPersona("");
      if (outcome.created > 0) onDone();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  /** File mau nam sau token, nen tai bang fetch roi luu bang blob URL. */
  async function downloadTemplate(seller: boolean) {
    try {
      const bearer = token.get();
      const res = await fetch(`${BASE}/accounts/import/template${seller ? "?seller=true" : ""}`, {
        headers: bearer ? { authorization: `Bearer ${bearer}` } : {},
      });
      const url = URL.createObjectURL(await res.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = seller ? "accounts-seller.csv" : "accounts-template.csv";
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e);
    }
  }

  if (!open) {
    return (
      <button className="btn btn-ghost" onClick={() => setOpen(true)}>
        Import CSV
      </button>
    );
  }

  const needsPersona = report?.rows.some((r) => !r.persona) ?? false;
  const hasPersona = !!personaId || !!newPersona.trim();

  return (
    <div className="card mb-5 p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="label">Import accounts from CSV</span>
        <button
          className="btn btn-ghost text-xs"
          onClick={() => {
            setOpen(false);
            setFile(null);
            setPasted("");
            setReport(null);
            setResult(null);
          }}
        >
          close
        </button>
      </div>

      <ErrorBox error={error} />

      <div className="card mb-3 p-3 text-sm" style={{ borderLeft: "3px solid var(--warn)" }}>
        A CSV holding passwords is a password file sitting on your disk. Delete it once the import
        is done — the values here are encrypted on the way in, but the file you uploaded is not.
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Workspace">
          <select value={workspaceId} onChange={(e) => setWorkspaceId(e.target.value)}>
            {workspaces.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Platform for rows with no platform column">
          <select value={platform} onChange={(e) => setPlatform(e.target.value)}>
            {PLATFORMS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Persona for rows that name none">
          {/*
            O chon KEM o go ten moi. Workspace moi tinh chua co persona nao, nen neu
            chi co o chon thi man hinh nay la mot ngo cut: no chan viec nhap va khong
            cho duong nao di tiep. Mot rang buoc dung van phai mo loi ra.
          */}
          <select
            value={personaId}
            onChange={(e) => setPersonaId(e.target.value)}
            disabled={!!newPersona.trim()}
          >
            <option value="">{personas.length ? "— none —" : "— no personas yet —"}</option>
            {personas.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <input
            className="mt-1"
            value={newPersona}
            onChange={(e) => setNewPersona(e.target.value)}
            placeholder={personas.length ? "…or name a new one" : "name your first persona"}
          />
        </Field>
      </div>

      <div className="mt-3">
        <span className="label mb-1 block">Paste accounts — one per line</span>
        <textarea
          rows={6}
          value={pasted}
          onChange={(e) => setPasted(e.target.value)}
          onBlur={() => pasted.trim() && check(pasted)}
          className="mono text-xs"
          spellCheck={false}
          placeholder={
            "username|password|hotmail|pass_hotmail|cookie\n" +
            "seed.fb.01|Matkhau123|abc@hotmail.com|Mailpass1|c_user=100012345; xs=41%3Aabc=="
          }
        />
        <p className="faint mt-1 text-xs">
          Keep the header line so the columns are named. Any of <span className="mono">|</span>{" "}
          <span className="mono">;</span> tab or comma works as the separator — it is read from
          the header.
        </p>
        {pasted.trim() && (
          <button className="btn mt-2" disabled={busy} onClick={() => check(pasted)}>
            Check these {pasted.trim().split("\n").length - 1} row(s)
          </button>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <span className="faint text-xs">or</span>
        <input
          ref={input}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={(e) => {
            const picked = e.target.files?.[0];
            if (picked) check(picked);
          }}
        />
        <button className="btn btn-ghost" disabled={busy} onClick={() => input.current?.click()}>
          {file ? "Choose a different file" : "Choose a CSV"}
        </button>
        <button className="btn btn-ghost text-xs" onClick={() => downloadTemplate(false)}>
          full template
        </button>
        <button className="btn btn-ghost text-xs" onClick={() => downloadTemplate(true)}>
          seller format
        </button>
        {file && <span className="mono faint text-xs">{file.name}</span>}
      </div>

      {busy && <p className="faint mt-3 text-sm">Working…</p>}

      {report && !result && (
        <div className="mt-4">
          <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
            <span>
              <strong className="tabular-nums">{report.ready}</strong> row
              {report.ready === 1 ? "" : "s"} ready
            </span>
            {report.with_cookies > 0 && (
              <span style={{ color: "var(--ok)" }}>
                {report.with_cookies} with a usable session — those skip the manual sign-in
              </span>
            )}
            {report.cookie_problems > 0 && (
              <span style={{ color: "var(--warn)" }}>
                {report.cookie_problems} cookie(s) will not work — see the table
              </span>
            )}
            {report.problems.length > 0 && (
              <span style={{ color: "var(--bad)" }}>
                {report.problems.length} problem{report.problems.length === 1 ? "" : "s"}
              </span>
            )}
          </div>

          {report.rejoined_rows > 0 && (
            <div className="card mb-3 p-3 text-sm">
              <span className="label">Separator inside a value</span>
              <p className="muted mt-1">
                {report.rejoined_rows} row(s) had more fields than the header, and the extra text
                was joined back onto the last column. TikTok cookies contain an unencoded{" "}
                <span className="mono">|</span> inside <span className="mono">ttwid</span>, which
                is the same character this file uses to separate columns — without this the cookie
                would arrive cut in half.
              </p>
            </div>
          )}

          {Object.keys(report.renamed_columns ?? {}).length > 0 && (
            <div className="card mb-3 p-3 text-sm">
              <span className="label">Columns read as</span>
              <p className="muted mt-1">
                {Object.entries(report.renamed_columns).map(([from, to]) => (
                  <span key={from} className="mono mr-3">
                    {from} → {to}
                  </span>
                ))}
              </p>
            </div>
          )}

          {report.with_cookies > 0 && (
            <div className="card mb-3 p-3 text-sm" style={{ borderLeft: "3px solid var(--warn)" }}>
              A cookie was issued to one device at one address. Loading it into a fresh profile
              behind a different proxy is exactly the situation platforms use cookies to detect —
              a valid cookie is not the same as a live session. Attach a proxy in the same country
              as the account, and expect some to land in the takeover queue.
            </div>
          )}

          {report.unknown_columns.length > 0 && (
            <div className="card mb-3 p-3 text-sm" style={{ borderLeft: "3px solid var(--warn)" }}>
              Columns nobody recognised, and their values were ignored:{" "}
              <span className="mono">{report.unknown_columns.join(", ")}</span>. A typo in a secret
              column here means those accounts get created with no password, and you find out at
              the first login.
            </div>
          )}

          {report.problems.length > 0 && (
            <div className="card mb-3 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="label" style={{ borderBottom: "1px solid var(--rule)" }}>
                    <th className="px-3 py-2 text-left font-normal">Line</th>
                    <th className="px-3 py-2 text-left font-normal">Handle</th>
                    <th className="px-3 py-2 text-left font-normal">Problem</th>
                  </tr>
                </thead>
                <tbody>
                  {report.problems.map((p, i) => (
                    <tr key={i} style={{ borderBottom: "1px solid var(--rule)" }}>
                      <td className="mono px-3 py-1.5 tabular-nums">{p.line}</td>
                      <td className="mono px-3 py-1.5">{p.handle || "—"}</td>
                      <td className="px-3 py-1.5">{p.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {report.rows.length > 0 && (
            <div className="card mb-3 overflow-x-auto" style={{ maxHeight: 280, overflowY: "auto" }}>
              <table className="w-full text-sm">
                <thead>
                  <tr className="label" style={{ borderBottom: "1px solid var(--rule)" }}>
                    <th className="px-3 py-2 text-left font-normal">Line</th>
                    <th className="px-3 py-2 text-left font-normal">Platform</th>
                    <th className="px-3 py-2 text-left font-normal">Handle</th>
                    <th className="px-3 py-2 text-left font-normal">Persona</th>
                    <th className="px-3 py-2 text-right font-normal">Cap</th>
                    <th className="px-3 py-2 text-left font-normal">Warm-up</th>
                    <th className="px-3 py-2 text-right font-normal">Secrets</th>
                    <th className="px-3 py-2 text-left font-normal">Session</th>
                  </tr>
                </thead>
                <tbody>
                  {report.rows.map((r) => (
                    <tr key={r.line} style={{ borderBottom: "1px solid var(--rule)" }}>
                      <td className="mono px-3 py-1.5 tabular-nums">{r.line}</td>
                      <td className="px-3 py-1.5">
                        <span className="pill pill-b">{r.platform}</span>
                      </td>
                      <td className="mono px-3 py-1.5">{r.handle}</td>
                      <td className="px-3 py-1.5">{r.persona ?? <span className="faint">—</span>}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{r.daily_cap}</td>
                      <td className="px-3 py-1.5">{r.start_warmup ? "yes" : "no"}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{r.secret_count}</td>
                      <td className="px-3 py-1.5" style={{ maxWidth: 320 }}>
                        {!r.has_cookie ? (
                          <span className="faint">no cookie — sign in by hand</span>
                        ) : r.cookie_note ? (
                          <span style={{ color: "var(--warn)", whiteSpace: "normal" }}>
                            {r.cookie_note}
                          </span>
                        ) : (
                          <span style={{ color: "var(--ok)" }}>ready</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {needsPersona && !hasPersona && (
            <div className="card mb-3 p-3 text-sm" style={{ borderLeft: "3px solid var(--bad)" }}>
              None of these rows name a persona, and none was chosen above. Pick one, or type a
              name in the box under the persona picker — accounts have to belong to somebody.
            </div>
          )}

          {report.with_cookies > 0 && (
            <label className="mb-3 flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={attachProxies}
                onChange={(e) => setAttachProxies(e.target.checked)}
                style={{ width: "auto" }}
              />
              Give each new profile a free, tested proxy — one account, one proxy, never shared
            </label>
          )}

          <div className="flex flex-wrap gap-2">
            <button
              className="btn"
              disabled={busy || report.ready === 0 || (needsPersona && !hasPersona)}
              onClick={() => run(false)}
            >
              Import {report.ready} account{report.ready === 1 ? "" : "s"}
            </button>
            {report.problems.length > 0 && report.ready > 0 && (
              <button
                className="btn btn-ghost"
                disabled={busy || (needsPersona && !hasPersona)}
                onClick={() => run(true)}
              >
                Import the good rows, skip the {report.problems.length} broken
              </button>
            )}
          </div>
        </div>
      )}

      {result && (
        <div className="card mt-4 p-3 text-sm" style={{ borderLeft: "3px solid var(--ok)" }}>
          <p>
            <strong className="tabular-nums">{result.created}</strong> account
            {result.created === 1 ? "" : "s"} created
            {result.skipped ? `, ${result.skipped} skipped` : ""}.
          </p>
          {result.detail && <p className="muted mt-1">{result.detail}</p>}
          {result.handles && result.handles.length > 0 && (
            <p className="mono faint mt-2 text-xs">{result.handles.join(", ")}</p>
          )}
          {(result.profiles_with_session ?? 0) > 0 && (
            <p className="muted mt-1">
              {result.profiles_with_session} profile(s) created with a saved session — no manual
              sign-in needed for those.
            </p>
          )}
          {(result.warnings ?? []).length > 0 && (
            <ul className="mt-2 flex flex-col gap-1" style={{ color: "var(--warn)" }}>
              {result.warnings!.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}
          <p className="muted mt-2">
            Accounts with no cookie still need a profile and a first sign-in by hand.
          </p>
        </div>
      )}
    </div>
  );
}
