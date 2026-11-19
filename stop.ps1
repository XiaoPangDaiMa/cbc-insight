#requires -Version 5.1
<#
.SYNOPSIS
    停止由 start.ps1 启动的后端与前端进程。

.DESCRIPTION
    先按 .run\*.pid 精确结束进程；pid 文件丢失时就按端口找占用者（只结束监听该端口的
    本地进程，不会误伤同名的其他程序）。找不到进程也算正常结束。
#>
param(
    [int]$ApiPort = 8000,
    [int]$WebPort = 5173
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$runDir = Join-Path $root ".run"

function Stop-ByPidFile($name, $label) {
    $pidFile = Join-Path $runDir "$name.pid"
    if (-not (Test-Path $pidFile)) { return }
    $processId = (Get-Content $pidFile -Raw).Trim()
    if ($processId -match '^\d+$') {
        $process = Get-Process -Id ([int]$processId) -ErrorAction SilentlyContinue
        if ($process) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            Write-Host "已结束$label（PID $processId）" -ForegroundColor Green
        }
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

function Stop-ByPort([int]$port, $name) {
    $connections = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($connection in $connections) {
        $process = Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
        if ($process) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            Write-Host "已结束占用 $port 端口的 $name（PID $($process.Id)）" -ForegroundColor Green
        }
    }
}

Stop-ByPidFile "backend" "后端（uvicorn）"
Stop-ByPidFile "frontend" "前端（vite）"
Stop-ByPort $ApiPort "后端（uvicorn）"
Stop-ByPort $WebPort "前端（vite/node）"

Write-Host "已停止。" -ForegroundColor DarkGray
