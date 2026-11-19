"""把 ``frontend/src/theme/tokens.json`` 展开成四端产物（NFR-M-07 单一配色来源，T-32）。

四个下游：
1. ``frontend/src/theme/tokens.generated.css``  —— CSS 自定义属性，界面唯一的取色入口；
2. ``frontend/src/theme/echarts.generated.json`` —— ECharts 主题（系列色 + 基础字号）；
3. ``backend/resources/cbc.mplstyle``           —— matplotlib rcParams，供服务端报告出图；
4. ``backend/resources/theme.json``             —— 服务端渲染器（报告 HTML / matplotlib）读的
   原始 token，避免在 Python 里写死十六进制色值（RK-22）。

改配色只改 ``tokens.json`` 再跑一次本脚本；**不要在组件里写字面十六进制色值**，
否则屏幕图与报告图的颜色会各自漂移（RK-22、RK-23）。

用法（在项目根目录或任意目录都可以执行）：
    python scripts/gen_theme.py            # 生成
    python scripts/gen_theme.py --check    # 只校验产物是否最新（CI / T-32 用）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


# 项目根 = 同时含有 frontend/src/theme/tokens.json 与 backend/ 的那一层。
# 这样脚本放在根目录 scripts/ 还是在 frontend/scripts/ 都能跑，避免搬目录就失效。
def _find_project_root() -> Path:
    for candidate in [Path(__file__).resolve().parent, *Path(__file__).resolve().parents]:
        if (candidate / "frontend" / "src" / "theme" / "tokens.json").is_file() and (candidate / "backend").is_dir():
            return candidate
    raise SystemExit("找不到项目根目录：请确认本脚本位于 cbc-insight/scripts/ 之下。")


PROJECT = _find_project_root()
FRONTEND = PROJECT / "frontend"
TOKENS = FRONTEND / "src" / "theme" / "tokens.json"
CSS_OUT = FRONTEND / "src" / "theme" / "tokens.generated.css"
ECHARTS_OUT = FRONTEND / "src" / "theme" / "echarts.generated.json"
MPL_OUT = PROJECT / "backend" / "resources" / "cbc.mplstyle"
THEME_OUT = PROJECT / "backend" / "resources" / "theme.json"

BANNER = "/* 由 scripts/gen_theme.py 从 tokens.json 生成，请勿手改。 */\n"


def _flat(color_group: dict[str, str], prefix: str) -> dict[str, str]:
    return {f"--{prefix}-{key.replace('_', '-')}": value for key, value in color_group.items()}


def build_css(tokens: dict[str, Any]) -> str:
    colors: dict[str, str] = {}
    colors.update(_flat(tokens["color"], "color"))
    for index, value in enumerate(tokens["chart"]["series"], start=1):
        colors[f"--chart-series-{index}"] = value

    lines = [BANNER, ":root {"]
    lines += [f"  {name}: {value};" for name, value in colors.items()]
    for key, value in tokens["space"].items():
        lines.append(f"  --space-{key}: {value}px;")
    for key, value in tokens["radius"].items():
        lines.append(f"  --radius-{key}: {value}px;")
    lines += [f"  --font-{key}: {value};" for key, value in tokens["font"].items()]
    lines.append("}")
    return "\n".join(lines) + "\n"


def build_echarts(tokens: dict[str, Any]) -> dict[str, Any]:
    color = tokens["color"]
    return {
        "color": tokens["chart"]["series"],
        "backgroundColor": "transparent",
        "textStyle": {"fontFamily": tokens["font"]["family"], "color": color["text_secondary"], "fontSize": 12},
        "title": {"textStyle": {"color": color["text_primary"], "fontWeight": 600}},
        "legend": {"textStyle": {"color": color["text_secondary"]}},
        "grid": {"borderColor": color["grid"]},
        "categoryAxis": {
            "axisLine": {"lineStyle": {"color": color["border"]}},
            "axisTick": {"show": False},
            "axisLabel": {"color": color["text_secondary"]},
            "splitLine": {"show": False},
        },
        "valueAxis": {
            "axisLine": {"show": False},
            "axisTick": {"show": False},
            "axisLabel": {"color": color["text_secondary"]},
            "splitLine": {"lineStyle": {"color": color["grid"]}},
        },
        "tooltip": {
            "backgroundColor": color["bg_surface"],
            "borderColor": color["border"],
            "textStyle": {"color": color["text_primary"], "fontSize": 12},
        },
        # 三态语义色固定，不随主题换色相（RK-23）
        "cbcStatus": {
            "low": color["status_low"],
            "normal": color["status_normal"],
            "high": color["status_high"],
            "na": color["status_na"],
            "refband": color["refband"],
        },
    }


def build_mplstyle(tokens: dict[str, Any]) -> str:
    """只写与颜色无关的版式项。

    **不要往这里写颜色**：matplotlibrc 把 ``#`` 当注释起始，``axes.edgecolor: #E2E8F0``
    会被截成空值（报 ``does not look like a color arg``），``cycler('color', ['#0072B2'])``
    也会在第一个 ``#`` 处断掉。颜色统一由 ``app/services/render.py`` 从 ``theme.json``
    注入 rcParams，仍然是单一来源（NFR-M-07）。
    """
    return "\n".join(
        [
            "# 由 scripts/gen_theme.py 从 tokens.json 生成，请勿手改。",
            "# 颜色不写在这里：matplotlibrc 视 '#' 为注释起始，十六进制色值会被截断。",
            "# 颜色由 backend/app/services/render.py 从 theme.json 注入（单一来源）。",
            "axes.grid: True",
            "grid.linewidth: 0.6",
            "grid.alpha: 0.7",
            "font.size: 11",
            "figure.dpi: 120",
            "savefig.dpi: 300",
            "axes.unicode_minus: False",
            "axes.titlesize: 12",
            "axes.titlelocation: left",
            "figure.autolayout: False",
            "",
        ]
    )


def render_all(tokens: dict[str, Any]) -> dict[Path, str]:
    return {
        CSS_OUT: build_css(tokens),
        ECHARTS_OUT: json.dumps(build_echarts(tokens), ensure_ascii=False, indent=2) + "\n",
        MPL_OUT: build_mplstyle(tokens),
        # 服务端原样消费：报告模板与 matplotlib 渲染器都从这里取色
        THEME_OUT: json.dumps(tokens, ensure_ascii=False, indent=2) + "\n",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tokens.json → CSS / ECharts / matplotlib")
    parser.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = parser.parse_args(argv)

    tokens = json.loads(TOKENS.read_text(encoding="utf-8"))
    stale: list[Path] = []
    for path, content in render_all(tokens).items():
        if args.check:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current != content:
                stale.append(path)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"wrote {path.relative_to(PROJECT)}")

    if stale:
        print("以下产物与 tokens.json 不一致，请重新运行 scripts/gen_theme.py：")
        for path in stale:
            print(f"  - {path.relative_to(PROJECT)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
