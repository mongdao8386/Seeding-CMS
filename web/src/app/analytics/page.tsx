"use client";

import { api, type Cohort, type Survival } from "@/lib/api";
import { Empty, ErrorBox, Loading, PageHead, useLoad } from "@/components/ui";

export default function Analytics() {
  const { data, error, loading } = useLoad<Survival>(() => api.get("/analytics/survival"));

  return (
    <>
      <PageHead
        title="Survival"
        hint="How long accounts last, and what changes it. Every row carries its sample size — with a handful of accounts per group, a gap between 60% and 75% is noise, not a finding."
      />

      <ErrorBox error={error} />
      {loading && <Loading />}

      {data && data.total === 0 && <Empty>{data.detail ?? "No accounts yet."}</Empty>}

      {data && data.total > 0 && (
        <>
          {data.overall && (
            <div className="card mb-6 flex flex-wrap gap-x-10 gap-y-4 p-4">
              <Figure label="Accounts" value={String(data.total)} />
              <Figure label="Still standing" value={pct(data.overall.survival)} />
              <Figure
                label="Median life of the ones lost"
                value={
                  data.overall.median_days_lived === null
                    ? "none lost yet"
                    : `${data.overall.median_days_lived} days`
                }
              />
              <Figure
                label="Times a person was needed"
                value={`${data.overall.takeovers_per_account} per account`}
              />
            </div>
          )}

          <Table
            title="By proxy type"
            hint="The single most expensive choice in the stack, and the easiest to change on a hunch."
            rows={data.by_proxy_kind}
            min={data.min_cohort}
          />
          <Table
            title="By proxy provider"
            hint="Read from the label you gave each proxy — name them after the provider and this table becomes useful."
            rows={data.by_proxy_label}
            min={data.min_cohort}
          />
          <Table
            title="By warm-up length"
            hint="How long an account existed before it started posting for real."
            rows={data.by_warmup_length}
            min={data.min_cohort}
          />
          <Table
            title="By posting rate"
            hint="Daily cap, which is the rate you asked for rather than the rate achieved."
            rows={data.by_posting_rate}
            min={data.min_cohort}
          />

          <p className="faint mt-6 max-w-3xl text-xs">
            Rows below {data.min_cohort} accounts are greyed out. They are not wrong, they are just
            too small to act on — one account dying moves a group of six by seventeen points. And
            none of this is a controlled experiment: accounts on cheaper proxies also tend to be the
            ones pushed hardest, so a difference here names a correlation, not a cause.
          </p>
        </>
      )}
    </>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="label block">{label}</span>
      <span className="mt-1 block text-xl font-semibold tabular-nums">{value}</span>
    </div>
  );
}

function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function Table({
  title,
  hint,
  rows,
  min,
}: {
  title: string;
  hint: string;
  rows: Cohort[];
  min: number;
}) {
  return (
    <section className="mb-6">
      <h2 className="text-sm font-semibold">{title}</h2>
      <p className="faint mb-2 max-w-2xl text-xs">{hint}</p>

      {rows.length === 0 ? (
        <Empty>Nothing to group yet.</Empty>
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="label" style={{ borderBottom: "1px solid var(--rule)" }}>
                <Th>Group</Th>
                <Th right>Accounts</Th>
                <Th right>Still standing</Th>
                <Th right>Lost</Th>
                <Th right>Waiting on a person</Th>
                <Th right>Median life</Th>
                <Th right>Takeovers each</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.label}
                  style={{
                    borderBottom: "1px solid var(--rule)",
                    opacity: row.trustworthy ? 1 : 0.5,
                  }}
                >
                  <td className="px-3 py-2">
                    {row.label}
                    {!row.trustworthy && (
                      <span className="faint ml-2 text-xs">under {min} — too small to read</span>
                    )}
                  </td>
                  <Td>{row.n}</Td>
                  <Td>
                    <Bar value={row.survival} />
                  </Td>
                  <Td>{row.gone}</Td>
                  <Td>{row.needs_human}</Td>
                  <Td>{row.median_days_lived === null ? "—" : `${row.median_days_lived}d`}</Td>
                  <Td>{row.takeovers_per_account}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th className={`px-3 py-2 font-normal ${right ? "text-right" : "text-left"}`}>{children}</th>;
}

function Td({ children }: { children: React.ReactNode }) {
  return <td className="px-3 py-2 text-right tabular-nums">{children}</td>;
}

/** So kem thanh: mot bang toan phan tram thi mat khong so sanh duoc hang nao voi hang nao. */
function Bar({ value }: { value: number }) {
  return (
    <span className="inline-flex items-center justify-end gap-2">
      <span
        style={{
          display: "inline-block",
          width: 56,
          height: 6,
          borderRadius: 3,
          background: "var(--rule-strong)",
          overflow: "hidden",
        }}
      >
        <span
          style={{
            display: "block",
            width: `${Math.round(value * 100)}%`,
            height: "100%",
            background: value >= 0.8 ? "var(--ok)" : value >= 0.5 ? "var(--warn)" : "var(--bad)",
          }}
        />
      </span>
      {pct(value)}
    </span>
  );
}
