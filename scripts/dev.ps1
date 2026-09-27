#Requires -Version 5.1

<#
.SYNOPSIS
    一键启动本地开发环境。

.DESCRIPTION
    检查本机环境,按需创建虚拟环境、安装依赖、生成演示数据,然后启动服务。

.PARAMETER Target
    server = 只启动服务端, web = 只启动前端, all = 两个都启动

.EXAMPLE
    .\scripts\dev.ps1 -Target server

.EXAMPLE
    .\scripts\dev.ps1 -Target all
#>

[CmdletBinding()]
param(
    [ValidateSet("server", "web", "all")]
    [string]$Target = "all"
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Continue"

$script:Root = Split-Path -Parent $PSScriptRoot
$script:HasError = $false

function Write-Title {
    param([string]$Text)
    Write-Host ""
    Write-Host "==================================================" -ForegroundColor DarkCyan
    Write-Host ("  " + $Text) -ForegroundColor White
    Write-Host "==================================================" -ForegroundColor DarkCyan
    Write-Host ""
}

function Write-Step {
    param([string]$Text)
    Write-Host ("[步骤] " + $Text) -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Text)
    Write-Host ("[完成] " + $Text) -ForegroundColor Green
}

function Write-Warn {
    param([string]$Text)
    Write-Host ("[提示] " + $Text) -ForegroundColor Yellow
}

function Write-Err {
    param([string]$Text)
    $script:HasError = $true
    Write-Host ("[错误] " + $Text) -ForegroundColor Red
}

function Pause-Window {
    Write-Host ""
    Read-Host "按回车键关闭本窗口"
}

function Test-CommandExists {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Start-Server {
    Write-Title "启动服务端"
    $serverDir = Join-Path $script:Root "server"
    Set-Location $serverDir

    if (-not (Test-CommandExists "python")) {
        Write-Err "没有找到 python 命令。"
        Write-Host "       请先安装 Python 3.12: https://www.python.org/downloads/"
        Write-Host "       安装时务必勾选 Add python.exe to PATH,装完重新运行本脚本。"
        Write-Host "       如果已经装过,请关掉这个窗口重新打开,让 PATH 生效。"
        return
    }

    $venvPython = Join-Path $serverDir ".venv\Scripts\python.exe"
    $venvReady = $false
    if (Test-Path $venvPython) {
        & $venvPython -c "import sys" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $venvReady = $true
            Write-Host "[跳过] 虚拟环境已存在且可用" -ForegroundColor DarkGray
        }
        else {
            Write-Warn "已有的虚拟环境不可用(通常是换过 Python 版本),自动重新创建"
            Remove-Item -LiteralPath (Join-Path $serverDir ".venv") -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    if (-not $venvReady) {
        Write-Step "创建虚拟环境 .venv"
        python -m venv .venv
        if (-not (Test-Path $venvPython)) {
            Write-Err "创建虚拟环境失败,请把上面的报错发给我。"
            return
        }
        Write-Ok "虚拟环境已创建"
    }

    Write-Step "检查并安装 Python 依赖(第一次需要一两分钟)"
    & $venvPython -m pip install --disable-pip-version-check -q -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Err "依赖安装失败,请检查网络后重试。"
        return
    }
    Write-Ok "Python 依赖就绪"

    $dbFile = Join-Path $serverDir "data\iap.db"
    if (-not (Test-Path $dbFile)) {
        Write-Step "生成演示数据(14 台示例设备与两周历史记录)"
        & $venvPython -m app.seed --reset
        Write-Ok "演示数据已生成"
    }
    else {
        Write-Host "[跳过] 数据库已存在" -ForegroundColor DarkGray
    }

    # 令牌: 优先读项目根目录的 .env,否则用默认值
    $envFile = Join-Path $script:Root ".env"
    if (Test-Path $envFile) {
        # 必须显式指定 UTF8: Windows PowerShell 5.1 默认按 ANSI 读取无 BOM 文件,
        # 会把中文注释和下一行配置粘在一起,导致变量解析失败
        foreach ($line in Get-Content -Path $envFile -Encoding UTF8) {
            if ($line -match "^\s*IAP_AGENT_TOKEN\s*=\s*(.+?)\s*$") {
                $env:IAP_AGENT_TOKEN = $Matches[1]
            }
            elseif ($line -match "^\s*IAP_READ_TOKEN\s*=\s*(.+?)\s*$") {
                $env:IAP_READ_TOKEN = $Matches[1]
            }
        }
    }
    if (-not $env:IAP_AGENT_TOKEN) { $env:IAP_AGENT_TOKEN = "dev-agent-token" }
    if (-not $env:IAP_READ_TOKEN) { $env:IAP_READ_TOKEN = "dev-read-token" }

    $lanIp = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
            Select-Object -First 1).IPAddress

    Write-Host ""
    Write-Ok "服务端启动中,请保持本窗口开着"
    Write-Host "       本机接口文档: http://127.0.0.1:8000/docs"
    if ($lanIp) {
        Write-Host ("       局域网地址:   http://" + $lanIp + ":8000   (其他电脑用这个地址上报)") -ForegroundColor Cyan
    }
    Write-Host ("       Agent 上报令牌: " + $env:IAP_AGENT_TOKEN) -ForegroundColor Cyan
    Write-Host ("       看板读取令牌:   " + $env:IAP_READ_TOKEN) -ForegroundColor Cyan
    Write-Host "       看板地址:     http://localhost:5173 (需要同时启动前端)"
    Write-Host ""

    # 监听 0.0.0.0 才能被局域网内其他电脑访问
    & $venvPython -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

    if ($script:HasError) { return }
    Write-Host ""
    Write-Warn "服务端已停止。"
}

