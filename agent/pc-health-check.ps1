#Requires -Version 5.1

<#
.SYNOPSIS
    电脑体检助手 - 一键检查 Windows 电脑的硬件、磁盘和安全状态

.DESCRIPTION
    检查系统信息、处理器、内存、磁盘空间、硬盘类型、防火墙、病毒防护和待重启状态,
    输出一份中文体检报告,并可保存为文本或 JSON 文件。

    实现上优先使用注册表和 .NET 接口,必要时才调用 CIM/WMI,
    因此在普通用户权限下也能跑出结果,不需要安装 Python 或其他软件。

.PARAMETER OutputPath
    报告保存路径,默认为脚本目录下的 reports 文件夹

.PARAMETER Json
    在保存文本报告的同时,再导出一份 JSON

.PARAMETER NoFile
    只在屏幕上显示,不保存文件

.EXAMPLE
    .\pc-health-check.ps1

.EXAMPLE
    .\pc-health-check.ps1 -Json

.EXAMPLE
    .\pc-health-check.ps1 -OutputPath D:\report\checkup.txt

.NOTES
    作者: 余柏润
    许可: MIT
#>

[CmdletBinding()]
param(
    [string]$OutputPath,
    [switch]$Json,
    [switch]$NoFile,

    # 以下参数用于对接集中管理平台;全部不填时脚本保持纯本地检查的行为
    [string]$ServerUrl,
    [string]$Token,
    [string]$QueueDir,
    [string]$ConfigPath,
    [switch]$NoUpload,
    [int]$UploadTimeoutSec = 20
)

Set-StrictMode -Version 2.0

# 默认读取脚本同目录的 config.json,命令行参数优先级更高
$script:BaseDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
if (-not $ConfigPath) {
    $defaultConfigPath = Join-Path $script:BaseDir "config.json"
    if (Test-Path $defaultConfigPath) { $ConfigPath = $defaultConfigPath }
}
if ($ConfigPath -and (Test-Path $ConfigPath)) {
    try {
        $config = Get-Content -Raw -Path $ConfigPath -Encoding UTF8 | ConvertFrom-Json
        if (-not $ServerUrl -and $config.PSObject.Properties["server_url"]) {
            $ServerUrl = [string]$config.server_url
        }
        if (-not $Token -and $config.PSObject.Properties["token"]) {
            $Token = [string]$config.token
        }
        if (-not $QueueDir -and $config.PSObject.Properties["queue_dir"]) {
            $QueueDir = [string]$config.queue_dir
        }
        if (-not $PSBoundParameters.ContainsKey("UploadTimeoutSec") -and $config.PSObject.Properties["timeout_sec"]) {
            $UploadTimeoutSec = [int]$config.timeout_sec
        }
    }
    catch {
        Write-Host ("  配置文件读取失败: " + $_.Exception.Message) -ForegroundColor DarkYellow
    }
}
if (-not $QueueDir) { $QueueDir = Join-Path $script:BaseDir "queue" }

$script:Report     = New-Object System.Collections.ArrayList
$script:Findings   = New-Object System.Collections.ArrayList
$script:Result     = [ordered]@{}
$script:ReadIssues = New-Object System.Collections.ArrayList

# 直接调用 Win32 API 读取内存和运行时长。
# 相比 WMI,这种方式不需要管理员权限,在受限环境下也能拿到数据。
$script:Win32Ready = $false
try {
    Add-Type -ErrorAction Stop -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public class PcHealthWin32
{
    [StructLayout(LayoutKind.Sequential)]
    public struct MEMORYSTATUSEX
    {
        public uint dwLength;
        public uint dwMemoryLoad;
        public ulong ullTotalPhys;
        public ulong ullAvailPhys;
        public ulong ullTotalPageFile;
        public ulong ullAvailPageFile;
        public ulong ullTotalVirtual;
        public ulong ullAvailVirtual;
        public ulong ullAvailExtendedVirtual;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool GlobalMemoryStatusEx(ref MEMORYSTATUSEX lpBuffer);

    [DllImport("kernel32.dll")]
    public static extern ulong GetTickCount64();
}
"@
    $script:Win32Ready = $true
}
catch {
    $script:Win32Ready = $false
}

function Get-Win32Memory {
    if (-not $script:Win32Ready) { return $null }
    try {
        $status = New-Object PcHealthWin32+MEMORYSTATUSEX
        $status.dwLength = [System.Runtime.InteropServices.Marshal]::SizeOf($status)
        if ([PcHealthWin32]::GlobalMemoryStatusEx([ref]$status)) {
            return [pscustomobject]@{
                TotalBytes     = [double]$status.ullTotalPhys
                AvailableBytes = [double]$status.ullAvailPhys
                LoadPercent    = [double]$status.dwMemoryLoad
            }
        }
    }
    catch { }
    return $null
}

function Get-SystemUptime {
    if (-not $script:Win32Ready) { return $null }
    try {
        $ms = [double][PcHealthWin32]::GetTickCount64()
        if ($ms -gt 0) { return [TimeSpan]::FromMilliseconds($ms) }
    }
    catch { }
    return $null
}

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host ("[{0}]" -f $Title) -ForegroundColor Cyan
    [void]$script:Report.Add("")
    [void]$script:Report.Add("[$Title]")
}

