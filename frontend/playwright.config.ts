import { defineConfig, devices } from "@playwright/test";

/**
 * E2E 只有一条主流程（SRS 10.3 / T-37）：
 * 注册 → 上传夹具 → 自动清洗完成并出图 → 导出中心预览 → 下载成功。
 *
 * 刻意**不铺开**做全流程矩阵：
 * - 界面会变，铺开的用例每天都要改，两周后就会被加 `test.skip`；
 * - 真正的规则细节已经由后端的 BR/FR 用例覆盖（157 例），E2E 的职责只是回答
 *   "整条链路还通不通"。
 *
 * 用例自己注册随机账号（不依赖预置数据），跑完在 teardown 里删掉账号名下的数据集，
 * 这样重复运行的结果一致（RK-25）。
 */
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.CBC_E2E_BASE ?? "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    acceptDownloads: true,
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // 不配 webServer：前后端由 start.ps1 起。让 E2E 自己拉起服务，会出现
  // "测试在跑、你以为在看演示站"的两套数据，排查时先要确认自己在看哪个库。
});
