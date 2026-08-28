"use client";

import { useEffect, useState } from "react";
import { api, type Named } from "@/lib/api";
import { ErrorBox, Field } from "@/components/ui";

const PLATFORMS = ["reddit", "threads", "x", "youtube", "instagram", "facebook", "tiktok"];

export function NewAccount({ onDone }: { onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [workspaces, setWorkspaces] = useState<Named[]>([]);
  const [personas, setPersonas] = useState<Named[]>([]);

  const [workspaceId, setWorkspaceId] = useState("");
  const [newWorkspace, setNewWorkspace] = useState("");
  const [personaId, setPersonaId] = useState("");
  const [newPersona, setNewPersona] = useState("");
  const [platform, setPlatform] = useState("threads");
  const [handle, setHandle] = useState("");
  const [dailyCap, setDailyCap] = useState(3);

  // Reddit di bang API nen can OAuth; con lai can mat khau de dang nhap tay.
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [password, setPassword] = useState("");
  const [totpSeed, setTotpSeed] = useState("");

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const isReddit = platform === "reddit";

  useEffect(() => {
    if (!open) return;
    api.get<Named[]>("/workspaces").then((w) => {
      setWorkspaces(w);
      if (w.length && !workspaceId) setWorkspaceId(w[0].id);
    });
    api.get<Named[]>("/personas").then(setPersonas);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      // DB trong thi chua co workspace nao - tao luon o day, thay vi bat nguoi dung
      // phai mo /docs goi API cho buoc dau tien.
      let wid = workspaceId;
      if (!wid) {
        if (!newWorkspace.trim()) throw new Error("Name your first workspace");
        const ws = await api.post<{ id: string }>("/workspaces", { name: newWorkspace.trim() });
        wid = ws.id;
        setWorkspaceId(wid);
      }

      let pid = personaId;
      if (!pid) {
        if (!newPersona.trim()) throw new Error("Pick an existing persona or name a new one");
        const created = await api.post<{ id: string }>("/personas", {
          workspace_id: wid,
          name: newPersona.trim(),
        });
        pid = created.id;
      }

      await api.post("/accounts", {
        persona_id: pid,
        platform,
        handle: handle.trim(),
        daily_cap: dailyCap,
        secrets: isReddit
          ? {
              client_id: clientId,
              client_secret: clientSecret,
              username: handle.trim(),
              password,
            }
          : { password, totp_seed: totpSeed },
      });

      setHandle("");
      setPassword("");
      setClientId("");
      setClientSecret("");
      setTotpSeed("");
      setNewPersona("");
      onDone();
      setOpen(false);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button className="btn mb-4" onClick={() => setOpen(true)}>
        Add account
      </button>
    );
  }

  return (
    <div className="card mb-4 p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="label">Add account</span>
        <button className="btn btn-ghost text-xs" onClick={() => setOpen(false)}>
          close
        </button>
      </div>

      <ErrorBox error={error} />

      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Workspace">
          {workspaces.length ? (
            <select value={workspaceId} onChange={(e) => setWorkspaceId(e.target.value)}>
              {workspaces.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          ) : (
            <input
              value={newWorkspace}
              onChange={(e) => setNewWorkspace(e.target.value)}
              placeholder="name your first workspace"
            />
          )}
        </Field>

        <Field label="Existing persona">
          <select
            value={personaId}
            onChange={(e) => setPersonaId(e.target.value)}
            disabled={!!newPersona.trim()}
          >
            <option value="">— create new —</option>
            {personas.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Or name a new persona">
          <input
            value={newPersona}
            onChange={(e) => setNewPersona(e.target.value)}
            placeholder="Hai Yen"
            disabled={!!personaId}
          />
        </Field>

        <Field label="Platform">
          <select value={platform} onChange={(e) => setPlatform(e.target.value)}>
            {PLATFORMS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Handle">
          <input
            value={handle}
            onChange={(e) => setHandle(e.target.value)}
            placeholder="account_name"
            className="mono text-sm"
          />
        </Field>

        <Field label="Daily cap after warm-up">
          <input
            type="number"
            min={1}
            max={50}
            value={dailyCap}
            onChange={(e) => setDailyCap(Number(e.target.value) || 1)}
          />
        </Field>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        {isReddit ? (
          <>
            <Field label="client_id">
              <input
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
                className="mono text-sm"
              />
            </Field>
            <Field label="client_secret">
              <input
                type="password"
                value={clientSecret}
                onChange={(e) => setClientSecret(e.target.value)}
                className="mono text-sm"
              />
            </Field>
            <Field label="Password">
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>
          </>
        ) : (
          <>
            <Field label="Password">
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>
            <Field label="TOTP seed (if 2FA is on)">
              <input
                value={totpSeed}
                onChange={(e) => setTotpSeed(e.target.value)}
                placeholder="JBSWY3DPEHPK3PXP"
                className="mono text-sm"
              />
            </Field>
          </>
        )}
      </div>

      <p className="faint mt-3 text-xs">
        {isReddit
          ? "Create a script-type app at reddit.com/prefs/apps using this same account."
          : "The password and TOTP seed are encrypted before they touch the database, and never read back out through the API."}
      </p>

      <button className="btn mt-3" disabled={!handle.trim() || busy} onClick={save}>
        Add
      </button>
    </div>
  );
}
