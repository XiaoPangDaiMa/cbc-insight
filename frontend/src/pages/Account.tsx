import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, keys } from "@/api/hooks";
import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/session";
import { fmtDateTime } from "@/lib/format";

/** 账号页（FR-34）：改名、改密。
 *
 * 三个容易被做错的细节，这里都按 8.3 处理：
 * 1. 改名后旧 Access Token 仍然可用，界面要提示"无需重新登录"（否则用户会以为没生效）；
 * 2. 改密成功后该用户全部 refresh token 失效，但当前 Access 仍有效到过期；
 * 3. 旧密码错误只标红"当前密码"输入框，**不清空其他字段**——重填一遍用户名是最让人恼火的交互。
 */
export function Account() {
  const { session, setSession } = useAuth();
  const me = useQuery({ queryKey: keys.me, queryFn: api.me });

  const [username, setUsername] = useState("");
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);

  async function submitRename(event: React.FormEvent) {
    event.preventDefault();
    setMessage(null);
    try {
      await api.rename(username.trim());
      if (session) setSession({ ...session, username: username.trim() });
      setMessage({ tone: "ok", text: "用户名已更新，当前登录状态不受影响。" });
      setUsername("");
    } catch (caught) {
      setMessage({
        tone: "error",
        text: caught instanceof ApiError && caught.code === 40902 ? "该用户名已被占用。" : "改名失败。",
      });
    }
  }

  async function submitPassword(event: React.FormEvent) {
    event.preventDefault();
    setMessage(null);
    setPasswordError(null);
    try {
      await api.changePassword(oldPassword, newPassword);
      setMessage({ tone: "ok", text: "密码已更新，其他设备上的登录将在令牌过期后失效。" });
      setOldPassword("");
      setNewPassword("");
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === 40102) {
        setPasswordError("当前密码不正确。");
      } else {
        setMessage({ tone: "error", text: caught instanceof Error ? caught.message : "改密失败。" });
      }
    }
  }

  return (
    <div className="flex max-w-xl flex-col gap-3">
      <section className="card p-4">
        <h1 className="text-[13px] font-medium" style={{ color: "var(--color-text-primary)" }}>
          账号信息
        </h1>
        <dl className="mt-2 grid grid-cols-2 gap-1 text-[12px]" style={{ color: "var(--color-text-secondary)" }}>
          <dt style={{ color: "var(--color-text-muted)" }}>用户名</dt>
          <dd>{me.data?.username ?? session?.username ?? "—"}</dd>
          <dt style={{ color: "var(--color-text-muted)" }}>数据归属</dt>
          <dd>仅本账号可见（v1.6 起没有角色之分）</dd>
          <dt style={{ color: "var(--color-text-muted)" }}>注册时间</dt>
          <dd>{fmtDateTime(me.data?.created_at)}</dd>
          <dt style={{ color: "var(--color-text-muted)" }}>最近登录</dt>
          <dd>{fmtDateTime(me.data?.last_login_at)}</dd>
        </dl>
      </section>

      <form onSubmit={submitRename} className="card flex flex-col gap-2 p-4">
        <h2 className="text-[13px] font-medium" style={{ color: "var(--color-text-primary)" }}>
          修改用户名
        </h2>
        <div className="flex gap-2">
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="新用户名（3–32 位）"
            minLength={3}
            maxLength={32}
            required
            className="flex-1 rounded border px-2 py-1.5 text-[12px]"
            style={{ borderColor: "var(--color-border)", color: "var(--color-text-primary)" }}
          />
          <button type="submit" className="rounded px-3 py-1.5 text-[12px] font-medium text-white" style={{ backgroundColor: "var(--color-brand)" }}>
            保存
          </button>
        </div>
      </form>

      <form onSubmit={submitPassword} className="card flex flex-col gap-2 p-4">
        <h2 className="text-[13px] font-medium" style={{ color: "var(--color-text-primary)" }}>
          修改密码
        </h2>
        <input
          type="password"
          value={oldPassword}
          onChange={(event) => setOldPassword(event.target.value)}
          placeholder="当前密码"
          autoComplete="current-password"
          required
          className="rounded border px-2 py-1.5 text-[12px]"
          style={{ borderColor: passwordError ? "var(--color-danger)" : "var(--color-border)", color: "var(--color-text-primary)" }}
        />
        {passwordError && (
          <p className="text-[11px]" style={{ color: "var(--color-danger)" }}>
            {passwordError}
          </p>
        )}
        <input
          type="password"
          value={newPassword}
          onChange={(event) => setNewPassword(event.target.value)}
          placeholder="新密码（8–64 位）"
          autoComplete="new-password"
          minLength={8}
          required
          className="rounded border px-2 py-1.5 text-[12px]"
          style={{ borderColor: "var(--color-border)", color: "var(--color-text-primary)" }}
        />
        <button type="submit" className="self-start rounded px-3 py-1.5 text-[12px] font-medium text-white" style={{ backgroundColor: "var(--color-brand)" }}>
          更新密码
        </button>
      </form>

      {message && (
        <p className="text-[12px]" style={{ color: message.tone === "ok" ? "var(--color-status-normal)" : "var(--color-danger)" }}>
          {message.text}
        </p>
      )}

      <p className="text-[11px]" style={{ color: "var(--color-text-muted)" }}>
        系统未收集邮箱，因此无法自助找回密码（这是有意的裁剪）。忘记密码时由管理员执行
        <code className="mx-1">python -m app.cli reset-password &lt;用户名&gt;</code>重置。
      </p>
    </div>
  );
}
