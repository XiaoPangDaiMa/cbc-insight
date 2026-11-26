import type { ReactNode } from "react";

/** 卡片头：标题 + 一句口径说明 + 徽标 + 右侧操作。
 *
 * 五个页面（分析 / 数据详情 / 区间 / 对比 / 导出）都要同一个样子，
 * 各写一份的结果是标题字号、间距、按钮位置全都不一样。
 * hint 不是装饰：图表卡上必须让人看见"这是哪个指标、n 多少、按什么口径判的"，
 * 否则滚动两屏之后没人记得自己在看哪张图（4.3.3）。
 */
export function CardHeader({
  title,
  hint,
  badge,
  actions,
}: {
  title: ReactNode;
  hint?: ReactNode;
  badge?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-[13px] font-medium" style={{ color: "var(--color-text-secondary)" }}>
            {title}
          </h2>
          {badge}
        </div>
        {hint && (
          <p className="mt-0.5 text-[11px]" style={{ color: "var(--color-text-muted)" }}>
            {hint}
          </p>
        )}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-1">{actions}</div>}
    </div>
  );
}
