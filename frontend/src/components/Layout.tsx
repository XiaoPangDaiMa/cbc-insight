import { NavLink, Outlet, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api, keys } from "@/api/hooks";
import { useAuth } from "@/auth/session";
import { IconChevron, IconCompare, IconDataset, IconDownload, IconLogout, IconSliders, IconWorkbench } from "@/components/icons";

/** 侧栏分三组：先"我在哪份数据上"，再"我有哪些配置"，最后"我是谁"。
 *
 * 之前五个条目平铺，工作台与"我的参考区间"看着是同一类东西；
 * 分组之后用户扫一眼就知道哪几个是数据、哪几个是设置。
 */
const NAV_GROUPS = [
  {
    title: "数据",
    items: [
      { to: "/", label: "工作台", icon: IconWorkbench, end: true },
      { to: "/compare", label: "数据集对比", icon: IconCompare },
    ],
  },
  {
    title: "配置",
    items: [
      { to: "/reference", label: "我的参考区间", icon: IconSliders },
      { to: "/export", label: "导出中心", icon: IconDownload },
    ],
  },
];

export function Layout() {
  const { session, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const datasetId = params.get("dataset");
  // 数据集详情页在导航里归到「工作台」之下：用户点的是"我的数据"，不是另一个模块。
  const onDataset = location.pathname.startsWith("/datasets");

  const workspace = useQuery({ queryKey: keys.workspace, queryFn: api.workspace });
  const datasets = workspace.data?.datasets ?? [];
  const current = datasets.find((item) => item.dataset_id === datasetId);
  const initials = (session?.username ?? "?").slice(0, 1).toUpperCase();

  return (
    <div className="flex h-screen overflow-hidden" style={{ backgroundColor: "var(--color-bg-page)" }}>
      <aside
        className="hidden h-full w-[232px] shrink-0 flex-col overflow-y-auto border-r px-2.5 pb-3 pt-3 md:flex"
        style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-bg-surface)" }}
      >
        <div className="flex items-center gap-2 px-2 pb-4">
          <span
            className="flex h-8 w-8 items-center justify-center rounded-lg text-[12px] font-semibold"
            style={{ backgroundColor: "var(--color-brand-soft)", color: "var(--color-brand)" }}
            aria-hidden="true"
          >
            CI
          </span>
          <span className="min-w-0">
            <span className="block truncate text-[15px] font-semibold leading-tight" style={{ color: "var(--color-text-primary)" }}>
              CBC Insight
            </span>
            <span className="block truncate text-[11px]" style={{ color: "var(--color-text-muted)" }}>
              血常规数据分析
            </span>
          </span>
        </div>

        <nav className="flex flex-col gap-0.5" aria-label="主导航">
          {NAV_GROUPS.map((group) => (
            <div key={group.title} className="flex flex-col">
              <div className="nav-group-title">{group.title}</div>
              {group.items.map((item) => {
                const Icon = item.icon;
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.end}
                    className={() => `nav-item${item.to === "/" && onDataset ? " is-active" : ""}`}
                  >
                    <Icon />
                    <span className="truncate">{item.label}</span>
                  </NavLink>
                );
              })}
            </div>
          ))}
        </nav>

        {/* 账户块固定在底部：用户名是"我登的是谁"，登出是操作，两者不该混在导航里 */}
        <div className="mt-auto pt-4">
          <div className="flex items-center gap-2 rounded-lg px-1.5 py-2" style={{ backgroundColor: "var(--color-bg-subtle)" }}>
            <span
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold"
              style={{ backgroundColor: "var(--color-brand)", color: "var(--color-bg-surface)" }}
              aria-hidden="true"
            >
              {initials}
            </span>
            <button
              type="button"
              onClick={() => navigate("/account")}
              className="min-w-0 flex-1 truncate text-left text-[12px]"
              style={{ color: "var(--color-text-secondary)" }}
              title="账号设置"
            >
              {session?.username}
            </button>
            <button
              type="button"
              className="icon-btn"
              title="登出"
              aria-label="登出"
              onClick={async () => {
                await logout();
                navigate("/login", { replace: true });
              }}
            >
              <IconLogout />
            </button>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header
          className="flex h-13 shrink-0 items-center justify-between gap-3 border-b px-4 py-2"
          style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-bg-surface)" }}
        >
          <div className="flex min-w-0 items-center gap-2">
            <IconDataset style={{ color: "var(--color-text-muted)" }} />
            <span className="shrink-0 text-[11px]" style={{ color: "var(--color-text-muted)" }}>
              当前数据集
            </span>
            <div className="relative min-w-0">
              <select
                value={datasetId ?? ""}
                onChange={(event) => {
                  const value = event.target.value;
                  if (value) navigate(`/datasets/${value}?dataset=${value}`);
                  else navigate("/");
                }}
                className="max-w-[280px] appearance-none truncate rounded-md border py-1 pl-2 pr-7 text-[12px]"
                style={{
                  borderColor: current ? "var(--color-border-strong)" : "var(--color-border)",
                  backgroundColor: "var(--color-bg-surface)",
                  color: current ? "var(--color-text-primary)" : "var(--color-text-muted)",
                }}
                aria-label="选择数据集"
              >
                <option value="">未选择数据集</option>
                {datasets.map((dataset) => (
                  <option key={dataset.dataset_id} value={dataset.dataset_id}>
                    {dataset.name}（{dataset.rows} 行）
                  </option>
                ))}
              </select>
              <IconChevron
                className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2"
                style={{ color: "var(--color-text-muted)" }}
              />
            </div>
            {current && (
              <span className="hidden truncate text-[11px] sm:inline" style={{ color: "var(--color-text-muted)" }}>
                · {current.rows} 行 · 区间 {current.ri_version}
              </span>
            )}
          </div>
          <div className="hidden shrink-0 text-[11px] md:block" style={{ color: "var(--color-text-muted)" }}>
            只做分布与区间判定，不做诊断
          </div>
        </header>

        {/* 窄屏（<768px）没有侧栏，导航改成横向可滚的一条。
            刻意不做抽屉：五个入口，滑一下比打开抽屉再点一下少一步。 */}
        <nav
          className="flex shrink-0 items-center gap-1 overflow-x-auto border-b px-2 py-1.5 md:hidden"
          style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-bg-surface)" }}
          aria-label="主导航（窄屏）"
        >
          {NAV_GROUPS.flatMap((group) => group.items).map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={() => `nav-item shrink-0 whitespace-nowrap${item.to === "/" && onDataset ? " is-active" : ""}`}
              >
                <Icon />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
          <NavLink to="/account" className="nav-item shrink-0 whitespace-nowrap">
            <span>账号</span>
          </NavLink>
        </nav>

        <main className="min-w-0 flex-1 overflow-y-auto p-3 sm:p-4">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
