import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

/**
 * 集成测试用的假后端。
 *
 * 只用 MSW 在 **network 层**拦截，而不是 mock 掉 `api.*`：
 * 前端真正会出错的地方往往在"URL 拼错、参数漏传、缓存键少一段"，
 * 把函数 mock 掉就把这一层保护一起 mock 掉了。
 */
export const calls: URL[] = [];

export function resetCalls(): void {
  calls.length = 0;
}

function metricStatus(datasetId: string) {
  return {
    ri_version: "2026.11.1",
    // 名字里带上 datasetId：串数据时断言会立刻发现"拿到的是另一份的卡"
    metrics: [
      {
        metric: "hgb",
        name_cn: `血红蛋白@${datasetId}`,
        unit: "g/L",
        decimals: 0,
        n: datasetId === "ds-a" ? 8 : 94,
        low: null,
        high: null,
        gender_dependent: true,
        ranges_by_gender: [
          { gender: "male", low: 130, high: 175 },
          { gender: "female", low: 115, high: 150 },
        ],
        median: datasetId === "ds-a" ? 148 : 130,
        q1: 0,
        q3: 0,
        min: 0,
        max: 0,
        max_deviation_pct: 0,
        status: "NORMAL",
        pct_low: 0,
        pct_normal: 1,
        pct_above: 0,
        pct_na: 0,
      },
    ],
    gender_missing_samples: 0,
    anomaly_rate: 0,
  };
}

export const server = setupServer(
  http.get("/api/v1/datasets/:datasetId/metric-status", ({ request, params }) => {
    calls.push(new URL(request.url));
    return HttpResponse.json(metricStatus(String(params.datasetId)));
  }),
  http.get("/api/v1/datasets/:datasetId/export/preview", ({ request }) => {
    calls.push(new URL(request.url));
    return HttpResponse.json({
      headers: ["样本序号", "性别"],
      rows: [["0", "男"]],
      total: 1,
      filename: "x.csv",
      scope: "filtered",
    });
  }),
);
