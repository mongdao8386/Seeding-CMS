"use client";

import { useEffect, useState } from "react";
import { api, type PlatformWindow } from "@/lib/api";
import { Empty, ErrorBox, Loading, PageHead, useLoad } from "@/components/ui";

const PLATFORMS = ["reddit", "threads", "x", "youtube", "instagram", "facebook", "tiktok"];

type Defaults = { active_from_hour: number; active_to_hour: number };

export default function Settings() {
  const windows = useLoad<PlatformWindow[]>(() => api.get("/windows"));
  const defaults = useLoad<Defaults>(() => api.get("/windows/defaults"));
  const [error, setError] = useState<unknown>(null);

  const byPlatform = new Map((windows.data ?? []).map((w) => [w.platform, w]));

  return (
    <>
      <PageHead
        title="Active hours"
        hint="When background activity is allowed to run, per platform. An account browsing at 4am every night is a clearer anomaly than an account that browses rarely — and a platform's own rhythm differs from its neighbours'."
      />

      <ErrorBox error={error ?? windows.error ?? defaults.error} />
      {(windows.loading || defaults.loading) && <Loading />}

      {defaults.data && (
        <p className="muted mb-4 text-sm">
          Platforms with no window of their own run {hour(defaults.data.active_from_hour)} –{" "}
          {hour(defaults.data.active_to_hour)}, in the server&apos;s own timezone.
        </p>
      )}

      {defaults.data && (
        <div className="card divide-y" style={{ borderColor: "var(--rule)" }}>
          {PLATFORMS.map((platform) => (
            <WindowRow
              key={platform}
              platform={platform}
              window={byPlatform.get(platform) ?? null}
              defaults={defaults.data!}
              onChanged={windows.reload}
              onError={setError}
            />
          ))}
        </div>
      )}

      {!defaults.loading && !defaults.data && <Empty>Could not read the defaults.</Empty>}

      <p className="faint mt-6 max-w-3xl text-xs">
        These hours govern background activity — feed scrolling, reading, reacting. Posting times
        come from each campaign&apos;s own spread window, which is set when the campaign is created.
        A window that wraps past midnight is not supported: waking hours that straddle 3am are the
        pattern this setting exists to avoid.
      </p>
    </>
  );
}

function hour(value: number): string {
  return `${String(value).padStart(2, "0")}:00`;
}

function WindowRow({
  platform,
  window: saved,
  defaults,
  onChanged,
  onError,
}: {
  platform: string;
  window: PlatformWindow | null;
  defaults: Defaults;
  onChanged: () => void;
  onError: (e: unknown) => void;
}) {
  const [from, setFrom] = useState(saved?.active_from_hour ?? defaults.active_from_hour);
  const [to, setTo] = useState(saved?.active_to_hour ?? defaults.active_to_hour);
  const [busy, setBusy] = useState(false);

  // Sau khi luu, danh sach duoc tai lai; keo o nhap theo de no khong hien gia tri cu.
  useEffect(() => {
    setFrom(saved?.active_from_hour ?? defaults.active_from_hour);
    setTo(saved?.active_to_hour ?? defaults.active_to_hour);
  }, [saved, defaults]);

  const custom = saved !== null;
  const dirty = custom
    ? from !== saved.active_from_hour || to !== saved.active_to_hour
    : from !== defaults.active_from_hour || to !== defaults.active_to_hour;
  const invalid = from >= to;

  async function save() {
    setBusy(true);
    try {
      await api.put(`/windows`, {
        platform,
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

  async function clear() {
    setBusy(true);
    try {
      await api.del(`/windows/${platform}`);
      onChanged();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 p-3">
      <span className="mono w-24 shrink-0 text-sm">{platform}</span>

      <span className={`pill ${custom ? "pill-a" : "pill-n"}`}>{custom ? "custom" : "default"}</span>

      <label className="flex items-center gap-2 text-sm">
        <span className="label">from</span>
        <HourPicker value={from} onChange={setFrom} />
      </label>
      <label className="flex items-center gap-2 text-sm">
        <span className="label">to</span>
        <HourPicker value={to} onChange={setTo} />
      </label>

      <span className="muted text-xs tabular-nums">{to - from} waking hours</span>

      {invalid && (
        <span className="text-xs" style={{ color: "var(--bad)" }}>
          the window must start before it ends
        </span>
      )}

      <div className="ml-auto flex gap-2">
        {dirty && !invalid && (
          <button className="btn text-xs" disabled={busy} onClick={save}>
            save
          </button>
        )}
        {custom && (
          <button className="btn btn-ghost text-xs" disabled={busy} onClick={clear}>
            reset to default
          </button>
        )}
      </div>
    </div>
  );
}

function HourPicker({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className="mono text-sm"
      style={{ width: 88 }}
    >
      {Array.from({ length: 24 }, (_, h) => (
        <option key={h} value={h}>
          {hour(h)}
        </option>
      ))}
    </select>
  );
}
