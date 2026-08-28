"use client";

import Link from "next/link";
import { api, type CampaignSummary, type Stats, type Takeover } from "@/lib/api";
import { ErrorBox, Loading, PageHead, useLoad, when } from "@/components/ui";

type Bundle = { stats: Stats; takeovers: Takeover[]; campaigns: CampaignSummary[] };

export default function Dashboard() {
  const { data, error, loading } = useLoad<Bundle>(async () => ({
    stats: await api.get<Stats>("/stats"),
    takeovers: await api.get<Takeover[]>("/takeovers"),
    campaigns: await api.get<CampaignSummary[]>("/campaigns"),
  }));

  return (
    <>
      <PageHead
        title="Overview"
        hint="What needs doing first, numbers second. If an account is waiting on you, that is the only thing worth looking at."
      />

      <ErrorBox error={error} />
      {loading && <Loading />}

      {data && (
        <>
          {data.takeovers.length > 0 ? (
            <Link href="/takeovers" className="block">
              <div
                className="card mb-6 p-4 transition hover:opacity-90"
                style={{ borderLeft: "3px solid var(--b)" }}
              >
                <span className="label" style={{ color: "var(--b)" }}>
                  Needs you
                </span>
                <p className="mt-1 text-lg font-semibold">
                  {data.takeovers.length} account{data.takeovers.length > 1 ? "s" : ""} waiting
                </p>
                <p className="muted mt-1 text-sm">
                  {data.takeovers
                    .slice(0, 3)
                    .map((t) => t.handle)
                    .join(", ")}
                  {data.takeovers.length > 3 && ` and ${data.takeovers.length - 3} more`}
                </p>
              </div>
            </Link>
          ) : (
            <div className="card mb-6 p-4" style={{ borderLeft: "3px solid var(--ok)" }}>
              <span className="label" style={{ color: "var(--ok)" }}>
                Queue is clear
              </span>
              <p className="muted mt-1 text-sm">No account is waiting on you.</p>
            </div>
          )}

          <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Tile
              label="Accounts"
              value={data.stats.accounts}
              note={`${data.stats.accounts_needing_human} need you`}
              alert={data.stats.accounts_needing_human > 0}
            />
            <Tile
              label="Live sessions"
              value={`${data.stats.profiles_alive}/${data.stats.profiles_total}`}
              note="signed in"
              alert={data.stats.profiles_total > 0 && data.stats.profiles_alive === 0}
            />
            <Tile
              label="Posts waiting"
              value={data.stats.jobs_scheduled}
              note={`${data.stats.jobs_succeeded} posted · ${data.stats.jobs_failed} failed`}
            />
            <Tile
              label="Ambient activity"
              value={data.stats.activity_scheduled_today}
              note="left today"
            />
          </div>

          <h2 className="mb-3 text-sm font-semibold">Recent campaigns</h2>
          {data.campaigns.length === 0 ? (
            <div className="card p-6 text-center">
              <p className="muted text-sm">No campaigns yet.</p>
              <Link href="/compose" className="mt-3 inline-block">
                <button className="btn">Write your first post</button>
              </Link>
            </div>
          ) : (
            <div className="card overflow-x-auto">
              <table className="grid">
                <thead>
                  <tr>
                    <th>Campaign</th>
                    <th>Starts</th>
                    <th>Spread over</th>
                    <th>Jobs</th>
                    <th>Posted</th>
                    <th>Failed</th>
                    <th>Needs you</th>
                  </tr>
                </thead>
                <tbody>
                  {data.campaigns.map((c) => (
                    <tr key={c.id}>
                      <td className="font-medium">
                        <Link href={`/schedule?campaign=${c.id}`} className="hover:underline">
                          {c.name}
                        </Link>
                      </td>
                      <td className="mono whitespace-nowrap text-xs">{when(c.starts_at)}</td>
                      <td className="mono text-xs">
                        {Math.round(c.stagger_window_seconds / 60)} min
                      </td>
                      <td className="mono">{c.total_jobs}</td>
                      <td className="mono" style={{ color: "var(--ok)" }}>
                        {c.succeeded || "—"}
                      </td>
                      <td className="mono" style={{ color: c.failed ? "var(--bad)" : undefined }}>
                        {c.failed || "—"}
                      </td>
                      <td className="mono" style={{ color: c.needs_human ? "var(--b)" : undefined }}>
                        {c.needs_human || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  );
}

function Tile({
  label,
  value,
  note,
  alert,
}: {
  label: string;
  value: number | string;
  note: string;
  alert?: boolean;
}) {
  return (
    <div className="card p-3">
      <div className="label">{label}</div>
      <div
        className="mono mt-1 text-2xl font-semibold tabular-nums"
        style={{ color: alert ? "var(--b)" : undefined }}
      >
        {value}
      </div>
      <div className="faint mt-0.5 text-xs">{note}</div>
    </div>
  );
}