function Write-Item {
    param([string]$Label, [string]$Value, [string]$Color = "Gray")
    # 中文在控制台占两个字符宽,这里按显示宽度补空格,保证冒号后的内容对齐
    $width = 0
    foreach ($ch in $Label.ToCharArray()) {
        if ([int][char]$ch -gt 127) { $width += 2 } else { $width += 1 }
    }
    $pad = [Math]::Max(2, 16 - $width)
    $line = "  " + $Label + (" " * $pad) + $Value
    Write-Host $line -ForegroundColor $Color
    [void]$script:Report.Add($line)
}

function Add-Finding {
    param([string]$Level, [string]$Message)
    [void]$script:Findings.Add([pscustomobject]@{ Level = $Level; Message = $Message })
}

function Add-ReadIssue {
    param([string]$What)
    [void]$script:ReadIssues.Add($What)
}

function Get-OrNull {
    param([scriptblock]$Action)
    try { return & $Action } catch { return $null }
}

function Get-RegistryValue {
    param([string]$Path, [string]$Name)
    try {
        $item = Get-ItemProperty -Path $Path -Name $Name -ErrorAction Stop
        return $item.$Name
    }
    catch {
        return $null
    }
}

function Format-Size {
    param([double]$Bytes)
    if ($Bytes -ge 1GB) { return ("{0:N1} GB" -f ($Bytes / 1GB)) }
    if ($Bytes -ge 1MB) { return ("{0:N1} MB" -f ($Bytes / 1MB)) }
    return ("{0:N0} KB" -f ($Bytes / 1KB))
}

# ===========================================================================
# 集中管理平台对接
# ===========================================================================

function Get-DeviceFingerprint {
    <#
    .SYNOPSIS
        生成设备指纹。
    .DESCRIPTION
        由计算机名、主板序列号、物理网卡 MAC、系统盘卷序列号组合后取哈希。
        只用计算机名的话,机器改名后平台会把它当成一台新设备,资产表就脏了。
    #>
    $parts = @()
    $parts += "name=" + $env:COMPUTERNAME.ToLower()

    $board = Get-OrNull {
        (Get-CimInstance -ClassName Win32_BaseBoard -ErrorAction Stop | Select-Object -First 1).SerialNumber
    }
    if ($board -and $board.Trim() -and $board.Trim() -notmatch "^(To be filled|Default string|None|0)$") {
        $parts += "board=" + $board.Trim().ToLower()
    }

    $mac = Get-OrNull {
        (Get-CimInstance -ClassName Win32_NetworkAdapter -Filter "PhysicalAdapter=True AND MACAddress IS NOT NULL" -ErrorAction Stop |
            Select-Object -First 1).MACAddress
    }
    if ($mac) {
        $macClean = ($mac -replace "[^0-9A-Fa-f]", "").ToLower()
        if ($macClean) { $parts += "mac=" + $macClean }
    }

    $volume = Get-OrNull {
        (Get-CimInstance -ClassName Win32_LogicalDisk -Filter "DeviceID='C:'" -ErrorAction Stop).VolumeSerialNumber
    }
    if ($volume) { $parts += "vol=" + $volume.Trim().ToLower() }

    $joined = $parts -join "|"
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($joined)
        $hash = $sha.ComputeHash($bytes)
        $hex = ($hash | ForEach-Object { $_.ToString("x2") }) -join ""
        return $hex.Substring(0, 32)
    }
    finally {
        $sha.Dispose()
    }
}

function ConvertTo-DoubleOrNull {
    param($Value)
    if ($null -eq $Value) { return $null }
    try {
        $number = [double]$Value
        if ([double]::IsNaN($number) -or [double]::IsInfinity($number)) { return $null }
        return $number
    }
    catch { return $null }
}

function ConvertTo-IntOrNull {
    param($Value)
    if ($null -eq $Value) { return $null }
    try { return [int]$Value } catch { return $null }
}

