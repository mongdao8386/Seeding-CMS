"use client";

import { useState } from "react";
import { api, qs, type Post } from "@/lib/api";
import { Empty, PLATFORM_LABEL, timeAgo, useLoad } from "@/components/ui";

/** Bài đã đăng: link, xoá trên nền tảng, sửa chú thích. Worker làm trong 1–2 phút. */
export function PublishedPosts({ accountId, limit = 60 }: { accountId?: string; limit?: number }) {
  const [showDeleted, setShowDeleted] = useState(false);
  const posts = useLoad(
    () => api.get<Post[]>(`/posts${qs({ account_id: accountId, include_deleted: showDeleted, limit })}`),
    [accountId, showDeleted, limit],
  );
  const [note, setNote] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [caption, setCaption] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  async function act(p: Post, path: "delete" | "edit" | "cancel", body?: unknown) {
    setBusy(p.attempt_id);
    setNote(null);
    try {
      await api.post(`/posts/${p.attempt_id}/${path}`, body);
      setEditing(null);
      posts.reload();
      if (path !== "cancel") setNote("Đã hẹn. Worker làm trong 1–2 phút, xem ở dòng thời gian.");
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  const items = posts.data ?? [];
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <span className="label">Đã đăng</span>
        <label className="flex items-center gap-2 text-xs text-muted">
          <input type="checkbox" checked={showDeleted} onChange={(e) => setShowDeleted(e.target.checked)} />
          hiện cả bài đã xoá
        </label>
      </div>
      {note && <div className="card border-l-[3px] border-accent p-3 text-sm">{note}</div>}
      {posts.error && <div className="text-sm text-bad-text">{posts.error}</div>}
      {items.length === 0 ? (
        <Empty>Chưa có bài nào lên. Bài đăng xong sẽ hiện ở đây, có link và nút xoá.</Empty>
      ) : (
        <div className="card overflow-hidden">
          {items.map((p) => (
            <div key={p.attempt_id} className={"flex flex-col gap-1.5 border-b border-line px-4 py-3 " + (p.deleted_at ? "opacity-60" : "")}>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                <span className="mono font-semibold">{p.handle}</span>
                <span className="text-muted">{PLATFORM_LABEL[p.platform]}</span>
                <span className="text-muted">· {timeAgo(p.posted_at)}</span>
                {p.deleted_at && <span className="pill bg-soft text-muted">đã xoá</span>}
                {p.edited_at && !p.deleted_at && <span className="pill bg-soft text-muted">đã sửa</span>}
                {p.pending && <span className="pill bg-warn-soft text-warn-text">{p.pending === "delete" ? "đang chờ xoá" : "đang chờ sửa"}</span>}
                {p.remote_url && (
                  <a href={p.remote_url} target="_blank" rel="noreferrer" className="text-xs">
                    mở bài
                  </a>
                )}
              </div>
              <div className="truncate text-sm text-muted" title={p.caption}>
                {p.caption}
              </div>
              {!p.deleted_at && (
                <div className="flex flex-wrap items-center gap-2">
                  {p.pending ? (
                    <button className="btn text-xs" disabled={busy === p.attempt_id} onClick={() => act(p, "cancel")}>
                      Huỷ
                    </button>
                  ) : editing === p.attempt_id ? (
                    <div className="flex w-full flex-col gap-2">
                      <textarea value={caption} onChange={(e) => setCaption(e.target.value)} rows={3} className="w-full px-2.5 py-2 text-sm" />
                      <div className="flex gap-2">
                        <button className="btn btn-primary text-xs" disabled={busy === p.attempt_id || !caption.trim()} onClick={() => act(p, "edit", { caption })}>
                          Sửa trên nền tảng
                        </button>
                        <button className="btn text-xs" onClick={() => setEditing(null)}>
                          Thôi
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <button
                        className="btn text-xs"
                        disabled={busy === p.attempt_id || !!p.can_edit}
                        title={p.can_edit ?? ""}
                        onClick={() => {
                          setEditing(p.attempt_id);
                          setCaption(p.caption);
                        }}
                      >
                        Sửa chú thích
                      </button>
                      <button
                        className="btn btn-ghost text-xs text-bad-text"
                        disabled={busy === p.attempt_id || !!p.can_delete}
                        title={p.can_delete ?? ""}
                        onClick={() => {
                          if (!confirm(`Xoá bài này trên ${PLATFORM_LABEL[p.platform]}? Không hoàn tác được.`)) return;
                          act(p, "delete");
                        }}
                      >
                        Xoá trên nền tảng
                      </button>
                      {(p.can_edit || p.can_delete) && <span className="text-xs text-faint">{p.can_delete ?? p.can_edit}</span>}
                    </>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
