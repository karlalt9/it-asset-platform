#Requires -Version 5.1

<#
.SYNOPSIS
    移除由 install-task.ps1 注册的计划任务。
#>

[CmdletBinding()]
param(
    [string]$TaskName = "IT Asset Platform Agent"
)

Set-StrictMode -Version 2.0

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host ("没有找到计划任务: " + $TaskName) -ForegroundColor Yellow
    return
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host ("已移除计划任务: " + $TaskName) -ForegroundColor Green
