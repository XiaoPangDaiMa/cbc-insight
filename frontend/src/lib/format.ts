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
