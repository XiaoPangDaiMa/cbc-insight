/** 加载占位：三种形状覆盖全站（卡片 / 图表 / 表格）。
 *
 * 用骨架屏而不是"加载中…"一句话，是因为后者会让页面高度在加载完成的瞬间跳变，
 * 用户刚要点的地方被顶走。骨架屏把高度先占住，视觉上也不至于是一片空白。
 * 尺寸刻意与真实组件对齐（卡片 ≈ 96px、图 320px），否则占位本身就是新的跳动源。
 */
export function SkeletonLine({ width = "100%", height = 12 }: { width?: string | number; height?: number }) {
  return <span className="skeleton block" style={{ width, height }} aria-hidden="true" />;
}

export function SkeletonCard({ lines = 3, height }: { lines?: number; height?: number }) {
  return (
    <div className="card p-3" style={{ height }} aria-hidden="true">
      <SkeletonLine width="40%" height={13} />
      <div className="mt-3 flex flex-col gap-2">
        {Array.from({ length: lines }, (_, index) => (
          <SkeletonLine key={index} width={index === lines - 1 ? "65%" : "100%"} height={11} />
        ))}
      </div>
    </div>
  );
}

export function SkeletonChart({ height = 320 }: { height?: number }) {
  return (
    <div className="card p-3" aria-hidden="true">
      <div className="flex items-center justify-between">
        <SkeletonLine width="180px" height={13} />
        <SkeletonLine width="48px" height={20} />
      </div>
      <div className="skeleton mt-3 w-full" style={{ height }} />
      <div className="mt-2">
        <SkeletonLine width="70%" height={12} />
      </div>
    </div>
  );
}

export function SkeletonTable({ rows = 6, columns = 4 }: { rows?: number; columns?: number }) {
  return (
    <div className="card overflow-hidden" aria-hidden="true">
      <div className="flex gap-3 border-b px-3 py-2" style={{ borderColor: "var(--color-border)" }}>
        {Array.from({ length: columns }, (_, index) => (
          <SkeletonLine key={index} width={`${100 / columns}%`} height={10} />
        ))}
      </div>
      <div className="flex flex-col gap-2 p-3">
        {Array.from({ length: rows }, (_, row) => (
          <div key={row} className="flex gap-3">
            {Array.from({ length: columns }, (_, column) => (
              <SkeletonLine key={column} width={`${100 / columns}%`} height={10} />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
