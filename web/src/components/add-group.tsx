"use client";

import { useEffect, useMemo, useState } from "react";
import { api, type Account } from "@/lib/api";
import { Field } from "@/components/ui";

const PLATFORMS = ["reddit", "threads", "x", "youtube", "instagram", "facebook", "tiktok"];

/** Them mot nhom vao chien dich da co, roi lap lich rieng cho no. */
export function AddGroup({
  campaignId,
  onDone,
  onError,
}: {
  campaignId: string;
  onDone: () => void;
  onError: (e: unknown) => void;
}) {
  const [open, setOpen] = useState(false);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [name, setName] = useState("");
  const [platform, setPlatform] = useState("threads");
  const [subreddit, setSubreddit] = useState("test");
  const [postKind, setPostKind] = useState<"post" | "comment">("post");
  const [targetUrl, setTargetUrl] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) api.get<Account[]>("/accounts").then(setAccounts).catch(onError);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const candidates = useMemo(
    () => accounts.filter((a) => a.platform === platform && a.status !== "dead"),
    [accounts, platform],
  );

  if (!open) {
    return (
      <button className="btn btn-ghost text-xs" onClick={() => setOpen(true)}>
        add group
      </button>
    );
  }

  return (
    <div
      className="card absolute right-0 z-10 mt-2 w-80 p-3"
      style={{ boxShadow: "0 8px 30px -12px rgba(0,0,0,.5)" }}
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="label">New group</span>
        <button className="btn btn-ghost text-xs" onClick={() => setOpen(false)}>
          close
        </button>
      </div>

      <div className="flex flex-col gap-2">
        <Field label="Name">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="threads side" />
        </Field>

        <Field label="Platform">
          <select
            value={platform}
            onChange={(e) => {
              setPlatform(e.target.value);
              setPicked(new Set());
            }}
          >
            {PLATFORMS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Action">
          <select
            value={postKind}
            onChange={(e) => setPostKind(e.target.value as "post" | "comment")}
          >
            <option value="post">Post to own profile</option>
            <option value="comment">Comment on a post</option>
          </select>
        </Field>

        {postKind === "comment" ? (
          <Field label="Post URL">
            <input
              value={targetUrl}
              onChange={(e) => setTargetUrl(e.target.value)}
              placeholder="https://…"
              className="mono text-sm"
            />
          </Field>
        ) : (
          platform === "reddit" && (
            <Field label="Subreddit">
              <input
                value={subreddit}
                onChange={(e) => setSubreddit(e.target.value)}
                className="mono text-sm"
              />
            </Field>
          )
        )}

        <div>
          <span className="label mb-1 block">
            Accounts — {picked.size} of {candidates.length}
          </span>
          {candidates.length === 0 ? (
            <p className="faint text-xs">No {platform} accounts.</p>
          ) : (
            <div className="flex flex-wrap gap-1" style={{ maxHeight: 120, overflowY: "auto" }}>
              {candidates.map((a) => {
                const on = picked.has(a.id);
                return (
                  <button
                    key={a.id}
                    className="mono rounded px-2 py-1 text-xs"
                    style={{
                      border: `1px solid ${on ? "var(--a)" : "var(--rule-strong)"}`,
                      background: on ? "var(--a-soft)" : "transparent",
                      color: on ? "var(--a)" : "var(--ink-2)",
                      cursor: "pointer",
                    }}
                    onClick={() => {
                      const next = new Set(picked);
                      on ? next.delete(a.id) : next.add(a.id);
                      setPicked(next);
                    }}
                  >
                    {a.handle}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <button
          className="btn"
          disabled={
            !name.trim() ||
            picked.size === 0 ||
            busy ||
            (postKind === "comment" && !targetUrl.trim())
          }
          onClick={async () => {
            setBusy(true);
            try {
              await api.post(`/campaigns/${campaignId}/groups`, {
                name: name.trim(),
                platform,
                post_kind: postKind,
                target:
                  postKind === "comment"
                    ? { url: targetUrl.trim() }
                    : platform === "reddit"
                      ? { subreddit: subreddit.trim() }
                      : {},
                account_ids: [...picked],
              });
              setOpen(false);
              setName("");
              setPicked(new Set());
              onDone();
            } catch (e) {
              onError(e);
            } finally {
              setBusy(false);
            }
          }}
        >
          Add and schedule
        </button>
      </div>
    </div>
  );
}
