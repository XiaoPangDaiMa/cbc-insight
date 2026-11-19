import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { StatusBadge } from "@/components/StatusBadge";
import type { Status } from "@/api/types";

describe("StatusBadge 的三重编码（BR-14）", () => {
  it.each<[Status, string, string]>([
    ["LOW", "偏低", "↓"],
    ["NORMAL", "正常", "—"],
    ["HIGH", "偏高", "↑"],
    ["NA", "未判定", "∅"],
  ])("%s 同时给出文字与符号", (status, text, symbol) => {
    render(<StatusBadge status={status} />);
    const badge = screen.getByText(text).closest("[data-status]");
    expect(badge).not.toBeNull();
    expect(badge).toHaveAttribute("data-status", status);
    // 符号与文字在同一个节点里——只靠颜色的方案在这里会失败
    expect(badge?.textContent).toContain(symbol);
    expect(badge?.textContent).toContain(text);
  });

  it("紧凑模式保留符号，去掉文字", () => {
    const { container } = render(<StatusBadge status="HIGH" compact />);
    const badge = container.querySelector("[data-status]");
    expect(badge?.textContent).toContain("↑");
    expect(badge?.textContent).not.toContain("偏高");
  });
});
