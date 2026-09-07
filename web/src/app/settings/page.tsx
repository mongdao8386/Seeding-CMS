"use client";

import { useEffect, useMemo, useState } from "react";
import { api, type PlatformWindow } from "@/lib/api";
import { Empty, ErrorBox, Loading, PageHead, useLoad } from "@/components/ui";
import { PostSlots } from "@/components/post-slots";

const PLATFORMS = ["reddit", "threads", "x", "youtube", "instagram", "facebook", "tiktok"];

/** 0 = Monday, matching Python's date.weekday(). */
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const WEEKDAYS = [0, 1, 2, 3, 4];
const WEEKEND = [5, 6];

type Defaults = { active_from_hour: number; active_to_hour: number };

export default function Settings() {
  const windows = useLoad<PlatformWindow[]>(() => api.get("/windows"));
  const defaults = useLoad<Defaults>(() => api.get("/windows/defaults"));
  const [error, setError] = useState<unknown>(null);
  const [open, setOpen] = useState<string | null>(null);

  const byPlatform = useMemo(() => {
    const map = new Map<string, Map<number, PlatformWindow>>();
    for (const w of windows.data ?? []) {
      if (!map.has(w.platform)) map.set(w.platform, new Map());
      map.get(w.platform)!.set(w.weekday, w);
    }
    return map;
  }, [windows.data]);

  return (
    <>
      <PageHead
        title="Active hours"
        hint="When background activity may run — per platform, per day of the week. An account awake at 4am is a clear anomaly; one that keeps identical hours seven days a week is a quieter one."
      />

      <ErrorBox error={error ?? windows.error ?? defaults.error} />
      {(windows.loading || defaults.loading) && <Loading />}

      {defaults.data && (
        <p className="muted mb-4 text-sm">
          Any day with no window of its own runs {hour(defaults.data.active_from_hour)} –{" "}
          {hour(defaults.data.active_to_hour)}, in the server&apos;s own timezone.
        </p>
      )}

      {defaults.data && (
        <div className="flex flex-col gap-2">
          {PLATFORMS.map((platform) => (
            <PlatformCard
              key={platform}
              platform={platform}
              days={byPlatform.get(platform) ?? new Map()}
              defaults={defaults.data!}
              expanded={open === platform}
              onToggle={() => setOpen(open === platform ? null : platform)}
              onChanged={windows.reload}
              onError={setError}
            />
          ))}
        </div>
      )}

      {!defaults.loading && !defaults.data && <Empty>Could not read the defaults.</Empty>}

      <PostSlots onError={setError} />

      <p className="faint mt-6 max-w-3xl text-xs">
        Active hours govern background activity — feed scrolling, reading, reacting, and the
        cross-account follows. Posting times come from the posting slots above when a platform
        has any, otherwise from each campaign&apos;s own spread window. A
        window that wraps past midnight is not supported: waking hours straddling 3am are the
        pattern this setting exists to avoid. End the day at 24:00 to run right up to midnight.
      </p>
    </>
  );
}

function hour(value: number): string {
  return `${String(value).padStart(2, "0")}:00`;
}

