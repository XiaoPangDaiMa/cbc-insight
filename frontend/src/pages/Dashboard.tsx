import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, keys } from "@/api/hooks";
import { ApiError } from "@/api/client";
import { DatasetCard } from "@/components/DatasetCard";
import { EmptyState, ErrorNotice } from "@/components/EmptyState";
import { MetricCard } from "@/components/MetricCard";
import { fmtPct } from "@/lib/format";

/** 工作台（FR-33）：登录后第一屏必须是"数据"，不是欢迎语或功能卡片墙（T-26）。
 *
 * 上传后 S1–S6 由后端自动跑完，这里只展示"数据健康度"一句话，
 * 明细折叠进数据集详情——用户不需要在上传阶段就理解 9 个 Stage（9.1）。
 */
export function Dashboard() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const workspace = useQuery({ queryKey: keys.workspace, queryFn: api.workspace });
  const latest = workspace.data?.latest ?? null;
  const latestStatus = useQuery({
    queryKey: latest ? keys.status(latest.dataset_id, "cleaned") : ["status", "none"],
    queryFn: () => api.status(latest!.dataset_id, "cleaned"),
    enabled: Boolean(latest),
  });

  const upload = useMutation({
    mutationFn: (file: File) => api.upload(file),
    onSuccess: (payload) => {
      void queryClient.invalidateQueries({ queryKey: keys.workspace });
      void queryClient.invalidateQueries({ queryKey: keys.datasets });
      navigate(`/datasets/${payload.dataset.dataset_id}`);
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteDataset(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.workspace });
      void queryClient.invalidateQueries({ queryKey: keys.datasets });
    },
  });

  function pick(files: FileList | null) {
    const file = files?.[0];
    if (file) upload.mutate(file);
  }

  const error = upload.error;

  return (
    <div className="flex flex-col gap-4">
      <section
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          pick(event.dataTransfer.files);
        }}
        className="card flex flex-col items-center gap-2 border-dashed px-6 py-8 text-center"
        style={{
          borderColor: dragging ? "var(--color-brand)" : "var(--color-border-strong)",
          backgroundColor: dragging ? "var(--color-brand-soft)" : "var(--color-bg-surface)",
        }}
      >
        <input
          ref={fileInput}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={(event) => pick(event.target.files)}
        />
        <div className="text-sm font-medium" style={{ color: "var(--color-text-primary)" }}>
          把血常规 CSV 拖进来，或
          <button type="button" onClick={() => fileInput.current?.click()} className="ml-1 underline" style={{ color: "var(--color-brand)" }}>
            选择文件
          </button>
        </div>
        <p className="max-w-lg text-[11px]" style={{ color: "var(--color-text-muted)" }}>
          上传后自动完成编码识别、字段映射、质量校验、清洗与区间判定；需要确认的字段会单独列出。
          上限 200 000 行 / 50 MB。
        </p>
        {upload.isPending && (
          <p className="text-[12px]" style={{ color: "var(--color-brand)" }}>
            正在解析与统计，行数较多时需要几十秒…
          </p>
        )}
        {error && (
          <div className="w-full max-w-lg text-left">
            <ErrorNotice error={error} />
            {error instanceof ApiError && error.code === 40004 && (
              <p className="mt-1 text-[11px]" style={{ color: "var(--color-text-secondary)" }}>
                缺少必填指标字段，请检查列名是否包含 HGB / WBC / PLT 等。
              </p>
            )}
          </div>
        )}
      </section>

      {workspace.isLoading && <p className="text-[12px]">加载中…</p>}
      {workspace.data?.empty && (
        <EmptyState title="还没有数据集" description="先上传一份脱敏的血常规 CSV，系统会自动跑完清洗与区间判定。" />
      )}

      {(workspace.data?.datasets.length ?? 0) > 0 && (
        <section className="flex flex-col gap-2">
          <h2 className="text-[13px] font-medium" style={{ color: "var(--color-text-secondary)" }}>
            我的数据集
          </h2>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {workspace.data?.datasets.map((dataset) => (
              <DatasetCard
                key={dataset.dataset_id}
                dataset={dataset}
                active={dataset.dataset_id === latest?.dataset_id}
                onOpen={() => navigate(`/datasets/${dataset.dataset_id}`)}
                onDelete={() => {
                  if (confirm(`删除「${dataset.name}」及其全部派生文件？`)) remove.mutate(dataset.dataset_id);
                }}
              />
            ))}
          </div>
        </section>
      )}

      {latest && latestStatus.data && (
        <section className="flex flex-col gap-2">
          <div className="flex items-baseline justify-between">
            <h2 className="text-[13px] font-medium" style={{ color: "var(--color-text-secondary)" }}>
              最近一次分析 · {latest.name}
            </h2>
            <span className="text-[11px]" style={{ color: "var(--color-text-muted)" }}>
              异常率 {fmtPct(latest.anomaly_rate)}
              {latestStatus.data.gender_missing_samples > 0 &&
                ` · 因关键字段缺失未判定：${latestStatus.data.gender_missing_samples} 条`}
            </span>
          </div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {latestStatus.data.metrics.slice(0, 8).map((item) => (
              <MetricCard key={item.metric} item={item} onClick={() => navigate(`/datasets/${latest.dataset_id}?metric=${item.metric}`)} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
