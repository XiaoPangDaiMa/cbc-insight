/** 极薄的 fetch 封装：只做三件事——带令牌、把 8.3 的 ``code`` 变成异常、401 时清会话。
 *
 * 不引 axios：这里只有 12 个端点，多一个依赖就多一份"它在干嘛"的疑问。
 */

import type { AuthTokens, ExportPreviewPayload, QueryPayload } from "./types";

export const TOKEN_KEY = "cbc.session";

export interface Session {
  access: string;
  refresh: string;
  username: string;
  userId: string;
}

export class ApiError extends Error {
  readonly code: number;
  readonly hint: string;
  readonly detail: unknown;
  readonly status: number;

  constructor(status: number, code: number, message: string, hint = "", detail: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.hint = hint;
    this.detail = detail;
  }
}

export function loadSession(): Session | null {
  const raw = localStorage.getItem(TOKEN_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Session;
  } catch {
    localStorage.removeItem(TOKEN_KEY);
    return null;
  }
}

export function saveSession(tokens: AuthTokens): Session {
  const session: Session = {
    access: tokens.access_token,
    refresh: tokens.refresh_token,
    username: tokens.username,
    userId: tokens.user_id,
  };
  localStorage.setItem(TOKEN_KEY, JSON.stringify(session));
  return session;
}

export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY);
}

let refreshing: Promise<Session | null> | null = null;

async function refreshSession(): Promise<Session | null> {
  const session = loadSession();
  if (!session?.refresh) return null;
  const response = await fetch("/api/v1/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: session.refresh }),
  });
  if (!response.ok) {
    clearSession();
    return null;
  }
  const data = (await response.json()) as { access_token: string };
  const next: Session = { ...session, access: data.access_token };
  localStorage.setItem(TOKEN_KEY, JSON.stringify(next));
  return next;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  form?: FormData;
  raw?: boolean;
  retry?: boolean;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const session = loadSession();
  const headers: Record<string, string> = {};
  if (session?.access) headers.Authorization = `Bearer ${session.access}`;
  let body: BodyInit | undefined;
  if (options.form) {
    body = options.form; // 让浏览器自己带 multipart 边界
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }

  const response = await fetch(`/api/v1${path}`, {
    method: options.method ?? "GET",
    headers,
    body,
  });

  if (response.status === 401 && options.retry !== false && session?.refresh) {
    refreshing = refreshing ?? refreshSession();
    const refreshed = await refreshing;
    refreshing = null;
    if (refreshed) return request<T>(path, { ...options, retry: false });
    clearSession();
  }

  if (options.raw) {
    if (!response.ok) throw await toError(response);
    return (await response.blob()) as T;
  }

  if (!response.ok) throw await toError(response);

  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    return (await response.text()) as unknown as T;
  }
  return (await response.json()) as T;
}

async function toError(response: Response): Promise<ApiError> {
  try {
    const payload = (await response.json()) as {
      code?: number;
      message?: string;
      hint?: string;
      detail?: unknown;
    };
    return new ApiError(response.status, payload.code ?? 50001, payload.message ?? "请求失败", payload.hint ?? "", payload.detail ?? null);
  } catch {
    return new ApiError(response.status, 50001, `请求失败（HTTP ${response.status}）`);
  }
}

/** 导出走独立的下载通道：文件名要从 ``Content-Disposition`` 取，中文名用 RFC 5987。 */
export async function download(path: string): Promise<{ blob: Blob; filename: string }> {
  const session = loadSession();
  const response = await fetch(`/api/v1${path}`, {
    headers: session?.access ? { Authorization: `Bearer ${session.access}` } : {},
  });
  if (!response.ok) throw await toError(response);
  const disposition = response.headers.get("content-disposition") ?? "";
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1];
  const fallback = /filename="?([^";]+)"?/i.exec(disposition)?.[1] ?? "export.csv";
  const filename = encoded ? decodeURIComponent(encoded) : fallback;
  return { blob: await response.blob(), filename };
}

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export type { ExportPreviewPayload, QueryPayload };
