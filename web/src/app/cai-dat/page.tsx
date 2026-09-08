"use client";

import { useEffect, useState } from "react";
import { api, type Platform, type Slot, type SlotMeta } from "@/lib/api";
import { Empty, ErrorNote, PLATFORM_LABEL, PageTitle, useLoad } from "@/components/ui";

/** Cài đặt — phần 2: giờ vàng. Nuôi / cảnh báo / signer vào ở phần 4. */
export default function SettingsPage() {
  const [platform, setPlatform] = useState<Platform>("tiktok");
  const slots = useLoad(() => api.get<Slot[]>("/slots"), []);
  const meta = useLoad(() => api.get<SlotMeta>("/slots/meta"), []);
  const [error, setError] = useState<string | null>(null);

  return (
    <>
      <PageTitle title="Cài đặt" />
      <ErrorNote message={error ?? slots.error} />

      <section className="card flex flex-col gap-4 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-[15px] font-semibold">Giờ vàng — {PLATFORM_LABEL[platform]}</div>
            <div className="text-[13px] text-muted">
              Bài được bám vào mốc gần nhất, mỗi tài khoản một mốc khác nhau trong ngày.
              {meta.data ? ` Múi giờ ${meta.data.timezone}.` : ""}
            </div>
          </div>
          <div className="flex gap-1.5 text-sm">
            {(["tiktok", "instagram", "x"] as Platform[]).map((p) => (
              <button key={p} className={"rounded-lg px-2.5 py-1.5 " + (platform === p ? "bg-soft font-medium" : "text-muted")} onClick={() => setPlatform(p)}>
                {PLATFORM_LABEL[p]}
              </button>
            ))}
          </div>
        </div>

        {meta.data && (
          <SlotEditor platform={platform} slots={(slots.data ?? []).filter((s) => s.platform === platform)} weekdays={meta.data.weekdays} onChange={slots.reload} onError={setError} />
        )}
      </section>

      <div className="mt-5">
        <Empty>Nhịp nuôi, cảnh báo Telegram và trạng thái signer vào ở phần 4.</Empty>
      </div>
    </>
  );
}

function SlotEditor({
  platform,
  slots,
  weekdays,
  onChange,
  onError,
}: {
  platform: Platform;
  slots: Slot[];
  weekdays: string[];
  onChange: () => void;
  onError: (m: string) => void;
}) {
  const [draft, setDraft] = useState<Record<number, number[]>>({});
  const [dirty, setDirty] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const t: Record<number, number[]> = {};
    for (let d = 0; d < 7; d++) t[d] = [];
    for (const s of slots) t[s.weekday].push(s.hour);
    for (const d of Object.keys(t)) t[+d].sort((a, b) => a - b);
    setDraft(t);
    setDirty(new Set());
  }, [slots, platform]);

  function toggle(day: number, hour: number) {
    const hours = draft[day] ?? [];
    const next = hours.includes(hour) ? hours.filter((h) => h !== hour) : [...hours, hour].sort((a, b) => a - b);
    setDraft({ ...draft, [day]: next });
    setDirty(new Set(dirty).add(day));
  }

  async function save() {
    setBusy(true);
    try {
      for (const day of dirty) {
        await api.put("/slots", { platform, weekdays: [day], times: (draft[day] ?? []).map((h) => ({ hour: h, minute: 0 })) });
      }
      onChange();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-2">
        {weekdays.map((name, day) => (
          <div key={day} className="grid grid-cols-[80px_minmax(0,1fr)] items-center gap-3 sm:grid-cols-[90px_minmax(0,1fr)]">
            <span className="text-muted">{name}</span>
            <div className="flex flex-wrap gap-1">
              {Array.from({ length: 24 }, (_, h) => h).map((h) => {
                const on = (draft[day] ?? []).includes(h);
                return (
                  <button
                    key={h}
                    className={"mono min-h-[30px] min-w-[38px] rounded-md px-1.5 text-[12px] " + (on ? "bg-accent-soft font-medium text-accent-dark ring-1 ring-accent" : "bg-softer text-faint hover:bg-soft")}
                    onClick={() => toggle(day, h)}
                  >
                    {String(h).padStart(2, "0")}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <div className="flex items-center gap-3">
        <button className="btn btn-primary" disabled={busy || dirty.size === 0} onClick={save}>
          {busy ? "Đang lưu…" : dirty.size ? `Lưu ${dirty.size} ngày` : "Không có gì đổi"}
        </button>
        <span className="text-xs text-muted">Bấm vào giờ để bật/tắt. Mỗi ngày nên 2–4 mốc; nhiều hơn là rải loãng.</span>
      </div>
    </div>
  );
}
