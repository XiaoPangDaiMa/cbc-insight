import { useQuery } from "@tanstack/react-query";

import { api, exportPath, keys } from "@/api/hooks";
import { fmtCount, fmtPct, patternLabel } from "@/lib/format";
import { ErrorNotice } from "@/components/EmptyState";
import { SkeletonCard, SkeletonTable } from "@/components/Skeleton";
import { ExportButton, useExport } from "@/lib/useExport";

const TOP_ROWS = 20;

/** 异常页（FR-17、FR-18、FR-30 的群体口径）。
 *
 * 三件事必须同时在场，缺一件就会被读成分诊结论：
 * 1. 分母（多少样本里有多少个异常样本），不是孤零零的百分比；
 * 2. 模式是"组合"而不是"病名"，所以每一条都带"倾向 / 偏低"这类描述性措辞；
 * 3. 未判定样本（缺性别、关键字段为空）单独列出——它们既不算异常也不算正常。
 */
export function AnomalyPanel({ datasetId }: { datasetId: string }) {
  const exporter = useExport();
  const anomaly = useQuery({
    queryKey: keys.anomaly(datasetId),
    queryFn: () => api.anomaly(datasetId),
    enabled: Boolean(datasetId),
  });
  const top = useQuery({
    queryKey: keys.exportPreview(datasetId, "summary", "only_abnormal"),
    queryFn: () => api.exportPreview(datasetId, "summary", { onlyAbnormal: true }),
    enabled: Boolean(datasetId),
  });

  if (anomaly.error) return <ErrorNotice error={anomaly.error} />;
  if (!anomaly.data) {
    return (
      <div className="flex flex-col gap-3">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }, (_, index) => (
            <SkeletonCard key={index} lines={2} height={88} />
          ))}
        </div>
        <SkeletonTable rows={8} columns={5} />
      </div>
    );
  }

  const data = anomaly.data;
  const patterns = Object.entries(data.pattern_counts).sort((a, b) => b[1] - a[1]);
  const patternMax = patterns.reduce((acc, [, count]) => Math.max(acc, count), 0) || 1;
  const headers = top.data?.headers ?? [];
  const rows = (top.data?.rows ?? []).slice(0, TOP_ROWS);

  const kpis = [
    { label: "异常率", value: fmtPct(data.anomaly_rate), hint: `${fmtCount(data.abnormal_samples)} / ${fmtCount(data.samples)} 个样本` },
    { label: "异常样本", value: fmtCount(data.abnormal_samples), hint: "至少一项超出参考区间" },
    { label: "异常项", value: fmtCount(data.abnormal_items), hint: "指标 × 样本 的越界次数" },
    { label: "未判定", value: fmtCount(data.na_samples), hint: `其中缺性别 ${fmtCount(data.gender_missing_samples)} 个样本` },
  ];

  return (
    <div className="flex flex-col gap-3">
      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {kpis.map((item) => (
          <div key={item.label} className="card lift p-3">
            <div className="text-[11px]" style={{ color: "var(--color-text-muted)" }}>
              {item.label}
            </div>
            <div className="mt-1 text-[20px] font-semibold" style={{ color: "var(--color-text-primary)" }}>
              {item.value}
            </div>
            <div className="mt-1 text-[11px]" style={{ color: "var(--color-text-muted)" }}>
              {item.hint}
            </div>
          </div>
        ))}
      </section>

      <section className="card p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-[13px] font-medium" style={{ color: "var(--color-text-secondary)" }}>
            模式分布
          </h2>
          <span className="text-[11px]" style={{ color: "var(--color-text-muted)" }}>
            区间口径 {data.ri_version}
          </span>
        </div>
        <ul className="mt-2 flex flex-col gap-1">
          {patterns.map(([pattern, count]) => (
            <li key={pattern} className="flex items-center gap-2 text-[11px]">
              <span className="w-40 shrink-0 truncate" style={{ color: "var(--color-text-secondary)" }} title={pattern}>
                {patternLabel(pattern)}
              </span>
              <span className="h-2 flex-1 overflow-hidden rounded" style={{ backgroundColor: "var(--color-bg-subtle)" }}>
                <span
                  className="block h-full rounded"
                  style={{
                    width: `${Math.max(2, (count / patternMax) * 100)}%`,
                    backgroundColor: pattern === "NORMAL" ? "var(--color-status-normal)" : "var(--color-brand)",
                  }}
                />
              </span>
              <span className="w-14 shrink-0 text-right tabular-nums" style={{ color: "var(--color-text-primary)" }}>
                {fmtCount(count)}
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-[11px]" style={{ color: "var(--color-text-muted)" }}>
          模式是"多项指标同时越界"的组合命名，不是病名。同一个模式在不同人身上的含义可能完全不同，
          这里只描述"像哪种组合"，不做判断。
        </p>
      </section>

      <section className="card p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-[13px] font-medium" style={{ color: "var(--color-text-secondary)" }}>
            异常样本（按异常指标数、严重度排序，最多 {TOP_ROWS} 条）
          </h2>
          <ExportButton
            label={`导出异常清单（${fmtCount(top.data?.total ?? data.abnormal_samples)} 条）`}
            path={exportPath(datasetId, "summary", { scope: "filtered", onlyAbnormal: true })}
            busy={exporter.busy}
            run={exporter.run}
            variant="solid"
          />
        </div>
        {exporter.error && (
          <p className="mt-1 text-[11px]" style={{ color: "var(--color-status-high)" }}>
            {exporter.error}
          </p>
        )}

        {top.error && <ErrorNotice error={top.error} />}
        {rows.length === 0 && !top.isLoading && (
          <p className="mt-2 text-[12px]" style={{ color: "var(--color-text-muted)" }}>
            没有异常样本：所有样本的指标都在参考区间内，或都因关键字段缺失而未判定。
          </p>
        )}
        {rows.length > 0 && (
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
                {rows.map((row, rowIndex) => (
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
        )}
        <p className="mt-2 text-[11px]" style={{ color: "var(--color-text-muted)" }}>
          导出的清单与上面这张表用的是同一份行数据；导出件带 UTF-8 BOM，Excel 直接打开不乱码。
        </p>
      </section>
    </div>
  );
}
