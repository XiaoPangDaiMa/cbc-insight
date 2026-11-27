/** 数字与单位的显示规则（4.4.6）。
 *
 * 三条硬规则：
 * 1. 缺失永远是 ``—``，不能显示 0 或空字符串——0 是真实的测量值，两者混淆会让
 *    "没测" 被读成 "测出来是 0"；
 * 2. 小数位由后端 ``decimals`` 给，前端不自己猜（HGB 是 0 位，WBC 是 2 位）；
 * 3. 百分比一律一位小数，且只在样本量 ≥ 1 时显示。
 */

export const EM_DASH = "—";

export function fmtNumber(value: number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EM_DASH;
  return value.toFixed(decimals);
}

/** 比率 → 百分比字符串。0.7345 → "73.5%"。 */
export function fmtPct(ratio: number | null | undefined, digits = 1): string {
  if (ratio === null || ratio === undefined || Number.isNaN(ratio)) return EM_DASH;
  return `${(ratio * 100).toFixed(digits)}%`;
}

/** 已经是百分数的值（如偏离度 124.0）→ "124.0%"。 */
export function fmtPercentValue(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EM_DASH;
  return `${value.toFixed(digits)}%`;
}

export function fmtCount(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EM_DASH;
  return String(Math.trunc(value));
}

export function fmtRange(low: number | null, high: number | null, decimals = 2, unit = ""): string {
  if (low === null || high === null) return EM_DASH;
  return `${fmtNumber(low, decimals)}–${fmtNumber(high, decimals)}${unit}`;
}

/** 后端时间是不带时区的 UTC 串；这里只做展示，不做时区换算。 */
export function fmtDateTime(value: string | null | undefined): string {
  if (!value) return EM_DASH;
  const text = value.replace("T", " ");
  return text.slice(0, 16);
}

export function fmtAge(age: number | null | undefined): string {
  if (age === null || age === undefined || Number.isNaN(age)) return EM_DASH;
  return `${Math.round(age)} 岁`;
}

export function genderLabel(gender: string | null | undefined): string {
  if (gender === "male") return "男";
  if (gender === "female") return "女";
  return EM_DASH;
}

/** 模式编码 → 中文（5.1 表）。
 *
 * 措辞全部是"倾向 / 偏低"这类描述性说法，**不出现病名**：系统只报告"哪些指标超出
 * 参考区间、组合起来像哪种模式"，不做诊断（1.3 范围外第一条）。
 * 未收录的编码原样显示，方便发现新增模式没同步翻译。
 */
const PATTERN_TEXT: Record<string, string> = {
  NORMAL: "未见指标超出参考区间",
  ANEMIA: "血红蛋白偏低（倾向）",
  MICRO: "红细胞偏小",
  MICRO_HYPO: "红细胞偏小且血红蛋白偏低（倾向）",
  MACRO: "红细胞偏大",
  POLYCYTHEMIA_SUSPECT: "血红蛋白偏高",
  THROMBOCYTOPENIA: "血小板偏低",
  THROMBOCYTOSIS: "血小板偏高",
  LEUKOCYTOSIS: "白细胞偏高",
  LEUKOPENIA: "白细胞偏低",
  MULTI_ABNORMAL: "多项指标超出参考区间",
  SINGLE_ABNORMAL: "单项指标超出参考区间",
  MIXED_ABNORMAL: "两项指标超出参考区间",
  UNCLASSIFIED: "其他异常组合（旧数据）",
  INSUFFICIENT_METRICS: "可判定指标不足 3 个，未给模式",
};

export function patternLabel(pattern: string | null | undefined): string {
  if (!pattern) return EM_DASH;
  return PATTERN_TEXT[pattern] ?? pattern;
}