function Start-Web {
    Write-Title "启动前端看板"
    $webDir = Join-Path $script:Root "web"
    Set-Location $webDir

    if (-not (Test-CommandExists "npm")) {
        Write-Err "没有找到 npm 命令。"
        Write-Host "       请先安装 Node.js 20 LTS: https://nodejs.org/"
        Write-Host "       安装时保持默认选项,装完重新运行本脚本。"
        Write-Host "       如果已经装过,请关掉这个窗口重新打开,让 PATH 生效。"
        return
    }

    if (-not (Test-Path (Join-Path $webDir "node_modules"))) {
        Write-Step "安装前端依赖(第一次需要几分钟)"
        npm install --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) {
            Write-Err "前端依赖安装失败,请检查网络后重试。"
            return
        }
        Write-Ok "前端依赖就绪"
    }
    else {
        Write-Host "[跳过] 前端依赖已存在" -ForegroundColor DarkGray
    }

    Write-Host ""
    Write-Ok "前端启动中,请保持本窗口开着"
    Write-Host "       看板地址: http://localhost:5173"
    Write-Host "       如果页面没有数据,请确认服务端窗口已经启动"
    Write-Host ""

    npm run dev

    if ($script:HasError) { return }
    Write-Host ""
    Write-Warn "前端已停止。"
}

function Start-All {
    Write-Title "启动完整环境"
    Write-Host "即将打开两个窗口: 服务端和前端看板。"
    Write-Host ""
    Write-Host "等两个窗口都出现地址提示后,用浏览器打开:"
    Write-Host "  http://localhost:5173" -ForegroundColor White
    Write-Host ""
    Write-Warn "首次启动会自动安装依赖,大约需要几分钟。"
    Write-Warn "关闭那两个窗口即可停止服务。"
    Write-Host ""

    $scriptPath = Join-Path $PSScriptRoot "dev.ps1"
    $arguments = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$scriptPath`"")

    Start-Process -FilePath "powershell.exe" -ArgumentList ($arguments + @("-Target", "server"))
    Start-Sleep -Seconds 3
    Start-Process -FilePath "powershell.exe" -ArgumentList ($arguments + @("-Target", "web"))

    Write-Ok "两个窗口已启动"
    Start-Sleep -Seconds 2
}

switch ($Target) {
    "server" { Start-Server }
    "web" { Start-Web }
    "all" { Start-All; Pause-Window }
}

if ($Target -ne "all") {
    Pause-Window
}
