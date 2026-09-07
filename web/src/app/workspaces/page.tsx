"use client";

import { useState } from "react";
import { api, type WorkspaceDetail } from "@/lib/api";
import { ConfirmButton, Empty, ErrorBox, Loading, PageHead, useLoad } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";

export default function Workspaces() {
  const rows = useLoad<WorkspaceDetail[]>(() => api.get("/workspaces/detail"));
  const workspace = useWorkspace();
  const [error, setError] = useState<unknown>(null);
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);

  function refresh() {
    rows.reload();
    workspace.reload();
  }

  async function create() {
    if (!newName.trim()) return;
    setBusy(true);
    try {
      await api.post("/workspaces", { name: newName.trim() });
      setNewName("");
      refresh();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  const empties = (rows.data ?? []).filter(
    (w) => w.personas === 0 && w.accounts === 0 && w.campaigns === 0 && w.content === 0,
  );

  return (
    <>
      <PageHead
        title="Workspaces"
        hint="A workspace holds personas, and personas hold accounts. Campaigns, content and hashtag pools belong to one too. Proxies and devices are shared across all of them — they are infrastructure, not content."
      />

      <ErrorBox error={error ?? rows.error} />
      {rows.loading && <Loading />}

      <div className="card mb-4 flex flex-wrap items-end gap-3 p-3">
        <div className="flex-1" style={{ minWidth: 220 }}>
          <span className="label mb-1 block">New workspace</span>
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && create()}
            placeholder="Chiến dịch tháng 9"
          />
        </div>
        <button className="btn" disabled={!newName.trim() || busy} onClick={create}>
          Create
        </button>
      </div>

      {empties.length > 1 && (
        <div className="card mb-4 p-3 text-sm" style={{ borderLeft: "3px solid var(--warn)" }}>
          {empties.length} workspaces are completely empty. Older versions of the test suite left
          one behind on every run — they are safe to delete, and deleting them makes the picker in
          the header usable again.
        </div>
      )}

      <div className="card overflow-x-auto">
        {rows.data?.length ? (
          <table className="grid">
            <thead>
              <tr>
                <th>Name</th>
                <th style={{ textAlign: "right" }}>Personas</th>
                <th style={{ textAlign: "right" }}>Accounts</th>
                <th style={{ textAlign: "right" }}>Campaigns</th>
                <th style={{ textAlign: "right" }}>Content</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.data.map((w) => (
                <Row key={w.id} workspace={w} onChanged={refresh} onError={setError} />
              ))}
            </tbody>
          </table>
        ) : (
          !rows.loading && <Empty>No workspaces yet.</Empty>
        )}
      </div>
    </>
  );
}

function Row({
  workspace: w,
  onChanged,
  onError,
}: {
  workspace: WorkspaceDetail;
  onChanged: () => void;
  onError: (e: unknown) => void;
}) {
  const current = useWorkspace();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(w.name);
  const [busy, setBusy] = useState(false);

  const empty = w.personas === 0 && w.accounts === 0 && w.campaigns === 0 && w.content === 0;
  const holdsWork = w.accounts > 0 || w.campaigns > 0;

  async function save() {
    setBusy(true);
    try {
      await api.patch(`/workspaces/${w.id}`, { name: name.trim() });
      setEditing(false);
      onChanged();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }

  async function remove(force: boolean) {
    setBusy(true);
    try {
      await api.del(`/workspaces/${w.id}${force ? "?force=true" : ""}`);
      onChanged();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <tr>
      <td>
        {editing ? (
          <input
            value={name}
            autoFocus
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") save();
              if (e.key === "Escape") {
                setName(w.name);
                setEditing(false);
              }
            }}
            style={{ maxWidth: 260 }}
          />
        ) : (
          <span className="text-sm">
            {w.name}
            {w.id === current.id && <span className="pill pill-a ml-2">selected</span>}
          </span>
        )}
      </td>
      <td className="tabular-nums" style={{ textAlign: "right" }}>
        {w.personas}
      </td>
      <td className="tabular-nums" style={{ textAlign: "right" }}>
        {w.accounts}
      </td>
      <td className="tabular-nums" style={{ textAlign: "right" }}>
        {w.campaigns}
      </td>
      <td className="tabular-nums" style={{ textAlign: "right" }}>
        {w.content}
      </td>
      <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
        {editing ? (
          <>
            <button className="btn text-xs" disabled={busy || !name.trim()} onClick={save}>
              save
            </button>
            <button
              className="btn btn-ghost ml-2 text-xs"
              onClick={() => {
                setName(w.name);
                setEditing(false);
              }}
            >
              cancel
            </button>
          </>
        ) : (
          <>
            <button className="btn btn-ghost text-xs" onClick={() => setEditing(true)}>
              rename
            </button>
            <span className="ml-2">
              <ConfirmButton onConfirm={() => remove(holdsWork)}>
                {empty ? "delete" : "delete everything"}
              </ConfirmButton>
            </span>
          </>
        )}
      </td>
    </tr>
  );
}
