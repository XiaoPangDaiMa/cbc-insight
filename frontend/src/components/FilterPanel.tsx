import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, exportPath, keys } from "@/api/hooks";
import type { FilterClause, MetricStatusItem } from "@/api/types";
import { fmtNumber } from "@/lib/format";
import { EmptyState, ErrorNotice } from "@/components/EmptyState";
import { ExportButton, useExport } from "@/lib/useExport";

type Op = FilterClause["op"];

const OPS: { value: Op; label: string }[] = [
  { value: "lt", label: "小于" },
  { value: "lte", label: "小于等于" },
  { value: "gt", label: "大于" },
  { value: "gte", label: "大于等于" },
  { value: "between", label: "介于" },
  { value: "eq", label: "等于" },
];

const PAGE_SIZE = 20;

/** 筛选页（FR-14、FR-15、FR-35）。
 *
 * 三个刻意的取舍：
 * 1. **条件为"与"**，不是"或"——医学上的"20–30 岁且 HGB 偏低"是交集，写错就是另一批人；
 * 2. 表格只展示、不就地编辑：一改条件就重算，避免"看到的是旧结果"；
 * 3. 导出按钮带的是**同一份条件**，所以导出条数恒等于页面上的命中数（T-29）。
 */
export function FilterPanel({ datasetId, metrics }: { datasetId: string; metrics: MetricStatusItem[] }) {
  const exporter = useExport();
  const [metric, setMetric] = useState(metrics[0]?.metric ?? "hgb");
  const [op, setOp] = useState<Op>("lt");
  const [value, setValue] = useState("");
  const [upper, setUpper] = useState("");
  const [gender, setGender] = useState("");
  const [ageMin, setAgeMin] = useState("");
  const [ageMax, setAgeMax] = useState("");
  const [page, setPage] = useState(1);
  const [applied, setApplied] = useState<{ filters: FilterClause[]; gender: string; ageMin: string; ageMax: string }>({
    filters: [],
    gender: "",
    ageMin: "",
    ageMax: "",
  });

  const filters = useMemo<FilterClause[]>(() => {
    const list: FilterClause[] = [];
    const low = Number(value);
    if (applied.filters.length === 0 && value !== "") return list;
    if (value !== "" && Number.isFinite(low)) {
      const clause: FilterClause = { metric, op, value: low };
      if (op === "between") {
        const high = Number(upper);
        if (!Number.isFinite(high)) return [];
        clause.upper = high;
      }
      list.push(clause);
    }
    return list;
  }, [applied, metric, op, upper, value]);

  const body = useMemo(
    () => ({
      filters: applied.filters,
      gender: applied.gender || null,
      age_min: applied.ageMin === "" ? null : Number(applied.ageMin),
      age_max: applied.ageMax === "" ? null : Number(applied.ageMax),
      page,
      size: PAGE_SIZE,
      stage: "cleaned",
    }),
    [applied, page],
  );

  const result = useQuery({
    queryKey: [...keys.dataset(datasetId), "query", body],
    queryFn: () => api.query(datasetId, body),
    enabled: Boolean(datasetId),
  });

  const exportOpts = {
    scope: "filtered" as const,
    filters: applied.filters,
    gender: applied.gender || null,
    ageMin: applied.ageMin === "" ? null : Number(applied.ageMin),
    ageMax: applied.ageMax === "" ? null : Number(applied.ageMax),
  };

  function apply() {
    setApplied({ filters, gender, ageMin, ageMax });
    setPage(1);
  }

  function reset() {
    setMetric(metrics[0]?.metric ?? "hgb");
    setOp("lt");
    setValue("");
    setUpper("");
    setGender("");
    setAgeMin("");
    setAgeMax("");
    setApplied({ filters: [], gender: "", ageMin: "", ageMax: "" });
    setPage(1);
  }

  const total = result.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const headers = result.data?.headers ?? [];
  const nameOf = (key: string) => {
    const item = metrics.find((m) => m.metric === key);
    return item?.name_cn ?? key;
  };

  return (
    <div className="flex flex-col gap-3">
      <section className="card lift p-3">
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-[11px]" style={{ color: "var(--color-text-muted)" }}>
            指标
            <select
              value={metric}
              onChange={(event) => setMetric(event.target.value)}
              className="rounded border px-2 py-1 text-[12px]"
              style={{ borderColor: "var(--color-border)", color: "var(--color-text-primary)" }}
            >
              {metrics.map((item) => (
                <option key={item.metric} value={item.metric}>
                  {item.name_cn}（{item.unit}）
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-[11px]" style={{ color: "var(--color-text-muted)" }}>
            条件
            <select
              value={op}
              onChange={(event) => setOp(event.target.value as Op)}
              className="rounded border px-2 py-1 text-[12px]"
              style={{ borderColor: "var(--color-border)", color: "var(--color-text-primary)" }}
            >
              {OPS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-[11px]" style={{ color: "var(--color-text-muted)" }}>
            数值
            <input
              value={value}
              onChange={(event) => setValue(event.target.value)}
              inputMode="decimal"
              placeholder="如 130"
              className="w-24 rounded border px-2 py-1 text-[12px]"
              style={{ borderColor: "var(--color-border)", color: "var(--color-text-primary)" }}
            />
          </label>

          {op === "between" && (
            <label className="flex flex-col gap-1 text-[11px]" style={{ color: "var(--color-text-muted)" }}>
              上限
              <input
                value={upper}
                onChange={(event) => setUpper(event.target.value)}
                inputMode="decimal"
                placeholder="如 175"
                className="w-24 rounded border px-2 py-1 text-[12px]"
                style={{ borderColor: "var(--color-border)", color: "var(--color-text-primary)" }}
              />
            </label>
          )}

          <label className="flex flex-col gap-1 text-[11px]" style={{ color: "var(--color-text-muted)" }}>
            性别
            <select
              value={gender}
              onChange={(event) => setGender(event.target.value)}
              className="rounded border px-2 py-1 text-[12px]"
              style={{ borderColor: "var(--color-border)", color: "var(--color-text-primary)" }}
            >
              <option value="">不限</option>
              <option value="male">男</option>
              <option value="female">女</option>
            </select>
          </label>

          <label className="flex flex-col gap-1 text-[11px]" style={{ color: "var(--color-text-muted)" }}>
            年龄下限
            <input
              value={ageMin}
              onChange={(event) => setAgeMin(event.target.value)}
              inputMode="numeric"
              placeholder="如 20"
              className="w-20 rounded border px-2 py-1 text-[12px]"
              style={{ borderColor: "var(--color-border)", color: "var(--color-text-primary)" }}
            />
          </label>

          <label className="flex flex-col gap-1 text-[11px]" style={{ color: "var(--color-text-muted)" }}>
            年龄上限
            <input
              value={ageMax}
              onChange={(event) => setAgeMax(event.target.value)}
              inputMode="numeric"
              placeholder="如 30"
              className="w-20 rounded border px-2 py-1 text-[12px]"
              style={{ borderColor: "var(--color-border)", color: "var(--color-text-primary)" }}
            />
          </label>

          <button
            type="button"
            onClick={apply}
            className="rounded px-3 py-1 text-[12px] font-medium"
            style={{ backgroundColor: "var(--color-brand)", color: "var(--color-bg-surface)" }}
          >
            应用
          </button>
          <button
            type="button"
            onClick={reset}
            className="rounded border px-3 py-1 text-[12px]"
            style={{ borderColor: "var(--color-border)", color: "var(--color-text-secondary)" }}
          >
            重置
          </button>
        </div>

        <p className="mt-2 text-[11px]" style={{ color: "var(--color-text-muted)" }}>
          多个条件之间是<b>与</b>的关系：只有同时满足的样本才会出现在下面。指标阈值比的是原始数值（单位见括号），
          不是"超出参考区间"的判定结果。
        </p>
      </section>

      <section className="card p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-[12px]" style={{ color: "var(--color-text-primary)" }}>
            命中 <b>{total}</b> 个样本
            {applied.filters.length > 0 && (
              <span style={{ color: "var(--color-text-muted)" }}>
                {" "}
                · 条件：{applied.filters.map((f) => `${nameOf(f.metric)} ${OPS.find((o) => o.value === f.op)?.label}
                ${fmtNumber(f.value, 0)}${f.upper ? `–${fmtNumber(f.upper, 0)}` : ""}`).join("，")}
              </span>
            )}
          </div>
          <ExportButton
            label={total > 0 ? `导出这 ${total} 条` : "导出（无命中）"}
            path={exportPath(datasetId, "filtered", exportOpts)}
            busy={exporter.busy}
            run={exporter.run}
            variant="solid"
          />
        </div>
        {exporter.error && <p className="mt-1 text-[11px]" style={{ color: "var(--color-status-high)" }}>{exporter.error}</p>}

        {result.error && <ErrorNotice error={result.error} />}
        {result.data && total === 0 && (
          <EmptyState title="没有符合条件的样本" description="把阈值放宽一些，或者点「重置」回到全量。" />
        )}
        {result.data && total > 0 && (
          <>
            <div className="mt-2 overflow-x-auto">
              <table className="row-hover w-full text-[11px]" style={{ color: "var(--color-text-secondary)" }}>
                <thead style={{ color: "var(--color-text-muted)" }}>
                  <tr>
                    {headers.map((head) => (
                      <th key={head} className="whitespace-nowrap px-2 py-1 text-left font-normal">
                        {head}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.data.rows.map((row, rowIndex) => (
                    <tr key={rowIndex} className="border-t" style={{ borderColor: "var(--color-border)" }}>
                      {row.map((cell, cellIndex) => (
                        <td key={cellIndex} className="whitespace-nowrap px-2 py-1">
                          {cell === null || cell === "" ? "—" : String(cell)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-2 flex items-center justify-between text-[11px]" style={{ color: "var(--color-text-muted)" }}>
              <span>
                第 {page} / {pages} 页
              </span>
              <div className="flex gap-1">
                <button
                  type="button"
                  disabled={page <= 1}
                  onClick={() => setPage((current) => Math.max(1, current - 1))}
                  className="rounded border px-2 py-0.5 disabled:opacity-40"
                  style={{ borderColor: "var(--color-border)" }}
                >
                  上一页
                </button>
                <button
                  type="button"
                  disabled={page >= pages}
                  onClick={() => setPage((current) => current + 1)}
                  className="rounded border px-2 py-0.5 disabled:opacity-40"
                  style={{ borderColor: "var(--color-border)" }}
                >
                  下一页
                </button>
              </div>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
