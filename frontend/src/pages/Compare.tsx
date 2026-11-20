import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, keys } from "@/api/hooks";
import type { CompareCell, ComparePayload } from "@/api/types";
import { EmptyState, ErrorNotice } from "@/components/EmptyState";
import { fmtCount, fmtNumber, fmtPct } from "@/lib/format";

const MAX_PICK = 4;

/** 数据集对比（FR-29 / BR-13）。
 *
 * 这个页面的价值是"并排看"，不是"比出胜负"。所以：
 * 1. 表头把每份数据的**判定口径**摆出来（区间版本、是否统一口径），口径不同就写在横幅里；
 * 2. 每一格只给"描述统计 + 三态占比"，不给 p 值、不写"显著"（后端接口根本没有这些字段）；
 * 3. 缺指标的列留空并解释原因，不补 0——补 0 会让「没测」和「测出来是 0」看起来一样。
 */
export function Compare() {
  const [picked, setPicked] = useState<string[]>([]);

  const datasets = useQuery({
    queryKey: keys.datasets,
    queryFn: api.datasets,
  });

  const items = datasets.data?.items ?? [];

  // 默认选中前两份：进来就有内容，而不是一个空表格 + "请选择"
  useEffect(() => {
    if (picked.length === 0 && items.length >= 2) {
      setPicked(items.slice(0, 2).map((item) => item.dataset_id));
    }
  }, [items, picked.length]);

  const canCompare = picked.length >= 2;
  const compare = useQuery({
    queryKey: keys.compare(picked, []),
    queryFn: () => api.compare(picked),
    enabled: canCompare,
  });

  const payload: ComparePayload | undefined = compare.data;
  const nameOf = useMemo(() => {
    const map = new Map<string, string>();
    for (const item of items) map.set(item.dataset_id, item.name);
    return (id: string) => map.get(id) ?? id.slice(0, 8);
  }, [items]);

  function toggle(id: string) {
    setPicked((current) => {
      if (current.includes(id)) return current.filter((item) => item !== id);
      if (current.length >= MAX_PICK) return current;
      return [...current, id];
    });
  }

  if (datasets.isError) return <ErrorNotice error={datasets.error} />;

  return (
    <div className="flex flex-col gap-3">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-[15px] font-semibold" style={{ color: "var(--color-text-primary)" }}>
            数据集对比
          </h1>
          <p className="mt-1 text-[12px]" style={{ color: "var(--color-text-muted)" }}>
            选择 2–{MAX_PICK} 份数据并排查看描述统计与三态占比。样本来源不同，这里只做展示，不做任何统计检验。
          </p>
        </div>
        <span className="text-[11px]" style={{ color: "var(--color-text-muted)" }}>
          已选 {picked.length} / {MAX_PICK}
        </span>
      </header>

      <section className="card lift p-3">
        <div className="flex flex-wrap gap-2">
          {items.map((item) => {
            const active = picked.includes(item.dataset_id);
            const disabled = !active && picked.length >= MAX_PICK;
            return (
              <button
                key={item.dataset_id}
                type="button"
                onClick={() => toggle(item.dataset_id)}
                disabled={disabled}
                className="rounded border px-2 py-1 text-left text-[11px] transition disabled:opacity-40"
                style={{
                  borderColor: active ? "var(--color-brand)" : "var(--color-border)",
                  backgroundColor: active ? "var(--color-brand-soft)" : "transparent",
                  color: active ? "var(--color-brand)" : "var(--color-text-secondary)",
                }}
              >
                <span className="block">{item.name}</span>
                <span style={{ color: "var(--color-text-muted)" }}>
                  {fmtCount(item.rows)} 行 · {item.ri_version}
                  {item.unified_ranges ? " · 统一口径" : ""}
                </span>
              </button>
            );
          })}
          {items.length === 0 && !datasets.isLoading && (
            <EmptyState title="还没有数据集" description="先到工作台上传一份 CSV，再回来做并排对比。" />
          )}
        </div>
      </section>

      {!canCompare && items.length > 0 && (
        <p className="text-[12px]" style={{ color: "var(--color-text-muted)" }}>
          至少选择 2 份数据才能对比（当前 {picked.length} 份）。
        </p>
      )}

      {compare.isError && <ErrorNotice error={compare.error} />}
      {canCompare && compare.isLoading && <p className="text-[12px]">计算中…</p>}

      {payload && (
        <>
          <section className="card lift p-3">
            <div className="flex flex-wrap gap-3">
              {payload.datasets.map((item) => (
                <div key={item.dataset_id} className="text-[11px]" style={{ color: "var(--color-text-secondary)" }}>
                  <div className="font-medium" style={{ color: "var(--color-text-primary)" }}>
                    {item.name}
                  </div>
                  <div style={{ color: "var(--color-text-muted)" }}>
                    {fmtCount(item.rows)} 行 · 区间 {item.ri_version} · 口径 {item.ri_source}
                    {item.unified_ranges ? "（统一口径）" : ""}
                  </div>
                  <div style={{ color: "var(--color-text-muted)" }}>
                    判定时刻 {item.judged_at ? item.judged_at.slice(0, 16).replace("T", " ") : "—"}
                  </div>
                </div>
              ))}
            </div>
            <ul className="mt-2 flex flex-col gap-1 text-[11px]" style={{ color: "var(--color-text-secondary)" }}>
              {payload.notes.map((note) => (
                <li key={note}>· {note}</li>
              ))}
            </ul>
            <p className="mt-2 rounded px-2 py-1 text-[11px]" style={{ backgroundColor: "var(--color-brand-soft)", color: "var(--color-brand)" }}>
              {payload.disclaimer}
            </p>
          </section>

          <section className="card p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-[13px] font-medium" style={{ color: "var(--color-text-secondary)" }}>
                指标并排
              </h2>
              <Legend />
            </div>

            {payload.side_by_side.length === 0 && (
              <EmptyState title="没有可对比的指标" description="两份数据没有共同的血液指标，或者所选指标在两边都为空。" />
            )}

            {payload.side_by_side.length > 0 && (
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-[11px]">
                  <thead style={{ color: "var(--color-text-muted)" }}>
                    <tr>
                      <th className="sticky left-0 px-2 py-1 text-left font-normal" style={{ backgroundColor: "var(--color-bg-surface)" }}>
                        指标
                      </th>
                      {payload.datasets.map((item) => (
                        <th key={item.dataset_id} className="px-2 py-1 text-left font-normal">
                          {nameOf(item.dataset_id)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {payload.side_by_side.map((row) => (
                      <tr key={row.metric} className="border-t align-top" style={{ borderColor: "var(--color-border)" }}>
                        <th className="sticky left-0 px-2 py-2 text-left font-normal" style={{ backgroundColor: "var(--color-bg-surface)", color: "var(--color-text-primary)" }}>
                          {row.name_cn}
                          <span className="ml-1" style={{ color: "var(--color-text-muted)" }}>
                            {row.unit}
                          </span>
                        </th>
                        {payload.datasets.map((item) => {
                          const cell = row.cells.find((candidate) => candidate.dataset_id === item.dataset_id);
                          return (
                            <td key={item.dataset_id} className="px-2 py-2">
                              {cell ? <Cell cell={cell} decimals={row.decimals} unit={row.unit} /> : (
                                <span style={{ color: "var(--color-text-muted)" }}>该数据集没有这一列</span>
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {payload.excluded.length > 0 && (
              <div className="mt-3">
                <h3 className="text-[12px] font-medium" style={{ color: "var(--color-text-secondary)" }}>
                  未参与对比（{payload.excluded.length}）
                </h3>
                <ul className="mt-1 flex flex-col gap-0.5 text-[11px]" style={{ color: "var(--color-text-muted)" }}>
                  {payload.excluded.map((item) => (
                    <li key={`${item.dataset_id}-${item.metric}`}>
                      · {item.dataset_name} / {item.metric}：{item.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}

function Cell({ cell, decimals, unit }: { cell: CompareCell; decimals: number; unit: string }) {
  return (
    <div className="flex flex-col gap-1">
      <div style={{ color: "var(--color-text-primary)" }}>
        中位 {fmtNumber(cell.median, decimals)}
        {unit ? ` ${unit}` : ""}
        <span className="ml-1" style={{ color: "var(--color-text-muted)" }}>
          （n = {fmtCount(cell.n)}
          {cell.missing > 0 ? `，缺 ${fmtCount(cell.missing)}` : ""}）
        </span>
      </div>
      <div style={{ color: "var(--color-text-muted)" }}>
        均值 {fmtNumber(cell.mean, decimals)} · 四分位 {fmtNumber(cell.q1, decimals)}–{fmtNumber(cell.q3, decimals)}
      </div>
      <Stacked cell={cell} />
      <div className="flex flex-wrap gap-2" style={{ color: "var(--color-text-muted)" }}>
        <span>偏低 {fmtPct(cell.pct_low)}</span>
        <span>正常 {fmtPct(cell.pct_normal)}</span>
        <span>偏高 {fmtPct(cell.pct_above)}</span>
        {cell.pct_na && cell.pct_na > 0 ? <span>未判定 {fmtPct(cell.pct_na)}</span> : null}
      </div>
    </div>
  );
}

function Stacked({ cell }: { cell: CompareCell }) {
  const segments = [
    { key: "low", value: cell.pct_low ?? 0, color: "var(--color-status-low)", label: "偏低" },
    { key: "normal", value: cell.pct_normal ?? 0, color: "var(--color-status-normal)", label: "正常" },
    { key: "above", value: cell.pct_above ?? 0, color: "var(--color-status-high)", label: "偏高" },
    { key: "na", value: cell.pct_na ?? 0, color: "var(--color-status-na)", label: "未判定" },
  ];
  return (
    <div className="flex h-1.5 w-40 overflow-hidden rounded" style={{ backgroundColor: "var(--color-bg-subtle)" }}>
      {segments.map((segment) =>
        segment.value > 0 ? (
          <span
            key={segment.key}
            title={`${segment.label} ${fmtPct(segment.value)}`}
            style={{ width: `${segment.value * 100}%`, backgroundColor: segment.color }}
          />
        ) : null,
      )}
    </div>
  );
}

function Legend() {
  const entries = [
    { color: "var(--color-status-low)", label: "偏低" },
    { color: "var(--color-status-normal)", label: "正常" },
    { color: "var(--color-status-high)", label: "偏高" },
    { color: "var(--color-status-na)", label: "未判定" },
  ];
  return (
    <div className="flex flex-wrap items-center gap-2 text-[11px]" style={{ color: "var(--color-text-muted)" }}>
      {entries.map((entry) => (
        <span key={entry.label} className="flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm" style={{ backgroundColor: entry.color }} />
          {entry.label}
        </span>
      ))}
    </div>
  );
}
