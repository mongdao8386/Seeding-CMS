"use client";

import { useState } from "react";
import { api, qs, type ProxyImportResult } from "@/lib/api";
import { ErrorBox, Field } from "@/components/ui";

const KINDS = ["residential", "mobile", "datacenter"];
const SCHEMES = ["http", "https", "socks5"];

/**
 * Dan mot danh sach proxy vao mot lan.
 *
 * Bat bien cua he thong la mot acc mot proxy, khong dung chung - nen so proxy luon
 * phai bang so tai khoan. Them tung cai qua form la viec on voi hai proxy va vo ly voi
 * bon muoi, dung nhu chuyen da xay ra voi tai khoan truoc khi co phan nhap CSV.
 */
export function ImportProxies({ onDone }: { onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [prefix, setPrefix] = useState("P");
  const [kind, setKind] = useState("residential");
  const [scheme, setScheme] = useState("http");
  const [region, setRegion] = useState("Vietnam");
  const [test, setTest] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<ProxyImportResult | null>(null);

  const lines = text
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith("#")).length;

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("text", text);
      const outcome = await api.postForm<ProxyImportResult>(
        `/proxies/import${qs({ label_prefix: prefix, kind, scheme, region, test })}`,
        form,
      );
      setResult(outcome);
      if (outcome.created > 0) onDone();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button className="btn btn-ghost" onClick={() => setOpen(true)}>
        Paste a proxy list
      </button>
    );
  }

  return (
    <div className="card mb-4 p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="label">Add proxies in bulk</span>
        <button
          className="btn btn-ghost text-xs"
          onClick={() => {
            setOpen(false);
            setResult(null);
          }}
        >
          close
        </button>
      </div>

      <ErrorBox error={error} />

      <span className="label mb-1 block">One proxy per line</span>
      <textarea
        rows={7}
        value={text}
        onChange={(e) => setText(e.target.value)}
        className="mono text-xs"
        spellCheck={false}
        placeholder={
          "1.2.3.4:8080\n" +
          "host.example.com:31159:username:password\n" +
          "username:password@5.6.7.8:9000\n" +
          "socks5://username:password@9.9.9.9:1080"
        }
      />
      <p className="faint mt-1 text-xs">
        Any of those four shapes. Lines starting with <span className="mono">#</span> are ignored.
      </p>

      <div className="mt-3 grid gap-3 sm:grid-cols-4">
        <Field label="Label prefix">
          <input value={prefix} onChange={(e) => setPrefix(e.target.value)} className="mono" />
        </Field>
        <Field label="Kind">
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Scheme when the line has none">
          <select value={scheme} onChange={(e) => setScheme(e.target.value)}>
            {SCHEMES.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Region">
          <input value={region} onChange={(e) => setRegion(e.target.value)} />
        </Field>
      </div>

      <label className="mt-3 flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={test}
          onChange={(e) => setTest(e.target.checked)}
          style={{ width: "auto" }}
        />
        Test each one after adding — a proxy nobody has tried is an unknown, and an unknown
        should not be bound to an account
      </label>

      <button className="btn mt-3" disabled={busy || lines === 0} onClick={run}>
        {busy ? "Working…" : `Add ${lines} prox${lines === 1 ? "y" : "ies"}`}
      </button>

      {result && (
        <div className="mt-4">
          <div
            className="card p-3 text-sm"
            style={{
              borderLeft: `3px solid ${
                result.duplicate_exit_ips.length
                  ? "var(--bad)"
                  : result.created && result.passed === result.tested
                    ? "var(--ok)"
                    : "var(--warn)"
              }`,
            }}
          >
            <p>
              <strong className="tabular-nums">{result.created}</strong> added
              {result.tested > 0 && (
                <>
                  , <strong className="tabular-nums">{result.passed}</strong> of {result.tested}{" "}
                  reachable
                </>
              )}
              {result.skipped.length > 0 && `, ${result.skipped.length} already registered`}.
            </p>

            {result.duplicate_exit_ips.length > 0 && (
              <p className="mt-1" style={{ color: "var(--bad)" }}>
                Two or more came out of the same IP:{" "}
                <span className="mono">{result.duplicate_exit_ips.join(", ")}</span>. That is one
                exit counted as several — accounts bound to them would share an address without
                anyone noticing.
              </p>
            )}
          </div>

          {result.results.some((r) => !r.ok) && (
            <div className="card mt-3 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="label" style={{ borderBottom: "1px solid var(--rule)" }}>
                    <th className="px-3 py-2 text-left font-normal">Label</th>
                    <th className="px-3 py-2 text-left font-normal">Why it failed</th>
                  </tr>
                </thead>
                <tbody>
                  {result.results
                    .filter((r) => !r.ok)
                    .map((r) => (
                      <tr key={r.label} style={{ borderBottom: "1px solid var(--rule)" }}>
                        <td className="mono px-3 py-1.5">{r.label}</td>
                        <td className="px-3 py-1.5">{r.error}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}

          {result.problems.length > 0 && (
            <div className="card mt-3 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="label" style={{ borderBottom: "1px solid var(--rule)" }}>
                    <th className="px-3 py-2 text-left font-normal">Line</th>
                    <th className="px-3 py-2 text-left font-normal">Text</th>
                    <th className="px-3 py-2 text-left font-normal">Problem</th>
                  </tr>
                </thead>
                <tbody>
                  {result.problems.map((p, i) => (
                    <tr key={i} style={{ borderBottom: "1px solid var(--rule)" }}>
                      <td className="mono px-3 py-1.5 tabular-nums">{p.line}</td>
                      <td className="mono px-3 py-1.5">{p.raw}</td>
                      <td className="px-3 py-1.5">{p.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
