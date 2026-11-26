import { useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api, keys } from "@/api/hooks";
import { AnomalyPanel } from "@/components/AnomalyPanel";
import { CardHeader } from "@/components/CardHeader";
import { EChart } from "@/components/EChart";
import { EmptyState, ErrorNotice } from "@/components/EmptyState";
import { FilterPanel } from "@/components/FilterPanel";
import { MetricCard } from "@/components/MetricCard";
import { QualityPanel } from "@/components/QualityPanel";
import { RangesPanel } from "@/components/RangesPanel";
import { SampleProfile } from "@/components/SampleProfile";
import { SegmentedTabs } from "@/components/SegmentedTabs";
import { SkeletonCard, SkeletonChart } from "@/components/Skeleton";
import { fmtNumber, fmtPercentValue, fmtRange } from "@/lib/format";
import { ExportButton, useExport } from "@/lib/useExport";

type Tab = "analysis" | "ranges" | "filter" | "anomaly" | "quality";

const TABS: { key: Tab; label: string }[] = [
  { key: "analysis", label: "分析" },
  { key: "ranges", label: "区间" },
  { key: "filter", label: "筛选" },
  { key: "anomaly", label: "异常" },
  { key: "quality", label: "数据详情" },
];

/** 数据集详情：五个 tab。分析页的区块顺序固定（4.3.3），质量图不放在本 tab。
 *
 * 分析页是"左图右单"两栏：左边指标卡 + 三张大图，右边固定一列（pill 常驻 + 选中样本的体检单）。
 * 右侧之所以不能"点开就替换整块"，是因为对照五十个样本时要来回点，
 * 每次都得先关掉再打开，等于把列表藏起来了。
 */
