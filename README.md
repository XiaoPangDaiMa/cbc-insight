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

### 用 Docker 起（pg + redis + api + nginx 一次到位）

```powershell
cd cbc-insight
copy .env.example .env      # 按需改 JWT_SECRET 与库密码；compose 会读取
docker compose up -d --build
# 前端 http://127.0.0.1:5173   后端 http://127.0.0.1:8000/docs
docker compose down
```

- 镜像里装了 **Noto Sans CJK**：缺中文字体时 matplotlib 不会报错，只会把中文画成方框，
  而这种问题只在导出报告时才会被发现（RK-05）。
- `web` 用 nginx 托管 `dist`，`/api/` 反代到 `api:8000`，上传上限放到 60 MB（与后端 50 MB 对齐留余量）。
- compose 的 `.env`（根目录）是给容器编排用的变量清单；后端自己的配置读 `backend/.env`，
  两处不要混：前者的变量名是 `POSTGRES_*`/`JWT_SECRET`，后者是 `CBC_*`。

### 用 WSL 里的 Postgres（本机开发现状，v1.8 起）

开发机现在的连接串指向 WSL 里的 PostgreSQL 18（`ubuntu 26.04`），不再用 SQLite。

```powershell
# 1) 起库（WSL 里的 systemd 服务，开机自启一般已生效）
wsl -u root -- service postgresql status

# 2) 首次只做一次：建角色与库（用 peer 认证，不需要超级用户密码）
wsl -u postgres -- psql -c "CREATE ROLE cbc LOGIN PASSWORD 'cbc_dev_password';"
wsl -u postgres -- psql -c "CREATE DATABASE cbc OWNER cbc ENCODING 'UTF8' TEMPLATE template0;"

# 3) 结构由 alembic 管（后端启动时也会自动 upgrade head）
cd backend
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m alembic check       # 期望 "No new upgrade operations detected"

# 4) 把旧的 SQLite 数据搬过来（保留 dataset.id，因为磁盘目录用它命名）
.venv\Scripts\python.exe ..\scripts\migrate_to_pg.py --target "postgresql+psycopg://cbc:cbc_dev_password@127.0.0.1:5432/cbc" --dry-run
.venv\Scripts\python.exe ..\scripts\migrate_to_pg.py --target "postgresql+psycopg://cbc:cbc_dev_password@127.0.0.1:5432/cbc"
```

- 想退回 SQLite：把 `backend/.env` 里的 `CBC_DATABASE_URL` 换成 sqlite 那行（文件里已注释好）。
  两套库的数据互不影响，切换后账号要重新注册。
- WSL 关机后 Windows 侧连不上是正常的（`Test-NetConnection 127.0.0.1 -Port 5432` 会变 False），
  `wsl -u root -- service postgresql start` 即可；后端连不上时 `pool_pre_ping` 会报"连接意外关闭"，
  不是配置错。
