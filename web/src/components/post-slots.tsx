"use client";

import { useEffect, useMemo, useState } from "react";
import { api, type PostSlot, type SlotMeta } from "@/lib/api";
import { Loading, useLoad } from "@/components/ui";

const PLATFORMS = ["tiktok", "instagram", "x", "facebook", "threads", "youtube", "reddit"];
/** 0 = Monday, matching Python's date.weekday(). */
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/**
 * Khung gio vang DANG BAI, theo nen tang va thu trong tuan.
 *
 * Khac "Active hours" o tren: do la KHOANG gio hoat dong nen, day la cac MOC gio roi
 * rac ma planner bam bai vao ("Tue 02:00, 04:00, 09:00"). Nen tang khong co moc nao
 * thi chien dich dung starts_at + cua so rai cua chinh no, nhu truoc.
 */
export function PostSlots({ onError }: { onError: (e: unknown) => void }) {
  const slots = useLoad<PostSlot[]>(() => api.get("/slots"));
  const meta = useLoad<SlotMeta>(() => api.get("/slots/meta"));
  const [open, setOpen] = useState<string | null>(null);

  const byPlatform = useMemo(() => {
    const map = new Map<string, Map<number, number[]>>();
    for (const s of slots.data ?? []) {
      if (!map.has(s.platform)) map.set(s.platform, new Map());
      const days = map.get(s.platform)!;
      days.set(s.weekday, [...(days.get(s.weekday) ?? []), s.hour].sort((a, b) => a - b));
    }
    return map;
  }, [slots.data]);

  return (
    <section className="mt-8">
      <h2 className="mb-1 text-base font-medium">Posting slots</h2>
      <p className="muted mb-3 text-sm">
        Golden hours to post at, per platform and weekday
        {meta.data ? `, in ${meta.data.timezone}` : ""}. A campaign lands each account on the
        next slot after its start time, spread across that day&apos;s slots, plus at most{" "}
        {meta.data ? Math.round(meta.data.jitter_max_seconds / 60) : 15} minutes. A platform with
        no slots keeps using the campaign&apos;s own start time and spread window.
      </p>

      {slots.loading && <Loading />}

      <div className="flex flex-col gap-2">
        {PLATFORMS.map((platform) => (
          <SlotCard
            key={platform}
            platform={platform}
            days={byPlatform.get(platform) ?? new Map()}
            expanded={open === platform}
            onToggle={() => setOpen(open === platform ? null : platform)}
            onChanged={slots.reload}
            onError={onError}
          />
        ))}
      </div>
    </section>
  );
}

function hh(h: number): string {
  return `${String(h).padStart(2, "0")}:00`;
}

/** "6, 10, 22" -> [6, 10, 22]; chu rac hoac gio ngoai 0-23 thi null. */
function parseHours(text: string): number[] | null {
  const parts = text
    .split(/[,\s;]+/)
    .map((p) => p.trim())
    .filter(Boolean);
  if (parts.length === 0) return null;
  const hours = parts.map((p) => Number(p.replace(/h$|:00$/i, "")));
  if (hours.some((h) => !Number.isInteger(h) || h < 0 || h > 23)) return null;
  return [...new Set(hours)].sort((a, b) => a - b);
}

