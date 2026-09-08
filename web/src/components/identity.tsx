"use client";

import { useState } from "react";
import { api, BASE_URL, token, type Identity, type Media } from "@/lib/api";
import { useLoad } from "@/components/ui";

/** Đổi tên / username / ảnh đại diện. Worker làm trong vài phút, kết quả lên dòng thời gian. */
export function IdentityCard({ accountId, onChanged }: { accountId: string; onChanged: () => void }) {
  const info = useLoad(() => api.get<Identity>(`/accounts/${accountId}/identity`), [accountId]);
  const media = useLoad(() => api.get<Media[]>("/media"), []);
  const [username, setUsername] = useState("");
  const [name, setName] = useState("");
  const [avatar, setAvatar] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const d = info.data;
  const images = (media.data ?? []).filter((m) => m.kind === "image" && m.has_thumbnail);
  const t = token.get();

  async function submit() {
    setBusy(true);
    setNote(null);
    try {
      await api.post(`/accounts/${accountId}/identity`, {
        username: username || null,
        display_name: name || null,
        avatar_media_id: avatar,
      });
      setUsername("");
      setName("");
      setAvatar(null);
      info.reload();
      onChanged();
      setNote("Đã hẹn. Worker đổi trong vài phút, xem ở dòng thời gian.");
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    setBusy(true);
    try {
      await api.del(`/accounts/${accountId}/identity`);
      info.reload();
      onChanged();
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!d) return null;
  const canUsername = !d.next_username_change_at || new Date(d.next_username_change_at) <= new Date();

  return (
    <section className="card flex flex-col gap-3 p-5">
      <span className="label">Đổi danh tính</span>
      {!d.supported ? (
        <p className="text-sm text-muted">{d.why_not}</p>
      ) : d.pending ? (
        <div className="flex flex-col gap-2 text-sm">
          <div>
            Đang chờ đổi: <span className="text-ink">{d.pending.plan}</span>
          </div>
          <div className="text-muted">
            lúc {new Date(d.pending.scheduled_at).toLocaleTimeString("vi", { hour: "2-digit", minute: "2-digit" })} ·{" "}
            {d.pending.status === "running" ? "đang chạy" : "sắp chạy"}
          </div>
          {d.pending.status === "scheduled" && (
            <button className="btn text-xs self-start" disabled={busy} onClick={cancel}>
              Huỷ
            </button>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-3 text-sm">
          <div className="flex flex-col gap-1.5">
            <label className="text-muted">Tên hiển thị</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="để trống = giữ nguyên" className="min-h-[36px] px-2.5" maxLength={50} />
            <div className="flex flex-wrap gap-1.5">
              {d.suggestions.names.map((n) => (
                <button key={n} className="pill bg-soft text-muted hover:text-ink" onClick={() => setName(n)}>
                  {n}
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-muted">Username</label>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder={canUsername ? "để trống = giữ nguyên" : "chưa đổi lại được"}
              disabled={!canUsername}
              className="mono min-h-[36px] px-2.5"
            />
            {canUsername ? (
              <div className="flex flex-wrap gap-1.5">
                {d.suggestions.usernames.map((u) => (
                  <button key={u} className="pill mono bg-soft text-muted hover:text-ink" onClick={() => setUsername(u)}>
                    {u}
                  </button>
                ))}
              </div>
            ) : (
              <div className="text-xs text-muted">
                Mới đổi gần đây. Đổi lại từ {new Date(d.next_username_change_at!).toLocaleDateString("vi")} ({d.min_days} ngày một lần).
              </div>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-muted">Ảnh đại diện — chọn từ thư viện</label>
            {images.length === 0 ? (
              <div className="text-xs text-muted">Chưa có ảnh nào. Tải ảnh ở Nội dung &amp; Lịch trước.</div>
            ) : (
              <div className="flex flex-wrap gap-2">
                {images.slice(0, 12).map((m) => (
                  <button
                    key={m.id}
                    title={m.original_name}
                    onClick={() => setAvatar(avatar === m.id ? null : m.id)}
                    className={"h-12 w-12 overflow-hidden rounded-full ring-2 " + (avatar === m.id ? "ring-accent" : "ring-transparent hover:ring-line")}
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={`${BASE_URL}/media/${m.id}/thumb${t ? `?t=${encodeURIComponent(t)}` : ""}`} alt="" className="h-full w-full object-cover" />
                  </button>
                ))}
              </div>
            )}
            <div className="text-xs text-faint">Mỗi tài khoản nhận một bản riêng: cắt lệch, đôi khi lật, chỉnh sáng nhẹ.</div>
          </div>

          <div className="flex items-center gap-3">
            <button className="btn btn-primary" disabled={busy || (!username && !name && !avatar)} onClick={submit}>
              {busy ? "…" : "Đổi trong vài phút"}
            </button>
          </div>
        </div>
      )}
      {note && <p className="text-xs text-muted">{note}</p>}
    </section>
  );
}
