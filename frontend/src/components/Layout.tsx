import { NavLink, Outlet, useNavigate, useSearchParams } from "react-router-dom";

import { useAuth } from "@/auth/session";
import { useQuery } from "@tanstack/react-query";
import { api, keys } from "@/api/hooks";

const NAV = [
  { to: "/", label: "工作台", end: true },
  { to: "/reference", label: "我的参考区间" },
  { to: "/export", label: "导出中心" },
  { to: "/account", label: "账号" },
];

export function Layout() {
  const { session, logout } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const datasetId = params.get("dataset");

  const workspace = useQuery({ queryKey: keys.workspace, queryFn: api.workspace });

  return (
    <div className="flex h-screen overflow-hidden" style={{ backgroundColor: "var(--color-bg-page)" }}>
      <aside
        className="flex h-full w-52 shrink-0 flex-col gap-1 overflow-y-auto border-r p-3"
        style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-bg-surface)" }}
      >
        <div className="px-2 py-3">
          <div className="text-sm font-semibold" style={{ color: "var(--color-brand)" }}>
            CBC Insight
          </div>
          <div className="text-[11px]" style={{ color: "var(--color-text-muted)" }}>
            血常规数据分析
          </div>
        </div>
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className="rounded px-2 py-1.5 text-[13px]"
            style={({ isActive }) => ({
              backgroundColor: isActive ? "var(--color-brand-soft)" : "transparent",
              color: isActive ? "var(--color-brand)" : "var(--color-text-secondary)",
            })}
          >
            {item.label}
          </NavLink>
        ))}
        <div className="mt-auto border-t pt-3 text-[11px]" style={{ borderColor: "var(--color-border)", color: "var(--color-text-muted)" }}>
          <div className="px-2">{session?.username}</div>
          <button
            type="button"
            onClick={async () => {
              await logout();
              navigate("/login", { replace: true });
            }}
            className="mt-1 px-2 py-1 text-left"
            style={{ color: "var(--color-text-secondary)" }}
          >
            登出
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header
          className="flex h-12 shrink-0 items-center justify-between gap-3 border-b px-4"
          style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-bg-surface)" }}
        >
          <div className="flex items-center gap-2 text-[12px]" style={{ color: "var(--color-text-secondary)" }}>
            <span style={{ color: "var(--color-text-muted)" }}>当前数据集</span>
            <select
              value={datasetId ?? ""}
              onChange={(event) => {
                const value = event.target.value;
                if (value) navigate(`/datasets/${value}`);
                else navigate("/");
              }}
              className="rounded border px-2 py-1 text-[12px]"
              style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-bg-surface)" }}
            >
              <option value="">（未选择）</option>
              {(workspace.data?.datasets ?? []).map((dataset) => (
                <option key={dataset.dataset_id} value={dataset.dataset_id}>
                  {dataset.name}（{dataset.rows} 行）
                </option>
              ))}
            </select>
          </div>
          <div className="text-[11px]" style={{ color: "var(--color-text-muted)" }}>
            只做分布与区间判定，不做诊断
          </div>
        </header>

        <main className="min-w-0 flex-1 overflow-y-auto p-4">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
