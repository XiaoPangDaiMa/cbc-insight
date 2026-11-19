import type { DatasetPayload } from "@/api/types";
import { fmtDateTime, fmtPct } from "@/lib/format";

/** 数据集卡片（FR-33 工作台的最小单元）。五行信息是硬要求：
 * 名称、行数、参考区间版本、健康度一句话、更新时间——缺任何一行，
 * 用户在切换数据集时就无法判断"这是哪一份、结论还成不成立"。
 */
export function DatasetCard({
  dataset,
  active = false,
  onOpen,
  onDelete,
}: {
  dataset: DatasetPayload;
  active?: boolean;
  onOpen?: () => void;
  onDelete?: () => void;
}) {
  return (
    <div
      className="card flex flex-col gap-2 p-4"
      style={{
        borderColor: active ? "var(--color-brand)" : "var(--color-border)",
        boxShadow: active ? "0 0 0 1px var(--color-brand)" : "none",
      }}
    >
      <div className="flex items-start justify-between gap-2">
        <button type="button" onClick={onOpen} className="text-left">
          <div className="text-sm font-semibold" style={{ color: "var(--color-text-primary)" }}>
            {dataset.name}
          </div>
          <div className="text-[11px]" style={{ color: "var(--color-text-muted)" }}>
            {dataset.original_filename}
          </div>
        </button>
        {onDelete && (
          <button
            type="button"
            onClick={onDelete}
            className="rounded border px-2 py-0.5 text-[11px]"
            style={{ borderColor: "var(--color-border)", color: "var(--color-danger)" }}
          >
            删除
          </button>
        )}
      </div>

      <dl className="grid grid-cols-2 gap-1 text-[11px]" style={{ color: "var(--color-text-secondary)" }}>
        <div>
          <dt className="inline" style={{ color: "var(--color-text-muted)" }}>
            行数{" "}
          </dt>
          <dd className="inline">{dataset.rows}</dd>
        </div>
        <div>
          <dt className="inline" style={{ color: "var(--color-text-muted)" }}>
            参考区间{" "}
          </dt>
          <dd className="inline">{dataset.ri_version}</dd>
        </div>
        <div>
          <dt className="inline" style={{ color: "var(--color-text-muted)" }}>
            异常率{" "}
          </dt>
          <dd className="inline">{fmtPct(dataset.anomaly_rate)}</dd>
        </div>
        <div>
          <dt className="inline" style={{ color: "var(--color-text-muted)" }}>
            更新{" "}
          </dt>
          <dd className="inline">{fmtDateTime(dataset.updated_at)}</dd>
        </div>
      </dl>

      <p className="text-[11px]" style={{ color: "var(--color-text-secondary)" }}>
        {dataset.health || "—"}
      </p>

      {dataset.status !== "cleaned" && (
        <p className="text-[11px]" style={{ color: "var(--color-danger)" }}>
          状态：{dataset.status}
        </p>
      )}
    </div>
  );
}
