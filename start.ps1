#requires -Version 5.1
<#
.SYNOPSIS
    一键启动 CBC Insight（后端 + 前端 + 打开浏览器）。

.DESCRIPTION
    按顺序做四件事，每一步都可重复执行：
      1. 检查 / 创建 Python 虚拟环境并按 backend\requirements.txt 装依赖；
      2. 启动后端（uvicorn，默认 8000），等到 /healthz 通过再继续；
      3. 检查 / 安装前端依赖（pnpm），启动 Vite（默认 5173）；
      4. 打开浏览器。

    端口已被占用时不会报错失败：先探活，活着就直接复用，避免"重复启动把原来的服务顶掉"。

.EXAMPLE
    .\start.ps1
    .\start.ps1 -NoBrowser            # 不自动开浏览器
    .\start.ps1 -ApiPort 8010 -WebPort 5180
#>
param(
    [switch]$NoBrowser,
    [int]$ApiPort = 8000,
    [int]$WebPort = 5173
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$runDir = Join-Path $root ".run"
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"
# 虚拟环境跟后端代码放在一起（backend\.venv）：整个 backend\ 目录因此可以单独拷走，
# 在 PyCharm 里打开 backend 时解释器也正好落在项目内，不需要到上级目录去找。
$venvDir = Join-Path $backendDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$apiUrl = "http://127.0.0.1:$ApiPort"
$webUrl = "http://127.0.0.1:$WebPort"

New-Item -ItemType Directory -Force -Path $runDir | Out-Null

function Write-Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Write-Ok($text) { Write-Host "    $text" -ForegroundColor Green }
function Write-Warn2($text) { Write-Host "    $text" -ForegroundColor Yellow }

function Test-Url($url, [int]$timeoutSec = 2) {
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec $timeoutSec
        return $response.StatusCode -eq 200
    } catch { return $false }
}

function Wait-Url($url, [int]$seconds, [string]$label) {
    for ($i = 0; $i -lt $seconds; $i++) {
        if (Test-Url $url) { return $true }
        Start-Sleep -Seconds 1
    }
    Write-Warn2 "$label 在 $seconds 秒内没有就绪，后面的步骤会继续，但可能需要手动刷新。"
    return $false
}

# ---------------------------------------------------------------- 1. Python 环境
Write-Step "检查 Python 环境"
if (-not (Test-Path $venvPython)) {
    Write-Warn2 "没有找到 .venv，开始创建（首次安装依赖大约 1–3 分钟）"
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        # 复用本机已装好的 CPython（uv 会自动找最高的已装版本），不另装解释器；
        # 想固定某个解释器版本时设 $env:CBC_PYTHON=D:\develop\Python\python.exe 再运行。
        if ($env:CBC_PYTHON) { & uv venv "$venvDir" --python $env:CBC_PYTHON } else { & uv venv "$venvDir" }
        # 国内网络直连 PyPI 常常卡住，默认走清华镜像；需要官方源时设 $env:CBC_PYPI=official
        $index = if ($env:CBC_PYPI -eq "official") { "https://pypi.org/simple" } else { "https://pypi.tuna.tsinghua.edu.cn/simple" }
        & uv pip install --python $venvPython -r (Join-Path $backendDir "requirements.txt") --index-url $index
    } else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if (-not $python) { throw "既没有 uv 也没有 python，请先安装 Python 3.11+ 或 uv。" }
        & python -m venv "$venvDir"
        & $venvPython -m pip install --upgrade pip
        & $venvPython -m pip install -r (Join-Path $backendDir "requirements.txt")
    }
    if (-not (Test-Path $venvPython)) { throw "虚拟环境创建失败。" }
}
$pyVersion = (& $venvPython -c "import sys; print('.'.join(map(str, sys.version_info[:2])))").Trim()
Write-Ok "Python $pyVersion @ backend\.venv"

