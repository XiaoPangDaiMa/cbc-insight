import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useAuth } from "@/auth/session";
import { ApiError } from "@/api/client";

/** 注册：只填用户名 + 两次密码，成功即进工作台（无邮箱，FR-34 v1.3 的裁剪）。
 *
 * 没有邮箱意味着**找不回密码**——这是有意的裁剪，答辩时要说清，而不是当漏洞（RK-20）。
 * 管理员侧的 `python -m app.cli reset-password` 是兜底手段。
 */
export function Register() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError("两次输入的密码不一致。");
      return;
    }
    setPending(true);
    try {
      await register(username.trim(), password);
      navigate("/", { replace: true });
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === 40902) {
        setError("该用户名已被占用，换一个或直接登录。");
      } else {
        setError(caught instanceof Error ? caught.message : "注册失败");
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center" style={{ backgroundColor: "var(--color-bg-page)" }}>
      <form onSubmit={submit} className="card w-80 p-6">
        <h1 className="text-base font-semibold" style={{ color: "var(--color-text-primary)" }}>
          注册
        </h1>
        <p className="mt-1 text-[11px]" style={{ color: "var(--color-text-muted)" }}>
          注册后直接进入工作台，无需再次登录
        </p>

        <label className="mt-4 block text-[12px]" style={{ color: "var(--color-text-secondary)" }}>
          用户名（3–32 位）
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            minLength={3}
            maxLength={32}
            required
            className="mt-1 w-full rounded border px-2 py-1.5 text-sm"
            style={{ borderColor: "var(--color-border)", color: "var(--color-text-primary)" }}
          />
        </label>
        <label className="mt-3 block text-[12px]" style={{ color: "var(--color-text-secondary)" }}>
          密码（8–64 位）
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            minLength={8}
            maxLength={64}
            required
            className="mt-1 w-full rounded border px-2 py-1.5 text-sm"
            style={{ borderColor: "var(--color-border)", color: "var(--color-text-primary)" }}
          />
        </label>
        <label className="mt-3 block text-[12px]" style={{ color: "var(--color-text-secondary)" }}>
          再输一次
          <input
            type="password"
            value={confirm}
            onChange={(event) => setConfirm(event.target.value)}
            minLength={8}
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
          {pending ? "注册中…" : "注册并进入"}
        </button>

        <p className="mt-3 text-center text-[11px]" style={{ color: "var(--color-text-muted)" }}>
          已有账号？
          <Link to="/login" className="ml-1" style={{ color: "var(--color-brand)" }}>
            登录
          </Link>
        </p>
      </form>
    </div>
  );
}
