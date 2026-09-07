"use client";

import { useEffect, useState } from "react";
import { api, type HashtagSet, type Named } from "@/lib/api";
import {
  ConfirmButton,
  Empty,
  ErrorBox,
  Field,
  Loading,
  PageHead,
  useLoad,
} from "@/components/ui";

const PLATFORMS = ["reddit", "threads", "x", "youtube", "instagram", "facebook", "tiktok"];

export default function Hashtags() {
  const sets = useLoad<HashtagSet[]>(() => api.get("/hashtag-sets"));
  const workspaces = useLoad<Named[]>(() => api.get("/workspaces"));
  const [workspaceId, setWorkspaceId] = useState("");
  const [error, setError] = useState<unknown>(null);

  const [name, setName] = useState("");
  const [platform, setPlatform] = useState("");
  const [raw, setRaw] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!workspaceId && workspaces.data?.length) setWorkspaceId(workspaces.data[0].id);
  }, [workspaces.data, workspaceId]);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      await api.post("/hashtag-sets", {
        workspace_id: workspaceId,
        name: name.trim(),
        platform: platform || null,
        tags: splitTags(raw),
      });
      setName("");
      setRaw("");
      sets.reload();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHead
        title="Hashtag pools"
        hint="A pool you draw from, not a fixed block you paste. Ten accounts wearing the identical tag string is the same duplicate footprint as identical text — so each account draws its own handful."
      />

      <ErrorBox error={error ?? sets.error} />

      <div className="card mb-6 p-4">
        <span className="label">New pool</span>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <Field label="Workspace">
            <select value={workspaceId} onChange={(e) => setWorkspaceId(e.target.value)}>
              {(workspaces.data ?? []).map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Name (letters, digits, - and _)">
            <input
              value={name}
              onChange={(e) => setName(e.target.value.replace(/[^A-Za-z0-9_-]/g, ""))}
              placeholder="ẩm thực"
              className="mono text-sm"
            />
          </Field>
          <Field label="Platform (optional)">
            <select value={platform} onChange={(e) => setPlatform(e.target.value)}>
              <option value="">any platform</option>
              {PLATFORMS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <div className="mt-3">
          <Field label="Tags — separate with spaces, commas or new lines">
            <textarea
              rows={3}
              value={raw}
              onChange={(e) => setRaw(e.target.value)}
              placeholder="#ănngon #sàigòn #reviewquán #đồăn #foodtour"
              className="mono text-sm"
            />
          </Field>
          <p className="faint mt-1 text-xs">
            {splitTags(raw).length} tag{splitTags(raw).length === 1 ? "" : "s"} — the more you add,
            the harder it is for two accounts to draw the same set.
          </p>
        </div>

        <button
          className="btn mt-3"
          disabled={!name.trim() || splitTags(raw).length === 0 || !workspaceId || busy}
          onClick={create}
        >
          Create pool
        </button>
      </div>

      {sets.loading && <Loading />}
      {sets.data?.length === 0 && !sets.loading && (
        <div className="card">
          <Empty>No pools yet.</Empty>
        </div>
      )}

      <div className="flex flex-col gap-4">
        {(sets.data ?? []).map((set) => (
          <PoolCard key={set.id} set={set} onChange={sets.reload} onError={setError} />
        ))}
      </div>
    </>
  );
}

function PoolCard({
  set,
  onChange,
  onError,
}: {
  set: HashtagSet;
  onChange: () => void;
  onError: (e: unknown) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [raw, setRaw] = useState(set.tags.join(" "));
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);

  const count = splitTags(raw).length;
  // P(n, 3): so to hop co thu tu khi rut 3 the.
  const draws = count >= 3 ? count * (count - 1) * (count - 2) : 0;

  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="mono text-base font-semibold">{set.name}</span>
        {set.platform ? (
          <span className="pill pill-b">{set.platform}</span>
        ) : (
          <span className="pill pill-n">any platform</span>
        )}
        <span className="faint text-xs">
          {set.tags.length} tags
          {draws > 0 && ` · ${draws.toLocaleString("en-GB")} ways to draw 3`}
        </span>

        <div className="ml-auto flex items-center gap-2">
          <button
            className="btn btn-ghost text-xs"
            onClick={() => {
              navigator.clipboard.writeText(set.placeholder);
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            }}
          >
            {copied ? "copied" : set.placeholder}
          </button>
          <button className="btn btn-ghost text-xs" onClick={() => setEditing(!editing)}>
            {editing ? "cancel" : "edit"}
          </button>
          <ConfirmButton
            onConfirm={async () => {
              try {
                const result = await api.del<{ detail: string }>(`/hashtag-sets/${set.id}`);
                if (result.detail?.includes("still reference")) onError(new Error(result.detail));
                onChange();
              } catch (e) {
                onError(e);
              }
            }}
          >
            delete
          </ConfirmButton>
        </div>
      </div>

      {editing ? (
        <div className="mt-3">
          <textarea
            rows={3}
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
            className="mono text-sm"
          />
          <button
            className="btn mt-2"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await api.patch(`/hashtag-sets/${set.id}`, { tags: splitTags(raw) });
                setEditing(false);
                onChange();
              } catch (e) {
                onError(e);
              } finally {
                setBusy(false);
              }
            }}
          >
            Save {count} tags
          </button>
        </div>
      ) : (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {set.tags.map((tag) => (
            <span key={tag} className="pill pill-n mono" style={{ textTransform: "none" }}>
              {tag}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function splitTags(raw: string): string[] {
  return raw
    .split(/[\s,\n]+/)
    .map((t) => t.trim())
    .filter(Boolean);
}
