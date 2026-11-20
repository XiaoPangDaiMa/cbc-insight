/** TanStack Query 的查询键与请求函数集中在这里，页面里不再出现裸字符串 URL。
 *
 * 查询键**必须含 datasetId**：不带 datasetId 的缓存键会在切换数据集时复用上一份
 * 数据，图和数据对不上而且看起来完全合理（RK-11、T-16）。
 */

import { request } from "./client";
import type {
  AnomalyPayload,
  AuthTokens,
  ChartPayload,
  CleanReportPayload,
  ComparePayload,
  DatasetPayload,
  ExportPreviewPayload,
  FilterState,
  MetricStatusPayload,
  MyRangesPayload,
  QueryPayload,
  RangeDraft,
  RangesSnapshotPayload,
  RangeVersionPayload,
  RejudgePayload,
  SampleProfilePayload,
  StatsPayload,
  UploadPayload,
  UserPayload,
  WorkspacePayload,
} from "./types";

/**
 * 导出链接的公共参数。
 *
 * `filters` 走 JSON 字符串，是因为导出必须是 GET（浏览器要能直接下载）；
 * 条件用 POST 提交就只能 fetch+blob，文件名的中文会经过一次 JS 兜底，更容易出错。
 */
export interface ExportOptions {
  scope?: "all" | "filtered";
  stage?: "raw" | "cleaned";
  filters?: FilterState["filters"];
  gender?: string | null;
  ageMin?: number | null;
  ageMax?: number | null;
  onlyAbnormal?: boolean;
}

/** 拼 `/export/...?kind=` 的查询串；预览与下载共用，参数顺序固定（T-29）。 */
export function exportQuery(kind: string, opts: ExportOptions = {}): string {
  const params = new URLSearchParams({ kind, scope: opts.scope ?? "all", stage: opts.stage ?? "cleaned" });
  if (opts.filters && opts.filters.length > 0) params.set("filters", JSON.stringify(opts.filters));
  if (opts.gender) params.set("gender", opts.gender);
  if (opts.ageMin !== null && opts.ageMin !== undefined) params.set("age_min", String(opts.ageMin));
  if (opts.ageMax !== null && opts.ageMax !== undefined) params.set("age_max", String(opts.ageMax));
  if (opts.onlyAbnormal) params.set("only_abnormal", "true");
  return params.toString();
}

/** 下载地址：与预览走同一套参数，避免"看到 5 行、下到 94 行"（RK-19）。 */
export function exportPath(datasetId: string, kind: string, opts: ExportOptions = {}): string {
  return `/datasets/${datasetId}/export/${kind}?${exportQuery(kind, opts)}`;
}

export const keys = {
  me: ["me"] as const,
  workspace: ["workspace"] as const,
  datasets: ["datasets"] as const,
  dataset: (id: string) => ["dataset", id] as const,
  status: (id: string, stage: string) => ["status", id, stage] as const,
  stats: (id: string) => ["stats", id] as const,
  cleanReport: (id: string) => ["clean-report", id] as const,
  anomaly: (id: string) => ["anomaly", id] as const,
  chart: (id: string, kind: string, metric: string) => ["chart", id, kind, metric] as const,
  profile: (id: string, index: number) => ["profile", id, index] as const,
  exportPreview: (id: string, kind: string, opts = "") => ["export-preview", id, kind, opts] as const,
  myRanges: ["my-ranges"] as const,
  rangeVersions: ["my-ranges", "versions"] as const,
  rangesSnapshot: (id: string) => ["ranges-snapshot", id] as const,
  compare: (ids: string[], metrics: string[]) => ["compare", ids.join(","), metrics.join(",")] as const,
};

export const api = {
  register: (username: string, password: string) =>
    request<AuthTokens>("/auth/register", {
      method: "POST",
      body: { username, password, password_confirm: password },
    }),
  login: (username: string, password: string) =>
    request<AuthTokens>("/auth/login", { method: "POST", body: { username, password } }),
  logout: (refresh: string) => request<{ ok: boolean }>("/auth/logout", { method: "POST", body: { refresh_token: refresh } }),
  me: () => request<UserPayload>("/auth/me"),
  rename: (newUsername: string) => request<{ ok: boolean }>("/auth/me", { method: "PATCH", body: { new_username: newUsername } }),
  changePassword: (oldPassword: string, newPassword: string) =>
    request<{ ok: boolean }>("/auth/me/password", {
      method: "PUT",
      body: { old_password: oldPassword, new_password: newPassword },
    }),

  workspace: () => request<WorkspacePayload>("/dashboard"),
  datasets: () => request<{ items: DatasetPayload[]; total: number }>("/datasets"),
  dataset: (id: string) => request<{ dataset: DatasetPayload }>(`/datasets/${id}`),
  renameDataset: (id: string, name: string) =>
    request<{ ok: boolean }>(`/datasets/${id}`, { method: "PATCH", body: { name } }),
  deleteDataset: (id: string) => request<{ ok: boolean }>(`/datasets/${id}`, { method: "DELETE" }),

  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<UploadPayload>("/datasets", { method: "POST", form });
  },

  status: (id: string, stage = "cleaned") =>
    request<MetricStatusPayload>(`/datasets/${id}/metric-status?stage=${stage}`),
  stats: (id: string, groupBy?: string) =>
    request<StatsPayload>(`/datasets/${id}/stats${groupBy ? `?group_by=${groupBy}` : ""}`),
  cleanReport: (id: string) => request<CleanReportPayload>(`/datasets/${id}/clean-report`),
  anomaly: (id: string, body: Record<string, unknown> = {}) =>
    request<AnomalyPayload>(`/datasets/${id}/anomaly`, { method: "POST", body }),
  chart: (id: string, kind: string, body: Record<string, unknown>) =>
    request<ChartPayload>(`/datasets/${id}/charts/${kind}`, { method: "POST", body }),
  profile: (id: string, index: number) =>
    request<SampleProfilePayload>(`/datasets/${id}/samples/${index}/profile`),
  query: (id: string, body: Record<string, unknown>) =>
    request<QueryPayload>(`/datasets/${id}/query`, { method: "POST", body }),
  exportPreview: (id: string, kind: string, opts: ExportOptions = {}) =>
    request<ExportPreviewPayload>(`/datasets/${id}/export/preview?${exportQuery(kind, opts)}`),

  // 三层区间（3.5.1）：默认只读，用户那份整份保存，临时那份只在图表请求里
  myRanges: () => request<MyRangesPayload>("/me/reference-ranges"),
  saveRanges: (ranges: RangeDraft, note: string) =>
    request<{ ok: boolean; version: number; digest: string }>("/me/reference-ranges", {
      method: "PUT",
      body: { ranges, note },
    }),
  resetRanges: () => request<{ ok: boolean }>("/me/reference-ranges/reset", { method: "POST" }),
  rangeVersions: () => request<{ items: RangeVersionPayload[] }>("/me/reference-ranges/versions"),
  rangesSnapshot: (id: string) => request<RangesSnapshotPayload>(`/datasets/${id}/ranges-snapshot`),
  rejudge: (id: string) => request<RejudgePayload>(`/datasets/${id}/rejudge`, { method: "POST", body: {} }),

  // 多数据集并排（FR-29）：只有描述统计与三态占比，接口层就不提供任何检验
  compare: (datasetIds: string[], metrics: string[] = []) =>
    request<ComparePayload>("/compare/stats", {
      method: "POST",
      body: { dataset_ids: datasetIds, metrics: metrics.length > 0 ? metrics : null },
    }),
};
