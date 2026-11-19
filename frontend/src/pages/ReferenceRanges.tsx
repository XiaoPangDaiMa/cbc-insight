/** 我的参考区间（FR-24，SRS 3.5.1 三层模型）。

三条界面上的硬规矩，改代码时别松：

* 默认值**只读**：它是别人实验室的表，不是你的表；改了就写进"我的区间"。
* 保存是**整份 15 项**，且必须填理由——只存差异会在默认表升级那天开始撒谎。
* 这里改完**不会**自动重判已有数据集（BR-18）：数据集详情页会显示"陈旧"并给一键重判。
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, keys } from "@/api/hooks";
import { ApiError } from "@/api/client";
import type { RangeDraft, RangeItem } from "@/api/types";
import { EmptyState } from "@/components/EmptyState";

interface DraftRow {
  metric: string;
  name_cn: string;
  unit: string;
  gender_dependent: boolean;
  low: string;
  high: string;
  female_low: string;
  female_high: string;
  default_low: number;
  default_high: number;
  default_female_low: number | null;
  default_female_high: number | null;
}

function toRows(items: Record<string, RangeItem>, base?: Record<string, RangeItem>): DraftRow[] {
  const reference = base ?? items;
  return Object.values(items).map((item) => ({
    metric: item.metric,
    name_cn: item.name_cn,
    unit: item.unit,
    gender_dependent: item.gender_dependent,
    low: String(item.low),
    high: String(item.high),
    female_low: item.female_low === null ? "" : String(item.female_low),
    female_high: item.female_high === null ? "" : String(item.female_high),
    default_low: reference[item.metric]?.low ?? item.low,
    default_high: reference[item.metric]?.high ?? item.high,
    default_female_low: reference[item.metric]?.female_low ?? null,
    default_female_high: reference[item.metric]?.female_high ?? null,
  }));
}

function toDraft(rows: DraftRow[]): RangeDraft {
  const draft: RangeDraft = {};
  for (const row of rows) {
    const entry: { low: number; high: number; female_low?: number | null; female_high?: number | null } = {
      low: Number(row.low),
      high: Number(row.high),
    };
    if (row.female_low !== "" && row.female_high !== "") {
      entry.female_low = Number(row.female_low);
      entry.female_high = Number(row.female_high);
    }
    draft[row.metric] = entry;
  }
  return draft;
}

export function ReferenceRanges() {
  const queryClient = useQueryClient();
  const mine = useQuery({ queryKey: keys.myRanges, queryFn: api.myRanges });
  const versions = useQuery({ queryKey: keys.rangeVersions, queryFn: api.rangeVersions });

  const [rows, setRows] = useState<DraftRow[]>([]);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!mine.data) return;
    const source = mine.data.mine?.items ?? mine.data.effective.items ?? mine.data.default.items;
    setRows(toRows(source, mine.data.default.items));
    setNote(mine.data.mine?.note ?? "");
  }, [mine.data]);

  const save = useMutation({
    mutationFn: () => api.saveRanges(toDraft(rows), note),
    onSuccess: async () => {
      setError("");
      await queryClient.invalidateQueries({ queryKey: keys.myRanges });
      await queryClient.invalidateQueries({ queryKey: keys.rangeVersions });
    },
    onError: (err: unknown) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  const reset = useMutation({
    mutationFn: () => api.resetRanges(),
    onSuccess: async () => {
      setError("");
      await queryClient.invalidateQueries({ queryKey: keys.myRanges });
      await queryClient.invalidateQueries({ queryKey: keys.rangeVersions });
    },
    onError: (err: unknown) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  const update = (metric: string, field: keyof DraftRow, value: string) =>
    setRows((current) => current.map((row) => (row.metric === metric ? { ...row, [field]: value } : row)));

  if (mine.isLoading) return <div className="text-[13px]">加载中…</div>;
  if (!mine.data) return <EmptyState title="读不到区间配置" description="刷新页面重试；若持续失败请查看后端日志。" />;

  const effective = mine.data.effective;
  const isDefault = !mine.data.mine;

  return (
    <div className="space-y-3">
      <header className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-base font-semibold">我的参考区间</h1>
          <p className="mt-1 text-[12px]" style={{ color: "var(--color-text-secondary)" }}>
            当前生效口径 <code>{effective.source}</code>（指纹 {effective.digest}）。
            {isDefault ? " 你还没有自定义区间，现在用的是默认表。" : ` 第 ${versions.data?.items[0]?.version ?? ""} 版，备注：${mine.data.mine?.note ?? ""}`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="rounded border px-3 py-1.5 text-[12px]"
            style={{ borderColor: "var(--color-border)", color: "var(--color-text-secondary)" }}
            onClick={() => {
              if (!mine.data.mine) return;
              if (window.confirm("回到默认区间会删除你自己保存的全部版本，确定吗？")) reset.mutate();
            }}
            disabled={isDefault || reset.isPending}
          >
            回到默认
          </button>
          <button
            type="button"
            className="rounded px-3 py-1.5 text-[12px] font-medium text-white disabled:opacity-50"
            style={{ backgroundColor: "var(--color-brand)" }}
            onClick={() => save.mutate()}
            disabled={save.isPending}
          >
            {save.isPending ? "保存中…" : "保存为新版本"}
          </button>
        </div>
      </header>

      <div className="card p-3">
        <label className="block text-[12px]" style={{ color: "var(--color-text-secondary)" }}>
          本次修改的理由（必填，会记进版本历史）
        </label>
        <input
          value={note}
          onChange={(event) => setNote(event.target.value)}
          maxLength={200}
          placeholder="例：按本院检验科 HGB 男性下限 125 调整"
          className="mt-1 w-full rounded border px-2 py-1.5 text-[13px]"
          style={{ borderColor: "var(--color-border)" }}
        />
      </div>

      {error ? (
        <div className="rounded border px-3 py-2 text-[12px]" style={{ borderColor: "var(--color-status-high)", color: "var(--color-status-high)" }}>
          {error}
        </div>
      ) : null}

      <div className="card overflow-hidden">
        <table className="w-full text-[12px]">
          <thead style={{ backgroundColor: "var(--color-bg-page)", color: "var(--color-text-secondary)" }}>
            <tr>
              <th className="px-3 py-2 text-left">指标</th>
              <th className="px-3 py-2 text-left">单位</th>
              <th className="px-3 py-2 text-right">下限</th>
              <th className="px-3 py-2 text-right">上限</th>
              <th className="px-3 py-2 text-right">女性下限</th>
              <th className="px-3 py-2 text-right">女性上限</th>
              <th className="px-3 py-2 text-left">默认表</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.metric} className="border-t" style={{ borderColor: "var(--color-border)" }}>
                <td className="px-3 py-1.5">
                  {row.name_cn}
                  <span className="ml-1" style={{ color: "var(--color-text-muted)" }}>
                    {row.metric}
                  </span>
                </td>
                <td className="px-3 py-1.5" style={{ color: "var(--color-text-muted)" }}>
                  {row.unit}
                </td>
                {(["low", "high"] as const).map((field) => (
                  <td key={field} className="px-3 py-1.5 text-right">
                    <input
                      type="number"
                      step="any"
                      value={row[field]}
                      onChange={(event) => update(row.metric, field, event.target.value)}
                      className="w-20 rounded border px-2 py-1 text-right text-[12px]"
                      style={{ borderColor: "var(--color-border)" }}
                    />
                  </td>
                ))}
                {(["female_low", "female_high"] as const).map((field) => (
                  <td key={field} className="px-3 py-1.5 text-right">
                    <input
                      type="number"
                      step="any"
                      value={row[field]}
                      onChange={(event) => update(row.metric, field, event.target.value)}
                      disabled={!row.gender_dependent}
                      placeholder={row.gender_dependent ? "" : "—"}
                      className="w-20 rounded border px-2 py-1 text-right text-[12px] disabled:opacity-40"
                      style={{ borderColor: "var(--color-border)" }}
                    />
                  </td>
                ))}
                <td className="px-3 py-1.5" style={{ color: "var(--color-text-muted)" }}>
                  {row.default_female_low !== null
                    ? `男 ${row.default_low}–${row.default_high} / 女 ${row.default_female_low}–${row.default_female_high}`
                    : `${row.default_low}–${row.default_high}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card p-3">
        <h2 className="text-[13px] font-medium">版本历史</h2>
        {versions.data?.items.length ? (
          <ul className="mt-2 space-y-1 text-[12px]" style={{ color: "var(--color-text-secondary)" }}>
            {versions.data.items.map((item) => (
              <li key={item.version}>
                v{item.version} · <code>{item.digest}</code> · {item.created_at ?? "—"} · {item.note}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-[12px]" style={{ color: "var(--color-text-muted)" }}>
            还没有保存过自己的区间。
          </p>
        )}
      </div>
    </div>
  );
}
