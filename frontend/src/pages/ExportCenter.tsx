import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api, keys } from "@/api/hooks";
import { download, saveBlob } from "@/api/client";
import { ErrorNotice, EmptyState } from "@/components/EmptyState";
import { SkeletonTable } from "@/components/Skeleton";

const KINDS = [
  { key: "items", label: "逐指标判定（长表）", hint: "每个样本 × 每个指标一行，含判定与偏离度" },
  { key: "summary", label: "样本级汇总", hint: "每个样本一行，含异常模式与严重度" },
  { key: "stats", label: "描述统计", hint: "指标级均值、中位数、区间与占比" },
  { key: "filtered", label: "筛选结果", hint: "当前筛选条件下的样本宽表" },
];

/** 导出中心（FR-35）：预览与下载共用同一套列定义（NFR-M-06、T-29）。
 *
 * 预览只读、不另造数据：后端 `build_export_frame` 出什么列，这里就显示什么列，
 * 下载文件也必须是同一批列——否则用户拿到的文件与刚才看到的不一样，事后极难发现。
 */
export function ExportCenter() {
  const [params, setParams] = useSearchParams();
  const datasetId = params.get("dataset") ?? "";
  const [kind, setKind] = useState("items");
  const [busy, setBusy] = useState(false);

  const datasets = useQuery({ queryKey: keys.datasets, queryFn: api.datasets });
  const preview = useQuery({
    queryKey: keys.exportPreview(datasetId, kind),
    queryFn: () => api.exportPreview(datasetId, kind),
    enabled: Boolean(datasetId),
  });

  async function doDownload() {
    setBusy(true);
    try {
      const { blob, filename } = await download(`/datasets/${datasetId}/export/${kind}`);
      saveBlob(blob, filename);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <header className="flex flex-wrap items-center gap-2">
        <h1 className="text-base font-semibold" style={{ color: "var(--color-text-primary)" }}>
          导出中心
        </h1>
        <select
          value={datasetId}
          onChange={(event) => {
            const merged = new URLSearchParams(params);
            merged.set("dataset", event.target.value);
            setParams(merged, { replace: true });
          }}
          className="rounded border px-2 py-1 text-[12px]"
          style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-bg-surface)" }}
        >
          <option value="">选择数据集</option>
          {(datasets.data?.items ?? []).map((item) => (
            <option key={item.dataset_id} value={item.dataset_id}>
              {item.name}（{item.rows} 行）
            </option>
          ))}
        </select>
      </header>

      {!datasetId && <EmptyState title="先选择一个数据集" description="导出的列由数据集决定；预览与下载共用同一套列定义。" />}

      {datasetId && (
        <>
          <section className="flex flex-wrap gap-2">
            {KINDS.map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setKind(item.key)}
                className="card px-3 py-2 text-left"
                style={{
                  borderColor: kind === item.key ? "var(--color-brand)" : "var(--color-border)",
                  boxShadow: kind === item.key ? "0 0 0 1px var(--color-brand)" : "none",
                }}
              >
                <div className="text-[12px] font-medium" style={{ color: "var(--color-text-primary)" }}>
                  {item.label}
                </div>
                <div className="text-[11px]" style={{ color: "var(--color-text-muted)" }}>
                  {item.hint}
                </div>
              </button>
            ))}
          </section>

          <section className="card p-3">
            <div className="flex items-center justify-between">
              <div className="text-[12px]" style={{ color: "var(--color-text-secondary)" }}>
                预览前 {preview.data?.rows.length ?? 0} 行 / 共 {preview.data?.total ?? 0} 行
              </div>
              <button
                type="button"
                onClick={doDownload}
                disabled={busy || !preview.data?.total}
                className="rounded px-3 py-1.5 text-[12px] font-medium text-white disabled:opacity-60"
                style={{ backgroundColor: "var(--color-brand)" }}
              >
                {busy ? "打包中…" : "下载 CSV"}
              </button>
            </div>

            {preview.error && <ErrorNotice error={preview.error} />}
            {preview.isLoading && <div className="mt-2"><SkeletonTable rows={6} columns={6} /></div>}

            {preview.data && (
              <div className="mt-2 overflow-x-auto">
                <table className="w-full whitespace-nowrap text-[11px]">
                  <thead style={{ color: "var(--color-text-muted)" }}>
                    <tr>
                      {preview.data.headers.map((header) => (
                        <th key={header} className="border-b px-2 py-1 text-left font-normal" style={{ borderColor: "var(--color-border)" }}>
                          {header}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody style={{ color: "var(--color-text-secondary)" }}>
                    {preview.data.rows.map((row, rowIndex) => (
                      <tr key={rowIndex}>
                        {row.map((cell, cellIndex) => (
                          <td key={cellIndex} className="border-b px-2 py-1" style={{ borderColor: "var(--color-border)" }}>
                            {cell === null ? "—" : String(cell)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="mt-2 text-[11px]" style={{ color: "var(--color-text-muted)" }}>
              文件为 UTF-8 with BOM、CRLF 换行，Excel 直接打开中文不乱码；同名 <code>*_meta.json</code> 记录行数、参考区间版本与生成时间。
            </p>
          </section>
        </>
      )}
    </div>
  );
}
