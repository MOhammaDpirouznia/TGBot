# GitHub One-Click Uploader for PowerShell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "       سامانه آپلود خودکار پروژه در گیتهاب (PowerShell)   " -ForegroundColor Cyan
Write-Host "===================================================" -ForegroundColor Cyan

$status = git status --short
if (-not $status) {
    Write-Host "هیچ تغییری برای آپلود وجود ندارد. پروژه کاملاً بروز است." -ForegroundColor Yellow
    exit 0
}

Write-Host "فایل‌های تغییر یافته:" -ForegroundColor DarkGray
git status -s

$msg = Read-Host "پیام کامیت (Enter برای پیام خودکار تاریخ و ساعت)"
if ([string]::IsNullOrWhiteSpace($msg)) {
    $now = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $msg = "بروزرسانی خودکار پروژه: $now"
}

Write-Host "`n[1/2] در حال ثبت تغییرات..." -ForegroundColor Green
git add .
git commit -m "$msg"

Write-Host "`n[2/2] در حال آپلود در گیتهاب..." -ForegroundColor Green
git push origin main

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n===================================================" -ForegroundColor Green
    Write-Host "   [موفقیت] تمام تغییرات با موفقیت در گیتهاب آپلود شد! " -ForegroundColor Green
    Write-Host "===================================================" -ForegroundColor Green
} else {
    Write-Host "`n===================================================" -ForegroundColor Red
    Write-Host "   [خطا] مشکلی در ارسال به گیتهاب رخ داد." -ForegroundColor Red
    Write-Host "===================================================" -ForegroundColor Red
}
