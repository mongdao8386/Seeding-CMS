"use client";

import { useEffect, useState } from "react";
import { api, type ImportCheck, type ImportResult, type Platform, type ProxyImportResult } from "@/lib/api";

import { PLATFORMS, PLATFORM_LABEL } from "@/components/ui";

/**
 * Dán tài khoản theo định dạng người bán: username|password|hotmail|pass_hotmail|cookie
 * (có header hay không đều được). Kiểm trước, tạo sau.
 */
export function ImportAccounts({ onDone, onClose }: { onDone: () => void; onClose: () => void }) {
  const [text, setText] = useState("");
  const [platform, setPlatform] = useState<Platform>("tiktok");
  const [role, setRole] = useState<"channel" | "booster">("channel");
  const [check, setCheck] = useState<ImportCheck | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Kiểm sau khi ngừng gõ một nhịp — kết quả kiểm là thứ người dùng nhìn để quyết định.
  useEffect(() => {
    if (!text.trim()) {
      setCheck(null);
      return;
    }
    const t = setTimeout(async () => {
      try {
        setCheck(await api.form<ImportCheck>("/accounts/import/check", { text, platform, role }));
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    }, 500);
    return () => clearTimeout(t);
  }, [text, platform, role]);

  async function run(partial: boolean) {
    setBusy(true);
    setError(null);
    try {
      const r = await api.form<ImportResult>("/accounts/import", {
        text,
        platform,
        role,
        partial,
        attach_proxies: true,
      });
      setResult(r);
      if (r.created > 0) onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const problems = check?.problems.length ?? 0;

  return (
    <div className="card mb-5 flex flex-col gap-4 p-4 sm:p-5">
      <div className="flex items-center justify-between">
        <span className="label">Dán tài khoản</span>
        <button className="btn btn-ghost text-xs" onClick={onClose}>
          đóng
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-muted">Nền tảng</span>
        {PLATFORMS.map((p) => (
          <button key={p} className="chip" data-on={platform === p} onClick={() => setPlatform(p)}>
            {PLATFORM_LABEL[p]}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-muted">Loại</span>
        <button className="chip" data-on={role === "channel"} onClick={() => setRole("channel")}>
          Xây kênh
        </button>
        <button className="chip" data-on={role === "booster"} onClick={() => setRole("booster")}>
          Tương tác chéo
        </button>
        <span className="text-xs text-faint">
          {role === "booster" ? "Chỉ thả tim / follow / bình luận vào bài của acc xây kênh. Không đăng, không cần proxy." : "Đăng bài, nuôi, được đội tương tác chéo đẩy. Cần proxy."}
        </span>
      </div>

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={"username|password|hotmail|pass_hotmail|cookie\nuser123|matkhau|a@hotmail.com|pass|sessionid=...; ttwid=..."}
        spellCheck={false}
      />

      {error && <p className="text-bad-text">{error}</p>}

      {check && (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap gap-4 text-sm">
            <span>
              <b>{check.ready}</b> dòng dùng được
            </span>
            <span className={check.with_cookies === check.ready ? "text-ok-text" : "text-warn-text"}>
              <b>{check.with_cookies}</b> có phiên đăng nhập
            </span>
            {check.cookie_problems > 0 && (
              <span className="text-warn-text">
                <b>{check.cookie_problems}</b> cookie hỏng
              </span>
            )}
            {problems > 0 && (
              <span className="text-bad-text">
                <b>{problems}</b> dòng có vấn đề
              </span>
            )}
          </div>
          {problems > 0 && (
            <ul className="text-sm text-muted">
              {check.problems.slice(0, 6).map((p) => (
                <li key={p.line}>
                  dòng {p.line}
                  {p.handle ? ` (${p.handle})` : ""}: {p.detail}
                </li>
              ))}
              {problems > 6 && <li>…và {problems - 6} dòng nữa</li>}
            </ul>
          )}
        </div>
      )}

      {result && (
        <div className={"rounded-lg p-3 text-sm " + (result.created ? "bg-ok-soft text-ok-text" : "bg-warn-soft text-warn-text")}>
          {result.created > 0 ? (
            <>
              Đã tạo <b>{result.created}</b> tài khoản, {result.profiles_with_session} có phiên đăng nhập.
            </>
          ) : (
            "Chưa nhập gì."
          )}
          {result.warnings.map((w, i) => (
            <div key={i} className="mt-1">
              {w}
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          className="btn btn-primary"
          disabled={busy || !check || check.ready === 0 || problems > 0}
          onClick={() => run(false)}
        >
          {busy ? "Đang nhập…" : `Nhập ${check?.ready ?? 0} tài khoản`}
        </button>
        {problems > 0 && check && check.ready > 0 && (
          <button className="btn" disabled={busy} onClick={() => run(true)}>
            Nhập {check.ready} dòng tốt, bỏ {problems} dòng hỏng
          </button>
        )}
        <span className="self-center text-xs text-faint">
          Mỗi tài khoản có phiên sẽ được gắn một proxy rảnh đã thử OK. Hết proxy thì dán thêm.
        </span>
      </div>
    </div>
  );
}

/** Dán proxy: host:port, host:port:user:pass, user:pass@host:port. */
export function ImportProxies({ onDone, onClose }: { onDone: () => void; onClose: () => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ProxyImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const lines = text.split("\n").filter((l) => l.trim() && !l.trim().startsWith("#")).length;

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.form<ProxyImportResult>("/proxies/import", { text, test: true });
      setResult(r);
      if (r.created > 0) onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card mb-5 flex flex-col gap-4 p-4 sm:p-5">
      <div className="flex items-center justify-between">
        <span className="label">Dán proxy</span>
        <button className="btn btn-ghost text-xs" onClick={onClose}>
          đóng
        </button>
      </div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={"host:port:user:pass\nuser:pass@host:port\nhost:port"}
        spellCheck={false}
      />
      {error && <p className="text-bad-text">{error}</p>}
      {result && (
        <div className="rounded-lg bg-softer p-3 text-sm">
          Đã thêm <b>{result.created}</b>, thử <b>{result.tested}</b>, qua <b className="text-ok-text">{result.passed}</b>.
          {result.duplicate_exit_ips.length > 0 && (
            <div className="mt-1 text-warn-text">
              Trùng IP ra: {result.duplicate_exit_ips.join(", ")} — hai proxy này thực ra là một lối ra.
            </div>
          )}
          {result.results
            .filter((r) => !r.ok)
            .map((r) => (
              <div key={r.label} className="mt-1 text-bad-text">
                {r.label}: {r.error}
              </div>
            ))}
          {result.problems.map((p) => (
            <div key={p.line} className="mt-1 text-warn-text">
              dòng {p.line}: {p.detail}
            </div>
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <button className="btn btn-primary" disabled={busy || lines === 0} onClick={run}>
          {busy ? "Đang thử từng proxy…" : `Thêm và thử ${lines} proxy`}
        </button>
        <span className="text-xs text-faint">Thử tuần tự, mỗi cái vài giây.</span>
      </div>
    </div>
  );
}