function New-MetricItem {
    param([string]$Key, $Value, [string]$Unit = "", [string]$Dimension = "")

    $number = ConvertTo-DoubleOrNull $Value
    if ($null -eq $number) { return $null }

    $item = [ordered]@{ key = $Key; value = $number }
    if ($Unit) { $item["unit"] = $Unit }
    if ($Dimension) { $item["dimension"] = $Dimension }
    return $item
}

function ConvertTo-MetricList {
    <#
    .SYNOPSIS
        把体检结果转换成平台约定的指标长表。
    #>
    param([System.Collections.IDictionary]$Result)

    $metrics = New-Object System.Collections.ArrayList

    $cpu = $Result["cpu"]
    if ($cpu) {
        foreach ($pair in @(
                @("cpu.load_percent", "load", "%"),
                @("cpu.cores", "cores", "个"))) {
            $item = New-MetricItem -Key $pair[0] -Value $cpu[$pair[1]] -Unit $pair[2]
            if ($item) { [void]$metrics.Add($item) }
        }
    }

    $memory = $Result["memory"]
    if ($memory) {
        foreach ($pair in @(
                @("memory.used_percent", "used_percent", "%"),
                @("memory.total_gb", "total_gb", "GB"),
                @("memory.free_gb", "free_gb", "GB"))) {
            $item = New-MetricItem -Key $pair[0] -Value $memory[$pair[1]] -Unit $pair[2]
            if ($item) { [void]$metrics.Add($item) }
        }
    }

    $computer = $Result["computer"]
    if ($computer) {
        $item = New-MetricItem -Key "system.uptime_days" -Value $computer["uptime_days"] -Unit "天"
        if ($item) { [void]$metrics.Add($item) }
    }

    $disks = $Result["disks"]
    if ($disks) {
        foreach ($disk in $disks) {
            $drive = [string]$disk["drive"]
            foreach ($pair in @(
                    @("disk.used_percent", "used_percent", "%"),
                    @("disk.total_gb", "total_gb", "GB"),
                    @("disk.free_gb", "free_gb", "GB"))) {
                $item = New-MetricItem -Key $pair[0] -Value $disk[$pair[1]] -Unit $pair[2] -Dimension $drive
                if ($item) { [void]$metrics.Add($item) }
            }
        }
    }

    $system = $Result["system"]
    if ($system) {
        $item = New-MetricItem -Key "system.pending_reboot" -Value $system["pending_reboot"] -Unit "个"
        if ($item) { [void]$metrics.Add($item) }
    }

    $hardware = $Result["hardware"]
    if ($hardware) {
        $item = New-MetricItem -Key "hardware.ssd_count" -Value $hardware["ssd_count"] -Unit "块"
        if ($item) { [void]$metrics.Add($item) }
    }

    $security = $Result["security"]
    if ($security) {
        foreach ($pair in @(
                @("security.firewall_disabled_profiles", "firewall_disabled_profiles", "个"),
                @("security.defender_realtime_off", "defender_realtime_off", "个"),
                @("security.defender_signature_age_days", "defender_signature_age_days", "天"))) {
            $item = New-MetricItem -Key $pair[0] -Value $security[$pair[1]] -Unit $pair[2]
            if ($item) { [void]$metrics.Add($item) }
        }
    }

    return $metrics
}

function New-ReportPayload {
    param(
        [System.Collections.IDictionary]$Result,
        [string]$Fingerprint,
        [string]$CollectedAt,
        [string]$AgentVersion = "2.0.0"
    )

    $computer = $Result["computer"]
    $cpu = $Result["cpu"]
    $memory = $Result["memory"]
    $hardware = $Result["hardware"]

    $hostname = [string]$computer["name"]
    if (-not $hostname) { $hostname = $env:COMPUTERNAME }

    return [ordered]@{
        report_id     = [guid]::NewGuid().ToString()
        collected_at  = $CollectedAt
        agent_version = $AgentVersion
        summary       = [string]$Result["summary"]
        device        = [ordered]@{
            fingerprint  = $Fingerprint
            hostname     = $hostname
            os_name      = [string]$computer["os"]
            architecture = [string]$computer["architecture"]
            cpu_model    = [string]$cpu["name"]
            cpu_cores    = ConvertTo-IntOrNull $cpu["cores"]
            cpu_threads  = ConvertTo-IntOrNull $cpu["threads"]
            ram_total_gb = ConvertTo-DoubleOrNull $memory["total_gb"]
            ssd_count    = ConvertTo-IntOrNull $hardware["ssd_count"]
        }
        metrics       = @(ConvertTo-MetricList -Result $Result)
        findings      = @()
    }
}

