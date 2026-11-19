import type { MetricStatusItem } from "@/api/types";
import { StatusBadge } from "@/components/StatusBadge";
import { fmtNumber, fmtPct, fmtPercentValue, fmtRange } from "@/lib/format";

/** 指标卡（群体口径）：一群样本的分布，不是某个人的结果。
 *
 * 与 SampleProfile（个体口径）刻意做成两个组件、两种措辞：
 * 拿一张卡去描述一个人，或拿一张体检单去代表一群人，都是错的（T-22、10.2）。
 */
export function MetricCard({
  item,
  active = false,
  onClick,
}: {
  item: MetricStatusItem;
  active?: boolean;
  onClick?: () => void;
}) {
  const status = item.status === "MIXED" ? "NA" : item.status;
  const rangeText = item.gender_dependent
    ? item.ranges_by_gender
        .map((band) => `${band.gender === "male" ? "男" : "女"} ${fmtRange(band.low, band.high, item.decimals)}`)
        .join(" / ")
    : fmtRange(item.low, item.high, item.decimals);

  return (
    <button
      type="button"
      onClick={onClick}
      className="card w-full p-3 text-left transition"
      style={{
        borderColor: active ? "var(--color-brand)" : "var(--color-border)",
        boxShadow: active ? "0 0 0 1px var(--color-brand)" : "none",
      }}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-sm font-medium" style={{ color: "var(--color-text-primary)" }}>
            {item.name_cn}
          </div>
          <div className="text-[11px]" style={{ color: "var(--color-text-muted)" }}>
            {item.metric.toUpperCase()} · {item.unit} · n = {item.n}
          </div>
        </div>
        {item.status === "MIXED" ? (
          <span className="rounded-full border px-2 py-0.5 text-xs" style={{ borderColor: "var(--color-border-strong)", color: "var(--color-text-secondary)" }}>
            两侧均异常
          </span>
        ) : (
          <StatusBadge status={status} />
        )}
      </div>

      <div className="mt-2 flex items-baseline gap-2">
        <span className="text-lg font-semibold" style={{ color: "var(--color-text-primary)" }}>
          {fmtNumber(item.median, item.decimals)}
        </span>
        <span className="text-[11px]" style={{ color: "var(--color-text-muted)" }}>
          中位数 · 参考 {rangeText}
        </span>
      </div>

      {/* 分布条：左偏低 / 中正常 / 右偏高，NA 单独一段灰 */}
      <div className="mt-2 flex h-1.5 overflow-hidden rounded-full" style={{ backgroundColor: "var(--color-bg-subtle)" }}>
        <span style={{ width: `${item.pct_low * 100}%`, backgroundColor: "var(--color-status-low)" }} />
        <span style={{ width: `${item.pct_normal * 100}%`, backgroundColor: "var(--color-status-normal)" }} />
        <span style={{ width: `${item.pct_above * 100}%`, backgroundColor: "var(--color-status-high)" }} />
        <span style={{ width: `${item.pct_na * 100}%`, backgroundColor: "var(--color-status-na)" }} />
      </div>
      <div className="mt-1 flex justify-between text-[11px]" style={{ color: "var(--color-text-muted)" }}>
        <span>偏低 {fmtPct(item.pct_low)}</span>
        <span>偏高 {fmtPct(item.pct_above)}</span>
        <span>最大偏离 {fmtPercentValue(item.max_deviation_pct)}</span>
      </div>
    </button>
  );
}
