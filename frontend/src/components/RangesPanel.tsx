/** 数据集详情里的「区间」tab（FR-24 前端部分、FR-36 重判、FR-37 试算）。

这一页存在的唯一理由：让"这份数据是按哪套区间判的"变成**看得见的事实**，而不是
用户脑子里的记忆。所以它把三件事并排放在一起：

1. 判定时用的快照（source / digest / 时间 / 15 项区间）；
2. 现在生效的口径——两者不同就亮"陈旧"横幅，并给一键重判；
3. 临时试算：改两条线立刻看到图怎么变，但**不保存、不导出**（RK-26）。

拖线交互是 FR-37 的目标形态；这里先做数字框（同一份 temp_ranges 请求参数），
拖动只是把数字框的值换成鼠标位置，后端契约不变。
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { EmptyState } from "@/components/EmptyState";
import { SkeletonCard, SkeletonTable } from "@/components/Skeleton";

import { api, keys } from "@/api/hooks";
import { ApiError } from "@/api/client";
import { EChart } from "@/components/EChart";
import type { ChartPayload } from "@/api/types";

export function RangesPanel({ datasetId }: { datasetId: string }) {
  const queryClient = useQueryClient();
  const snapshot = useQuery({
    queryKey: keys.rangesSnapshot(datasetId),
    queryFn: () => api.rangesSnapshot(datasetId),
    enabled: Boolean(datasetId),
  });

  const [metric, setMetric] = useState("hgb");
  const [low, setLow] = useState("");
  const [high, setHigh] = useState("");
  const [trial, setTrial] = useState<{ metric: string; low: number; high: number } | null>(null);
  const [error, setError] = useState("");

  const trialChart = useQuery({
    queryKey: ["trial", datasetId, trial?.metric, trial?.low, trial?.high],
    queryFn: () =>
      api.chart(datasetId, "box", {
        metric: trial!.metric,
        temp_ranges: { [trial!.metric]: { low: trial!.low, high: trial!.high } },
      }),
    enabled: Boolean(datasetId) && trial !== null,
    retry: false,
  });

  const rejudge = useMutation({
    mutationFn: () => api.rejudge(datasetId),
    onSuccess: async () => {
      setError("");
      await queryClient.invalidateQueries({ queryKey: keys.rangesSnapshot(datasetId) });
      await queryClient.invalidateQueries({ queryKey: keys.dataset(datasetId) });
      await queryClient.invalidateQueries({ queryKey: keys.status(datasetId, "cleaned") });
      await queryClient.invalidateQueries({ queryKey: ["chart", datasetId] });
    },
    onError: (err: unknown) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  if (snapshot.isLoading) {
    return (
      <div className="flex flex-col gap-3">
        <SkeletonCard lines={2} height={92} />
        <SkeletonTable rows={8} columns={6} />
      </div>
    );
  }
  if (!snapshot.data) {
    return <EmptyState title="读不到判定快照" description="刷新重试；若持续失败，说明这份数据的快照文件已损坏。" />;
  }

  const data = snapshot.data;
  const items = Object.values(data.snapshot.items ?? {});
  const missingSnapshot = data.has_snapshot === false;

  return (
    <div className="flex flex-col gap-3">
      {missingSnapshot ? (
        <div
          className="flex flex-wrap items-center justify-between gap-2 rounded border px-3 py-2 text-[12px]"
          style={{ borderColor: "var(--color-status-high)", color: "var(--color-status-high)" }}
        >
          <span>
            这份数据是在"判定快照"功能上线之前判的，没有留下当时用的区间——不能说它过期，只能说无从复核。
            重判一次即可补上快照（S1–S5 与样本序号都不变）。
          </span>
          <button
            type="button"
            className="rounded px-3 py-1 text-[12px] font-medium text-white disabled:opacity-50"
            style={{ backgroundColor: "var(--color-status-high)" }}
            onClick={() => rejudge.mutate()}
            disabled={rejudge.isPending}
          >
            {rejudge.isPending ? "重判中…" : "补建快照并重判"}
          </button>
        </div>
      ) : data.stale ? (
        <div
          className="flex flex-wrap items-center justify-between gap-2 rounded border px-3 py-2 text-[12px]"
          style={{ borderColor: "var(--color-status-high)", color: "var(--color-status-high)" }}
        >
          <span>
            这份数据是按 <code>{data.snapshot.source}</code> 判的，而你现在生效的是 <code>{data.current.source}</code>——
            结论已经陈旧，但没有自动改（改区间不等于改结论）。
          </span>
          <button
            type="button"
            className="rounded px-3 py-1 text-[12px] font-medium text-white disabled:opacity-50"
            style={{ backgroundColor: "var(--color-status-high)" }}
            onClick={() => rejudge.mutate()}
            disabled={rejudge.isPending}
          >
            {rejudge.isPending ? "重判中…" : "按当前区间重判"}
          </button>
        </div>
      ) : (
        <p className="text-[12px]" style={{ color: "var(--color-text-secondary)" }}>
          判定口径与当前生效区间一致（<code>{data.current.source}</code>）。
        </p>
      )}

      {error ? (
        <p className="text-[12px]" style={{ color: "var(--color-status-high)" }}>
          {error}
        </p>
      ) : null}

      <section className="card p-3 text-[12px]">
        <h2 className="text-[13px] font-medium">判定快照</h2>
        <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-4" style={{ color: "var(--color-text-secondary)" }}>
          <div>
            <dt style={{ color: "var(--color-text-muted)" }}>口径</dt>
            <dd>
              <code>{data.snapshot.source ?? "—"}</code>
            </dd>
          </div>
          <div>
            <dt style={{ color: "var(--color-text-muted)" }}>指纹</dt>
            <dd>
              <code>{data.snapshot.digest ?? "—"}</code>
            </dd>
          </div>
          <div>
            <dt style={{ color: "var(--color-text-muted)" }}>判定时刻</dt>
            <dd>{data.judged_at ?? "—"}</dd>
          </div>
          <div>
            <dt style={{ color: "var(--color-text-muted)" }}>统一口径</dt>
            <dd>{data.snapshot.unified ? "是（无视性别）" : "否（按性别）"}</dd>
          </div>
        </dl>
        <p className="mt-2" style={{ color: "var(--color-text-muted)" }}>
          要改区间请到 <Link to="/reference" style={{ color: "var(--color-brand)" }}>我的参考区间</Link>
          ；改完回到这里点重判，S1–S5 的产物与样本序号都不会变。
        </p>
      </section>

      <section className="card overflow-hidden">
        <table className="w-full text-[12px]">
          <thead style={{ backgroundColor: "var(--color-bg-page)", color: "var(--color-text-secondary)" }}>
            <tr>
              <th className="px-3 py-2 text-left">指标</th>
              <th className="px-3 py-2 text-left">单位</th>
              <th className="px-3 py-2 text-right">下限</th>
              <th className="px-3 py-2 text-right">上限</th>
              <th className="px-3 py-2 text-right">女性下限</th>
              <th className="px-3 py-2 text-right">女性上限</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.metric} className="border-t" style={{ borderColor: "var(--color-border)" }}>
                <td className="px-3 py-1.5">
                  {item.name_cn} <span style={{ color: "var(--color-text-muted)" }}>{item.metric}</span>
                </td>
                <td className="px-3 py-1.5" style={{ color: "var(--color-text-muted)" }}>
                  {item.unit}
                </td>
                <td className="px-3 py-1.5 text-right">{item.low}</td>
                <td className="px-3 py-1.5 text-right">{item.high}</td>
                <td className="px-3 py-1.5 text-right">{item.female_low ?? "—"}</td>
                <td className="px-3 py-1.5 text-right">{item.female_high ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card p-3">
        <div className="flex flex-wrap items-end gap-2 text-[12px]">
          <div>
            <div style={{ color: "var(--color-text-muted)" }}>临时试算指标</div>
            <select
              value={metric}
              onChange={(event) => setMetric(event.target.value)}
              className="mt-1 rounded border px-2 py-1 text-[12px]"
              style={{ borderColor: "var(--color-border)" }}
            >
              {items.map((item) => (
                <option key={item.metric} value={item.metric}>
                  {item.name_cn}
                </option>
              ))}
            </select>
          </div>
          <div>
            <div style={{ color: "var(--color-text-muted)" }}>下限</div>
            <input
              type="number"
              step="any"
              value={low}
              onChange={(event) => setLow(event.target.value)}
              className="mt-1 w-24 rounded border px-2 py-1 text-[12px]"
              style={{ borderColor: "var(--color-border)" }}
            />
          </div>
          <div>
            <div style={{ color: "var(--color-text-muted)" }}>上限</div>
            <input
              type="number"
              step="any"
              value={high}
              onChange={(event) => setHigh(event.target.value)}
              className="mt-1 w-24 rounded border px-2 py-1 text-[12px]"
              style={{ borderColor: "var(--color-border)" }}
            />
          </div>
          <button
            type="button"
            className="rounded px-3 py-1.5 text-[12px] font-medium text-white disabled:opacity-50"
            style={{ backgroundColor: "var(--color-brand)" }}
            onClick={() => {
              setError("");
              if (low === "" || high === "") {
                setError("试算需要同时给出下限与上限");
                return;
              }
              setTrial({ metric, low: Number(low), high: Number(high) });
            }}
          >
            试算
          </button>
          {trial ? (
            <button
              type="button"
              className="rounded border px-3 py-1.5 text-[12px]"
              style={{ borderColor: "var(--color-border)", color: "var(--color-text-secondary)" }}
              onClick={() => setTrial(null)}
            >
              还原
            </button>
          ) : null}
        </div>

        {trial ? (
          <div className="mt-3">
            <div
              className="mb-2 inline-flex items-center gap-2 rounded px-2 py-1 text-[11px]"
              style={{ backgroundColor: "var(--color-brand-soft)", color: "var(--color-brand)" }}
            >
              临时试算 · 未保存 · 不可导出
            </div>
            {trialChart.isError ? (
              <p className="text-[12px]" style={{ color: "var(--color-status-high)" }}>
                {trialChart.error instanceof ApiError ? trialChart.error.message : "试算失败"}
              </p>
            ) : trialChart.data ? (
              <TrialChart payload={trialChart.data} />
            ) : (
              <p className="text-[12px]">试算中…</p>
            )}
          </div>
        ) : (
          <p className="mt-2 text-[12px]" style={{ color: "var(--color-text-muted)" }}>
            填两条线看看"同一份数据、换一套标准"会怎样：只影响这张图，不写库、不影响报告与导出。
          </p>
        )}
      </section>
    </div>
  );
}

function TrialChart({ payload }: { payload: ChartPayload }) {
  return (
    <div>
      <EChart option={payload.echarts_option ?? {}} height={320} />
      <p className="mt-1 text-[12px]" style={{ color: "var(--color-text-secondary)" }}>
        {payload.caption}
      </p>
      <p className="text-[11px]" style={{ color: "var(--color-text-muted)" }}>
        口径 <code>{payload.ri_effective?.source}</code>（{payload.ri_effective?.trial ? "临时" : "已保存"}）
      </p>
    </div>
  );
}
