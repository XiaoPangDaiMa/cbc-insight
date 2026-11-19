/** 从 CSS 自定义属性读取颜色，保证图表与界面同源（NFR-M-07）。
 *
 * ECharts 的 option 里**不能**出现字面色值：颜色一律在渲染前从 CSS 变量取，
 * 这样改 tokens.json 重跑 gen_theme.py，屏幕图与报告图的取色会一起变（T-32）。
 */

export type StatusKey = "LOW" | "NORMAL" | "HIGH" | "NA";

const STATUS_VAR: Record<StatusKey, string> = {
  LOW: "--color-status-low",
  NORMAL: "--color-status-normal",
  HIGH: "--color-status-high",
  NA: "--color-status-na",
};

const STATUS_SYMBOL: Record<StatusKey, string> = {
  LOW: "↓",
  NORMAL: "—",
  HIGH: "↑",
  NA: "∅",
};

const STATUS_TEXT: Record<StatusKey, string> = {
  LOW: "偏低",
  NORMAL: "正常",
  HIGH: "偏高",
  NA: "未判定",
};

export function cssVar(name: string, fallback = ""): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export function statusColor(status: StatusKey): string {
  return cssVar(STATUS_VAR[status], "#64748B");
}

export function statusSymbol(status: StatusKey): string {
  return STATUS_SYMBOL[status];
}

export function statusText(status: StatusKey): string {
  return STATUS_TEXT[status];
}

export function statusVarName(status: StatusKey): string {
  return STATUS_VAR[status];
}

/** 有序的分类色（箱线图按性别、热力图按方向等），全部来自 tokens。 */
export function seriesColor(index: number): string {
  return cssVar(`--chart-series-${(index % 8) + 1}`, "#0072B2");
}

export function chartPalette(): string[] {
  return Array.from({ length: 8 }, (_, i) => seriesColor(i));
}