function Send-ReportPayload {
    param(
        [System.Collections.IDictionary]$Payload,
        [string]$ServerUrl,
        [string]$Token,
        [int]$TimeoutSec = 20
    )

    # 显式转成 UTF-8 字节,避免 Windows PowerShell 5.1 把中文按本地代码页发送
    $json = $Payload | ConvertTo-Json -Depth 6 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $uri = $ServerUrl.TrimEnd("/") + "/api/v1/agents/report"

    return Invoke-RestMethod -Uri $uri -Method Post -Body $bytes `
        -ContentType "application/json; charset=utf-8" `
        -Headers @{ "X-Agent-Token" = $Token } `
        -TimeoutSec $TimeoutSec -ErrorAction Stop
}

function Save-PendingReport {
    param(
        [System.Collections.IDictionary]$Payload,
        [string]$QueueDir,
        [int]$MaxItems = 200
    )

    if (-not (Test-Path $QueueDir)) {
        New-Item -ItemType Directory -Path $QueueDir -Force | Out-Null
    }

    $name = "report_{0}_{1}.json" -f (Get-Date -Format "yyyyMMdd_HHmmss"), ([guid]::NewGuid().ToString("N").Substring(0, 8))
    $path = Join-Path $QueueDir $name
    $Payload | ConvertTo-Json -Depth 6 -Compress | Out-File -FilePath $path -Encoding UTF8

    # 控制队列上限,避免机器长期离线把磁盘写满
    $files = @(Get-ChildItem -Path $QueueDir -Filter "report_*.json" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending)
    if ($files.Count -gt $MaxItems) {
        $files | Select-Object -Skip $MaxItems | Remove-Item -Force -ErrorAction SilentlyContinue
    }
    return $path
}

function Invoke-QueueFlush {
    <#
    .SYNOPSIS
        补发离线期间积压的报告。
    .DESCRIPTION
        每条报告带着生成时的 report_id 补发,服务端按 (设备, report_id) 幂等入库,
        因此重复补发不会产生重复数据。
    #>
    param(
        [string]$ServerUrl,
        [string]$Token,
        [string]$QueueDir,
        [int]$TimeoutSec = 20,
        [int]$MaxSend = 50
    )

    $result = @{ sent = 0; failed = 0 }
    if (-not (Test-Path $QueueDir)) { return $result }

    $files = @(Get-ChildItem -Path $QueueDir -Filter "report_*.json" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime | Select-Object -First $MaxSend)

    foreach ($file in $files) {
        try {
            $body = [System.IO.File]::ReadAllText($file.FullName, [System.Text.Encoding]::UTF8)
            $bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
            $uri = $ServerUrl.TrimEnd("/") + "/api/v1/agents/report"
            Invoke-RestMethod -Uri $uri -Method Post -Body $bytes `
                -ContentType "application/json; charset=utf-8" `
                -Headers @{ "X-Agent-Token" = $Token } `
                -TimeoutSec $TimeoutSec -ErrorAction Stop | Out-Null
            Remove-Item -Path $file.FullName -Force -ErrorAction SilentlyContinue
            $result.sent++
        }
        catch {
            # 服务端不可用时立刻停下,不做无意义的连续重试
            $result.failed++
            break
        }
    }
    return $result
}

