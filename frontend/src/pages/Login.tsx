import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "@/auth/session";
import { ApiError } from "@/api/client";

export function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      await login(username.trim(), password);
      const from = (location.state as { from?: string } | null)?.from ?? "/";
      navigate(from, { replace: true });
    } catch (caught) {
      // 42902 是账号锁定：文案要说清"等多久"，但不能透露还剩几次（8.3）
      if (caught instanceof ApiError && caught.code === 42902) {
        setError("连续登录失败次数过多，请 15 分钟后再试。");
      } else if (caught instanceof ApiError && caught.code === 40101) {
        setError("用户名或密码不正确。");
      } else {
        setError(caught instanceof Error ? caught.message : "登录失败");
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center" style={{ backgroundColor: "var(--color-bg-page)" }}>
      <form onSubmit={submit} className="card w-80 p-6">
        <h1 className="text-base font-semibold" style={{ color: "var(--color-text-primary)" }}>
          登录
        </h1>
        <p className="mt-1 text-[11px]" style={{ color: "var(--color-text-muted)" }}>
          血常规数据分析与可视化系统
        </p>

        <label className="mt-4 block text-[12px]" style={{ color: "var(--color-text-secondary)" }}>
          用户名
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
            required
            className="mt-1 w-full rounded border px-2 py-1.5 text-sm"
            style={{ borderColor: "var(--color-border)", color: "var(--color-text-primary)" }}
          />
        </label>
        <label className="mt-3 block text-[12px]" style={{ color: "var(--color-text-secondary)" }}>
          密码
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
            className="mt-1 w-full rounded border px-2 py-1.5 text-sm"
            style={{ borderColor: "var(--color-border)", color: "var(--color-text-primary)" }}
          />
        </label>

        {error && (
          <p className="mt-3 text-[12px]" style={{ color: "var(--color-danger)" }}>
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={pending}
          className="mt-4 w-full rounded px-3 py-2 text-sm font-medium text-white disabled:opacity-60"
          style={{ backgroundColor: "var(--color-brand)" }}
        >
          {pending ? "登录中…" : "登录"}
        </button>

        <p className="mt-3 text-center text-[11px]" style={{ color: "var(--color-text-muted)" }}>
          还没有账号？
          <Link to="/register" className="ml-1" style={{ color: "var(--color-brand)" }}>
            注册
          </Link>
        </p>
      </form>
    </div>
  );
}
