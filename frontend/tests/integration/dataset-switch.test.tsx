import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { api, keys } from "@/api/hooks";
import type { MetricStatusPayload } from "@/api/types";
import { calls, resetCalls, server } from "./server";

/**
 * T-16 的前端版本：切换数据集不能串数据。
 *
 * 后端那边已经用 `dataset_id` 做了归属校验，但前端真正会翻车的是**缓存键**：
 * `["status", stage]` 少写 datasetId 时，切到另一份数据仍会先渲染上一份的卡片，
 * 而且看起来完全正常（数字、单位、区间都合理）。所以这里断言三件事：
 *   1）两次请求打到不同的 URL；
 *   2）缓存里两套数据各自独立；
 *   3）切回来立刻是原来那份，而不是继续显示另一份的数字。
 */

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function useMetricStatus(datasetId: string) {
  return useQuery<MetricStatusPayload>({
    queryKey: keys.status(datasetId, "cleaned"),
    queryFn: () => api.status(datasetId),
  });
}

describe("切换数据集", () => {
  beforeAll(() => server.listen());
  afterEach(() => {
    server.resetHandlers();
    resetCalls();
  });
  afterAll(() => server.close());
  beforeEach(() => localStorage.clear());

  it("两次切换各自拿到自己的数据，缓存互不覆盖", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result, rerender } = renderHook(({ id }) => useMetricStatus(id), {
      wrapper: wrapper(client),
      initialProps: { id: "ds-a" },
    });

    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data?.metrics[0].name_cn).toBe("血红蛋白@ds-a");
    expect(result.current.data?.metrics[0].n).toBe(8);

    rerender({ id: "ds-b" });
    await waitFor(() => expect(result.current.data?.metrics[0].name_cn).toBe("血红蛋白@ds-b"));
    expect(result.current.data?.metrics[0].n).toBe(94);

    expect(calls.map((url) => url.pathname)).toEqual([
      "/api/v1/datasets/ds-a/metric-status",
      "/api/v1/datasets/ds-b/metric-status",
    ]);

    expect(client.getQueryData(keys.status("ds-a", "cleaned"))).toBeDefined();
    expect(client.getQueryData(keys.status("ds-b", "cleaned"))).toBeDefined();

    rerender({ id: "ds-a" });
    expect(result.current.data?.metrics[0].name_cn).toBe("血红蛋白@ds-a");
  });

  it("换一个阶段（stage）也不会复用另一阶段的缓存", () => {
    expect(keys.status("ds-a", "cleaned")).not.toEqual(keys.status("ds-a", "raw"));
  });
});
