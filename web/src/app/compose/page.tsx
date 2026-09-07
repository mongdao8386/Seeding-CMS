"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  api,
  qs,
  type ContentItem,
  type HashtagSet,
  type MediaAsset,
  type Named,
  type Preview,
} from "@/lib/api";
import {
  AuthedImage,
  ConfirmButton,
  Empty,
  ErrorBox,
  Field,
  PageHead,
  Pager,
  SearchBox,
  humanDuration,
  useLoad,
  usePaged,
  when,
} from "@/components/ui";
import { useWorkspace } from "@/components/workspace";

const SAMPLE_TITLE = "{Just tried|Been testing|Gave a spin to} a {scheduling|posting} tool";
const SAMPLE_BODY =
  "{I've|I have} been {using|running} it for {a few days|a week} now and {it's solid|it holds up}. {Anyone else?|Has anyone tried it?}";

export default function Compose() {
  const workspace = useWorkspace();
  const [title, setTitle] = useState(SAMPLE_TITLE);
  const [body, setBody] = useState(SAMPLE_BODY);
  const [mediaRef, setMediaRef] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [count, setCount] = useState(5);
  const [editingId, setEditingId] = useState<string | null>(null);

  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);

  const workspaces = useLoad<Named[]>(() => api.get("/workspaces"));
  const items = usePaged<ContentItem>("/content", ({ limit, offset, q }) =>
    `/content${qs({ limit, offset, q })}`,
  );
  const media = useLoad<MediaAsset[]>(() => api.get("/media"));
  const pools = useLoad<HashtagSet[]>(() => api.get("/hashtag-sets"));
  const [workspaceId, setWorkspaceId] = useState("");

  const bodyRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!workspaceId && workspaces.data?.length) setWorkspaceId(workspaces.data[0].id);
  }, [workspaces.data, workspaceId]);

  // Xem truoc co do tre de khong goi API sau moi phim go.
  useEffect(() => {
    if (!title.trim()) {
      setPreview(null);
      return;
    }
    const timer = setTimeout(() => {
      api
        .post<Preview>("/content/preview", {
          title_template: title,
          body_template: body,
          account_count: count,
          workspace_id: workspaceId || null,
        })
        .then((p) => (setPreview(p), setError(null)))
        .catch(setError);
    }, 350);
    return () => clearTimeout(timer);
  }, [title, body, count, workspaceId]);

  /**
   * Tai file len roi gan LUON vao bai dang.
   *
   * Truoc day phai sang man hinh Media tai len, quay lai Compose, roi tim trong o
   * chon. Ba buoc cho mot viec, va o chon thi cang dai ra sau moi lan tai.
   *
   * Van la cung mot kho media chu khong phai kho rieng: file van hien o man hinh
   * Media, van bi kiem tra truoc khi xoa, van duoc render lai rieng cho tung tai
   * khoan luc dang. Chi bo di quang duong di lai.
   */
  async function uploadAndAttach(files: FileList | File[] | null) {
    const list = files ? Array.from(files) : [];
    const file = list[0];
    if (!file || !workspaceId) return;

    // Mot bai mot file. Tha ba file vao thi lay cai dau va noi ro, thay vi im lang
    // bo hai cai kia.
    setUploading(true);
    setError(null);
    try {
      const asset = await api.upload<MediaAsset>(`/media?workspace_id=${workspaceId}`, file);
      setMediaRef(asset.filename);
      await media.reload();
      if (list.length > 1) {
        setError(
          new Error(
            `Attached ${file.name}. A post carries one file, so the other ${list.length - 1} ` +
              "were not uploaded — put them in the Media library if you need them.",
          ),
        );
      }
    } catch (e) {
      setError(e);
    } finally {
      setUploading(false);
      setDragging(false);
    }
  }

  const chosenMedia = useMemo(
    () => (media.data ?? []).find((m) => m.filename === mediaRef) ?? null,
    [media.data, mediaRef],
  );

  /** Chen cho danh hashtag ngay tai vi tri con tro trong o than bai. */
  function insertPlaceholder(placeholder: string) {
    const el = bodyRef.current;
    if (!el) {
      setBody(`${body} ${placeholder}`.trim());
      return;
    }
    const start = el.selectionStart ?? body.length;
    const end = el.selectionEnd ?? body.length;

    // Them khoang trang khi can. Thieu buoc nay thi the dinh lien vao chu ben canh
    // va bai len thanh "#saasI've been..." - nhin la biet may sinh ra.
    const before = body.slice(0, start);
    const after = body.slice(end);
    const lead = before && !/\s$/.test(before) ? " " : "";
    const trail = after && !/^\s/.test(after) ? " " : "";

    const insert = `${lead}${placeholder}${trail}`;
    setBody(`${before}${insert}${after}`);

    const caret = start + insert.length;
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(caret, caret);
    });
  }

  function reset() {
    setEditingId(null);
    setTitle(SAMPLE_TITLE);
    setBody(SAMPLE_BODY);
    setMediaRef(null);
    setSaved(null);
  }

  async function save(approve: boolean) {
    setSaving(true);
    setSaved(null);
    setError(null);
    try {
      if (editingId) {
        await api.patch(`/content/${editingId}`, {
          title_template: title,
          body_template: body,
          media_ref: mediaRef,
          approved: approve,
        });
        setSaved(approve ? "Updated and approved." : "Updated.");
      } else {
        const created = await api.post<ContentItem>("/content", {
          workspace_id: workspaceId,
          title_template: title,
          body_template: body,
          media_ref: mediaRef,
        });
        if (approve) await api.post(`/content/${created.id}/approve`);
        setSaved(approve ? "Saved and approved." : "Saved as draft.");
        setEditingId(created.id);
      }
      items.reload();
      media.reload();
    } catch (e) {
      setError(e);
    } finally {
      setSaving(false);
    }
  }

  const risky = preview && preview.collision_risk > 0.2;

  return (
    <>
      <PageHead
        title="Compose"
        hint="Every account gets its own variant. The number of combinations your template can produce is the number that matters — two accounts posting the same text is the clearest spam signal there is."
      />

      <ErrorBox error={error ?? workspaces.error} />

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="flex flex-col gap-4">
          {editingId && (
            <div className="card p-3 text-sm" style={{ borderLeft: "3px solid var(--a)" }}>
              Editing saved content.{" "}
              <button className="underline" style={{ color: "var(--a)" }} onClick={reset}>
                start a new one instead
              </button>
            </div>
          )}

          <Field label={"Title — {a|b|c} syntax"}>
            <textarea
              rows={3}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="mono text-sm"
              placeholder="{Chào|Xin chào} mọi người, {mình|em} vừa tìm được {chỗ này|quán này}"
            />
          </Field>

          <Field label="Body">
            <textarea
              ref={bodyRef}
              rows={5}
              value={body}
              onChange={(e) => setBody(e.target.value)}
              className="mono text-sm"
              placeholder={
                "{Ăn ở đây|Ghé đây} {mấy lần rồi|hôm qua}, {ngon thật|ổn áp phết}. " +
                "{Ai quan tâm thì|Bạn nào cần thì} nhắn mình nhé.\n\n[[tags:ẩm thực:3]]"
              }
            />
          </Field>

          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="label">Hashtag pools — click to insert</span>
              <Link href="/hashtags" className="label hover:opacity-70" style={{ color: "var(--a)" }}>
                manage
              </Link>
            </div>
            {pools.data?.length ? (
              <div className="flex flex-wrap gap-1.5">
                {pools.data.map((p) => (
                  <button
                    key={p.id}
                    className="mono rounded px-2 py-1 text-xs"
                    style={{
                      border: "1px solid var(--rule-strong)",
                      background: "transparent",
                      color: "var(--ink-2)",
                      cursor: "pointer",
                    }}
                    title={p.tags.slice(0, 8).join(" ")}
                    onClick={() => insertPlaceholder(p.placeholder)}
                  >
                    {p.name} ({p.tags.length})
                  </button>
                ))}
              </div>
            ) : (
              <p className="faint text-xs">
                No pools yet. <Link href="/hashtags" className="underline">Create one</Link> — a
                pool of 20 tags drawn 3 at a time gives 6,840 combinations, far more than spintax
                branches.
              </p>
            )}
          </div>

          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="label">Media</span>
              <Link href="/media" className="label hover:opacity-70" style={{ color: "var(--a)" }}>
                library
              </Link>
            </div>

            {chosenMedia ? (
              <div className="card flex items-center gap-3 p-2">
                {chosenMedia.has_thumbnail && (
                  <AuthedImage
                    path={`/media/${chosenMedia.id}/thumb`}
                    alt={chosenMedia.original_name}
                    style={{ width: 96, height: 54, objectFit: "cover", borderRadius: 3 }}
                  />
                )}
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{chosenMedia.original_name}</p>
                  <p className="faint mono text-xs">
                    {chosenMedia.kind}
                    {chosenMedia.width ? ` · ${chosenMedia.width}×${chosenMedia.height}` : ""}
                    {chosenMedia.duration_seconds
                      ? ` · ${humanDuration(chosenMedia.duration_seconds)}`
                      : ""}
                  </p>
                </div>
                <button className="btn btn-ghost text-xs" onClick={() => setMediaRef(null)}>
                  remove
                </button>
              </div>
            ) : (
              <>
                <label
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragging(true);
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    uploadAndAttach(e.dataTransfer.files);
                  }}
                  className="flex cursor-pointer flex-col items-center justify-center rounded p-5 text-center"
                  style={{
                    border: `1px dashed ${dragging ? "var(--a)" : "var(--rule-strong)"}`,
                    background: dragging ? "var(--a-soft)" : "transparent",
                  }}
                >
                  <input
                    type="file"
                    accept="image/*,video/*"
                    className="hidden"
                    disabled={uploading || !workspaceId}
                    onChange={(e) => uploadAndAttach(e.target.files)}
                  />
                  <span className="text-sm">
                    {uploading
                      ? "Uploading…"
                      : dragging
                        ? "Drop to attach"
                        : "Drop an image or video here, or click to pick one"}
                  </span>
                  <span className="faint mt-1 text-xs">
                    It goes into the Media library and attaches to this post in one step.
                  </span>
                </label>

                {(media.data?.length ?? 0) > 0 && (
                  <div className="mt-2">
                    <span className="label">or reuse something already uploaded</span>
                    <select
                      className="mt-1"
                      value=""
                      onChange={(e) => setMediaRef(e.target.value || null)}
                    >
                      <option value="">— no media —</option>
                      {(media.data ?? []).map((m) => (
                        <option key={m.id} value={m.filename}>
                          {m.original_name} ({m.kind})
                        </option>
                      ))}
                    </select>
                  </div>
                )}
              </>
            )}
            <p className="faint mt-1 text-xs">
              Instagram and TikTok refuse text-only posts.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Workspace">
              <select
                value={workspaceId}
                onChange={(e) => setWorkspaceId(e.target.value)}
                disabled={!!editingId}
              >
                {(workspaces.data ?? []).map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={`Preview for ${count} account${count > 1 ? "s" : ""}`}>
              <input
                type="range"
                min={1}
                max={100}
                value={count}
                onChange={(e) => setCount(Number(e.target.value))}
                style={{ padding: 0, border: "none" }}
              />
            </Field>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button className="btn" disabled={saving || !workspaceId} onClick={() => save(true)}>
              {editingId ? "Update and approve" : "Save and approve"}
            </button>
            <button
              className="btn btn-ghost"
              disabled={saving || !workspaceId}
              onClick={() => save(false)}
            >
              {editingId ? "Update" : "Save draft"}
            </button>
            {saved && (
              <span className="text-sm" style={{ color: "var(--ok)" }}>
                {saved}
              </span>
            )}
          </div>
        </div>

        <div>
          {preview && (
            <>
              <div className="mb-3 grid grid-cols-3 gap-3">
                <Metric label="Combinations" value={preview.combinations.toLocaleString("en-GB")} />
                <Metric
                  label="From hashtags"
                  value={
                    preview.hashtag_combinations > 1
                      ? `×${preview.hashtag_combinations.toLocaleString("en-GB")}`
                      : "—"
                  }
                />
                <Metric
                  label="Collision risk"
                  value={`${Math.round(preview.collision_risk * 100)}%`}
                  alert={!!risky}
                />
              </div>

              {preview.warning && (
                <div
                  className="card mb-3 p-3 text-sm"
                  style={{
                    borderLeft: `3px solid ${
                      preview.unknown_pools.length ? "var(--bad)" : "var(--warn)"
                    }`,
                  }}
                >
                  {preview.warning}
                </div>
              )}

              <span className="label mb-2 block">
                What each account will actually post
              </span>
              <div className="flex flex-col gap-3">
                {preview.samples.map((s, i) => (
                  <div key={i} className="card overflow-hidden">
                    {chosenMedia?.has_thumbnail && (
                      <AuthedImage
                        path={`/media/${chosenMedia.id}/thumb`}
                        alt=""
                        style={{
                          width: "100%",
                          maxHeight: 160,
                          objectFit: "cover",
                          display: "block",
                        }}
                      />
                    )}
                    <div className="p-3">
                      <div className="flex items-baseline gap-2">
                        <span className="label shrink-0">acc {i + 1}</span>
                        <span className="text-sm font-medium">{s.title}</span>
                      </div>
                      {s.body && (
                        <p className="muted mt-1 whitespace-pre-wrap text-sm">{s.body}</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>

              <p className="faint mt-2 text-xs">
                These samples use a placeholder seed; the real combinations depend on the campaign
                id, so they will differ. The combination count and collision risk are exact. Each
                account also gets its own re-rendered copy of the media file.
              </p>
            </>
          )}
        </div>
      </div>

      <div className="mb-3 mt-10 flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold">Saved content</h2>
        <SearchBox value={items.query} onChange={items.setQuery} placeholder="search text…" />
        <div className="ml-auto">
          <Pager
            total={items.total}
            offset={items.offset}
            pageSize={items.pageSize}
            onGoto={items.goto}
            noun="item"
          />
        </div>
      </div>
      <div className="card overflow-x-auto">
        {items.items.length ? (
          <table className="grid">
            <thead>
              <tr>
                <th>Title</th>
                <th>Media</th>
                <th>Status</th>
                <th>Created</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.items.map((c: ContentItem) => (
                <tr key={c.id}>
                  <td className="mono max-w-md truncate text-xs">{c.title_template}</td>
                  <td className="mono text-xs">{c.media_ref ?? "—"}</td>
                  <td>
                    <span className={`pill ${c.approved ? "pill-ok" : "pill-warn"}`}>
                      {c.approved ? "approved" : "draft"}
                    </span>
                  </td>
                  <td className="mono whitespace-nowrap text-xs">{when(c.created_at)}</td>
                  <td>
                    <div className="flex justify-end gap-2">
                      <button
                        className="btn btn-ghost text-xs"
                        onClick={() => {
                          setEditingId(c.id);
                          setTitle(c.title_template);
                          setBody(c.body_template);
                          setMediaRef(c.media_ref);
                          setSaved(null);
                          window.scrollTo({ top: 0, behavior: "smooth" });
                        }}
                      >
                        edit
                      </button>
                      <ConfirmButton
                        onConfirm={async () => {
                          try {
                            await api.del(`/content/${c.id}`);
                            if (editingId === c.id) reset();
                            items.reload();
                          } catch (e) {
                            setError(e);
                          }
                        }}
                      >
                        delete
                      </ConfirmButton>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>Nothing saved yet.</Empty>
        )}
      </div>
    </>
  );
}

function Metric({ label, value, alert }: { label: string; value: string; alert?: boolean }) {
  return (
    <div className="card p-2.5">
      <div className="label">{label}</div>
      <div
        className="mono mt-0.5 text-lg font-semibold tabular-nums"
        style={{ color: alert ? "var(--b)" : undefined }}
      >
        {value}
      </div>
    </div>
  );
}
