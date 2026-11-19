import { describe, expect, it } from "vitest";

import { EM_DASH, fmtAge, fmtCount, fmtDateTime, fmtNumber, fmtPct, fmtPercentValue, fmtRange, genderLabel } from "@/lib/format";

describe("数字格式化（4.4.6）", () => {
  it("缺失值显示破折号，不显示 0", () => {
    expect(fmtNumber(null, 2)).toBe(EM_DASH);
    expect(fmtNumber(undefined, 0)).toBe(EM_DASH);
    expect(fmtNumber(0, 2)).toBe("0.00");
  });

  it("小数位由后端给，前端不自作主张", () => {
    expect(fmtNumber(147.5, 0)).toBe("148");
    expect(fmtNumber(6.2, 2)).toBe("6.20");
    expect(fmtNumber(316.1234, 1)).toBe("316.1");
  });

  it("比率与百分数分开处理", () => {
    expect(fmtPct(0.7345)).toBe("73.5%");
    expect(fmtPct(null)).toBe(EM_DASH);
    expect(fmtPercentValue(124)).toBe("124.0%");
  });

  it("参考区间两端都有值才拼", () => {
    expect(fmtRange(130, 175, 0, "g/L")).toBe("130–175g/L");
    expect(fmtRange(null, 175, 0)).toBe(EM_DASH);
  });

  it("年龄与性别标签", () => {
    expect(fmtAge(25.4)).toBe("25 岁");
    expect(fmtAge(null)).toBe(EM_DASH);
    expect(genderLabel("male")).toBe("男");
    expect(genderLabel("female")).toBe("女");
    expect(genderLabel(null)).toBe(EM_DASH);
  });

  it("计数与时间", () => {
    expect(fmtCount(8.9)).toBe("8");
    expect(fmtCount(undefined)).toBe(EM_DASH);
    expect(fmtDateTime("2026-11-18T13:34:11.018685")).toBe("2026-11-18 13:34");
    expect(fmtDateTime(null)).toBe(EM_DASH);
  });
});
