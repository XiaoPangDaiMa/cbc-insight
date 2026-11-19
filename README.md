# CBC Insight · 血常规数据分析与可视化系统

[![CI](https://github.com/XiaoPangDaiMa/cbc-insight/actions/workflows/ci.yml/badge.svg)](https://github.com/XiaoPangDaiMa/cbc-insight/actions/workflows/ci.yml)

上传一份脱敏的血常规（CBC）CSV，一分钟内看清三件事：**血象长什么样、谁不在参考区间内、
这些与性别和年龄是什么关系**——每个结论都附样本量 `n` 与判定依据。

> 本系统只做**分布描述与参考区间判定**，不做诊断、不预测疾病、不接医院系统。
> 数据为公开脱敏数据集或课程用样本；单人纵向趋势与任何临床结论都不在范围内。

需求文档：`D:\Study\fullstack-ai-agent-roadmap-main\血常规数据分析与可视化系统-需求与分析说明书.md`
（编号 CBC-INSIGHT-SRS-001，v1.5，共 27 条 FR / 17 条 BR / 37 条验收用例）。

---

## 一、一键启动（推荐）

**双击 `start.bat`** —— 或者右键 `start.ps1` →「使用 PowerShell 运行」。

脚本会按顺序做四件事，每件都可重复执行：

1. 检查 `backend/.venv`，没有就用**本机已装的 Python** 创建（不另装解释器）并按 `backend/requirements.txt` 装依赖（首次 1–3 分钟）；
2. 启动后端 `uvicorn`（8000），**等到 `/healthz` 通过**才继续；
3. 检查 `frontend/node_modules`，没有就 `pnpm install`，再启动 Vite（5173）；
4. 打开浏览器。

```text
==============================================
 CBC Insight 已启动
   前端  http://127.0.0.1:5173
   后端  http://127.0.0.1:8000/docs
   演示账号  demo_student / demo-2026-pass
   停止服务  .\stop.ps1
==============================================
```

| 入口 | 地址 |
|---|---|
| 前端界面 | <http://127.0.0.1:5173> |
| 后端 Swagger | <http://127.0.0.1:8000/docs> |
| 健康检查 | <http://127.0.0.1:8000/healthz> |
| 演示账号 | `demo_student` / `demo-2026-pass`（名下已有一份 8 行样本） |

**常用参数**

```powershell
.\start.ps1 -NoBrowser                 # 不自动开浏览器
.\start.ps1 -ApiPort 8010 -WebPort 5180   # 换端口（8000 被别的项目占用时）
$env:CBC_PYPI = "official"; .\start.ps1   # 走官方 PyPI 而不是清华镜像
.\stop.ps1                             # 停止（含 Vite 派生的 node 子进程）
```

**设计上的三个小决定**（都是被踩过的坑）

- **端口已在监听就先探活再决定**：活着就直接复用，不会把正在跑的服务顶掉，也不会因为"端口被占用"而报错退出。
- **启动成功的判据是探活，不是进程还在**：`uvicorn` 进程起来到能接请求之间有约 1 秒空窗，按进程判断会让前端在空窗期里报"接口连不上"。
- **停止时先按 PID 文件、再按端口兜底**：Vite 会派生一个 node 子进程，只杀父进程会留下占着 5173 的孤儿。

---

## 二、手动启动（想看日志时用）

```powershell
# 后端（虚拟环境就在 backend 里）
cd cbc-insight\backend
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 前端（另开一个终端）
cd cbc-insight\frontend
pnpm install      # 首次
pnpm dev
```

数据库默认 **SQLite**（`backend/data/app.db`，首次启动自动建表，零依赖即可跑通）。
真实部署或需要多用户并发时换 **Postgres**（依赖已包含 `psycopg`，只需给连接串）：

```powershell
# WSL 里跑 PG 时，Windows 侧直接用 127.0.0.1:5432 即可（WSL2 会转发 localhost）
$env:CBC_DATABASE_URL = "postgresql+psycopg://cbc:cbc@127.0.0.1:5432/cbc"
```

切换后数据在 PG 实例里，`backend/data/` 下不会出现任何数据库文件；两种库的表结构由同一份
SQLAlchemy 模型创建（`app/db/models.py`），换库不需要改代码。

---

## 三、在 IDE 里打开（PyCharm / WebStorm）

**先说结论**：这是一个**单仓库双子项目（monorepo）**，不是两个独立仓库。前后端确实是分离的
——`backend/` 与 `frontend/` 各自是一套完整工程，有各自的依赖与启动方式——但它们在**同一个
目录树里**，因为有三样东西横跨两边（见本节最后）。根目录下那些看起来"多余"的文件，绝大多数
是**编排文件或生成物**，不需要你打开。

### 打开方式 A：两个窗口（推荐，索引最快、补全最准）

| IDE | 打开这个目录 | 你会看到 |
|---|---|---|
| PyCharm | `cbc-insight\backend` | `app/`、`resources/`、`tests/`、`pyproject.toml` |
| WebStorm | `cbc-insight\frontend` | `src/`、`tests/`、`package.json`、`vite.config.ts` |

代价是跨端跳转看不到（点后端接口名不会跳到前端 `types.ts`），根目录脚本也看不到。

**PyCharm 四步**

1. `File → Open` 选 `D:\Project\Study Auto\cbc-insight\backend`（**不要选根目录**，
   否则 PyCharm 会把 `frontend/node_modules` 当成项目内容去索引，几万个小文件，卡十分钟）。
2. `Settings → Project → Python Interpreter → Add Interpreter → Existing`，
   选 `D:\Project\Study Auto\cbc-insight\backend\.venv\Scripts\python.exe`。
   虚拟环境就在 `backend/` 里，与 `requirements.txt`、`app/`、`tests/` 同处一个目录单元，
   所以「PyCharm 打开 backend」时解释器不需要到上级目录去找。
3. `Run → Edit Configurations → + → Python`，加两个配置：
   - 起后端：module name `uvicorn`，parameters `app.main:app --host 127.0.0.1 --port 8000`，
     working directory `...\cbc-insight\backend`
   - 跑测试：module name `pytest`，parameters `-q`，working directory `...\cbc-insight\backend`
4. 不需要手动 Mark as Sources Root——`pyproject.toml` 里的
   `[tool.pytest.ini_options] testpaths = ["tests"]` 与 ruff 配置已经说明了目录职责。

**WebStorm 三步**

1. `File → Open` 选 `...\cbc-insight\frontend`，等待索引结束（首次会读 `pnpm-lock.yaml`）。
2. `package.json` 里的脚本会自动出现在右上角的 npm/pnpm 面板：`dev`、`build`、`test:unit`。
3. 若面板找不到 pnpm（WebStorm 的包管理器检测偶尔漏掉），直接在 Terminal 里跑 `pnpm dev`，
   一样能拿到调试与热更新。`tsconfig.json` 里的 `@/*` 别名 WebStorm 自动识别，无需配置。

### 打开方式 B：一个窗口打开根目录

PyCharm 打开 `cbc-insight\` 也能干活（WebStorm 同理），但要额外做两件事，否则体验更差：

- `Settings → Project Structure` 把 `backend` 标为 Sources Root，把 `frontend` 从内容根里排除；
- 解释器仍指 `backend\.venv`（与打开 `backend` 时是同一个）。

只在你需要"前端改一行的同时在根目录跑脚本"时才值得这么开。

### 在 IDE 里启动（按绿三角之前必须做的两件事）

**第一件：给 PyCharm 配解释器。** 右下角如果显示 `<无解释器>`，按绿三角只会报
"No Python interpreter configured"。
`Settings → Project: backend → Python Interpreter → Add Interpreter → Add Local Interpreter →
Existing`，选 `D:\Project\Study Auto\cbc-insight\backend\.venv\Scripts\python.exe`。

**第二件：确认启动参数。** 仓库里已经放好三份运行配置（JetBrains 的 `.run/` 目录，
重启 IDE 后会出现在右上角下拉框里）：

| 配置名 | 所在项目 | 内容 |
|---|---|---|
| 后端 API (uvicorn 8000) | `backend` | 模块 `uvicorn`，参数 `app.main:app --host 127.0.0.1 --port 8000` |
| 后端测试 (pytest) | `backend` | 模块 `pytest`，参数 `tests -q` |
| 前端 dev (vite 5173) | `frontend` | npm 脚本 `dev`（pnpm） |

没出现就手动建一个（`Run → Edit Configurations → + → Python`），关键是这三格：

| 字段 | 填什么 | 说明 |
|---|---|---|
| 类型 | `Python` | 不要选脚本路径 |
| 模块名（`-m`） | `uvicorn` | 选 "module name" 而不是 "script path" |
| 参数 | `app.main:app --host 127.0.0.1 --port 8000` | 注意是 `app.main:app`，两个点一个冒号 |
| 工作目录 | `$PROJECT_DIR$`（即 `backend`） | **填错这里必挂** |

**工作目录填成项目根会直接报错**，实测原文：

```text
ModuleNotFoundError: No module named 'app'
```

原因：`app` 包在 `backend/app/` 下，`uvicorn` 会把**当前工作目录**塞进 `sys.path`；
工作目录是项目根时，根目录下没有 `app/`，自然找不到。

**启动顺序**：先起后端，等日志出现 `Uvicorn running on http://127.0.0.1:8000`，再起前端。
前端 `vite.config.ts` 的代理把 `/api` 写死到 8000——后端没起时页面能打开，但所有接口都是
`ECONNREFUSED`（浏览器控制台里会看到 500/502），看起来像"前端写错了"，其实是后端没启动。

**验证三连**：

1. <http://127.0.0.1:8000/healthz> → `{"ok":true,"version":"0.1.0"}`
2. <http://127.0.0.1:8000/docs> → Swagger 能打开
3. <http://127.0.0.1:5173> → 用 `demo_student` / `demo-2026-pass` 登录，工作台有数据集卡片

**WebStorm 里起前端**：右上角运行配置选「前端 dev (vite 5173)」；或者打开底部 Terminal 敲
`pnpm dev`（最稳，不受 npm 面板识别影响）。热更新、断点、Console 都一样。

### 根目录那些文件的身份

| 路径 | 是什么 | 要不要打开 |
|---|---|---|
| `start.bat` / `start.ps1` / `stop.ps1` | 一键启停（编排前端 + 后端） | 一般不用，双击即可 |
| `README.md` | 本文件 | — |
| `scripts/gen_theme.py` | **跨端**：读前端 tokens.json，写后端 matplotlib 样式 | 改配色时才看 |
| `scripts/smoke_local.py` | 用 TestClient 跑一遍主链路，不需要起服务器 | 想快速自检时看 |
| `backend/`、`frontend/` | 两个真正的项目（后端的 `.venv` 与 `data` 都在它里面） | 见上 |
| `backend/.venv/` | Python 依赖，与后端代码同目录 | 不要打开 |
| `backend/data/` | 上传的原始件、每步中间结果（parquet/json）、默认 SQLite 库 | 排查数据问题时看 |
| `.run/` | `start.ps1` 写下的进程 PID，`stop.ps1` 用 | 不要碰 |
| `node_modules/`、`dist/` | 前端依赖与构建产物 | 不要打开 |

### 为什么没有拆成两个仓库

不是偷懒，是这三样东西真的横跨两边：

1. **配色只有一个源**：`frontend/src/theme/tokens.json` → `scripts/gen_theme.py` → 同时生成
   前端 CSS 变量、ECharts 主题**和后端** `backend/resources/cbc.mplstyle`。拆开后一侧改色，
   另一侧不知道，屏幕图与报告图的颜色会慢慢漂移（RK-22，而且"两边看着都正常"，极难发现）。
2. **接口契约要同一次提交**：`frontend/src/api/types.ts` 与 `backend/app/api/v1/*` 是同一份
   契约的两半，改字段必须一起改、一起提交，否则提交历史里会出现"前端调一个不存在的字段"。
3. **仓库级文件**：一键启动脚本、`requirements.txt`、`.gitignore`、测试命令都定义在根上。

如果交付时确实被要求"前后端两个仓库"：`backend/` 与 `frontend/` 各自都能独立成库
（前者有 `pyproject.toml` + `requirements.txt`，后者有 `package.json` + `pnpm-lock.yaml`），
根级编排文件本来就不属于任何一边，删掉不影响两边单独运行。

---

## 四、目录

```text
cbc-insight/
├─ start.bat / start.ps1 / stop.ps1     一键启动与停止
├─ backend/
│  ├─ app/
│  │  ├─ api/v1/        auth · datasets · dashboard · reference
│  │  ├─ core/          config · errors · security · deps
│  │  ├─ db/            base · models · session
│  │  ├─ pipeline/      reading → mapping → units → validators → cleaning → rules → stats → captions
│  │  ├─ schemas/       pydantic 请求/响应
│  │  └─ services/      pipeline_runner · datasets · chart · loader
│  ├─ resources/        reference_ranges.yaml · field_dict.yaml · field_mapping.yaml
│  │                    cleaning_strategy.yaml · caption_templates.yaml · cbc.mplstyle(生成)
│  ├─ tests/            BR 规则单测 + 管线夹具 + 接口级回归（110 用例）
│  ├─ data/             raw · processed · rendered · reports + app.db（运行时生成）
│  ├─ .venv/            Python 依赖（与 requirements.txt 同级，跟后端一起搬走即可）
│  └─ requirements.txt
├─ frontend/
│  ├─ src/
│  │  ├─ api/           client · hooks · types（与 8.1 API 一一对应）
│  │  ├─ auth/          会话与路由守卫
│  │  ├─ components/    StatusBadge · MetricCard · SampleProfile · DatasetCard · EChart · Layout
│  │  ├─ lib/           format（4.4.6 数字规则）· colors（从 CSS 变量取色）
│  │  ├─ pages/         Login · Register · Dashboard · DatasetDetail · ExportCenter · Account
│  │  └─ theme/         tokens.json（唯一配色来源）+ 生成产物
│  └─ tests/            unit（不进 src/，NFR-M-08）
├─ scripts/             根级工具（跨前后端，不属于任何一边）
│  ├─ gen_theme.py       tokens.json → CSS 变量 / ECharts 主题 / matplotlib rcParams
│  └─ smoke_local.py     TestClient 冒烟：注册→上传→图表→导出→删除
└─ .run/                进程 PID（stop.ps1 用）
```

运行时会落盘的东西（都在 `backend/data/`）：`raw/{id}.csv`（原始件）、`processed/{id}/*.parquet|json`
（S1–S7 每一步的中间结果）、`rendered/`（静态图）、`reports/`（HTML 报告）、`app.db`（默认 SQLite 库）。
**每步落盘**是"可复现"承诺的实现基础：任何一步出问题都能单独重跑，答辩时也能展示中间结果。

---

## 五、测试与质量门禁

```powershell
cd cbc-insight\backend
.venv\Scripts\python.exe -m pytest -q        # 110 passed
.venv\Scripts\ruff.exe check app tests       # All checks passed

cd ..\frontend
pnpm exec tsc --noEmit                          # 类型检查
pnpm exec vitest run tests/unit                 # 11 passed
pnpm build                                      # 产出 dist/
```

- 后端测试扁平放在 `backend/tests/`，**`app/` 下不出现 `test_*.py`**（NFR-M-08）；
  接口级用例用临时 SQLite + 临时数据目录，因此**不需要 Docker**。
- 前端单元测试在 `frontend/tests/unit/`，`src/` 下不出现 `*.test.tsx`。
  图表只断言传给 ECharts 的 `option` 对象，不比像素（像素比对会因为字体/dpi 差异常年变红，最后一定被删掉）。
- 覆盖率门禁只对 `app/pipeline/` 与 `app/services/` 设 80%，路由层靠"每个端点三个用例"覆盖。

---

## 六、改配色 / 改参考区间

**配色只从一处出**：

```powershell
cd cbc-insight
backend\.venv\Scripts\python.exe scripts\gen_theme.py          # 重新生成三端
backend\.venv\Scripts\python.exe scripts\gen_theme.py --check  # 校验产物是否最新（T-32）
```

改 `frontend/src/theme/tokens.json` 后重跑，CSS 变量、ECharts 主题、matplotlib 样式同时更新；
**组件里不写任何字面十六进制色值**。

**参考区间**在 `backend/resources/reference_ranges.yaml`（默认 WS/T 405-2012 成人区间，
男女分开，版本号 `v2026.11.1`）。也可以在界面或 `PUT /api/v1/reference-ranges` 改，
每次修改都会入库一份只读快照，历史报告仍可复现。

---

## 七、已实现的功能（对照需求文档）

| 需求 | 落地情况 |
|---|---|
| FR-01 上传 | 编码探测（UTF-8/-BOM/GBK/GB18030）、分隔符投票、哈希去重 409、体积/行数上限 |
| FR-02 映射 | 别名表 + 模糊匹配，必填字段缺失抛 40004，人工确认后重跑整条管线 |
| FR-03 预览 | 分页 ≤100 行，带 `sample_index` 与 `age_band` |
| FR-04 校验 | DQ-01~06、值域/重复/逻辑一致性（`\|hct − rbc×mcv/10\|/hct > 15%`） |
| FR-05 清洗 | 类型修复 → 置空 → 剔列（核心三字段豁免）→ 去重 → 逻辑置空 → 删全空行 → 分组中位数填充 |
| FR-06 对比 | 清洗前后行数、按原因计数的删除明细 |
| FR-07~13 图 | 箱线（按性别分组 + 两组参考带）、直方（区间内外占比）、相关热力（Spearman + 数学耦合标注）、散点 |
| FR-14 筛选 | 过滤条件与年龄/性别组合，结果与导出共用同一列定义 |
| FR-16/17 判定 | 11 种模式 + `UNCLASSIFIED` 兜底、严重度排序；`gender` 缺失判 `NA`，不套男性区间 |
| FR-18/19/35 导出 | UTF-8-BOM CSV + 同名 `*_meta.json`，预览与下载列名/顺序/数量完全一致 |
| FR-30 指标状态 | 常驻面板，三通道编码（颜色 + ↑↓—∅ + 文字），`MIXED` 显示"两侧均异常" |
| FR-31 体检单 | 条长用标准化位置 `pos = (x − low) / (high − low)`，量纲不同也可比 |
| FR-32 图注 | 模板渲染 + 四条退化规则（n<10 无 p 值、p≥0.05 不说"显著"、\|ρ\|<0.3 不解读、缺 gender 不提男女） |
| FR-33/34 账号 | 注册即登录、改名、改密、连续失败 5 次锁 15 分钟、登出吊销 refresh |
| FR-28 数据集 | 列表、切换、重命名、级联删除（含磁盘文件清理） |

## 八、还没做

- 前端「筛选」tab 与异常清单导出（M3 余项）、FR-29 多数据集并排对比（M4）、
  FR-20/21 图表与 HTML 报告导出（M4）、Playwright E2E（M4）。
- Redis 队列：当前 10 万行以内走同步链路，超过 `sync_clean_budget_seconds` 再接 RQ。
- PDF 解析（FR-25）、跨数据集统计推断（v2，且须先论证可比性）。

---

## 九、三条实现与需求文档不一致的地方（待同步回 SRS）

1. **BR-07 / 5.1 缺兜底模式**：11 种模式之外，"1–2 项异常但不匹配任何模式"的样本无处归类。
   实现新增 `UNCLASSIFIED`（其他异常组合）；异常 ≥3 项仍归 `MULTI_ABNORMAL`。
2. **3.4 把 rbc 的"万/µL"写成 ÷1000**：按量纲应是 **÷100**（1×10¹²/L = 100 万/µL）。
   已按 ÷100 实现；照文档原文实现会得到 10 倍偏差。
3. **BR-03 未区分核心字段**：缺失率 > 30% 整列剔除若作用在 `hgb/wbc/plt` 上，
   S6 会输出"没有任何异常"——用户看到一份干净报告，比报错更危险。
   实现中核心三字段豁免剔列、只记告警。

---

## 十、免责声明

本系统面向教学与研究，使用公开脱敏数据；输出仅为"是否超出参考区间"的机械判定，
不构成任何医学诊断或建议。参考区间默认取 WS/T 405-2012 成人区间，不同实验室、不同检测
系统存在差异，实际应以报告单标注为准，且可在系统中配置与换版。
