# 日报越狱 · 安装脚本：不需要管理员权限，装到当前用户目录，建快捷方式，能在「应用和功能」里卸载。
# 双击同目录的「安装.bat」即可。参数只给测试用：-Silent 不提问、不建快捷方式、不启动；-Target 指定安装目录。
param(
    [string]$Target = (Join-Path $env:LOCALAPPDATA 'Programs\DailyPrison'),
    [switch]$Silent,
    [switch]$NoLaunch,
    [ValidateSet('ask', 'yes', 'no')][string]$AutoStart = 'ask'   # 开机自启：ask 问一下 / yes / no（脚本化安装用）
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$src = Join-Path $here 'DailyPrison'
$version = if (Test-Path (Join-Path $here 'version.txt')) { (Get-Content (Join-Path $here 'version.txt') | Select-Object -First 1).Trim() } else { '0.0.0' }
$exe = Join-Path $Target 'DailyPrison.exe'
$appName = '日报越狱'

function Say($msg, $color = 'White') { if (-not $Silent) { Write-Host $msg -ForegroundColor $color } }

if (-not (Test-Path (Join-Path $src 'DailyPrison.exe'))) {
    Write-Host "找不到安装文件（$src）。请先把压缩包完整解压，再运行安装。" -ForegroundColor Red
    exit 1
}
Say "== 安装 $appName $version ==" 'Cyan'

# 1) 检查 WebView2 运行时（窗口就是靠它显示的；Win11 自带，Win10 装过新版 Edge 也有）
$guid = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
$hasWebView2 = @("HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$guid", "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$guid",
                 "HKCU:\Software\Microsoft\EdgeUpdate\Clients\$guid") | Where-Object { Test-Path $_ }
if (-not $hasWebView2) {
    Say '！没检测到 WebView2 运行时，软件可能打不开窗口。' 'Yellow'
    Say '  请先安装：https://go.microsoft.com/fwlink/p/?LinkId=2124703 （微软官方，约 2MB）' 'Yellow'
    if (-not $Silent) { Start-Process 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' }
}

# 2) 关掉正在运行的旧版本（升级安装）
Get-Process DailyPrison -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 800

# 3) 复制文件（/MIR：升级时清掉旧文件；设置和日报数据不在这个目录，不会丢）
Say "复制文件到 $Target ..."
New-Item -ItemType Directory -Force -Path $Target | Out-Null
robocopy $src $Target /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { Write-Host "复制文件失败（robocopy 错误码 $LASTEXITCODE）" -ForegroundColor Red; exit 1 }
Copy-Item (Join-Path $here 'uninstall.ps1') (Join-Path $Target 'uninstall.ps1') -Force

# 4) 快捷方式 + 开机自启（测试用 -Silent 时都不建）
function New-Shortcut($path, $arguments) {
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut($path)
    $lnk.TargetPath = $exe; $lnk.Arguments = $arguments; $lnk.WorkingDirectory = $Target
    $lnk.IconLocation = "$exe,0"; $lnk.Description = '日报越狱：自动写日报并提交'
    $lnk.Save()
}
if (-not $Silent) {
    New-Shortcut (Join-Path ([Environment]::GetFolderPath('Desktop')) "$appName.lnk") ''
    $menu = Join-Path ([Environment]::GetFolderPath('Programs')) $appName
    New-Item -ItemType Directory -Force -Path $menu | Out-Null
    New-Shortcut (Join-Path $menu "$appName.lnk") ''
    Say '已创建桌面和开始菜单快捷方式。'
    $auto = if ($AutoStart -eq 'yes') { 0 } elseif ($AutoStart -eq 'no') { 1 } else { $Host.UI.PromptForChoice('开机自启', '开机后自动在右下角托盘守着，到点自动提交日报（推荐）。要开启吗？', @('&是', '&否'), 0) }
    if ($auto -eq 0) {
        New-Shortcut (Join-Path ([Environment]::GetFolderPath('Startup')) "$appName.lnk") '--tray'
        Say '已开启开机自启（以后可以在软件的「典狱长办公室」里关）。'
    }
}

# 5) 注册到「应用和功能」，之后可以从那里卸载
if (-not $Silent) {
    $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DailyPrison'
    New-Item -Path $key -Force | Out-Null
    $props = @{ DisplayName = $appName; DisplayVersion = $version; Publisher = '日报越狱'; InstallLocation = $Target; DisplayIcon = "$exe,0"
                UninstallString = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $Target 'uninstall.ps1')`"" }
    foreach ($k in $props.Keys) { Set-ItemProperty -Path $key -Name $k -Value $props[$k] }
    Set-ItemProperty -Path $key -Name NoModify -Value 1 -Type DWord
}

Say "`n安装完成。" 'Green'
Say '首次打开会先让你登记日报系统的账号密码（只存在这台电脑的 Windows 凭据管理器里）。'
Say '提醒：这台电脑上要装有 Claude Code 或 Codex 之一（软件借它们来写日报），并且能访问日报系统。'
if (-not $Silent -and -not $NoLaunch) { Start-Process $exe }
