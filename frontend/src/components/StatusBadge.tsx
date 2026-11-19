import type { Status } from "@/api/types";
import { statusColor, statusSymbol, statusText } from "@/lib/colors";

/** 三态徽标：颜色 + 符号 + 文字同时出现（BR-14）。
 *
 * 只给颜色是不够的——灰度打印、答辩投影偏色、色觉差异都会把红绿蓝压成一片。
 * 因此符号（↑/↓/—/∅）与中文文字必须和颜色在同一个组件里产出，不能靠调用方记得补。
 * 颜色一律从 CSS 变量取（tokens.json 是唯一来源），组件里没有字面色值。
 */
export function StatusBadge({ status, compact = false }: { status: Status; compact?: boolean }) {
  const color = statusColor(status);
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium"
      style={{
        color,
        borderColor: color,
        backgroundColor: `color-mix(in srgb, ${color} 10%, transparent)`,
      }}
      data-status={status}
    >
      <span aria-hidden="true" className="font-mono leading-none">
        {statusSymbol(status)}
      </span>
      {!compact && <span>{statusText(status)}</span>}
    </span>
  );
}

export function StatusDot({ status }: { status: Status }) {
  return (
    <span
      className="inline-block h-2 w-2 rounded-full"
      style={{ backgroundColor: statusColor(status) }}
      title={statusText(status)}
      aria-label={statusText(status)}
    />
  );
}
