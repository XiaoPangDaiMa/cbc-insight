import { useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api, keys } from "@/api/hooks";
import { EChart } from "@/components/EChart";
import { MetricCard } from "@/components/MetricCard";
import { SampleProfile } from "@/components/SampleProfile";
import { EmptyState, ErrorNotice } from "@/components/EmptyState";
import { fmtPct, fmtPercentValue } from "@/lib/format";

type Tab = "analysis" | "filter" | "anomaly" | "quality";

const TABS: { key: Tab; label: string }[] = [
  { key: "analysis", label: "分析" },
  { key: "filter", label: "筛选" },
  { key: "anomaly", label: "异常" },
  { key: "quality", label: "数据详情" },
];

/** 数据集详情：四个 tab。分析页的区块顺序固定（4.3.3），质量图不放在本 tab。 */
export function DatasetDetail() {
  const { datasetId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab | null) ?? "analysis";
  const metricParam = params.get("metric");
  const [selected, setSelected] = useState<string | null>(metricParam);
  const [sampleIndex, setSampleIndex] = useState<number | null>(null);

  const dataset = useQuery({
    queryKey: keys.dataset(datasetId),
    queryFn: () => api.dataset(datasetId),
    enabled: Boolean(datasetId),
  });
  const status = useQuery({
    queryKey: keys.status(datasetId, "cleaned"),
    queryFn: () => api.status(datasetId),
    enabled: Boolean(datasetId),
  });

  const activeMetric = useMemo(() => {
    if (selected) return selected;
    return status.data?.metrics[0]?.metric ?? "hgb";
  }, [selected, status.data]);

  const box = useQuery({
    queryKey: keys.chart(datasetId, "box", activeMetric),
    queryFn: () => api.chart(datasetId, "box", { metric: activeMetric }),
    enabled: Boolean(datasetId) && tab === "analysis",
  });
  const hist = useQuery({
    queryKey: keys.chart(datasetId, "hist", activeMetric),
    queryFn: () => api.chart(datasetId, "hist", { metric: activeMetric }),
    enabled: Boolean(datasetId) && tab === "analysis",
  });
  const corr = useQuery({
    queryKey: keys.chart(datasetId, "corr", "all"),
    queryFn: () => api.chart(datasetId, "corr", {}),
    enabled: Boolean(datasetId) && tab === "analysis",
  });
  const profile = useQuery({
    queryKey: keys.profile(datasetId, sampleIndex ?? -1),
    queryFn: () => api.profile(datasetId, sampleIndex!),
    enabled: sampleIndex !== null,
  });
  const anomaly = useQuery({
    queryKey: keys.anomaly(datasetId),
    queryFn: () => api.anomaly(datasetId),
    enabled: Boolean(datasetId) && tab === "anomaly",
  });
  const cleanReport = useQuery({
    queryKey: keys.cleanReport(datasetId),
    queryFn: () => api.cleanReport(datasetId),
    enabled: Boolean(datasetId) && tab === "quality",
  });

  function switchTab(next: Tab) {
    const merged = new URLSearchParams(params);
    merged.set("tab", next);
    setParams(merged, { replace: true });
  }

  if (dataset.isError) return <ErrorNotice error={dataset.error} />;
  if (!dataset.data) return <p className="text-[12px]">加载中…</p>;

  return (
    <div className="flex flex-col gap-3">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-base font-semibold" style={{ color: "var(--color-text-primary)" }}>
            {dataset.data.dataset.name}
          </h1>
          <p className="text-[11px]" style={{ color: "var(--color-text-muted)" }}>
            {dataset.data.dataset.rows} 行 · 参考区间 {dataset.data.dataset.ri_version} · {dataset.data.dataset.health}
          </p>
        </div>
        <nav className="flex gap-1">
          {TABS.map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => switchTab(item.key)}
              className="rounded px-2 py-1 text-[12px]"
              style={{
                backgroundColor: tab === item.key ? "var(--color-brand-soft)" : "transparent",
                color: tab === item.key ? "var(--color-brand)" : "var(--color-text-secondary)",
              }}
            >
              {item.label}
            </button>
          ))}
        </nav>
      </header>

      {tab === "analysis" && (
        <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_320px]">
          <div className="flex flex-col gap-3">
            <section className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {status.data?.metrics.map((item) => (
                <MetricCard
                  key={item.metric}
                  item={item}
                  active={item.metric === activeMetric}
                  onClick={() => {
                    setSelected(item.metric);
                    const merged = new URLSearchParams(params);
                    merged.set("metric", item.metric);
                    setParams(merged, { replace: true });
                  }}
                />
              ))}
            </section>

            <section className="card p-3">
              <h2 className="text-[13px] font-medium" style={{ color: "var(--color-text-secondary)" }}>
                分布（按性别分组，叠加参考区间）
              </h2>
              {box.error && <ErrorNotice error={box.error} />}
              {box.data && <EChart option={box.data.echarts_option} height={320} />}
              {box.data && (
                <p className="mt-1 text-[12px]" style={{ color: "var(--color-text-primary)" }}>
                  {box.data.caption}
                </p>
              )}
            </section>

            <section className="card p-3">
              <h2 className="text-[13px] font-medium" style={{ color: "var(--color-text-secondary)" }}>
                直方图（区间内外占比）
              </h2>
              {hist.error && <ErrorNotice error={hist.error} />}
              {hist.data && <EChart option={hist.data.echarts_option} height={280} />}
              {hist.data && (
                <p className="mt-1 text-[12px]" style={{ color: "var(--color-text-primary)" }}>
                  {hist.data.caption}
                </p>
              )}
            </section>

            <section className="card p-3">
              <h2 className="text-[13px] font-medium" style={{ color: "var(--color-text-secondary)" }}>
                指标间相关（含数学耦合标注）
              </h2>
              {corr.error && <ErrorNotice error={corr.error} />}
              {corr.data && <EChart option={corr.data.echarts_option} height={360} />}
              {corr.data && (
                <p className="mt-1 text-[12px]" style={{ color: "var(--color-text-primary)" }}>
                  {corr.data.caption}
                </p>
              )}
            </section>
          </div>

          <div>
            {profile.data ? (
              <SampleProfile profile={profile.data} onClose={() => setSampleIndex(null)} />
            ) : (
              <div className="card p-4">
                <div className="text-[12px] font-medium" style={{ color: "var(--color-text-primary)" }}>
                  单样本体检单
                </div>
                <p className="mt-1 text-[11px]" style={{ color: "var(--color-text-muted)" }}>
                  点击任一数据点可打开该样本的全部指标。条长按"在参考区间中的位置"标准化，
                  因此 HGB 与 MCH 的条长可以直接比较。
                </p>
                {box.data && box.data.points.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {box.data.points.slice(0, 12).map((point) => (
                      <button
                        key={point.sample_index}
                        type="button"
                        onClick={() => setSampleIndex(point.sample_index)}
                        className="rounded border px-2 py-0.5 text-[11px]"
                        style={{ borderColor: "var(--color-border)", color: "var(--color-text-secondary)" }}
                        title={`偏离 ${fmtPercentValue(point.deviation_pct)}`}
                      >
                        #{point.sample_index}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "filter" && (
        <EmptyState
          title="筛选（M3 交付）"
          description="按年龄、性别与指标阈值筛选样本，结果与导出共用同一套列定义。当前版本先交付分析页。"
        />
      )}

      {tab === "anomaly" && (
        <section className="card p-3">
          {anomaly.error && <ErrorNotice error={anomaly.error} />}
          {anomaly.data && (
            <>
              <h2 className="text-[13px] font-medium" style={{ color: "var(--color-text-secondary)" }}>
                异常与模式分布
              </h2>
              <p className="mt-1 text-[12px]" style={{ color: "var(--color-text-primary)" }}>
                {anomaly.data.abnormal_samples} / {anomaly.data.samples} 个样本至少有一项超出参考区间（
                {fmtPct(anomaly.data.anomaly_rate)}），共 {anomaly.data.abnormal_items} 个异常项。
              </p>
              <ul className="mt-2 grid gap-1 text-[12px] sm:grid-cols-2 lg:grid-cols-3">
                {Object.entries(anomaly.data.pattern_counts).map(([pattern, count]) => (
                  <li
                    key={pattern}
                    className="flex justify-between rounded px-2 py-1"
                    style={{ backgroundColor: "var(--color-bg-subtle)" }}
                  >
                    <span style={{ color: "var(--color-text-secondary)" }}>{pattern}</span>
                    <span style={{ color: "var(--color-text-primary)" }}>{count}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}

      {tab === "quality" && (
        <section className="card p-3">
          {cleanReport.error && <ErrorNotice error={cleanReport.error} />}
          {cleanReport.data && (
            <>
              <h2 className="text-[13px] font-medium" style={{ color: "var(--color-text-secondary)" }}>
                清洗前后对比
              </h2>
              <p className="mt-1 text-[12px]" style={{ color: "var(--color-text-primary)" }}>
                {cleanReport.data.health}
              </p>
              <table className="mt-2 w-full text-[12px]">
                <thead style={{ color: "var(--color-text-muted)" }}>
                  <tr>
                    <th className="text-left font-normal">步骤</th>
                    <th className="text-left font-normal">字段</th>
                    <th className="text-right font-normal">计数</th>
                    <th className="text-left font-normal">说明</th>
                  </tr>
                </thead>
                <tbody style={{ color: "var(--color-text-secondary)" }}>
                  {cleanReport.data.log.map((entry, index) => (
                    <tr key={`${entry.step}-${index}`} className="border-t" style={{ borderColor: "var(--color-border)" }}>
                      <td>{entry.step}</td>
                      <td>{entry.field ?? "—"}</td>
                      <td className="text-right">{entry.count}</td>
                      <td>{entry.note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {cleanReport.data.unit_log.length > 0 && (
                <ul className="mt-2 text-[11px]" style={{ color: "var(--color-text-muted)" }}>
                  {cleanReport.data.unit_log.map((line) => (
                    <li key={line}>· {line}</li>
                  ))}
                </ul>
              )}
            </>
          )}
        </section>
      )}
    </div>
  );
}
