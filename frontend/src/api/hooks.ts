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
  DatasetPayload,
  ExportPreviewPayload,
  MetricStatusPayload,
  QueryPayload,
  SampleProfilePayload,
  StatsPayload,
  UploadPayload,
  UserPayload,
  WorkspacePayload,
} from "./types";

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
  exportPreview: (id: string, kind: string) => ["export-preview", id, kind] as const,
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
  exportPreview: (id: string, kind: string, scope = "all") =>
    request<ExportPreviewPayload>(`/datasets/${id}/export/preview?kind=${kind}&scope=${scope}`),
};
