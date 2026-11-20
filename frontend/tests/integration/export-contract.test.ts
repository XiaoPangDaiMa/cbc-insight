import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { api, exportPath, exportQuery } from "@/api/hooks";
import { calls, resetCalls, server } from "./server";

/**
 * RK-19 / T-29 的前端版本：预览与下载必须是**同一套参数**。
 *
 * 这一条曾经真实出过事：预览按筛选条件返回 45 行，下载却走了不带条件的地址，
 * 用户拿到 94 行，而且界面上一切正常。所以断言两件事：
 *   1）预览请求的查询串与下载地址的查询串一字不差；
 *   2）筛选条件、性别、年龄、只看异常这些参数确实都在串里（不是"看起来一样"）。
 */
describe("导出的预览与下载", () => {
  beforeAll(() => server.listen());
  afterEach(() => {
    server.resetHandlers();
    resetCalls();
  });
  afterAll(() => server.close());

  const opts = {
    scope: "filtered" as const,
    filters: [{ metric: "hgb", op: "lt" as const, value: 130 }],
    gender: "female",
    ageMin: 20,
    ageMax: 30,
    onlyAbnormal: true,
  };

  it("预览请求的参数与下载地址完全一致", async () => {
    await api.exportPreview("ds-a", "summary", opts);

    const preview = calls.at(-1);
    expect(preview).toBeDefined();
    const download = new URL(exportPath("ds-a", "summary", opts), "http://localhost");

    expect(download.pathname).toBe("/datasets/ds-a/export/summary");
    expect(download.searchParams.get("kind")).toBe("summary");
    // 关键断言：query 一字不差
    expect(download.search).toBe(`?${preview?.searchParams.toString()}`);
  });

  it("参数确实落进了查询串，而不是被默认值吃掉", () => {
    const params = new URLSearchParams(exportQuery("summary", opts));

    expect(params.get("scope")).toBe("filtered");
    expect(params.get("stage")).toBe("cleaned");
    expect(params.get("gender")).toBe("female");
    expect(params.get("age_min")).toBe("20");
    expect(params.get("age_max")).toBe("30");
    expect(params.get("only_abnormal")).toBe("true");
    expect(JSON.parse(params.get("filters") ?? "[]")).toEqual(opts.filters);
  });

  it("不带可选参数时不留下空壳参数", () => {
    const params = new URLSearchParams(exportQuery("items", {}));

    expect(params.has("filters")).toBe(false);
    expect(params.has("gender")).toBe(false);
    expect(params.has("only_abnormal")).toBe(false);
    expect(params.get("scope")).toBe("all");
  });

  it("换一份数据集就是另一个地址，不会沿用上一份的预览", () => {
    expect(exportPath("ds-a", "items", opts)).not.toBe(exportPath("ds-b", "items", opts));
  });
});
