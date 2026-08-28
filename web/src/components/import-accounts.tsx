"use client";

import { useEffect, useRef, useState } from "react";
import {
  api,
  type ImportReport,
  type ImportResult,
  type Named,
  token,
} from "@/lib/api";
import { ErrorBox, Field } from "@/components/ui";

const BASE = process.env.NEXT_PUBLIC_API ?? "http://127.0.0.1:8000";

/**
 * Nhap tai khoan hang loat tu CSV, hai lua.
 *
 * Lua mot chi KIEM va hien ket qua; khong tao gi ca. Nhap thang mot file 200 dong ma
 * dong 173 hong thi 172 dong da nam trong database va nguoi dung khong biet sua tu dau.
 */
export function ImportAccounts({ onDone }: { onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [workspaces, setWorkspaces] = useState<Named[]>([]);
  const [workspaceId, setWorkspaceId] = useState("");
  const [personas, setPersonas] = useState<Named[]>([]);
  const [personaId, setPersonaId] = useState("");

  const [file, setFile] = useState<File | null>(null);
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
        if (w.length) setWorkspaceId((current) => current || w[0].id);
      })
      .catch(setError);
    api.get<Named[]>("/personas").then(setPersonas).catch(setError);
  }, [open]);

  async function check(picked: File) {
    setFile(picked);
    setResult(null);
    setError(null);
    setBusy(true);
    try {
      setReport(await api.upload<ImportReport>("/accounts/import/check", picked));
    } catch (e) {
      setError(e);
      setReport(null);
    } finally {
      setBusy(false);
    }
  }

  async function run(partial: boolean) {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const query = new URLSearchParams({ workspace_id: workspaceId });
      if (personaId) query.set("persona_id", personaId);
      if (partial) query.set("partial", "true");
      const outcome = await api.upload<ImportResult>(`/accounts/import?${query}`, file);
      setResult(outcome);
      if (outcome.created > 0) onDone();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  /** File mau nam sau token, nen tai bang fetch roi luu bang blob URL. */
  async function downloadTemplate() {
    try {
      const bearer = token.get();
      const res = await fetch(`${BASE}/accounts/import/template`, {
        headers: bearer ? { authorization: `Bearer ${bearer}` } : {},
      });
      const url = URL.createObjectURL(await res.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "accounts-template.csv";
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

  return (
    <div className="card mb-5 p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="label">Import accounts from CSV</span>
        <button
          className="btn btn-ghost text-xs"
          onClick={() => {
            setOpen(false);
            setFile(null);
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

        <Field label="Persona for rows that name none">
          <select value={personaId} onChange={(e) => setPersonaId(e.target.value)}>
            <option value="">— none —</option>
            {personas.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3">
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
        <button className="btn" disabled={busy} onClick={() => input.current?.click()}>
          {file ? "Choose a different file" : "Choose a CSV"}
        </button>
        <button className="btn btn-ghost text-xs" onClick={downloadTemplate}>
          download a template
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
            {report.problems.length > 0 && (
              <span style={{ color: "var(--bad)" }}>
                {report.problems.length} problem{report.problems.length === 1 ? "" : "s"}
              </span>
            )}
          </div>

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
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {needsPersona && !personaId && (
            <div className="card mb-3 p-3 text-sm" style={{ borderLeft: "3px solid var(--bad)" }}>
              Some rows name no persona and none was chosen above. Pick a fallback, or add a
              persona column to the file.
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            <button
              className="btn"
              disabled={busy || report.ready === 0 || (needsPersona && !personaId)}
              onClick={() => run(false)}
            >
              Import {report.ready} account{report.ready === 1 ? "" : "s"}
            </button>
            {report.problems.length > 0 && report.ready > 0 && (
              <button
                className="btn btn-ghost"
                disabled={busy || (needsPersona && !personaId)}
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
          <p className="muted mt-2">
            Each one still needs a profile and a first sign-in by hand before it can post.
          </p>
        </div>
      )}
    </div>
  );
}
