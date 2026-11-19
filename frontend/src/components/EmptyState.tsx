import type { ReactNode } from "react";

/** 空状态：永远说清楚"下一步做什么"，不留一张白屏。 */
export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div
      className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-6 py-10 text-center"
      style={{ borderColor: "var(--color-border-strong)", color: "var(--color-text-secondary)" }}
    >
      <div className="text-sm font-medium" style={{ color: "var(--color-text-primary)" }}>
        {title}
      </div>
      {description && <p className="max-w-md text-[12px]">{description}</p>}
      {action}
    </div>
  );
}

export function ErrorNotice({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : "请求失败";
  return (
    <div
      className="rounded border px-3 py-2 text-[12px]"
      style={{ borderColor: "var(--color-danger)", color: "var(--color-danger)", backgroundColor: "var(--color-bg-surface)" }}
    >
      {message}
    </div>
  );
}
