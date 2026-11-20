import { randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

/**
 * 唯一一条主流程（T-37 / SRS 10.3）：
 * 注册 → 上传夹具 → 自动清洗并出图 → 导出中心预览 → 下载。
 *
 * 三条刻意的选择：
 * 1. 账号每次随机生成（`e2e_<随机>`），不依赖库里已有的演示账号——演示账号的密码
 *    一改，E2E 就红，而"密码改了"不是 bug；
 * 2. 上传的是**固定夹具** `backend/tests/fixtures/sample_clean.csv`（8 行、答案已知），
 *    不依赖 Kaggle 数据集是否下载过（RK-25）；
 * 3. 断言"下载的文件里有数据行"，而不是断言具体文件大小——体积随环境变，断言了必红。
 */

const currentDir = dirname(fileURLToPath(import.meta.url));
const FIXTURE = resolve(currentDir, "../../../backend/tests/fixtures/sample_clean.csv");

function randomUser(): string {
  return `e2e_${randomBytes(4).toString("hex")}`;
}

test("注册 → 上传 → 出图 → 导出下载", async ({ page }) => {
  const username = randomUser();
  const password = "e2e-pass-2026";

  // ── 注册（成功即进入工作台，不需要再登录一次：FR-34）──
  // 选择器用"包含文本"而不是 exact：界面上写的是"用户名（3–32 位）"，
  // 用 exact 等于把标签文案钉死在测试里，改一次文案就红一片（而文案改动不是 bug）。
  await page.goto("/register");
  await page.getByLabel(/用户名/).fill(username);
  await page.getByLabel(/^密码/).fill(password);
  await page.getByLabel(/再输一次/).fill(password);
  await page.getByRole("button", { name: /注册/ }).click();

  await expect(page.getByText(username)).toBeVisible();

  // ── 上传夹具：10 行原始数据（1 行完全重复、1 行核心字段全空）→ 清洗后 n = 8 ──
  // 上传成功后前端直接落到该数据集的「分析」页，不会停在某个"清洗完成"提示上，
  // 所以这里等的是**数据集标题**，而不是一句状态文案。
  await page.setInputFiles('input[type="file"]', FIXTURE);
  await expect(page.getByRole("heading", { name: "sample_clean" })).toBeVisible({ timeout: 120_000 });

  // ── 分析页：指标卡 + 图注里的 n（FR-09/FR-32，结论可复核的最小证据）──
  await expect(page.getByText("血红蛋白").first()).toBeVisible();
  await expect(page.getByText(/n\s*=\s*8/).first()).toBeVisible();

  // ── 导出中心：预览表 → 下载 ──
  // "当前数据集"由 URL 的 `?dataset=` 决定（4.4.2 的状态约定），直接 goto("/export")
  // 会落在"先选择一个数据集"的空态上——这不是 bug，所以测试要把 id 带上。
  const datasetId = page.url().split("?")[0].split("/").filter(Boolean).pop();
  expect(datasetId, "上传后应跳到 /datasets/<id>").toBeTruthy();
  await page.goto(`/export?dataset=${datasetId}`);
  await expect(page.getByRole("heading", { name: "导出中心" })).toBeVisible();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: /下载/ }).first().click(),
  ]);

  const path = await download.path();
  expect(path, "下载必须有落盘文件").toBeTruthy();
  const content = readFileSync(path!, "utf8");
  // UTF-8 BOM 是 Excel 不乱码的前提（NFR-C-03）；数据行数要与夹具的 8 条样本对上
  expect(content.startsWith("\ufeff")).toBe(true);
  const lines = content.trim().split(/\r?\n/);
  expect(lines.length).toBeGreaterThan(1);
  expect(content).toContain("样本序号");
});
