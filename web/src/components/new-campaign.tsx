"use client";

import { useEffect, useMemo, useState } from "react";
import { api, qs, type Account, type ContentItem, type Named, type Page } from "@/lib/api";
import { ErrorBox, Field, SearchBox } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";

const PLATFORMS = ["reddit", "threads", "x", "youtube", "instagram", "facebook", "tiktok"];

export function NewCampaign({ onDone }: { onDone: (campaignId: string) => void }) {
  const workspace = useWorkspace();
  const [open, setOpen] = useState(false);
  const [workspaces, setWorkspaces] = useState<Named[]>([]);
  const [contents, setContents] = useState<ContentItem[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);

  const [workspaceId, setWorkspaceId] = useState("");
  const [contentId, setContentId] = useState("");
  const [name, setName] = useState("");
  const [platform, setPlatform] = useState("reddit");
  const [subreddit, setSubreddit] = useState("test");
  const [postKind, setPostKind] = useState<"post" | "comment">("post");
  const [targetUrl, setTargetUrl] = useState("");
  const [repeat, setRepeat] = useState<"none" | "daily" | "weekly">("none");
  const [repeatUntil, setRepeatUntil] = useState("");
  const [spreadMinutes, setSpreadMinutes] = useState(60);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [matching, setMatching] = useState(0);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!open) return;
    api.get<Named[]>("/workspaces").then((w) => {
      setWorkspaces(w);
      if (w.length && !workspaceId) setWorkspaceId(workspace.id || w[0].id);
    });
    api.get<Page<ContentItem>>("/content?approved=true&limit=200").then((p) => setContents(p.items));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Loc o SERVER theo nen tang va tu khoa. Tai het ve roi loc bang JavaScript nghia la
  // keo 200 tai khoan qua mang de hien ra 8 cai - va vuot 500 thi im lang mat phan duoi.
  useEffect(() => {
    if (!open) return;
    const timer = setTimeout(() => {
      api
        .get<Page<Account>>(`/accounts${qs({ platform, q: search, limit: 200 })}`)
        .then((p) => {
          setAccounts(p.items);
          setMatching(p.total);
        })
        .catch(setError);
    }, 200);
    return () => clearTimeout(timer);
  }, [open, platform, search]);

  // Acc chet khong dang duoc nua; loc o day thay vi o server de con dem duoc tong so.
  const candidates = useMemo(() => accounts.filter((a) => a.status !== "dead"), [accounts]);

  // Chua san sang thi KHONG cho chon. Truoc day o chon hien het, va truong hop te nhat
  // khong phai la job that bai: profile co ma khong co proxy thi trinh duyet van mo,
  // van dang duoc, chi la di ra bang dia chi nha ban - va moi acc nhu vay deu hien ra
  // tren cung mot IP.
  const usable = useMemo(() => candidates.filter((a) => a.ready), [candidates]);
  const blocked = useMemo(() => candidates.filter((a) => !a.ready), [candidates]);

  const approved = contents;
  const count = picked.size;

  // Cua so qua hep so voi so tai khoan la mau hinh de phat hien nhat.
  const tooTight = count > 1 && spreadMinutes / count < 3;

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const campaign = await api.post<{ id: string }>("/campaigns", {
        workspace_id: workspaceId,
        content_item_id: contentId,
        name: name.trim(),
        stagger_window_seconds: spreadMinutes * 60,
        repeat,
        repeat_until: repeat === "none" || !repeatUntil ? null : new Date(repeatUntil).toISOString(),
        groups: [
          {
            name: `${platform} ${postKind === "comment" ? "comments" : "group"}`,
            platform,
            post_kind: postKind,
            target:
              postKind === "comment"
                ? { url: targetUrl.trim() }
                : platform === "reddit"
                  ? { subreddit: subreddit.trim() }
                  : {},
            account_ids: [...picked],
          },
        ],
      });
      await api.post(`/campaigns/${campaign.id}/plan`);
      setOpen(false);
      setPicked(new Set());
      setName("");
      onDone(campaign.id);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button className="btn mb-5" onClick={() => setOpen(true)}>
        New campaign
      </button>
    );
  }

  return (
    <div className="card mb-5 p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="label">New campaign</span>
        <button className="btn btn-ghost text-xs" onClick={() => setOpen(false)}>
          close
        </button>
      </div>

      <ErrorBox error={error} />

      {approved.length === 0 && (
        <div className="card mb-3 p-3 text-sm" style={{ borderLeft: "3px solid var(--warn)" }}>
          Nothing has been approved yet. Head to Compose to write and approve a post first.
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Campaign name">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Feature launch"
          />
        </Field>

        <Field label="Workspace">
          <select value={workspaceId} onChange={(e) => setWorkspaceId(e.target.value)}>
            {workspaces.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Content (approved only)">
          <select value={contentId} onChange={(e) => setContentId(e.target.value)}>
            <option value="">— pick one —</option>
            {approved.map((c) => (
              <option key={c.id} value={c.id}>
                {c.title_template.slice(0, 60)}
                {c.media_ref ? ` [${c.media_ref}]` : ""}
              </option>
            ))}
          </select>
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

        <Field label="What are these accounts doing?">
          <select
            value={postKind}
            onChange={(e) => setPostKind(e.target.value as "post" | "comment")}
          >
            <option value="post">Posting to their own profile</option>
            <option value="comment">Commenting on someone else&apos;s post</option>
          </select>
        </Field>

        {postKind === "comment" ? (
          <Field label="Post to comment on">
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

        <Field label="Repeat">
          <select
            value={repeat}
            onChange={(e) => setRepeat(e.target.value as "none" | "daily" | "weekly")}
          >
            <option value="none">Run once</option>
            <option value="daily">Every day</option>
            <option value="weekly">Every week</option>
          </select>
        </Field>

        {repeat !== "none" && (
          <Field label="Repeat until (leave blank for no end)">
            <input
              type="date"
              value={repeatUntil}
              onChange={(e) => setRepeatUntil(e.target.value)}
            />
          </Field>
        )}

        <Field label={`Spread over ${spreadMinutes} minutes`}>
          <input
            type="range"
            min={0}
            max={480}
            step={5}
            value={spreadMinutes}
            onChange={(e) => setSpreadMinutes(Number(e.target.value))}
            style={{ padding: 0, border: "none" }}
          />
        </Field>
      </div>

      <div className="mt-4">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span className="label">
            {platform} accounts — {count} of {usable.length} ready selected
          </span>
          <SearchBox value={search} onChange={setSearch} placeholder="search handle…" />
          <button
            className="btn btn-ghost text-xs"
            onClick={() =>
              setPicked(
                picked.size === usable.length ? new Set() : new Set(usable.map((a) => a.id)),
              )
            }
          >
            {picked.size === usable.length && usable.length > 0 ? "clear" : "select all ready"}
          </button>
        </div>

        {matching > candidates.length && (
          <p className="faint mb-2 text-xs">
            Showing {candidates.length} of {matching} — narrow with the search box to reach the rest.
          </p>
        )}

        {candidates.length === 0 ? (
          <p className="faint py-3 text-sm">
            No {platform} accounts yet. Add one on the Accounts screen.
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {usable.map((a) => {
              const on = picked.has(a.id);
              return (
                <button
                  key={a.id}
                  onClick={() => {
                    const next = new Set(picked);
                    on ? next.delete(a.id) : next.add(a.id);
                    setPicked(next);
                  }}
                  className="mono rounded px-2 py-1 text-xs"
                  style={{
                    border: `1px solid ${on ? "var(--a)" : "var(--rule-strong)"}`,
                    background: on ? "var(--a-soft)" : "transparent",
                    color: on ? "var(--a)" : "var(--ink-2)",
                    cursor: "pointer",
                  }}
                >
                  {a.handle}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {blocked.length > 0 && (
        <div className="card mt-3 p-3 text-sm" style={{ borderLeft: "3px solid var(--warn)" }}>
          <span className="label" style={{ color: "var(--warn)" }}>
            {blocked.length} {platform} account{blocked.length === 1 ? "" : "s"} cannot post yet
          </span>
          <ul className="muted mt-1 flex flex-col gap-0.5">
            {blocked.slice(0, 8).map((a) => (
              <li key={a.id}>
                <span className="mono">{a.handle}</span> — {a.blocked_reason}
              </li>
            ))}
          </ul>
          {blocked.length > 8 && (
            <p className="faint mt-1 text-xs">…and {blocked.length - 8} more.</p>
          )}
        </div>
      )}

      {postKind === "comment" && count > 1 && (
        <div className="card mt-3 p-3 text-sm" style={{ borderLeft: "3px solid var(--warn)" }}>
          {count} of your accounts will comment under the same post. Real threads do not collect
          {" "}{count} first-time commenters in one window — keep the spread wide, and consider
          splitting them across several posts instead.
        </div>
      )}

      {repeat !== "none" && !repeatUntil && (
        <div className="card mt-3 p-3 text-sm" style={{ borderLeft: "3px solid var(--warn)" }}>
          With no end date this chain keeps spawning copies until you stop it by hand. Every copy
          costs {count} post{count === 1 ? "" : "s"} against your daily caps.
        </div>
      )}

      {tooTight && (
        <div className="card mt-3 p-3 text-sm" style={{ borderLeft: "3px solid var(--warn)" }}>
          {count} accounts across {spreadMinutes} minutes averages under three minutes between
          posts. A window that tight for this many accounts is an easy pattern to spot — widen it.
        </div>
      )}

      {spreadMinutes === 0 && count > 1 && (
        <div className="card mt-3 p-3 text-sm" style={{ borderLeft: "3px solid var(--bad)" }}>
          A zero-minute spread means every account posts in the same second. That is the single
          most detectable pattern there is.
        </div>
      )}

      <button
        className="btn mt-4"
        disabled={
          !name.trim() ||
          !contentId ||
          count === 0 ||
          busy ||
          (postKind === "comment" && !targetUrl.trim())
        }
        onClick={create}
      >
        Create and schedule {count > 0 ? `(${count} post${count === 1 ? "" : "s"})` : ""}
      </button>
    </div>
  );
}
