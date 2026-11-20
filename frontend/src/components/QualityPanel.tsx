/** 数据质量图（FR-13）。
 *
 * 三块图分开画：完整率（哪列缺得厉害）、DQ 评分（整体可信到什么程度）、
 * 剔除原因（剩下的 N 行有没有系统性缺口）。放一张图里必然互相挤压。
 *
 * 这里只负责"把图摆到页面上"，所有数字都来自后端落库的 quality / clean_report，
 * 与报告里那张表用的是同一份结果——两处各算一遍，迟早对不上。
 */
import { useQuery } from "@tanstack/react-query";

import { api, keys } from "@/api/hooks";
import type { ChartPanel } from "@/api/types";
import { EChart } from "@/components/EChart";
import { ErrorNotice, EmptyState } from "@/components/EmptyState";

const PANEL_HEIGHT: Record<ChartPanel["id"], number> = {
  completeness: 270,
  dq: 270,
  removed: 280,
};

/** 剔除原因是一张饼：只说明"占多少"，占半栏就够，撑满整行会显得空旷。 */
const PANEL_SPAN: Record<ChartPanel["id"], string> = {
  completeness: "",
  dq: "",
  removed: "",
};

const PANEL_HINT: Record<ChartPanel["id"], string> = {
  completeness: "条越短表示那一列缺得越多；横线是最低可接受线，低于它的字段下结论要谨慎。",
  dq: "空档表示这一项未计算（缺少计算所需字段），不是 0 分。",
  removed: "清洗剔除的行不是「异常样本」——畸形值、整行空、完全重复才是脏数据。",
};

export function QualityPanel({ datasetId }: { datasetId: string }) {
  const quality = useQuery({
    queryKey: keys.chart(datasetId, "quality", ""),
    queryFn: () => api.chart(datasetId, "quality", {}),
  });

  if (quality.error) return <ErrorNotice error={quality.error} />;
  if (quality.isLoading) return <p className="text-[12px]" style={{ color: "var(--color-text-muted)" }}>正在计算数据质量…</p>;
  if (!quality.data) return null;

  const panels = quality.data.panels ?? [];
  if (panels.length === 0) {
    return <EmptyState title="没有可展示的质量指标" description="这份数据在入库时没有留下完整率或 DQ 记录。" />;
  }

  return (
    <section className="card p-3">
      <h2 className="text-[13px] font-medium" style={{ color: "var(--color-text-secondary)" }}>
        数据质量图
      </h2>
      <p className="mt-1 text-[12px]" style={{ color: "var(--color-text-primary)" }}>
        {quality.data.caption}
      </p>
      <div className="mt-2 grid gap-3 xl:grid-cols-2">
        {panels.map((panel) => (
          <figure key={panel.id} className={`min-w-0 ${PANEL_SPAN[panel.id]}`}>
            <figcaption
              className="mb-1 text-[12px] font-medium"
              style={{ color: "var(--color-text-secondary)" }}
            >
              {panel.title}
            </figcaption>
            <EChart option={panel.echarts_option} height={PANEL_HEIGHT[panel.id]} />
            <p className="mt-1 text-[11px]" style={{ color: "var(--color-text-muted)" }}>
              {PANEL_HINT[panel.id]}
            </p>
          </figure>
        ))}
      </div>
    </section>
  );
}
