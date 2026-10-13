# 日报越狱 · 卸载脚本：删程序、快捷方式、开机自启和「应用和功能」里的条目。
# 你的设置、保存的密码、日报数据（默认 D:\工作）会保留，想彻底清掉的话手动删，路径见最后的提示。
param([switch]$Silent)
$ErrorActionPreference = 'Continue'
$target = Split-Path -Parent $MyInvocation.MyCommand.Path
$appName = '日报越狱'

Get-Process DailyPrison -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 800

Remove-Item (Join-Path ([Environment]::GetFolderPath('Desktop')) "$appName.lnk") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path ([Environment]::GetFolderPath('Startup')) "$appName.lnk") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path ([Environment]::GetFolderPath('Programs')) $appName) -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DailyPrison' -Recurse -Force -ErrorAction SilentlyContinue

if (-not $Silent) {
    Write-Host "已卸载 $appName。" -ForegroundColor Green
    Write-Host "保留了你的设置和日报数据，想彻底清掉可以手动删除："
    Write-Host "  设置和日志：$env:APPDATA\daily-prison"
    Write-Host "  日报数据：D:\工作（或你在设置里指定的数据目录）"
    Write-Host "  保存的密码：控制面板 → 凭据管理器 → Windows 凭据 → 名为 daily-prison 的条目"
}
# 脚本自己在安装目录里，退出后再删目录（延迟 2 秒，等脚本结束）
Start-Process cmd -ArgumentList '/c', "ping 127.0.0.1 -n 3 >nul & rmdir /s /q `"$target`"" -WindowStyle Hidden
