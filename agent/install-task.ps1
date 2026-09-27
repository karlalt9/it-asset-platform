#Requires -Version 5.1

<#
.SYNOPSIS
    把体检脚本注册成 Windows 计划任务,定时上报到集中管理平台。

.DESCRIPTION
    服务地址和令牌会写入脚本同目录的 config.json,计划任务本身只调用脚本。
    这样令牌不会出现在任务命令行里,避免被其他用户从任务定义里直接看到。

.PARAMETER ServerUrl
    服务端地址,例如 http://10.0.0.5:8000

.PARAMETER Token
    服务端配置的 IAP_AGENT_TOKEN

.PARAMETER IntervalHours
    上报间隔,默认 4 小时

.PARAMETER TaskName
    计划任务名称

.PARAMETER StartNow
    注册完成后立刻触发一次

.EXAMPLE
    .\install-task.ps1 -ServerUrl http://10.0.0.5:8000 -Token your-token -StartNow
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ServerUrl,
    [Parameter(Mandatory)][string]$Token,
    [int]$IntervalHours = 4,
    [string]$TaskName = "IT Asset Platform Agent",
    [switch]$StartNow
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "pc-health-check.ps1"
if (-not (Test-Path $scriptPath)) {
    throw "没有找到 pc-health-check.ps1,请把它和本脚本放在同一目录"
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "提示: 当前不是管理员,任务会在你登录后按计划运行。" -ForegroundColor Yellow
}

# 写入配置,计划任务只调用脚本本身
$configPath = Join-Path $PSScriptRoot "config.json"
if (Test-Path $configPath) {
    $backup = Join-Path $PSScriptRoot ("config.backup_{0}.json" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
    Copy-Item -LiteralPath $configPath -Destination $backup -Force
    Write-Host ("  已有配置已备份到: " + (Split-Path -Leaf $backup)) -ForegroundColor DarkGray
}

$config = [ordered]@{
    server_url  = $ServerUrl
    token       = $Token
    queue_dir   = ""
    timeout_sec = 20
}
$config | ConvertTo-Json | Out-File -FilePath $configPath -Encoding UTF8
Write-Host ("  配置已写入: " + $configPath) -ForegroundColor DarkCyan

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$scriptPath`" -NoFile"

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Hours $IntervalHours) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -User $env:USERNAME `
    -Description "定时采集本机硬件与系统状态并上报到 IT 资产巡检平台" `
    -Force | Out-Null

Write-Host ("  计划任务已注册: " + $TaskName + ",每 " + $IntervalHours + " 小时运行一次") -ForegroundColor Green

if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "  已触发一次运行,几秒后可到看板上确认设备是否出现。" -ForegroundColor DarkCyan
}

Write-Host ""
Write-Host "卸载方式: 运行同目录的 uninstall-task.ps1" -ForegroundColor DarkGray