# ---------------------------------------------------------------- 2. 数据库（仅当 .env 指向 WSL 里的 Postgres）
# WSL 空闲会自动停机，一停机 127.0.0.1:5432 就没了，后端启动时报"连接超时"。
# 这里先确认数据库在线，并留一个常驻会话把它钉住（stop.ps1 会一起关掉）。
$envFile = Join-Path $backendDir ".env"
if ((Test-Path $envFile) -and (Select-String -Path $envFile -Pattern "postgresql" -Quiet)) {
    Write-Step "检查 WSL 里的 Postgres"
    # wsl -l -q 在 Windows 上输出 UTF-16，PowerShell 读出来常带 \0，先清掉再判断
    $distro = (& wsl -l -q 2>$null | ForEach-Object { ($_ -replace "`0", "").Trim() } | Where-Object { $_ } | Select-Object -First 1)
    if (-not $distro) {
        Write-Warn2 "没找到 WSL 发行版，但 backend\.env 指向 Postgres —— 后端可能连不上数据库"
    } else {
        $distro = $distro.Trim()
        $keepAlive = Join-Path $runDir "wsl.pid"
        $alive = $false
        if (Test-Path $keepAlive) {
            $oldPid = (Get-Content $keepAlive -Raw).Trim()
            if ($oldPid -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) { $alive = $true }
        }
        if (-not $alive) {
            $proc = Start-Process -FilePath "wsl.exe" `
                -ArgumentList "-d", $distro, "-u", "root", "--", "bash", "-lc", `
                    "pg_ctlcluster 18 main start >/dev/null 2>&1; exec tail -f /dev/null" `
                -WindowStyle Hidden -PassThru
            Set-Content -Path $keepAlive -Value $proc.Id -Encoding ascii
        }
        $ready = $false
        for ($i = 0; $i -lt 20; $i++) {
            Start-Sleep -Milliseconds 800
            if ((Test-NetConnection 127.0.0.1 -Port 5432 -InformationLevel Quiet -WarningAction SilentlyContinue)) {
                $ready = $true
                break
            }
        }
        if ($ready) { Write-Ok "Postgres 127.0.0.1:5432 已就绪（$distro）" }
        else { Write-Warn2 "5432 仍连不上，后端会报数据库连接失败；可先手动执行 wsl -d $distro -u root service postgresql start" }
    }
}

# ---------------------------------------------------------------- 3. 后端
Write-Step "启动后端（端口 $ApiPort）"
if (Test-Url "$apiUrl/healthz") {
    Write-Ok "后端已在运行，直接复用：$apiUrl"
} else {
    $backend = Start-Process -FilePath $venvPython `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$ApiPort" `
        -WorkingDirectory $backendDir -PassThru -WindowStyle Minimized
    Set-Content -Path (Join-Path $runDir "backend.pid") -Value $backend.Id -Encoding ascii
    if (Wait-Url "$apiUrl/healthz" 40 "后端") {
        Write-Ok "后端就绪：$apiUrl  （接口文档 $apiUrl/docs）"
    }
}

# ---------------------------------------------------------------- 4. 前端
Write-Step "检查前端依赖"
$viteBin = Join-Path $frontendDir "node_modules\.bin\vite.cmd"
if (-not (Test-Path $viteBin)) {
    $pnpm = Get-Command pnpm -ErrorAction SilentlyContinue
    if (-not $pnpm) { throw "没有找到 pnpm。请先执行：npm i -g pnpm" }
    Write-Warn2 "首次安装前端依赖（约 1–2 分钟）"
    Push-Location $frontendDir
    try {
        # pnpm 12 默认拦截 esbuild 的构建脚本并以非零码退出，但 esbuild 的平台二进制会由可选依赖装上，
        # vite 仍可正常工作，因此这里只提示、不中断。
        & pnpm install
        if (-not (Test-Path $viteBin)) { throw "前端依赖安装失败，请手动进入 frontend 目录执行 pnpm install。" }
    } finally { Pop-Location }
}

Write-Step "启动前端（端口 $WebPort）"
if (Test-Url $webUrl) {
    Write-Ok "前端已在运行，直接复用：$webUrl"
} else {
    $frontend = Start-Process -FilePath "pnpm.cmd" `
        -ArgumentList "exec", "vite", "--port", "$WebPort", "--strictPort" `
        -WorkingDirectory $frontendDir -PassThru -WindowStyle Minimized
    Set-Content -Path (Join-Path $runDir "frontend.pid") -Value $frontend.Id -Encoding ascii
    if (Wait-Url $webUrl 60 "前端") { Write-Ok "前端就绪：$webUrl" }
}

# ---------------------------------------------------------------- 5. 打开浏览器
if (-not $NoBrowser) { Start-Process $webUrl }

Write-Host ""
Write-Host "==============================================" -ForegroundColor DarkGray
Write-Host " CBC Insight 已启动" -ForegroundColor White
Write-Host "   前端  $webUrl" -ForegroundColor White
Write-Host "   后端  $apiUrl/docs" -ForegroundColor White
Write-Host "   首次使用  打开页面直接注册账号（无邮箱，找回密码见 README）" -ForegroundColor DarkGray
Write-Host "   停止服务  .\stop.ps1" -ForegroundColor DarkGray
Write-Host "==============================================" -ForegroundColor DarkGray
