"use client";

import { useEffect, useMemo, useState } from "react";
import { api, qs, type Account, type Page } from "@/lib/api";
import { Field, SearchBox } from "@/components/ui";

const PLATFORMS = ["reddit", "threads", "x", "youtube", "instagram", "facebook", "tiktok"];

/**
 * Them mot nhom vao chien dich da co, roi lap lich rieng cho no.
 *
 * Truoc day day la mot popover `absolute` nam trong cot Groups. Cot do rong 300px, con
 * bang nay rong 320px, va the card boc ngoai co `overflow-hidden` de bo goc - nen form
 * bi CAT MAT mot nua va khong dung duoc.
 *
 * Gio no la mot panel toan chieu rong, dat tren ba cot, giong het form tao chien dich.
 * Khong con gi de cat, va co du cho cho danh sach tai khoan.
 */
export function AddGroup({
  campaignId,
  onDone,
  onClose,
  onError,
}: {
  campaignId: string;
  onDone: () => void;
  onClose: () => void;
  onError: (e: unknown) => void;
}) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [name, setName] = useState("");
  const [platform, setPlatform] = useState("threads");
  const [subreddit, setSubreddit] = useState("test");
  const [postKind, setPostKind] = useState<"post" | "comment">("post");
  const [targetUrl, setTargetUrl] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [matching, setMatching] = useState(0);
  const [busy, setBusy] = useState(false);

  // Loc o server. O muc vai tram tai khoan, tai het ve roi loc o day la keo ca danh
  // sach qua mang de hien ra vai dong.
  useEffect(() => {
    const timer = setTimeout(() => {
      api
        .get<Page<Account>>(`/accounts${qs({ platform, q: search, limit: 200 })}`)
        .then((p) => {
          setAccounts(p.items);
          setMatching(p.total);
        })
        .catch(onError);
    }, 200);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [platform, search]);

  // Chi acc san sang: profile + proxy + phien dang nhap. Xem core/readiness.py.
  const candidates = useMemo(
    () => accounts.filter((a) => a.status !== "dead" && a.ready),
    [accounts],
  );
  const blockedCount = accounts.filter((a) => a.status !== "dead" && !a.ready).length;

  return (
    <div className="card mb-4 p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="label">New group</span>
        <button className="btn btn-ghost text-xs" onClick={onClose}>
          close
        </button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
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
          <div className="mb-1 flex items-center gap-2">
            <span className="label">Accounts — {picked.size} picked</span>
            <SearchBox value={search} onChange={setSearch} placeholder="search…" />
          </div>
          {matching > candidates.length && (
            <p className="faint mb-1 text-xs">
              Showing {candidates.length} of {matching} — search to reach the rest.
            </p>
          )}
          {candidates.length === 0 ? (
            <p className="faint text-xs">
              No {platform} account is ready
              {blockedCount > 0 ? ` (${blockedCount} need a proxy or a sign-in)` : ""}.
            </p>
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
              onClose();
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