function Invoke-PlatformUpload {
    param(
        [System.Collections.IDictionary]$Result,
        [string]$ServerUrl,
        [string]$Token,
        [string]$QueueDir,
        [string]$CollectedAt,
        [int]$TimeoutSec = 20
    )

    $flushed = Invoke-QueueFlush -ServerUrl $ServerUrl -Token $Token -QueueDir $QueueDir -TimeoutSec $TimeoutSec
    if ($flushed.sent -gt 0) {
        Write-Host ("  已补发 {0} 条离线数据" -f $flushed.sent) -ForegroundColor DarkCyan
    }

    $fingerprint = Get-DeviceFingerprint
    $payload = New-ReportPayload -Result $Result -Fingerprint $fingerprint -CollectedAt $CollectedAt

    try {
        $response = Send-ReportPayload -Payload $payload -ServerUrl $ServerUrl -Token $Token -TimeoutSec $TimeoutSec
        if ($response.status -eq "duplicate") {
            Write-Host ("  上报成功(该次采集此前已入库, 设备 ID {0})" -f $response.device_id) -ForegroundColor DarkCyan
        }
        else {
            Write-Host ("  已上报到平台: 设备 ID {0}, 新增告警 {1} 条" -f $response.device_id, $response.alerts_created) -ForegroundColor Green
        }
        return "sent"
    }
    catch {
        $path = Save-PendingReport -Payload $payload -QueueDir $QueueDir
        Write-Host ("  上报失败,已存入离线队列: " + (Split-Path -Leaf $path)) -ForegroundColor Yellow
        Write-Host ("  原因: " + $_.Exception.Message) -ForegroundColor DarkGray
        return "queued"
    }
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor DarkCyan
Write-Host "  电脑体检助手  PC Health Check" -ForegroundColor White
Write-Host "  正在检查,请稍候..." -ForegroundColor DarkGray
Write-Host "==================================================" -ForegroundColor DarkCyan

$now = Get-Date
[void]$script:Report.Add("电脑体检报告")
[void]$script:Report.Add("生成时间: " + $now.ToString("yyyy-MM-dd HH:mm:ss"))

# ---------- 系统信息 ----------
Write-Section "系统信息"

$computerName = $env:COMPUTERNAME
$userName = $env:USERNAME
$arch = $env:PROCESSOR_ARCHITECTURE

$cvPath = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion"
$productName = Get-RegistryValue -Path $cvPath -Name "ProductName"
$displayVersion = Get-RegistryValue -Path $cvPath -Name "DisplayVersion"
$buildNumber = Get-RegistryValue -Path $cvPath -Name "CurrentBuildNumber"

if ($productName) {
    if ($buildNumber -and [int]$buildNumber -ge 22000) {
        $productName = $productName -replace "Windows 10", "Windows 11"
    }
    if ($displayVersion) { $osName = "$productName $displayVersion" } else { $osName = $productName }
    if ($buildNumber) { $osName = "$osName (内部版本 $buildNumber)" }
}
else {
    $osName = [System.Environment]::OSVersion.VersionString
    Add-ReadIssue "操作系统名称"
}

$uptime = $null
$span = Get-SystemUptime
$osCim = Get-OrNull { Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop }
if (-not $span -and $osCim -and $osCim.LastBootUpTime) {
    $span = $now - $osCim.LastBootUpTime
}
if ($span) {
    $uptime = "{0} 天 {1} 小时 {2} 分钟" -f $span.Days, $span.Hours, $span.Minutes
}
else {
    $uptime = "无法读取"
    Add-ReadIssue "系统运行时长"
}

Write-Item "计算机名" $computerName
Write-Item "当前用户" $userName
Write-Item "操作系统" $osName
Write-Item "系统架构" $arch
Write-Item "已运行" $uptime
$uptimeDays = $null
if ($span) { $uptimeDays = [math]::Round($span.TotalDays, 2) }
$script:Result["computer"] = @{
    name = $computerName; user = $userName; os = $osName
    architecture = $arch; uptime = $uptime; uptime_days = $uptimeDays
}

# ---------- 处理器 ----------
Write-Section "处理器"

$cpuPath = "HKLM:\HARDWARE\DESCRIPTION\System\CentralProcessor\0"
$cpuName = Get-RegistryValue -Path $cpuPath -Name "ProcessorNameString"
if (-not $cpuName) {
    $cpuName = $env:PROCESSOR_IDENTIFIER
    if (-not $cpuName) {
        $cpuName = "无法读取"
        Add-ReadIssue "处理器型号"
    }
}
else {
    $cpuName = $cpuName.Trim()
}

$threads = $env:NUMBER_OF_PROCESSORS
$cores = $null
$cpuLoad = $null
$cpuCim = Get-OrNull { Get-CimInstance -ClassName Win32_Processor -ErrorAction Stop | Select-Object -First 1 }
if ($cpuCim) {
    if ($cpuCim.NumberOfCores) { $cores = $cpuCim.NumberOfCores }
    if ($null -ne $cpuCim.LoadPercentage) { $cpuLoad = $cpuCim.LoadPercentage }
}

Write-Item "型号" $cpuName
if ($cores) {
    Write-Item "核心/线程" ("{0} 核 / {1} 线程" -f $cores, $threads)
}
else {
    Write-Item "逻辑处理器" ("{0} 个" -f $threads)
}
if ($null -ne $cpuLoad) {
    Write-Item "当前负载" ("{0}%" -f $cpuLoad)
}

$script:Result["cpu"] = @{ name = $cpuName; cores = $cores; threads = $threads; load = $cpuLoad }

if ($null -ne $cpuLoad -and [int]$cpuLoad -ge 85) {
    Add-Finding -Level "警告" -Message ("处理器当前负载 {0}%,检查一下是否有程序占用过高" -f $cpuLoad)
}

# ---------- 内存 ----------
Write-Section "内存"

$totalBytes = $null
$freeBytes = $null

# 第一选择:Win32 API(不需要管理员权限)
$mem = Get-Win32Memory
if ($mem) {
    $totalBytes = $mem.TotalBytes
    $freeBytes = $mem.AvailableBytes
}

# 第二选择:WMI
if (-not $totalBytes -and $osCim) {
    try {
        $totalBytes = [double]$osCim.TotalVisibleMemorySize * 1KB
        $freeBytes = [double]$osCim.FreePhysicalMemory * 1KB
    }
    catch { }
}

if (-not $totalBytes) {
    $cs = Get-OrNull { Get-CimInstance -ClassName Win32_ComputerSystem -ErrorAction Stop }
    if ($cs -and $cs.TotalPhysicalMemory) {
        $totalBytes = [double]$cs.TotalPhysicalMemory
        $available = Get-OrNull {
            (Get-Counter -Counter "\Memory\Available MBytes" -ErrorAction Stop).CounterSamples[0].CookedValue
        }
        if ($available) { $freeBytes = [double]$available * 1MB }
    }
}

if ($totalBytes -and $freeBytes) {
    $usedPercent = [math]::Round((($totalBytes - $freeBytes) / $totalBytes) * 100, 1)
    Write-Item "总容量" (Format-Size $totalBytes)
    Write-Item "可用" (Format-Size $freeBytes)
    $memColor = if ($usedPercent -ge 85) { "Yellow" } else { "Gray" }
    Write-Item "使用率" ("{0}%" -f $usedPercent) $memColor
    $script:Result["memory"] = @{
        total_gb = [math]::Round($totalBytes / 1GB, 1)
        free_gb = [math]::Round($freeBytes / 1GB, 1)
        used_percent = $usedPercent
    }
    if ($usedPercent -ge 85) {
        Add-Finding -Level "警告" -Message ("内存使用率 {0}%,关掉不用的程序,或考虑加内存条" -f $usedPercent)
    }
    else {
        Add-Finding -Level "正常" -Message ("内存使用率 {0}%,状态良好" -f $usedPercent)
    }
}
else {
    Write-Item "状态" "无法读取内存信息" "DarkGray"
    Add-ReadIssue "内存信息"
}

# ---------- 磁盘 ----------
Write-Section "磁盘空间"

$diskResult = @()
$drives = @()
try {
    $drives = [System.IO.DriveInfo]::GetDrives() | Where-Object { $_.DriveType -eq "Fixed" -and $_.IsReady }
}
catch { }

foreach ($drive in $drives) {
    try {
        $size = [double]$drive.TotalSize
        $free = [double]$drive.AvailableFreeSpace
        if ($size -le 0) { continue }
        $usedPercent = [math]::Round((($size - $free) / $size) * 100, 1)
        $freeGb = $free / 1GB
        $label = $drive.Name.TrimEnd("\")
        $line = "{0} 总容量 {1,-10} 可用 {2,-10} 已用 {3}%" -f $label, (Format-Size $size), (Format-Size $free), $usedPercent
        $color = "Gray"
        if ($usedPercent -ge 85 -or $freeGb -lt 20) { $color = "Yellow" }
        Write-Host ("  " + $line) -ForegroundColor $color
        [void]$script:Report.Add("  " + $line)
        $diskResult += @{
            drive = $label
            total_gb = [math]::Round($size / 1GB, 1)
            free_gb = [math]::Round($freeGb, 1)
            used_percent = $usedPercent
        }

        if ($usedPercent -ge 85) {
            Add-Finding -Level "警告" -Message ("{0} 盘已用 {1}%,清理一下临时文件和不用的软件" -f $label, $usedPercent)
        }
        elseif ($freeGb -lt 20) {
            Add-Finding -Level "注意" -Message ("{0} 盘只剩 {1:N1} GB,低于 20 GB 建议清理" -f $label, $freeGb)
        }
    }
    catch { }
}

if ($diskResult.Count -eq 0) {
    Write-Item "状态" "无法读取磁盘信息" "DarkGray"
    Add-ReadIssue "磁盘信息"
}
$script:Result["disks"] = $diskResult

# ---------- 硬盘类型 ----------
Write-Section "硬盘类型"

$physicalDisks = @()
$wmiDisks = @()
try {
    $physicalDisks = @(Get-PhysicalDisk -ErrorAction Stop | Select-Object -First 3)
}
catch {
    try {
        $wmiDisks = @(Get-CimInstance -ClassName Win32_DiskDrive -ErrorAction Stop | Select-Object -First 3)
    }
    catch {
        $wmiDisks = @()
    }
}

if ($physicalDisks.Count -gt 0) {
    foreach ($pd in $physicalDisks) {
        $media = switch ($pd.MediaType) {
            "SSD" { "固态硬盘 SSD" }
            "HDD" { "机械硬盘 HDD" }
            default { "$($pd.MediaType)" }
        }
        Write-Item $pd.FriendlyName ("{0}  {1}" -f $media, (Format-Size $pd.Size))
    }
    $isSsd = @($physicalDisks | Where-Object { $_.MediaType -eq "SSD" }).Count -gt 0
    if (-not $isSsd) {
        Add-Finding -Level "注意" -Message "没检测到固态硬盘,换成 SSD 能明显加快开机和软件启动"
    }
}
elseif ($wmiDisks.Count -gt 0) {
    foreach ($wd in $wmiDisks) {
        Write-Item $wd.Model (Format-Size $wd.Size)
    }
}
else {
    Write-Item "状态" "无法读取硬盘型号(可以试试以管理员身份运行)" "DarkGray"
}

$ssdCount = $null
if ($physicalDisks.Count -gt 0) {
    $ssdCount = @($physicalDisks | Where-Object { $_.MediaType -eq "SSD" }).Count
}
$script:Result["hardware"] = @{ ssd_count = $ssdCount }

# ---------- 安全状态 ----------
Write-Section "安全状态"

$firewallStates = @()
$profiles = Get-OrNull { Get-NetFirewallProfile -ErrorAction Stop }
if ($profiles) {
    foreach ($p in $profiles) {
        $label = switch ($p.Name) {
            "Domain" { "域网络" }
            "Private" { "专用网络" }
            "Public" { "公用网络" }
            default { "$($p.Name)" }
        }
        $firewallStates += [pscustomobject]@{ Name = $label; Enabled = [bool]$p.Enabled }
    }
}
else {
    # 降级方案:直接读注册表,普通权限也能读到
    $fwPath = "HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy"
    foreach ($item in @(
            @{ Key = "DomainProfile"; Label = "域网络" },
            @{ Key = "StandardProfile"; Label = "专用网络" },
            @{ Key = "PublicProfile"; Label = "公用网络" })) {
        $value = Get-RegistryValue -Path "$fwPath\$($item.Key)" -Name "EnableFirewall"
        if ($null -ne $value) {
            $firewallStates += [pscustomobject]@{ Name = $item.Label; Enabled = ([int]$value -eq 1) }
        }
    }
}

if ($firewallStates.Count -gt 0) {
    $disabled = @($firewallStates | Where-Object { -not $_.Enabled })
    if ($disabled.Count -eq 0) {
        Write-Item "防火墙" "全部配置文件已开启" "Green"
    }
    else {
        Write-Item "防火墙" ("以下配置未开启: " + (($disabled | ForEach-Object { $_.Name }) -join ", ")) "Yellow"
        Add-Finding -Level "警告" -Message "Windows 防火墙没有全部开启"
    }
}
else {
    Write-Item "防火墙" "无法读取状态" "DarkGray"
    Add-ReadIssue "防火墙状态"
}

$defender = Get-OrNull { Get-MpComputerStatus -ErrorAction Stop }
if ($defender) {
    if ($defender.RealTimeProtectionEnabled) {
        Write-Item "病毒防护" "实时保护已开启" "Green"
    }
    else {
        Write-Item "病毒防护" "实时保护未开启,建议马上打开" "Yellow"
        Add-Finding -Level "警告" -Message "Windows 病毒防护的实时保护没有开启"
    }
    if ($defender.AntivirusSignatureLastUpdated) {
        $sigDays = ($now - $defender.AntivirusSignatureLastUpdated).Days
        if ($sigDays -ge 7) {
            Add-Finding -Level "注意" -Message ("病毒库已经 {0} 天没更新" -f $sigDays)
        }
    }
}
else {
    Write-Item "病毒防护" "无法读取状态(可能装了第三方杀毒软件)" "DarkGray"
}

$firewallDisabled = $null
if ($firewallStates.Count -gt 0) {
    $firewallDisabled = @($firewallStates | Where-Object { -not $_.Enabled }).Count
}
$realtimeOff = $null
if ($defender) { $realtimeOff = if ($defender.RealTimeProtectionEnabled) { 0 } else { 1 } }
$signatureAgeDays = $null
if ($defender -and $defender.AntivirusSignatureLastUpdated) {
    $signatureAgeDays = [math]::Round(($now - $defender.AntivirusSignatureLastUpdated).TotalDays, 1)
}
$script:Result["security"] = @{
    firewall_disabled_profiles = $firewallDisabled
    defender_realtime_off      = $realtimeOff
    defender_signature_age_days = $signatureAgeDays
}

# ---------- 系统状态 ----------
Write-Section "系统状态"

$pendingReboot = $false
foreach ($path in @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending",
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired")) {
    if (Test-Path $path) { $pendingReboot = $true }
}

if ($pendingReboot) {
    Write-Item "待重启" "有未完成的更新,建议重启生效" "Yellow"
    Add-Finding -Level "注意" -Message "系统有待重启的更新"
}
else {
    Write-Item "待重启" "无" "Green"
}

$script:Result["system"] = @{ pending_reboot = if ($pendingReboot) { 1 } else { 0 } }

if ($script:ReadIssues.Count -gt 0) {
    Add-Finding -Level "注意" -Message ("以下项目没有读到: " + ($script:ReadIssues -join "、") + "。可以试试用管理员身份重新运行")
}

# ---------- 体检结论 ----------
Write-Section "体检结论"

$warnings = @($script:Findings | Where-Object { $_.Level -eq "警告" })
$notices = @($script:Findings | Where-Object { $_.Level -eq "注意" })

if ($warnings.Count -gt 0) {
    $summary = "发现 {0} 项需要处理的问题" -f $warnings.Count
    $summaryColor = "Yellow"
}
elseif ($notices.Count -gt 0) {
    $summary = "整体正常,有 {0} 项可以优化的地方" -f $notices.Count
    $summaryColor = "Gray"
}
else {
    $summary = "一切正常,电脑状态良好"
    $summaryColor = "Green"
}

Write-Host ("  " + $summary) -ForegroundColor $summaryColor
[void]$script:Report.Add("  " + $summary)

foreach ($finding in $script:Findings) {
    $text = "  [{0}] {1}" -f $finding.Level, $finding.Message
    $color = switch ($finding.Level) {
        "警告" { "Yellow" }
        "正常" { "DarkGray" }
        default { "Gray" }
    }
    Write-Host $text -ForegroundColor $color
    [void]$script:Report.Add($text)
}

$script:Result["findings"] = $script:Findings
$script:Result["summary"] = $summary

# ---------- 保存报告 ----------
if (-not $NoFile) {
    if (-not $OutputPath) {
        $baseDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
        $OutputPath = Join-Path $baseDir ("reports\体检报告_{0}.txt" -f $now.ToString("yyyyMMdd_HHmmss"))
    }
    $outDir = Split-Path -Parent $OutputPath
    if ($outDir -and -not (Test-Path $outDir)) {
        New-Item -ItemType Directory -Path $outDir -Force | Out-Null
    }
    $script:Report | Out-File -FilePath $OutputPath -Encoding UTF8
    Write-Host ""
    Write-Host ("  报告已保存: " + $OutputPath) -ForegroundColor DarkCyan

    if ($Json) {
        $jsonPath = [System.IO.Path]::ChangeExtension($OutputPath, ".json")
        $script:Result | ConvertTo-Json -Depth 5 | Out-File -FilePath $jsonPath -Encoding UTF8
        Write-Host ("  JSON 已保存: " + $jsonPath) -ForegroundColor DarkCyan
    }
}

# ---------- 上报到集中管理平台 ----------
if ($NoUpload) {
    Write-Host ""
    Write-Host "  已跳过上报(-NoUpload)" -ForegroundColor DarkGray
}
elseif ($ServerUrl -and $Token) {
    Write-Host ""
    Write-Host "  正在上报到管理平台..." -ForegroundColor DarkCyan
    $collectedAt = $now.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    try {
        Invoke-PlatformUpload -Result $script:Result -ServerUrl $ServerUrl -Token $Token `
            -QueueDir $QueueDir -CollectedAt $collectedAt -TimeoutSec $UploadTimeoutSec | Out-Null
    }
    catch {
        Write-Host ("  上报流程异常: " + $_.Exception.Message) -ForegroundColor Yellow
    }
}
else {
    Write-Host ""
    Write-Host "  未配置管理平台地址或令牌,跳过上报" -ForegroundColor DarkGray
    Write-Host "  需要集中管理时用 -ServerUrl 和 -Token 指定,或填写同目录的 config.json" -ForegroundColor DarkGray
}

Write-Host ""
