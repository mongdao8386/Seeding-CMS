"use client";

import { useEffect, useState } from "react";
import { api, qs, type CampaignSummary, type Group, type Job } from "@/lib/api";
import { NewCampaign } from "@/components/new-campaign";
import { AddGroup } from "@/components/add-group";
import {
  ConfirmButton,
  Empty,
  ErrorBox,
  Loading,
  PageHead,
  Pager,
  SearchBox,
  Status,
  useLoad,
  usePaged,
  when,
} from "@/components/ui";

const ALL = "__all__";

export default function Schedule() {
  const campaigns = usePaged<CampaignSummary>("/campaigns", ({ limit, offset, q }) =>
    `/campaigns${qs({ limit, offset, q })}`,
  );
  const [campaignId, setCampaignId] = useState("");
  const [groupId, setGroupId] = useState(ALL);
  const [addingGroup, setAddingGroup] = useState(false);

  const [groups, setGroups] = useState<Group[] | null>(null);
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const [nonce, setNonce] = useState(0);

  // Trang tong quan tro sang day kem ?campaign=… ; doc mot lan luc mo trang.
  useEffect(() => {
    const fromUrl = new URLSearchParams(window.location.search).get("campaign");
    if (fromUrl) setCampaignId(fromUrl);
  }, []);

  useEffect(() => {
    if (!campaignId && campaigns.items.length) setCampaignId(campaigns.items[0].id);
  }, [campaigns.items, campaignId]);

  useEffect(() => {
    if (!campaignId) return;
    setLoading(true);
    setGroupId(ALL);
    api
      .get<Group[]>(`/campaigns/${campaignId}/groups`)
      .then((g) => (setGroups(g), setError(null)))
      .catch(setError)
      .finally(() => setLoading(false));
  }, [campaignId, nonce]);

  useEffect(() => {
    if (!campaignId) return;
    const query = groupId === ALL ? "" : `?group_id=${groupId}`;
    api
      .get<Job[]>(`/campaigns/${campaignId}/jobs${query}`)
      .then((j) => (setJobs(j), setError(null)))
      .catch(setError);
  }, [campaignId, groupId, nonce]);

  const campaign = campaigns.items.find((c) => c.id === campaignId);
  const reload = () => setNonce((n) => n + 1);

  async function spawnNext() {
    if (!campaign) return;
    try {
      const clone = await api.post<{ id: string }>(`/campaigns/${campaign.id}/spawn-next`);
      campaigns.reload();
      setCampaignId(clone.id);
      reload();
    } catch (e) {
      setError(e);
    }
  }

  return (
    <>
      <PageHead
        title="Schedule"
        hint="Campaign, then group, then post — pick along the row to narrow what you see. Each account lands on a random point inside the spread window."
      />

      <ErrorBox error={error ?? campaigns.error} />

      <NewCampaign
        onDone={(id) => {
          campaigns.reload();
          setCampaignId(id);
          reload();
        }}
      />

      {campaign && campaign.repeat !== "none" && (
        <div className="card mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 p-3 text-sm">
          <span className="label">Repeats {campaign.repeat}</span>
          <span className="muted">
            {campaign.next_run
              ? `Next copy spawns ${when(campaign.next_run)}.`
              : "This chain has passed its end date — no more copies will spawn."}
            {campaign.repeat_until ? ` Ends ${when(campaign.repeat_until)}.` : ""}
          </span>
          {campaign.next_run && (
            <button className="btn btn-ghost ml-auto text-xs" onClick={spawnNext}>
              spawn the next one now
            </button>
          )}
        </div>
      )}

      {campaign?.repeat_parent_id && (
        <div className="card mb-4 p-3 text-sm">
          <span className="label">Copy</span>
          <span className="muted ml-3">
            This campaign was spawned from a repeating one. Editing it changes this run only.
          </span>
        </div>
      )}

      {addingGroup && campaignId && (
        <AddGroup
          campaignId={campaignId}
          onDone={() => {
            setAddingGroup(false);
            reload();
            campaigns.reload();
          }}
          onClose={() => setAddingGroup(false)}
          onError={setError}
        />
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.4fr)]">
        {/* --- Cot 1: chien dich --- */}
        <Pane
          title="Campaigns"
          count={campaigns.total}
          action={
            <SearchBox
              value={campaigns.query}
              onChange={campaigns.setQuery}
              placeholder="search…"
            />
          }
          footer={
            <Pager
              total={campaigns.total}
              offset={campaigns.offset}
              pageSize={campaigns.pageSize}
              onGoto={campaigns.goto}
              noun="campaign"
            />
          }
        >
          {campaigns.items.length ? (
            campaigns.items.map((c) => (
              <Row
                key={c.id}
                active={c.id === campaignId}
                onClick={() => setCampaignId(c.id)}
                title={c.name}
                badge={
                  c.repeat_parent_id
                    ? "copy"
                    : c.repeat !== "none"
                      ? c.repeat
                      : undefined
                }
                meta={
                  `${when(c.starts_at)} · spread ${Math.round(c.stagger_window_seconds / 60)} min` +
                  (c.next_run ? ` · next ${when(c.next_run)}` : "")
                }
                counts={{
                  total: c.total_jobs,
                  ok: c.succeeded,
                  bad: c.failed,
                  human: c.needs_human,
                }}
                action={
                  <ConfirmButton
                    onConfirm={async () => {
                      try {
                        await api.del(`/campaigns/${c.id}?force=true`);
                        setCampaignId("");
                        campaigns.reload();
                        reload();
                      } catch (e) {
                        setError(e);
                      }
                    }}
                  >
                    delete
                  </ConfirmButton>
                }
              />
            ))
          ) : (
            <Empty>
              {campaigns.query ? "Nothing matches that search." : "No campaigns yet."}
            </Empty>
          )}
        </Pane>

        {/* --- Cot 2: nhom --- */}
        <Pane
          title="Groups"
          count={groups?.length ?? 0}
          action={
            campaignId ? (
              <button
                className="btn btn-ghost text-xs"
                onClick={() => setAddingGroup((v) => !v)}
              >
                {addingGroup ? "close" : "add group"}
              </button>
            ) : null
          }
        >
          {loading && <Loading />}
          {!loading && groups?.length ? (
            <>
              <Row
                active={groupId === ALL}
                onClick={() => setGroupId(ALL)}
                title="All groups"
                meta={`${groups.reduce((n, g) => n + g.account_count, 0)} accounts in total`}
                counts={{
                  total: groups.reduce((n, g) => n + g.total_jobs, 0),
                  ok: groups.reduce((n, g) => n + g.succeeded, 0),
                  bad: groups.reduce((n, g) => n + g.failed, 0),
                  human: groups.reduce((n, g) => n + g.needs_human, 0),
                }}
              />
              {groups.map((g) => (
                <Row
                  key={g.id}
                  active={g.id === groupId}
                  onClick={() => setGroupId(g.id)}
                  title={g.name}
                  badge={g.post_kind === "comment" ? "comments" : g.platform}
                  meta={
                    `${g.account_count} account${g.account_count === 1 ? "" : "s"}` +
                    (g.post_kind === "comment"
                      ? ` · under ${shortUrl(g.target?.url)}`
                      : g.target?.subreddit
                        ? ` · r/${g.target.subreddit}`
                        : "")
                  }
                  counts={{
                    total: g.total_jobs,
                    ok: g.succeeded,
                    bad: g.failed,
                    human: g.needs_human,
                  }}
                  action={
                    <ConfirmButton
                      onConfirm={async () => {
                        try {
                          await api.del(`/campaigns/${campaignId}/groups/${g.id}?force=true`);
                          reload();
                          campaigns.reload();
                        } catch (e) {
                          setError(e);
                        }
                      }}
                    >
                      delete
                    </ConfirmButton>
                  }
                />
              ))}
            </>
          ) : (
            !loading && (
              <Empty>
                {campaign
                  ? "This campaign has no group, so it has no posts. Press \u201cadd group\u201d above."
                  : "Pick a campaign."}
              </Empty>
            )
          )}
        </Pane>

        {/* --- Cot 3: bai dang --- */}
        <Pane title="Posts" count={jobs?.length ?? 0}>
          {jobs?.length ? (
            jobs.map((job) => (
              <div
                key={job.id}
                className="border-b p-2.5 last:border-b-0"
                style={{ borderColor: "var(--rule)" }}
              >
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="mono w-24 shrink-0 text-xs tabular-nums">
                    {when(job.scheduled_at)}
                  </span>
                  <span className="mono w-28 shrink-0 truncate text-xs font-medium">
                    {job.handle}
                  </span>
                  <Status value={job.status} />
                  {job.remote_url && (
                    <a
                      href={job.remote_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-xs underline"
                      style={{ color: "var(--a)" }}
                    >
                      view
                    </a>
                  )}
                </div>
                <p className="mt-1 text-sm">{job.title}</p>
                {job.last_error && (
                  <p
                    className="mono mt-1 truncate text-xs"
                    style={{ color: "var(--ink-3)" }}
                    title={job.last_error}
                  >
                    {job.last_error}
                  </p>
                )}
              </div>
            ))
          ) : (
            <Empty>{campaignId ? "No posts in this selection." : "Pick a campaign."}</Empty>
          )}
        </Pane>
      </div>
    </>
  );
}

function Pane({
  title,
  count,
  action,
  footer,
  children,
}: {
  title: string;
  count: number;
  action?: React.ReactNode;
  /** Thanh duoi cot - de phan trang, nam ngoai vung cuon de luon nhin thay. */
  footer?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="card overflow-hidden">
      <div
        className="flex items-center gap-2 border-b px-3 py-2"
        style={{ borderColor: "var(--rule-strong)", background: "var(--surface-2)" }}
      >
        <span className="label">{title}</span>
        <span className="faint mono text-xs tabular-nums">{count}</span>
        <div className="relative ml-auto">{action}</div>
      </div>
      <div style={{ maxHeight: "60vh", overflowY: "auto" }}>{children}</div>
      {footer && (
        <div
          className="flex items-center justify-end border-t px-3 py-2"
          style={{ borderColor: "var(--rule)" }}
        >
          {footer}
        </div>
      )}
    </div>
  );
}

function Row({
  active,
  onClick,
  title,
  meta,
  badge,
  counts,
  action,
}: {
  active: boolean;
  onClick: () => void;
  title: string;
  meta: string;
  badge?: string;
  counts: { total: number; ok: number; bad: number; human: number };
  action?: React.ReactNode;
}) {
  return (
    <div
      onClick={onClick}
      className="cursor-pointer border-b p-2.5 last:border-b-0"
      style={{
        borderColor: "var(--rule)",
        background: active ? "var(--a-soft)" : "transparent",
        borderLeft: `3px solid ${active ? "var(--a)" : "transparent"}`,
      }}
    >
      <div className="flex items-start gap-2">
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{title}</span>
        {badge && <span className="pill pill-b shrink-0">{badge}</span>}
        <div onClick={(e) => e.stopPropagation()}>{action}</div>
      </div>
      <p className="faint mono mt-0.5 truncate text-xs">{meta}</p>
      <p className="mono mt-1 text-xs tabular-nums">
        <span className="faint">{counts.total} posts</span>
        {counts.ok > 0 && <span style={{ color: "var(--ok)" }}> · {counts.ok} live</span>}
        {counts.bad > 0 && <span style={{ color: "var(--bad)" }}> · {counts.bad} failed</span>}
        {counts.human > 0 && <span style={{ color: "var(--b)" }}> · {counts.human} need you</span>}
      </p>
    </div>
  );
}

/** URL day du lam vo layout cot. Chi giu ten mien va doan cuoi. */
function shortUrl(url?: unknown): string {
  if (typeof url !== "string" || !url) return "a post";
  try {
    const parsed = new URL(url);
    const last = parsed.pathname.split("/").filter(Boolean).pop();
    return last ? `${parsed.hostname}/…/${last.slice(0, 18)}` : parsed.hostname;
  } catch {
    return url.slice(0, 30);
  }
}
