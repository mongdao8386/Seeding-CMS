"use client";

import { useState } from "react";
import { api, qs, type GraphAudit, type GraphEdge, type Page } from "@/lib/api";
import { Empty, ErrorBox, Loading, PageHead, Pager, Status, useLoad, usePaged, when } from "@/components/ui";

export default function Network() {
  const audit = useLoad<GraphAudit>(() => api.get("/graph"));
  const edges = usePaged<GraphEdge>("/graph/edges", ({ limit, offset }) =>
    `/graph/edges${qs({ limit, offset })}`,
  );
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function grow() {
    setBusy(true);
    try {
      await api.post("/graph/plan");
      audit.reload();
      edges.reload();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  const a = audit.data;

  return (
    <>
      <PageHead
        title="Network"
        hint="Follows and engagement between your own accounts. This is the most useful thing here and the most dangerous: a post with no engagement does not travel, but a dense follow graph is how a whole cluster gets found at once."
      />

      <ErrorBox error={error ?? audit.error ?? edges.error} />
      {audit.loading && <Loading />}

      {a && (
        <>
          <div className="card mb-4 flex flex-wrap gap-x-10 gap-y-4 p-4">
            <Figure label="Accounts" value={String(a.accounts)} />
            <Figure label="Follows between them" value={String(a.edges)} />
            <Figure
              label="Density"
              value={`${(a.density * 100).toFixed(1)}%`}
              note={`ceiling ${(a.max_density * 100).toFixed(0)}%`}
              bad={a.density > a.max_density}
            />
            <Figure
              label="Reciprocated"
              value={`${(a.mutual_rate * 100).toFixed(0)}%`}
              note={`${a.mutual_pairs} pairs`}
            />
            <Figure label="Most follows by one account" value={String(a.max_following)} />
            <Figure label="Not connected to anyone" value={String(a.isolated)} />

            <div className="ml-auto self-center">
              <button className="btn" disabled={busy} onClick={grow}>
                Grow the graph a little
              </button>
            </div>
          </div>

          {a.warnings.map((warning, i) => (
            <div
              key={i}
              className="card mb-3 p-3 text-sm"
              style={{
                borderLeft: `3px solid ${
                  warning.startsWith("Unverifiable") ? "var(--warn)" : "var(--bad)"
                }`,
              }}
            >
              {warning}
            </div>
          ))}

          {a.edges === 0 && (
            <div className="card mb-4 p-3 text-sm">
              <span className="label">Nothing yet</span>
              <p className="muted mt-1">
                No account follows another. Press <em>Grow the graph a little</em> to add a few
                edges — a few, deliberately. Fifty follows appearing in one morning is an event,
                not a social network.
              </p>
            </div>
          )}
        </>
      )}

      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold">Edges</h2>
        <Pager
          total={edges.total}
          offset={edges.offset}
          pageSize={edges.pageSize}
          onGoto={edges.goto}
          noun="follow"
        />
      </div>

      <div className="card overflow-x-auto">
        {edges.loading && <Loading />}
        {edges.items.length ? (
          <table className="grid">
            <thead>
              <tr>
                <th>Follower</th>
                <th>Follows</th>
                <th>Platform</th>
                <th>State</th>
                <th>Planned</th>
                <th>Done</th>
              </tr>
            </thead>
            <tbody>
              {edges.items.map((e) => (
                <tr key={e.id}>
                  <td className="mono text-xs">{e.follower}</td>
                  <td className="mono text-xs">{e.target}</td>
                  <td>
                    <span className="pill pill-b">{e.platform}</span>
                  </td>
                  <td>
                    <Status value={e.status === "done" ? "succeeded" : e.status === "failed" ? "failed" : "scheduled"} />
                  </td>
                  <td className="faint text-xs">{when(e.created_at)}</td>
                  <td className="faint text-xs">{when(e.done_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          !edges.loading && <Empty>No follows planned yet.</Empty>
        )}
      </div>

      <div className="card mt-5 p-4 text-sm">
        <span className="label">What this does on its own</span>
        <ul className="muted mt-2 flex flex-col gap-1.5">
          <li>
            A <em>planned</em> edge is not a real follow yet. It becomes one when the worker opens
            the browser, clicks, and <strong>sees the button change to Following</strong> — never
            before. An edge that says done but was never clicked makes every number above wrong.
          </li>
          <li>
            When a post goes live, only a <strong>fraction</strong> of that account&apos;s followers
            engage, starting at least 18 minutes later and spread over hours. Twelve likes in forty
            seconds is the shape of a button, not of people.
          </li>
          <li>
            Reposts are rare on purpose. They are public, permanent, and they draw a visible line
            between two of your accounts.
          </li>
        </ul>
      </div>
    </>
  );
}

function Figure({
  label,
  value,
  note,
  bad,
}: {
  label: string;
  value: string;
  note?: string;
  bad?: boolean;
}) {
  return (
    <div>
      <span className="label block">{label}</span>
      <span
        className="mt-1 block text-xl font-semibold tabular-nums"
        style={bad ? { color: "var(--bad)" } : undefined}
      >
        {value}
      </span>
      {note && <span className="faint text-xs">{note}</span>}
    </div>
  );
}
