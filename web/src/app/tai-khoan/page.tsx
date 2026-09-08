"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api, ApiError, qs, type AccountRole, type AccountRow,
  type BulkDeleteOut, type Page, type Platform, type Proxy } from "@/lib/api";
import { ImportAccounts, ImportProxies } from "@/components/import-panel";
import {
  Avatar,
  Empty,
  ErrorNote,
  PageTitle,
  PLATFORM_LABEL,
  PLATFORMS,
  SessionDot,
  StatusPill,
  timeAgo,
  useLoad,
} from "@/components/ui";

type Filter = "all" | "ready" | "blocked" | "needs_human";
const PAGE = 50;

export default function AccountsPage() {
  return (
    <Suspense>
      <Accounts />
    </Suspense>
  );
}

function Accounts() {
  const params = useSearchParams();
  const [panel, setPanel] = useState<"acc" | "proxy" | null>(params.get("dan") === "acc" ? "acc" : null);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [platform, setPlatform] = useState<Platform | "">("");
  const [role, setRole] = useState<AccountRole | "">("");
  const [offset, setOffset] = useState(0);
  const [tab, setTab] = useState<"acc" | "proxy">("acc");

  const query = qs({
    limit: PAGE,
    offset,
    q,
    platform,
    role,
    ready: filter === "ready" ? true : filter === "blocked" ? false : undefined,
    status: filter === "needs_human" ? "needs_human" : undefined,
  });
  const accounts = useLoad(() => api.get<Page<AccountRow>>(`/accounts${query}`), [query]);
  const proxies = useLoad(() => api.get<Page<Proxy>>("/proxies?limit=500"), []);
  const reloadAll = () => {
    accounts.reload();
    proxies.reload();
  };

  const total = accounts.data?.total ?? 0;
  const freeProxies = (proxies.data?.items ?? []).filter((p) => !p.bound_handle && p.status === "ok").length;

  return (
    <>
      <PageTitle
        title="Tài khoản"
        action={
          <>
            <button className="btn" onClick={() => setPanel(panel === "proxy" ? null : "proxy")}>
              Dán proxy
            </button>
            <button className="btn btn-primary" onClick={() => setPanel(panel === "acc" ? null : "acc")}>
              Dán tài khoản
            </button>
          </>
        }
      />
      <ErrorNote message={accounts.error ?? proxies.error} />

      {panel === "acc" && <ImportAccounts onDone={reloadAll} onClose={() => setPanel(null)} />}
      {panel === "proxy" && <ImportProxies onDone={reloadAll} onClose={() => setPanel(null)} />}

      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center">
        <input
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOffset(0);
          }}
          placeholder="Tìm handle…"
          className="w-full lg:w-[280px]"
        />
        <div className="flex flex-wrap gap-1.5">
          {(
            [
              ["all", "Tất cả"],
              ["ready", "Sẵn sàng"],
              ["blocked", "Chưa sẵn sàng"],
              ["needs_human", "Cần bạn"],
            ] as [Filter, string][]
          ).map(([k, label]) => (
            <button
              key={k}
              className="chip"
              data-on={filter === k}
              onClick={() => {
                setFilter(k);
                setOffset(0);
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="flex gap-1.5 text-sm">
          {(
            [
              ["", "Mọi loại"],
              ["channel", "Xây kênh"],
              ["booster", "Tương tác chéo"],
            ] as [AccountRole | "", string][]
          ).map(([k, label]) => (
            <button
              key={k || "any"}
              className={"rounded-lg px-2.5 py-1.5 " + (role === k ? "bg-soft font-medium text-ink" : "text-muted")}
              onClick={() => {
                setRole(k);
                setOffset(0);
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="grow" />
        <div className="flex gap-1.5 text-sm">
          {(["", ...PLATFORMS] as const).map((p) => (
            <button
              key={p || "all"}
              className={"rounded-lg px-2.5 py-1.5 " + (platform === p ? "bg-soft font-medium text-ink" : "text-muted")}
              onClick={() => {
                setPlatform(p);
                setOffset(0);
              }}
            >
              {p ? PLATFORM_LABEL[p] : "Mọi nền tảng"}
            </button>
          ))}
        </div>
      </div>

      <div className="mb-3 flex gap-4 text-sm">
        <button className={tab === "acc" ? "font-semibold" : "text-muted"} onClick={() => setTab("acc")}>
          Tài khoản {total ? `(${total})` : ""}
        </button>
        <button className={tab === "proxy" ? "font-semibold" : "text-muted"} onClick={() => setTab("proxy")}>
          Proxy {proxies.data ? `(${proxies.data.total})` : ""}
        </button>
      </div>

      {tab === "acc" ? (
        <AccountList
          page={accounts.data}
          loading={accounts.loading}
          offset={offset}
          onPage={setOffset}
          freeProxies={freeProxies}
          onChange={reloadAll}
        />
      ) : (
        <ProxyList proxies={proxies.data?.items ?? []} onChange={reloadAll} />
      )}
    </>
  );
}

function AccountList({
  page,
  loading,
  offset,
  onPage,
  freeProxies,
  onChange,
}: {
  page: Page<AccountRow> | null;
  loading: boolean;
  offset: number;
  onPage: (n: number) => void;
  freeProxies: number;
  onChange: () => void;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function bulkDelete(all: boolean) {
    const n = all ? page?.total ?? 0 : selected.size;
    if (!n) return;
    const what = all ? `TẤT CẢ ${n} tài khoản` : `${n} tài khoản đã chọn`;
    if (!confirm(`Xoá ${what}? Profile, cookie, thông tin đăng nhập, lịch nuôi và lịch đăng của chúng mất hết. Không hoàn tác được.`)) return;
    setBusy(true);
    setNote(null);
    try {
      const body = all ? { all: true } : { ids: [...selected] };
      let r = await api.post<BulkDeleteOut>("/accounts/bulk-delete", body);
      if (r.skipped.length && confirm(`${r.detail}.\n\nXoá cả ${r.skipped.length} tài khoản đã đăng bài (${r.skipped.slice(0, 5).join(", ")}${r.skipped.length > 5 ? "…" : ""})?`)) {
        const again = await api.post<BulkDeleteOut>("/accounts/bulk-delete", { ...body, force: true });
        r = { ...again, deleted: r.deleted + again.deleted };
      }
      setNote(`Đã xoá ${r.deleted} tài khoản.`);
      setSelected(new Set());
      onChange();
    } catch (e) {
      setNote(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!page && loading) return <p className="text-muted">Đang tải…</p>;
  if (!page || page.items.length === 0) {
    return (
      <>
        {note && <div className="card mb-3 p-3 text-sm text-muted">{note}</div>}
        <Empty>Chưa có tài khoản nào khớp. Bấm “Dán tài khoản” để nhập từ file người bán.</Empty>
      </>
    );
  }
  const blocked = page.items.filter((a) => !a.ready && a.status !== "dead").length;
  const allOnPage = page.items.every((a) => selected.has(a.id));

  function toggle(id: string) {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-softer px-4 py-2 text-sm lg:px-5">
        <label className="flex items-center gap-2 text-muted">
          <input
            type="checkbox"
            checked={allOnPage}
            onChange={() => setSelected(allOnPage ? new Set() : new Set(page.items.map((a) => a.id)))}
          />
          chọn cả trang
        </label>
        <button className="btn btn-ghost text-xs text-bad-text" disabled={busy || selected.size === 0} onClick={() => bulkDelete(false)}>
          Xoá đã chọn{selected.size ? ` (${selected.size})` : ""}
        </button>
        <button className="btn btn-ghost text-xs text-bad-text" disabled={busy} onClick={() => bulkDelete(true)}>
          Xoá tất cả ({page.total})
        </button>
        {note && <span className="text-muted">{note}</span>}
      </div>
      <div className="hidden grid-cols-[28px_minmax(0,2fr)_90px_130px_110px_minmax(0,1.6fr)_130px] gap-4 border-b border-line px-5 py-2.5 lg:grid">
        {["", "Tài khoản", "Proxy", "Phiên", "Nuôi", "Việc gần nhất", "Trạng thái"].map((h, i) => (
          <span key={i} className="label">
            {h}
          </span>
        ))}
      </div>

      {page.items.map((a) => (
        <Link
          key={a.id}
          href={`/tai-khoan/${a.id}`}
          className="grid grid-cols-[auto_auto_minmax(0,1fr)_auto] items-center gap-3 border-b border-line px-4 py-3 hover:bg-softer lg:grid-cols-[28px_minmax(0,2fr)_90px_130px_110px_minmax(0,1.6fr)_130px] lg:gap-4 lg:px-5"
        >
          <input
            type="checkbox"
            checked={selected.has(a.id)}
            onClick={(e) => {
              e.stopPropagation();
            }}
            onChange={(e) => {
              e.stopPropagation();
              toggle(a.id);
            }}
            onMouseDown={(e) => e.stopPropagation()}
          />
          <div className="flex items-center gap-2.5 lg:contents">
            <Avatar handle={a.handle} tone={a.ready ? "ok" : a.status === "dead" ? "muted" : "warn"} />
            <div className="flex min-w-0 flex-col lg:contents">
              <span className="mono truncate font-medium">{a.handle}</span>
              <span className="text-xs text-muted lg:hidden">
                {PLATFORM_LABEL[a.platform]} · {a.proxy_label ?? "chưa có proxy"} ·{" "}
                {a.warm_day ? `nuôi ngày ${a.warm_day}` : "chưa nuôi"}
              </span>
            </div>
          </div>
          <span className="mono hidden text-muted lg:block">{a.proxy_label ?? <span className="text-bad">— chưa có —</span>}</span>
          <span className="hidden lg:block">
            <SessionDot alive={a.session_alive} />
          </span>
          <span className="hidden text-muted lg:block">{a.warm_day ? `ngày ${a.warm_day}` : "chưa bắt đầu"}</span>
          <span className="hidden truncate text-muted lg:block">
            {a.last_posted_at ? `Đăng bài · ${timeAgo(a.last_posted_at)}` : "Chưa làm gì"}
          </span>
          <span className="col-start-4 row-start-1 lg:col-start-auto lg:row-start-auto">
            <StatusPill account={a} />
          </span>
        </Link>
      ))}

      <div className="flex flex-col gap-2 bg-softer px-4 py-3 text-sm text-muted sm:flex-row sm:items-center sm:justify-between lg:px-5">
        <span>
          {blocked > 0
            ? `${blocked} tài khoản chưa sẵn sàng — ${freeProxies > 0 ? `có ${freeProxies} proxy rảnh` : "dán thêm proxy là dùng được"}.`
            : "Mọi tài khoản trong trang đều sẵn sàng."}
        </span>
        <span className="flex items-center gap-2">
          <button className="btn btn-ghost text-xs" disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - PAGE))}>
            ‹
          </button>
          {offset + 1}–{Math.min(offset + PAGE, page.total)} trong {page.total}
          <button className="btn btn-ghost text-xs" disabled={offset + PAGE >= page.total} onClick={() => onPage(offset + PAGE)}>
            ›
          </button>
        </span>
      </div>
    </div>
  );
}

function ProxyList({ proxies, onChange }: { proxies: Proxy[]; onChange: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (proxies.length === 0) return <Empty>Chưa có proxy. Bấm “Dán proxy”.</Empty>;

  async function test(p: Proxy) {
    setBusy(p.id);
    try {
      await api.post(`/proxies/${p.id}/test`);
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }
  async function remove(p: Proxy) {
    if (!confirm(`Xoá ${p.label}?`)) return;
    try {
      await api.del(`/proxies/${p.id}`);
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="card overflow-hidden">
      <ErrorNote message={error} />
      {proxies.map((p) => (
        <div key={p.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-line px-4 py-3 lg:px-5">
          <span className="mono w-14 font-medium">{p.label}</span>
          <span className="mono text-muted">
            {p.host}:{p.port}
          </span>
          <span
            className={
              "pill " +
              (p.status === "ok" ? "bg-ok-soft text-ok-text" : p.status === "failing" ? "bg-bad-soft text-bad-text" : "bg-soft text-muted")
            }
          >
            {p.status === "ok" ? "OK" : p.status === "failing" ? "hỏng" : "chưa thử"}
          </span>
          <span className="mono text-xs text-muted">{p.last_exit_ip ?? ""}</span>
          {p.tiktok_render && (
            <span
              className={"text-xs " + (p.tiktok_last_ok ? "text-ok-text" : "text-warn-text")}
              title="Web TikTok qua proxy này: số lần hiện trang / số lần mở, thời gian hiện trung bình (từ các job trình duyệt)"
            >
              TikTok {p.tiktok_render}
            </span>
          )}
          <span className="text-sm text-muted">{p.bound_handle ? `→ ${p.bound_handle}` : "rảnh"}</span>
          <span className="grow" />
          <button className="btn btn-ghost text-xs" disabled={busy === p.id} onClick={() => test(p)}>
            {busy === p.id ? "đang thử…" : "thử"}
          </button>
          {!p.bound_handle && (
            <button className="btn btn-ghost text-xs text-bad-text" onClick={() => remove(p)}>
              xoá
            </button>
          )}
          {p.last_error && p.status === "failing" && (
            <div className="w-full text-xs text-bad-text">{p.last_error}</div>
          )}
        </div>
      ))}
    </div>
  );
}
