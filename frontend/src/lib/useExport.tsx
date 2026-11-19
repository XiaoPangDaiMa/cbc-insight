import { useState } from "react";

import { download, saveBlob } from "@/api/client";

/** 下载/打开导出文件：都走带令牌的 download 通道，文件名从 Content-Disposition 取。
 *
 * 单独抽出来是因为筛选页、异常页、分析页都要导出；三处各写一份的话，
 * "预览的列"和"下载的文件"迟早会变成两套参数（RK-19）。
 */
export function useExport() {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(path: string, mode: "save" | "open" = "save") {
    setBusy(path);
    setError(null);
    try {
      const { blob, filename } = await download(path);
      if (mode === "open") {
        const url = URL.createObjectURL(blob);
        window.open(url, "_blank", "noopener");
        // 给新标签页留出读取时间再回收，否则 Safari/Firefox 会先崩掉
        window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
      } else {
        saveBlob(blob, filename);
      }
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "导出失败");
      return false;
    } finally {
      setBusy(null);
    }
  }

  return { busy, error, run };
}

export function ExportButton({
  label,
  path,
  mode = "save",
  busy,
  run,
  variant = "ghost",
}: {
  label: string;
  path: string;
  mode?: "save" | "open";
  busy: string | null;
  run: (path: string, mode?: "save" | "open") => Promise<unknown>;
  variant?: "ghost" | "solid";
}) {
  const solid = variant === "solid";
  return (
    <button
      type="button"
      onClick={() => void run(path, mode)}
      disabled={busy !== null}
      className="rounded px-2 py-[3px] text-[11px] transition disabled:opacity-50"
      style={
        solid
          ? { backgroundColor: "var(--color-brand)", color: "var(--color-bg-surface)" }
          : { border: "1px solid var(--color-border)", color: "var(--color-text-secondary)" }
      }
    >
      {busy === path ? "…" : label}
    </button>
  );
}
