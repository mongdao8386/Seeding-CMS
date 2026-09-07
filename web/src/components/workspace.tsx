"use client";

import { createContext, useContext, useEffect, useState } from "react";
import Link from "next/link";
import { api, type Named } from "@/lib/api";
import { AUTH_READY } from "@/components/token-gate";

const KEY = "seeding-cms-workspace";

type Ctx = {
  id: string;
  name: string;
  list: Named[];
  setId: (id: string) => void;
  reload: () => void;
};

const WorkspaceCtx = createContext<Ctx>({
  id: "",
  name: "",
  list: [],
  setId: () => {},
  reload: () => {},
});

export const useWorkspace = () => useContext(WorkspaceCtx);

/**
 * Workspace dang chon, dung chung cho ca dashboard.
 *
 * Truoc day moi man hinh tu hoi lay workspace rieng, va man hinh Accounts thi khong
 * hoi gi ca - no liet ke tat ca tai khoan cua moi workspace. Ket qua la o chon
 * workspace trong form tao tai khoan trong nhu mot cai dieu khien nhung khong dieu
 * khien gi: chon workspace nao thi danh sach persona van y het.
 *
 * Luu trong localStorage de khong bi mat khi chuyen trang.
 */
export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const [list, setList] = useState<Named[]>([]);
  const [id, setIdState] = useState("");
  const [nonce, setNonce] = useState(0);

  // Provider nay nam NGOAI TokenGate, nen lan goi dau tien co the roi vao luc chua co
  // token. Nghe tin hieu tu TokenGate de goi lai ngay khi dang nhap xong, thay vi de o
  // chon nam trong cho toi luc nguoi dung tai lai trang.
  useEffect(() => {
    const again = () => setNonce((n) => n + 1);
    window.addEventListener(AUTH_READY, again);
    return () => window.removeEventListener(AUTH_READY, again);
  }, []);

  useEffect(() => {
    api
      .get<Named[]>("/workspaces")
      .then((rows) => {
        setList(rows);
        setIdState((current) => {
          if (current && rows.some((w) => w.id === current)) return current;
          let saved: string | null = null;
          try {
            saved = localStorage.getItem(KEY);
          } catch {
            /* trinh duyet chan localStorage - cu chon cai dau tien */
          }
          if (saved && rows.some((w) => w.id === saved)) return saved;
          return rows[0]?.id ?? "";
        });
      })
      .catch(() => setList([]));
  }, [nonce]);

  function setId(next: string) {
    setIdState(next);
    try {
      localStorage.setItem(KEY, next);
    } catch {
      /* khong luu duoc thi van dung duoc trong phien nay */
    }
  }

  const name = list.find((w) => w.id === id)?.name ?? "";

  return (
    <WorkspaceCtx.Provider
      value={{ id, name, list, setId, reload: () => setNonce((n) => n + 1) }}
    >
      {children}
    </WorkspaceCtx.Provider>
  );
}

/**
 * O chon tren thanh dieu huong.
 *
 * KHONG tu an di khi danh sach rong. Ban dau no `return null` cho truong hop do, va
 * chinh dieu do lam mot loi that tro nen vo hinh: provider bi dat sai cho nen danh
 * sach luon rong, o chon luon an, va nhin vao giao dien thi giong het nhu tinh nang
 * chua bao gio duoc lam. Mot dieu khien tu bien mat khong bao cho ai biet la no hong.
 */
export function WorkspacePicker() {
  const { id, list, setId } = useWorkspace();

  if (list.length === 0) {
    return (
      <span className="faint text-xs" title="No workspaces loaded yet">
        no workspace
      </span>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <label className="flex items-center gap-2">
        <span className="label">workspace</span>
        <select
          value={id}
          onChange={(e) => setId(e.target.value)}
          className="text-sm"
          style={{ maxWidth: 190 }}
        >
          {list.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </select>
      </label>

      {/*
        Duong di thang tu cho CHON sang cho SUA. Nguoi dung dang nghi ve workspace o
        dung cho nay; bat ho di tim mot muc o cuoi thanh menu la bat ho nho ra rang
        muc do ton tai.
      */}
      <Link
        href="/workspaces"
        className="label hover:opacity-70"
        style={{ color: "var(--a)" }}
        title="Rename, delete, or create a workspace"
      >
        edit
      </Link>
    </div>
  );
}