- 集成测试 `tests/test_pg_dialect.py` 跑在真库上时会**自己造行再删行**，不碰现有数据。

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
| `backend/.env` | 本机配置（连接串、密钥）。**不进仓库**，从 `.env.example` 复制 | 换库/换端口时看 |
| `backend/alembic/` | 数据库迁移脚本（v1.8 起），`alembic.ini` 在它旁边 | 改模型时才看 |
| `scripts/migrate_to_pg.py` | 把 SQLite 开发库搬到 Postgres（保留原始 id） | 切库时跑一次 |
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
├─ docker-compose.yml                   另一条起法：db + redis + api + web（见下）
├─ .env.example                         docker / 生产用的环境变量清单
├─ LICENSE                              MIT + 一段"不做诊断"的用途声明
├─ backend/
│  ├─ app/
│  │  ├─ api/v1/        auth · datasets · reports · compare · dashboard · ranges · reference
│  │  ├─ core/          config · errors · security · deps · cache
│  │  ├─ db/            base · models · session
│  │  ├─ pipeline/      reading → mapping → units → validators → cleaning → rules → stats → captions
│  │  ├─ schemas/       pydantic 请求/响应
│  │  └─ services/      pipeline_runner · datasets · chart · quality_chart · render · report
│  │                    compare · ranges_service · loader
│  ├─ resources/        reference_ranges.yaml · field_dict.yaml · field_mapping.yaml
│  │                    cleaning_strategy.yaml · caption_templates.yaml
│  │                    report_template.html.j2
│  │                    cbc.mplstyle + theme.json（scripts/gen_theme.py 生成，勿手改）
│  ├─ tests/            BR 规则单测 + 管线夹具 + 接口级回归（180 用例）
│  ├─ data/             raw · processed · rendered · reports + app.db（运行时生成）
│  ├─ .venv/            Python 依赖（与 requirements.txt 同级，跟后端一起搬走即可）
│  ├─ Dockerfile        python:3.13-slim + Noto CJK 字体
│  └─ requirements.txt
├─ frontend/
│  ├─ src/
│  │  ├─ api/           client · hooks · types（与 8.1 API 一一对应）
│  │  ├─ auth/          会话与路由守卫
│  │  ├─ components/    StatusBadge · MetricCard · SampleProfile · DatasetCard · EChart · Layout
│  │  │                 FilterPanel · AnomalyPanel · RangesPanel · QualityPanel
│  │  ├─ lib/           format（4.4.6 数字规则）· colors（从 CSS 变量取色）· useExport
│  │  ├─ pages/         Login · Register · Dashboard · DatasetDetail · Compare
│  │  │                 ReferenceRanges · ExportCenter · Account
│  │  └─ theme/         tokens.json（唯一配色来源）+ 生成产物
│  ├─ tests/            unit / integration / e2e（都不进 src/，NFR-M-08）
│  ├─ Dockerfile        构建 dist → nginx:1.27-alpine 托管
│  └─ nginx.conf        SPA 回退 + /api 反代 + 60MB 上传上限
├─ scripts/             根级工具（跨前后端，不属于任何一边）
│  ├─ gen_theme.py       tokens.json → CSS 变量 / ECharts 主题 / matplotlib rcParams / theme.json
│  ├─ import_local.py    把手上的 CSV 走正式上传接口登记进库（不手改数据库）
│  ├─ migrate_b3.py      老库迁移（补 ri_source/judged_at/ranges_snapshot + user_ranges 表 + 删 role）
│  ├─ smoke_local.py     TestClient 冒烟：注册→上传→图表→导出→删除
│  ├─ smoke_b3/b4/b5.py  真起服务后的接口级冒烟（区间/筛选/对比）
│  └─ download_datasets.py  Kaggle 数据集下载与哈希校验（可选）
└─ .run/                进程 PID（stop.ps1 用）
```

运行时会落盘的东西（都在 `backend/data/`）：`raw/{id}.csv`（原始件）、`processed/{id}/*.parquet|json`
（S1–S7 每一步的中间结果）、`rendered/`（静态图）、`reports/`（HTML 报告）、`app.db`（默认 SQLite 库）。
**每步落盘**是"可复现"承诺的实现基础：任何一步出问题都能单独重跑，答辩时也能展示中间结果。

---

## 五、测试与质量门禁

```powershell
cd cbc-insight\backend
.venv\Scripts\python.exe -m pytest -q        # 197 passed（其中 4 条只在 Postgres 上跑）
.venv\Scripts\ruff.exe check app tests ..\scripts   # All checks passed

cd ..\frontend
pnpm exec tsc --noEmit                          # 类型检查
pnpm exec vitest run tests/unit                 # 11 passed
pnpm exec vitest run tests/integration          # 6 passed（MSW 拦 network 层）
pnpm run build                                  # 产出 dist/

cd ..\frontend
pnpm run test:e2e                               # 一条主流程（需先 .\start.ps1）
```

- 后端测试扁平放在 `backend/tests/`，**`app/` 下不出现 `test_*.py`**（NFR-M-08）；
  接口级用例用临时 SQLite + 临时数据目录，因此**不需要 Docker**。
- 前端单元测试在 `frontend/tests/unit/`，`src/` 下不出现 `*.test.tsx`。
  图表只断言传给 ECharts 的 `option` 对象，不比像素（像素比对会因为字体/dpi 差异常年变红，最后一定被删掉）。
- 前端集成测试在 `frontend/tests/integration/`，用 **MSW 在 network 层拦截**而不是 mock 掉 `api.*`：
  前端真正会翻车的是"URL 拼错、参数漏传、缓存键少一段"，把函数 mock 掉就把这层保护一起 mock 掉了。
  目前两条：切数据集不串数（T-16）、预览与下载参数一字不差（RK-19 / T-29）。
- 覆盖率门禁只对 `app/pipeline/` 与 `app/services/` 设 80%，路由层靠"每个端点三个用例"覆盖。
- **E2E 只有一条**（T-37）：注册 → 上传夹具 → 出图 → 导出下载。它自己注册随机账号、用固定夹具，
  不依赖演示数据；跑之前前端 5173 与后端 8000 要在跑（先 `.\start.ps1 -NoBrowser`）。
  刻意**不铺开**成矩阵：界面会变，铺开的用例两周后就会被人加 `test.skip`，等于没有。

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

**参考区间**默认表在 `backend/resources/reference_ranges.yaml`（WS/T 405-2012 成人区间，
男女分开，版本号 `v2026.11.1`）。它**只读**——谁也不能改默认表，包括管理员（v1.6 起没有管理员）。

改区间走「我的参考区间」页（侧栏第三个入口，接口 `/api/v1/me/reference-ranges`）：

| 层 | 谁能改 | 存哪 | 标识 |
|---|---|---|---|
| 默认 | 谁都不能改 | YAML（只读） | `default@2026.11.1` |
| 我的 | 自己，整份 15 项一起存，**必须填理由** | 数据库 `user_ranges`（只追加，版本号 +1） | `user#v3` |
| 临时 | 只在数据集详情「区间」tab 里试算 | 内存，不落库 | `temp#03bd4c2d1852` |

- **改了区间不会自动重判**。旧判定还留在原地，页面顶部出现「按当前区间重判」横幅；
  点它只重放 S6–S7（10 万行约 3–8 秒，`sample_index` 一个都不变），旧口径快照归档到
  `backend/data/processed/<id>/history/`。
- **临时试算不落库、不出现在导出件里**——试算态禁止导出，这是硬约束（RK-26）。
- 每份判定都把当时生效的整份区间快照进 `artifacts/ranges.snapshot.json`，所以"这份结论是按
  哪套区间算的"永远可查；报告、CSV 的 `*_meta.json` 里都带 `ri_source` 与 `ranges_digest`。

> 老库升级（B3 之前建的库）要先跑一次迁移，它会先备份 `backend/data/app.db`：
> `backend\.venv\Scripts\python.exe scripts\migrate_b3.py --dry-run` 看一眼，去掉 `--dry-run` 执行。
> 新克隆的仓库不需要——`create_all` 直接建新结构。

---

## 七、已实现的功能（对照需求文档）

| 需求 | 落地情况 |
|---|---|
| FR-01 上传 | 编码探测（UTF-8/-BOM/GBK/GB18030）、分隔符投票、哈希去重 409、体积/行数/列数上限；扩展名 + magic bytes + NUL 字节检查；清洗后不达可用性门槛落 `status=rejected`（只能看质量报告，不能分析与导出） |
| FR-02 映射 | 别名表 + 模糊匹配，必填字段缺失抛 40004，人工确认后重跑整条管线 |
| FR-03 预览 | 分页 ≤100 行，带 `sample_index` 与 `age_band` |
| FR-04 校验 | DQ-01~06、值域/重复/逻辑一致性（`\|hct − rbc×mcv/10\|/hct > 15%`） |
| FR-05 清洗 | 类型修复 → 置空 → 剔列（核心三字段豁免）→ 去重 → 逻辑置空 → 删全空行 → 分组中位数填充 |
| FR-06 对比 | 清洗前后行数、按原因计数的删除明细 |
| FR-07~13 图 | 箱线（按性别分组 + 两组参考带，须端取 1.5×IQR、离群点画散点、轴窗口按 `Q3±3×IQR` 收住）、直方（区间内外占比，零值可单列一桶、长尾不撑满横轴）、相关热力（Spearman + 数学耦合标注）、散点、**质量图（完整率条形 + DQ-01~06 + 剔除原因饼图，三块同屏）** |
| FR-14 筛选 | 指标阈值（< / ≤ / > / ≥ / 介于 / =）+ 性别 + 年龄区间，条件之间是"与"；命中数与导出行数同源 |
| FR-15 筛选视图 | 分页表格（20 行/页），条件回显，0 命中给空态而不是空白页 |
| FR-16/17 判定 | 11 种模式 + `UNCLASSIFIED` 兜底、严重度排序；`gender` 缺失判 `NA`，不套男性区间；`unified_ranges` 显式开关（用户勾选才按统一区间判，结果标 `unified`） |
| FR-18/19/35 导出 | UTF-8-BOM CSV + 同名 `*_meta.json`，预览与下载列名/顺序/数量完全一致；异常清单默认只含异常样本、按异常指标数降序；看不懂的筛选条件返回 42201 而不是"当作没写" |
| FR-30 指标状态 | 常驻面板，三通道编码（颜色 + ↑↓—∅ + 文字），`MIXED` 显示"两侧均异常" |
| FR-31 体检单 | 条长用标准化位置 `pos = (x − low) / (high − low)`，量纲不同也可比 |
| FR-32 图注 | 模板渲染 + 四条退化规则（n<10 无 p 值、p≥0.05 不说"显著"、\|ρ\|<0.3 不解读、缺 gender 不提男女） |
| FR-33/34 账号 | 注册即登录、改名、改密、连续失败 5 次锁 15 分钟、登出吊销 refresh；**v1.6 起无角色概念**，只有归属隔离 |
| FR-28 数据集 | 列表、切换、重命名、级联删除（含磁盘文件清理） |
| FR-24/36/37 区间 | 三层区间（临时 > 我的 > 默认）、整份保存 + 必填理由、版本历史、重判只重放 S6–S7、拖/输试算不落库 |
| FR-20/21 报告与图 | 单文件 HTML（base64 内嵌 4 图：箱线/直方/热力 + 质量图三联，含免责声明）、PNG 300dpi / SVG 下载 |
| FR-29 并排对比 | 2–4 份数据集按指标并排：每格给 n / 缺失数 / 中位数 / 四分位 / 均值 / 三态占比条；口径不同（区间版本、`default` vs `unified`）会显式提示；**响应里没有 p 值、置信区间、效应量**（BR-13） |

## 八、还没做

- Redis 队列：目前 10 万行以内走同步链路（实测 19.4 s），超过 `sync_clean_budget_seconds` 才需要 RQ。
  结果缓存已接（`app/core/cache.py`：键里含 `dataset_id` 与判定口径，没配 Redis 时自动退化为进程内缓存）。
- PDF 上传解析（FR-26）、跨数据集统计推断（v2，且须先论证可比性）、审计日志（FR-25）、术语表（FR-27）。

---

## 九、六条实现与需求文档不一致的地方（待同步回 SRS）

1. **BR-07 / 5.1 缺兜底模式**：11 种模式之外，"1–2 项异常但不匹配任何模式"的样本无处归类。
   实现新增 `UNCLASSIFIED`（其他异常组合）；异常 ≥3 项仍归 `MULTI_ABNORMAL`。
2. **3.4 把 rbc 的"万/µL"写成 ÷1000**：按量纲应是 **÷100**（1×10¹²/L = 100 万/µL）。
   已按 ÷100 实现；照文档原文实现会得到 10 倍偏差。
3. **BR-03 未区分核心字段**：缺失率 > 30% 整列剔除若作用在 `hgb/wbc/plt` 上，
   S6 会输出"没有任何异常"——用户看到一份干净报告，比报错更危险。
   实现中核心三字段豁免剔列、只记告警。

4. **区间项数写成 16，实际是 15 项**：`reference_ranges.yaml` 里是
   `wbc/rbc/hgb/hct/mcv/mch/mchc/rdw/plt/mpv` + 五分类百分比（`neut/lymph/mono/eo/baso_pct`），
   共 15 项——五分类**绝对值**（`NE#` 等）没有独立参考区间，在分类上属于派生量。
   SRS 3.5.1 与 FR-24 的"16 项"应改为 15 项；实现以 15 项为准（`ranges_service.RANGE_METRICS`）。

5. **`/ranges-snapshot` 多返回一个 `has_snapshot`**：B3 之前判定的老数据没有快照，
   "没有快照"与"不陈旧"是两件事——前者该提示"补建快照并重判"，后者才该说"口径一致"。
   这个字段未写进 SRS 8.1，建议补上。

6. **SRS 没定义"传了一份不能用的数据"会发生什么**：8.3 的错误码里没有对应业务码
   （`40903` 是区间版本冲突，实现里也没做 `base_version`），所以实现复用 `42201`，
   并新增两个 SRS 未写的行为：
   - 文件层闸门：扩展名白名单 `.csv/.txt` + magic bytes + NUL 字节检查 → `40003`；
   - 配额闸：`CBC_MAX_ROWS`（默认 20 万）/`CBC_MAX_COLUMNS`（默认 60）真正生效 → `40002`；
   - 可用性闸：清洗后行数 < 5、核心字段（`hgb/wbc/plt`）可解析比例 < 60%、或有效指标 < 3
     时，数据集落库为 `status=rejected`（只保留质量报告），统计/图表/筛选/导出/报告
     一律 `42201` 拒绝。
   建议在 SRS 里补一条 BR（"不可用数据不得产出任何结论"）与 `status` 的新取值。

---

## 十、常见问题

这些都是"会在自己机器上真实撞到"的问题，按被问到的顺序记；每条都给了判断依据，而不是"再试一次"。

**1. 打开 5173 是白屏，或者页面上所有请求都 404。**
后端没起，或者起的是旧代码。判断依据：`curl http://127.0.0.1:8000/healthz` 应返回 `{"ok": true, ...}`。
`start.ps1` 之所以要轮询这个地址，就是因为"进程起来了"和"服务能用了"是两件事（Vite 的 `/api` 代理在后端未就绪时只会给你 `ECONNREFUSED`）。
改了后端代码要重启后端；前端由 Vite 热更新，不用重启。

**2. 运行配置里报 `ModuleNotFoundError: No module named 'app'`。**
工作目录不是 `backend/`。`app` 是相对导入，必须在 `backend/` 下执行 `python -m uvicorn app.main:app`。

**3. 图里的中文变成方框。**
服务器渲染（报告 PNG）依赖 `matplotlib` 找到中文字体：Docker 镜像里已装 `fonts-noto-cjk`；
本机需要 `Noto Sans SC` / `Microsoft YaHei` / `SimHei` 之一。浏览器里的 ECharts 用的是系统字体，通常不会出这个问题。

**4. 改了参考区间，页面上判决却没变。**
这是**故意**的：改区间不会自动重判（改了就要重跑十万行，而你只是想先看看）。
判定结果上会挂"陈旧"横幅，去数据集详情 «区间» tab 点「按当前区间重判」——只重放 S6–S7，`sample_index` 一个都不动。

**5. 导入后异常率特别高，是不是算错了？**
先看数据集详情顶部那行"健康状况"，它会写明单位换算（例如 `hgb 原单位 g/dL → g/L（×10）`）。
单位判错会整体偏移；确认单位后，再看是否该勾选"本数据集无性别，按统一区间判定"——
没有性别时 `hgb/rbc/hct` 会一律判 `NA`，强行套男性区间会得出"全都偏低"的假结论（BR-17）。

**6. E2E 跑不起来。**
`pnpm run test:e2e` 要求后端 8000 与前端 5173 都在跑（配置里刻意不启 `webServer`，
避免"测试在跑、你在看演示站"两套数据混在一起）。换地址用 `CBC_E2E_BASE=http://127.0.0.1:8080 npx playwright test`。

**7. 十万行为什么要十几秒？**
真实数据的耗时构成与优化前后对比写在 `docs/真实数据体检.md`：瓶颈原本在清洗去重与逐行判定，
现在 S1–S7 合计约 19 s（其中 S7 统计 8 s 是 pandas 分组本身的开销）。超过 30 s 才需要考虑上队列。

**8. 传错文件会怎样？——三道闸，各有各的报错。**
- 文件层（`40003`）：只收 `.csv/.txt`；`.xlsx` 会提示"请在 Excel 里另存为 CSV"；改后缀也拦得住
  （看 magic bytes 与 NUL 字节）。
- 配额层（`40002`）：`CBC_MAX_ROWS`（默认 20 万行）/ `CBC_MAX_COLUMNS`（默认 60 列）真的会被检查。
- 可用性层（`42201` + `status=rejected`）：清洗后行数 < 5、核心字段 `hgb/wbc/plt` 能解析成数值的比例
  < 60%、或有效指标 < 3 时，数据集落库但只能看质量报告——统计、图表、筛选、导出、报告全部拒绝。
  这一层专门拦"表头对得上、值却是『正常/阴性』"的数据：不拦的话，清洗会把值全置空，
  系统会一本正经地输出"异常率 0%，全部正常"，比报错危险得多。

**9. 箱线图上的橙点是什么？为什么 y 轴不画到最大值？**
橙点是**离群点**（超出 `Q1−1.5×IQR` ~ `Q3+1.5×IQR` 的观测值），不是错误数据，按 BR-06 一律保留。
y 轴窗口由 `Q3±3×IQR` 决定：如果让一个 34% 的嗜碱性粒细胞值把轴拉满，箱体（Q1–Q3）会被压成一条线，
看图的人会以为"这组全是 0"。窗口外的点不画，但个数与最大值写在图内副标题里
（例如"离群点 2865 个，其中 1010 个超出显示范围未画出（最大 35.4）"）——图可以裁，数据不能少报。

**10. 直方图为什么只显示到某个值？第一根柱子为什么特别高？**
同一把尺子：窗口 = `Q3±3×IQR`，覆盖不到的部分（通常是长尾）单独计数并写在副标题里。
如果某个指标有大量**恰好为 0** 的样本（`baso_pct` 有 96%），零值会被单列成"0"一桶，
否则等宽分箱会让第一桶吃掉九成样本、后面 19 桶全空，等于没画。

---

## 十一、免责声明

本系统面向教学与研究，使用公开脱敏数据；输出仅为"是否超出参考区间"的机械判定，
不构成任何医学诊断或建议。参考区间默认取 WS/T 405-2012 成人区间，不同实验室、不同检测
系统存在差异，实际应以报告单标注为准，且可在系统中配置与换版。