export function DatasetDetail() {
  const { datasetId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab | null) ?? "analysis";
  const metricParam = params.get("metric");
  const [selected, setSelected] = useState<string | null>(metricParam);
  const [sampleIndex, setSampleIndex] = useState<number | null>(null);
  const exporter = useExport();

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

  const activeItem = status.data?.metrics.find((item) => item.metric === activeMetric);

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

  function pickMetric(metric: string) {
    setSelected(metric);
    const merged = new URLSearchParams(params);
    merged.set("metric", metric);
    setParams(merged, { replace: true });
  }

  if (dataset.isError) return <ErrorNotice error={dataset.error} />;

  if (!dataset.data) {
    return (
      <div className="flex flex-col gap-3">
        <SkeletonCard lines={2} />
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }, (_, index) => (
            <SkeletonCard key={index} lines={2} height={104} />
          ))}
        </div>
        <SkeletonChart height={320} />
      </div>
    );
  }

  const metricHint = activeItem
    ? `${activeItem.name_cn} · 单位 ${activeItem.unit} · n = ${activeItem.n} · 参考 ${fmtRange(activeItem.low, activeItem.high, activeItem.decimals)}`
    : undefined;

  return (
    <div className="flex flex-col gap-3">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h1 className="truncate text-base font-semibold" style={{ color: "var(--color-text-primary)" }}>
            {dataset.data.dataset.name}
          </h1>
          <p className="mt-0.5 text-[11px]" style={{ color: "var(--color-text-muted)" }}>
            {dataset.data.dataset.rows} 行 · 参考区间 {dataset.data.dataset.ri_version} · {dataset.data.dataset.health}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <ExportButton
            label="打开报告"
            path={`/datasets/${datasetId}/report.html`}
            mode="open"
            busy={exporter.busy}
            run={exporter.run}
          />
          <ExportButton
            label="下载报告"
            path={`/datasets/${datasetId}/report.html`}
            busy={exporter.busy}
            run={exporter.run}
            variant="solid"
          />
        </div>
      </header>
      {exporter.error && (
        <p className="text-[11px]" style={{ color: "var(--color-status-high)" }}>
          {exporter.error}
        </p>
      )}

      {/* tab 条贴在内容区顶部：既像"第二层顶栏"，又只属于这份数据集 */}
      <div
        className="sticky top-0 z-10 -mx-4 flex items-center justify-between gap-2 border-b px-4 py-2"
        style={{ backgroundColor: "var(--color-bg-page)", borderColor: "var(--color-border)" }}
      >
        <SegmentedTabs items={TABS} value={tab} onChange={switchTab} ariaLabel="数据集视图" />
        <span className="hidden text-[11px] sm:block" style={{ color: "var(--color-text-muted)" }}>
          {activeMetric && tab === "analysis" ? `当前指标：${activeItem?.name_cn ?? activeMetric}` : ""}
        </span>
      </div>

      {tab === "ranges" && <RangesPanel datasetId={datasetId} />}

      {tab === "analysis" && (
        <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_248px]">
          <div className="flex min-w-0 flex-col gap-3">
            <section className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {status.isLoading
                ? Array.from({ length: 9 }, (_, index) => <SkeletonCard key={index} lines={2} height={104} />)
                : status.data?.metrics.map((item) => (
                    <MetricCard
                      key={item.metric}
                      item={item}
                      active={item.metric === activeMetric}
                      onClick={() => pickMetric(item.metric)}
                    />
                  ))}
            </section>

            {box.isLoading ? (
              <SkeletonChart height={320} />
            ) : (
              <section className="card p-3">
                <CardHeader
                  title="箱线图"
                  hint={`${metricHint ?? ""} · 按性别分组，横虚线为参考区间`}
                  actions={
                    <ExportButton
                      label="PNG"
                      path={`/datasets/${datasetId}/charts/box/image?fmt=png&metric=${activeMetric}`}
                      busy={exporter.busy}
                      run={exporter.run}
                    />
                  }
                />
                {box.error && <ErrorNotice error={box.error} />}
                {box.data && <EChart option={box.data.echarts_option ?? {}} height={320} />}
                {box.data && (
                  <p className="mt-1 text-[12px]" style={{ color: "var(--color-text-primary)" }}>
                    {box.data.caption}
                  </p>
                )}
              </section>
            )}

            {hist.isLoading ? (
              <SkeletonChart height={280} />
            ) : (
              <section className="card p-3">
                <CardHeader
                  title="直方图"
                  hint={`${metricHint ?? ""} · 竖线为参考区间上下限`}
                  actions={
                    <ExportButton
                      label="PNG"
                      path={`/datasets/${datasetId}/charts/hist/image?fmt=png&metric=${activeMetric}`}
                      busy={exporter.busy}
                      run={exporter.run}
                    />
                  }
                />
                {hist.error && <ErrorNotice error={hist.error} />}
                {hist.data && <EChart option={hist.data.echarts_option ?? {}} height={280} />}
                {hist.data && (
                  <p className="mt-1 text-[12px]" style={{ color: "var(--color-text-primary)" }}>
                    {hist.data.caption}
                  </p>
                )}
              </section>
            )}

            {corr.isLoading ? (
              <SkeletonChart height={520} />
            ) : (
              <section className="card p-3">
                <CardHeader
                  title="相关性（Spearman）"
                  hint={`${status.data?.metrics.length ?? 0} 个指标 · 对角线为自身 · 格内数值为 ρ`}
                  actions={
                    <ExportButton
                      label="PNG"
                      path={`/datasets/${datasetId}/charts/corr/image?fmt=png`}
                      busy={exporter.busy}
                      run={exporter.run}
                    />
                  }
                />
                {corr.error && <ErrorNotice error={corr.error} />}
                {corr.data && <EChart option={corr.data.echarts_option ?? {}} height={560} />}
                {corr.data && (
                  <p className="mt-1 text-[12px]" style={{ color: "var(--color-text-primary)" }}>
                    {corr.data.caption}
                  </p>
                )}
              </section>
            )}
          </div>

          {/* 右侧固定列：pill 网格常驻，体检单在它下面滚动 */}
          <aside className="card flex min-w-0 flex-col p-3 xl:sticky xl:top-14 xl:max-h-[calc(100vh-5.5rem)]">
            <div className="flex items-center justify-between">
              <h2 className="text-[13px] font-medium" style={{ color: "var(--color-text-secondary)" }}>
                单样本体检
              </h2>
              {sampleIndex !== null && (
                <button
                  type="button"
                  className="icon-btn"
                  onClick={() => setSampleIndex(null)}
                  aria-label="关闭体检单"
                >
                  关闭
                </button>
              )}
            </div>
            <p className="mt-0.5 text-[11px]" style={{ color: "var(--color-text-muted)" }}>
              点样本号看这个人：条长按"在参考区间中的位置"标准化，HGB 与 MCH 可直接比长短。
            </p>

            {box.data && box.data.points.length > 0 ? (
              <div className="mt-2 flex flex-wrap gap-1">
                {box.data.points.slice(0, 24).map((point) => (
                  <button
                    key={point.sample_index}
                    type="button"
                    className="pill"
                    aria-pressed={sampleIndex === point.sample_index}
                    onClick={() => setSampleIndex(point.sample_index)}
                    title={`${activeItem?.name_cn ?? activeMetric} 偏离 ${fmtPercentValue(point.deviation_pct)}`}
                  >
                    #{point.sample_index}
                  </button>
                ))}
                {box.data.points.length > 24 && (
                  <span className="self-center text-[10px]" style={{ color: "var(--color-text-muted)" }}>
                    另有 {box.data.points.length - 24} 个
                  </span>
                )}
              </div>
            ) : (
              <p className="mt-2 text-[11px]" style={{ color: "var(--color-text-muted)" }}>
                当前指标没有可点的样本。
              </p>
            )}

            <div
              className="mt-3 min-h-0 flex-1 overflow-y-auto border-t pt-3"
              style={{ borderColor: "var(--color-border)" }}
            >
              {sampleIndex === null ? (
                <EmptyState title="还没选样本" description="点上面的样本号，这里显示该样本的 15 个指标与参考区间。" />
              ) : profile.isLoading ? (
                <div className="flex flex-col gap-2">
                  <SkeletonCard lines={2} height={56} />
                  <SkeletonCard lines={4} height={120} />
                </div>
              ) : profile.error ? (
                <ErrorNotice error={profile.error} />
              ) : profile.data ? (
                <SampleProfile profile={profile.data} />
              ) : null}
            </div>

            {activeItem && (
              <p className="mt-2 text-[10px]" style={{ color: "var(--color-text-muted)" }}>
                当前指标中位数 {fmtNumber(activeItem.median, activeItem.decimals)} {activeItem.unit}，样本号来自这张图。
              </p>
            )}
          </aside>
        </div>
      )}

      {tab === "filter" && <FilterPanel datasetId={datasetId} metrics={status.data?.metrics ?? []} />}

      {tab === "anomaly" && <AnomalyPanel datasetId={datasetId} />}

      {tab === "quality" && (
        <div className="grid gap-3">
          {/* FR-13：质量图放在「数据详情」里，不放进「分析」——那里是看结论的地方，
              这里是问"这份数据能不能用"的地方（4.3.3 的区块划分）。 */}
          <QualityPanel datasetId={datasetId} />
          <section className="card p-3">
            {cleanReport.isLoading && <SkeletonCard lines={4} height={140} />}
            {cleanReport.error && <ErrorNotice error={cleanReport.error} />}
            {cleanReport.data && (
              <>
                <CardHeader title="清洗前后对比" hint={cleanReport.data.health} />
                <table className="row-hover mt-2 w-full text-[12px]">
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
                        <td className="pl-3">{entry.detail}</td>
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
        </div>
      )}
    </div>
  );
}