function PlatformCard({
  platform,
  days,
  defaults,
  expanded,
  onToggle,
  onChanged,
  onError,
}: {
  platform: string;
  days: Map<number, PlatformWindow>;
  defaults: Defaults;
  expanded: boolean;
  onToggle: () => void;
  onChanged: () => void;
  onError: (e: unknown) => void;
}) {
  const [busy, setBusy] = useState(false);
  const custom = days.size > 0;

  // Cac ngay dat giong het nhau thi hien mot dong gon; khac nhau thi phai mo ra xem.
  const shapes = new Set(
    [...days.values()].map((w) => `${w.active_from_hour}-${w.active_to_hour}`),
  );
  const uniform = custom && days.size === 7 && shapes.size === 1;

  async function apply(weekdays: number[], from: number, to: number) {
    setBusy(true);
    try {
      await api.put("/windows", {
        platform,
        weekdays,
        active_from_hour: from,
        active_to_hour: to,
      });
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
      await api.del(`/windows/${platform}${weekday === undefined ? "" : `?weekday=${weekday}`}`);
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
        <span className={`pill ${custom ? "pill-a" : "pill-n"}`}>
          {custom ? (uniform ? "custom" : "per day") : "default"}
        </span>

        <span className="muted text-xs">
          {custom ? summary(days, defaults) : `${hour(defaults.active_from_hour)} – ${hour(defaults.active_to_hour)} every day`}
        </span>

        <div className="ml-auto flex gap-2">
          {custom && (
            <button className="btn btn-ghost text-xs" disabled={busy} onClick={() => clear()}>
              reset all
            </button>
          )}
          <button className="btn btn-ghost text-xs" onClick={onToggle}>
            {expanded ? "done" : "edit"}
          </button>
        </div>
      </div>

      {expanded && (
        <div className="border-t p-3" style={{ borderColor: "var(--rule)" }}>
          <Bulk defaults={defaults} busy={busy} onApply={apply} />

          <div className="mt-3 flex flex-col gap-1">
            {DAYS.map((label, weekday) => (
              <DayRow
                key={weekday}
                label={label}
                weekday={weekday}
                window={days.get(weekday) ?? null}
                defaults={defaults}
                busy={busy}
                onApply={(from, to) => apply([weekday], from, to)}
                onClear={() => clear(weekday)}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** Mot dong tom tat de khong phai mo ra moi lan muon biet dang dat gi. */
function summary(days: Map<number, PlatformWindow>, defaults: Defaults): string {
  const parts: string[] = [];
  const groups = new Map<string, number[]>();

  for (let d = 0; d < 7; d++) {
    const w = days.get(d);
    const key = w
      ? `${hour(w.active_from_hour)} – ${hour(w.active_to_hour)}`
      : `${hour(defaults.active_from_hour)} – ${hour(defaults.active_to_hour)}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(d);
  }

  for (const [range, list] of groups) {
    parts.push(`${list.map((d) => DAYS[d]).join(" ")} ${range}`);
  }
  return parts.join("  ·  ");
}

function Bulk({
  defaults,
  busy,
  onApply,
}: {
  defaults: Defaults;
  busy: boolean;
  onApply: (weekdays: number[], from: number, to: number) => void;
}) {
  const [from, setFrom] = useState(defaults.active_from_hour);
  const [to, setTo] = useState(defaults.active_to_hour);
  const invalid = from >= to;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="label">Set</span>
      <HourPicker value={from} onChange={setFrom} />
      <span className="faint text-xs">to</span>
      <HourPicker value={to} onChange={setTo} max={24} />

      {invalid ? (
        <span className="text-xs" style={{ color: "var(--bad)" }}>
          must start before it ends
        </span>
      ) : (
        <>
          <button
            className="btn text-xs"
            disabled={busy}
            onClick={() => onApply([0, 1, 2, 3, 4, 5, 6], from, to)}
          >
            all week
          </button>
          <button
            className="btn btn-ghost text-xs"
            disabled={busy}
            onClick={() => onApply(WEEKDAYS, from, to)}
          >
            Mon–Fri
          </button>
          <button
            className="btn btn-ghost text-xs"
            disabled={busy}
            onClick={() => onApply(WEEKEND, from, to)}
          >
            Sat–Sun
          </button>
        </>
      )}
    </div>
  );
}

function DayRow({
  label,
  weekday,
  window: saved,
  defaults,
  busy,
  onApply,
  onClear,
}: {
  label: string;
  weekday: number;
  window: PlatformWindow | null;
  defaults: Defaults;
  busy: boolean;
  onApply: (from: number, to: number) => void;
  onClear: () => void;
}) {
  const [from, setFrom] = useState(saved?.active_from_hour ?? defaults.active_from_hour);
  const [to, setTo] = useState(saved?.active_to_hour ?? defaults.active_to_hour);

  // Sau khi luu, danh sach tai lai; keo o nhap theo de no khong hien gia tri cu.
  useEffect(() => {
    setFrom(saved?.active_from_hour ?? defaults.active_from_hour);
    setTo(saved?.active_to_hour ?? defaults.active_to_hour);
  }, [saved, defaults]);

  const custom = saved !== null;
  const dirty = custom
    ? from !== saved.active_from_hour || to !== saved.active_to_hour
    : from !== defaults.active_from_hour || to !== defaults.active_to_hour;
  const invalid = from >= to;
  const weekendish = weekday >= 5;

  return (
    <div
      className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded px-2 py-1.5"
      style={{ background: weekendish ? "var(--surface-2)" : "transparent" }}
    >
      <span className="mono w-10 shrink-0 text-xs">{label}</span>
      <HourPicker value={from} onChange={setFrom} />
      <span className="faint text-xs">to</span>
      <HourPicker value={to} onChange={setTo} max={24} />
      <span className="faint text-xs tabular-nums">{to - from}h</span>

      {!custom && <span className="faint text-xs">default</span>}

      {invalid && (
        <span className="text-xs" style={{ color: "var(--bad)" }}>
          starts after it ends
        </span>
      )}

      <div className="ml-auto flex gap-2">
        {dirty && !invalid && (
          <button className="btn text-xs" disabled={busy} onClick={() => onApply(from, to)}>
            save
          </button>
        )}
        {custom && (
          <button className="btn btn-ghost text-xs" disabled={busy} onClick={onClear}>
            reset
          </button>
        )}
      </div>
    </div>
  );
}

function HourPicker({
  value,
  onChange,
  max = 23,
}: {
  value: number;
  onChange: (v: number) => void;
  max?: number;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className="mono text-sm"
      style={{ width: 84 }}
    >
      {Array.from({ length: max + 1 }, (_, h) => (
        <option key={h} value={h}>
          {hour(h)}
        </option>
      ))}
    </select>
  );
}
