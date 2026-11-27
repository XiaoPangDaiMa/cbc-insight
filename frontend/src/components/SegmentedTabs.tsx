import { useRef } from "react";

/** 分段控件：选中态靠"白底 + 阴影"，而不是换颜色。
 *
 * 为什么不用高亮色：这套界面里颜色已经承载三态语义（偏低蓝 / 正常绿 / 偏高红），
 * 再让颜色表示"当前 tab"，用户就要在同一块屏幕上同时解读两套颜色含义（BR-14）。
 *
 * 键盘可用：←/→ 在 tab 之间移动，Home/End 跳首尾，焦点跟随选中项——
 * 只用鼠标能操作的功能，在答辩现场用投影器时经常点不准。
 */
export function SegmentedTabs<T extends string>({
  items,
  value,
  onChange,
  ariaLabel,
  className = "",
}: {
  items: { key: T; label: string }[];
  value: T;
  onChange: (next: T) => void;
  ariaLabel?: string;
  className?: string;
}) {
  const container = useRef<HTMLDivElement>(null);

  function focusAt(index: number) {
    const buttons = container.current?.querySelectorAll<HTMLButtonElement>("[role='tab']");
    buttons?.[index]?.focus();
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    const index = items.findIndex((item) => item.key === value);
    const last = items.length - 1;
    let next = index;
    if (event.key === "ArrowRight") next = index >= last ? 0 : index + 1;
    else if (event.key === "ArrowLeft") next = index <= 0 ? last : index - 1;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = last;
    else return;
    event.preventDefault();
    onChange(items[next].key);
    focusAt(next);
  }

  return (
    <div
      ref={container}
      className={`seg overflow-x-auto ${className}`}
      role="tablist"
      aria-label={ariaLabel}
      onKeyDown={onKeyDown}
    >
      {items.map((item) => {
        const selected = item.key === value;
        return (
          <button
            key={item.key}
            type="button"
            role="tab"
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            className="seg-item shrink-0 whitespace-nowrap"
            onClick={() => onChange(item.key)}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