function SlotCard({
  platform,
  days,
  expanded,
  onToggle,
  onChanged,
  onError,
}: {
  platform: string;
  days: Map<number, number[]>;
  expanded: boolean;
  onToggle: () => void;
  onChanged: () => void;
  onError: (e: unknown) => void;
}) {
  const [busy, setBusy] = useState(false);
  const configured = days.size > 0;
  const total = [...days.values()].reduce((n, hs) => n + hs.length, 0);

  async function apply(weekdays: number[], hours: number[]) {
    setBusy(true);
    try {
      await api.put("/slots", { platform, weekdays, hours });
      onChanged();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }

  async function clear(weekday?: number) {
    setBusy(true);
    try {
      await api.del(`/slots/${platform}${weekday === undefined ? "" : `?weekday=${weekday}`}`);
      onChanged();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 p-3">
        <button
          className="btn btn-ghost text-xs"
          onClick={onToggle}
          style={{ minWidth: 28 }}
          aria-label={expanded ? "collapse" : "expand"}
        >
          {expanded ? "▾" : "▸"}
        </button>
        <span className="mono w-24 shrink-0 text-sm">{platform}</span>
        <span className={`pill ${configured ? "pill-a" : "pill-n"}`}>
          {configured ? `${total} slots` : "none"}
        </span>
        <span className="muted text-xs">
          {configured
            ? [...days.entries()]
                .sort(([a], [b]) => a - b)
                .map(([d, hs]) => `${DAYS[d]} ${hs.map(hh).join(" ")}`)
                .join("  ·  ")
            : "campaign start time + spread window"}
        </span>
        <div className="ml-auto flex gap-2">
          {configured && (
            <button className="btn btn-ghost text-xs" disabled={busy} onClick={() => clear()}>
              clear all
            </button>
          )}
          <button className="btn btn-ghost text-xs" onClick={onToggle}>
            {expanded ? "done" : "edit"}
          </button>
        </div>
      </div>

      {expanded && (
        <div className="border-t p-3" style={{ borderColor: "var(--rule)" }}>
          <BulkSlots busy={busy} onApply={apply} />
          <div className="mt-3 flex flex-col gap-1">
            {DAYS.map((label, weekday) => (
              <SlotRow
                key={weekday}
                label={label}
                weekday={weekday}
                hours={days.get(weekday) ?? []}
                busy={busy}
                onApply={(hours) => apply([weekday], hours)}
                onClear={() => clear(weekday)}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function BulkSlots({
  busy,
  onApply,
}: {
  busy: boolean;
  onApply: (weekdays: number[], hours: number[]) => void;
}) {
  const [text, setText] = useState("");
  const hours = parseHours(text);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="label">Set</span>
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="6, 10, 22"
        className="mono text-sm"
        style={{ width: 160 }}
      />
      {text && !hours && (
        <span className="text-xs" style={{ color: "var(--bad)" }}>
          hours 0–23, comma-separated
        </span>
      )}
      {hours && (
        <>
          <button className="btn text-xs" disabled={busy} onClick={() => onApply([0, 1, 2, 3, 4, 5, 6], hours)}>
            all week
          </button>
          <button className="btn btn-ghost text-xs" disabled={busy} onClick={() => onApply([0, 1, 2, 3, 4], hours)}>
            Mon–Fri
          </button>
          <button className="btn btn-ghost text-xs" disabled={busy} onClick={() => onApply([5, 6], hours)}>
            Sat–Sun
          </button>
        </>
      )}
    </div>
  );
}

function SlotRow({
  label,
  weekday,
  hours: saved,
  busy,
  onApply,
  onClear,
}: {
  label: string;
  weekday: number;
  hours: number[];
  busy: boolean;
  onApply: (hours: number[]) => void;
  onClear: () => void;
}) {
  const [text, setText] = useState(saved.join(", "));
  useEffect(() => setText(saved.join(", ")), [saved]);

  const parsed = parseHours(text);
  const dirty = (parsed ?? []).join(",") !== saved.join(",");
  const weekendish = weekday >= 5;

  return (
    <div
      className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded px-2 py-1.5"
      style={{ background: weekendish ? "var(--surface-2)" : "transparent" }}
    >
      <span className="mono w-10 shrink-0 text-xs">{label}</span>
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="no slots"
        className="mono text-sm"
        style={{ width: 160 }}
      />
      <span className="faint text-xs">{saved.length ? saved.map(hh).join("  ") : "—"}</span>
      {text && !parsed && (
        <span className="text-xs" style={{ color: "var(--bad)" }}>
          hours 0–23
        </span>
      )}
      <div className="ml-auto flex gap-2">
        {dirty && parsed && (
          <button className="btn text-xs" disabled={busy} onClick={() => onApply(parsed)}>
            save
          </button>
        )}
        {saved.length > 0 && (
          <button className="btn btn-ghost text-xs" disabled={busy} onClick={onClear}>
            clear
          </button>
        )}
      </div>
    </div>
  );
}
