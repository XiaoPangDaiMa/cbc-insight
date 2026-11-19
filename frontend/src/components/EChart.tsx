import { useMemo } from "react";
import * as echarts from "echarts";
import { useEffect, useRef } from "react";

import { chartPalette } from "@/lib/colors";

/** ECharts 的 React 包装：只做 init / setOption / resize / dispose 四件事。
 *
 * 刻意不引入 echarts-for-react：这里需要的东西太少，多一个依赖就多一个
 * "它到底改了 option 的哪里" 的黑盒。option 完全由调用方（页面/服务端）决定，
 * 颜色在 cssVar 里从 tokens 取，所以组件不持有任何配色知识。
 */
export function EChart({
  option,
  height = 360,
  onPointClick,
}: {
  option: Record<string, unknown>;
  height?: number;
  onPointClick?: (sampleIndex: number) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const instance = useRef<echarts.ECharts | null>(null);

  const themed = useMemo(() => {
    const palette = chartPalette();
    return {
      ...option,
      color: (option.color as string[] | undefined) ?? palette,
    };
  }, [option]);

  useEffect(() => {
    if (!container.current) return;
    const chart = echarts.init(container.current, undefined, { renderer: "canvas" });
    instance.current = chart;
    return () => {
      chart.dispose();
      instance.current = null;
    };
  }, []);

  useEffect(() => {
    instance.current?.setOption(themed, true);
  }, [themed]);

  useEffect(() => {
    if (!instance.current) return;
    const observer = new ResizeObserver(() => instance.current?.resize());
    if (container.current) observer.observe(container.current);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const chart = instance.current;
    if (!chart || !onPointClick) return;
    const handler = (params: unknown) => {
      const payload = params as { data?: unknown; value?: unknown };
      const data = payload.data;
      // 服务端给了 points[]，但图上的点到不到 sample_index，所以用 "dataIndex" 兜底不可靠；
      // 这里只处理箱线图/柱状图明确带 sample_index 的情况，其余静默忽略（交互只读，BR-15）。
      if (data && typeof data === "object" && "sample_index" in (data as Record<string, unknown>)) {
        const index = Number((data as Record<string, unknown>).sample_index);
        if (Number.isFinite(index)) onPointClick(index);
      }
    };
    chart.on("click", handler);
    return () => {
      chart.off("click", handler);
    };
  }, [onPointClick]);

  return <div ref={container} style={{ width: "100%", height }} role="img" />;
}
