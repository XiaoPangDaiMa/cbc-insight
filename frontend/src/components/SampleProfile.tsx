import type { SampleProfilePayload } from "@/api/types";
import { StatusBadge } from "@/components/StatusBadge";
import { fmtAge, fmtNumber, fmtRange, genderLabel } from "@/lib/format";
import { statusColor } from "@/lib/colors";

/** 单样本体检单（个体口径，FR-31）。
 *
 * 条长用的是**标准化位置** ``pos = (x − low) / (high − low)``，不是原始值：
 * 直接按原始值画，HGB（100+）的条永远比 MCH（30 左右）长，看起来像"更严重"，
 * 而这是量纲造成的错觉（RK-17、T-22）。
 */
export function SampleProfile({
  profile,
  onClose,
}: {
  profile: SampleProfilePayload;
  onClose?: () => void;
}) {
  return (
    <aside className="card flex h-full flex-col gap-3 p-4">
      <header className="flex items-start justify-between gap-2">
        <div>
          <div className="text-sm font-semibold" style={{ color: "var(--color-text-primary)" }}>
            样本 #{profile.sample_index}
          </div>
          <div className="text-[11px]" style={{ color: "var(--color-text-muted)" }}>
            {genderLabel(profile.gender)} · {fmtAge(profile.age)}
          </div>
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="rounded border px-2 py-0.5 text-xs"
            style={{ borderColor: "var(--color-border)", color: "var(--color-text-secondary)" }}
            aria-label="关闭体检单"
          >
            关闭
          </button>
        )}
      </header>

      {profile.gender_missing && (
        <p className="rounded px-2 py-1 text-[11px]" style={{ backgroundColor: "var(--color-bg-subtle)", color: "var(--color-text-secondary)" }}>
          该样本缺少性别，依赖性别的指标（HGB/RBC/HCT）未判定。这不是"正常"，是"无法判断"。
        </p>
      )}

      <ul className="flex flex-col gap-2 overflow-y-auto pr-1">
        {profile.items.map((item) => {
          const color = statusColor(item.status);
          const width = item.pos === null ? 100 : Math.max(2, Math.min(100, item.pos * 100));
          return (
            <li key={item.metric}>
              <div className="flex items-baseline justify-between gap-2 text-xs">
                <span style={{ color: "var(--color-text-primary)" }}>{item.name_cn}</span>
                <span style={{ color: "var(--color-text-secondary)" }}>
                  {fmtNumber(item.value, item.decimals)} {item.unit}
                </span>
                <StatusBadge status={item.status} compact />
              </div>
              <div className="mt-1 h-1.5 w-full rounded-full" style={{ backgroundColor: "var(--color-bg-subtle)" }}>
                <div
                  className="h-1.5 rounded-full"
                  style={{
                    width: `${width}%`,
                    backgroundColor: color,
                    opacity: item.status === "NA" ? 0.6 : 1,
                  }}
                />
              </div>
              <div className="mt-0.5 flex justify-between text-[10px]" style={{ color: "var(--color-text-muted)" }}>
                <span>参考 {fmtRange(item.low, item.high, item.decimals)}</span>
                <span>{item.reason ? `未判定：${item.reason}` : item.pos === null ? "无参考区间" : `区间位置 ${(item.pos * 100).toFixed(0)}%`}</span>
              </div>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
