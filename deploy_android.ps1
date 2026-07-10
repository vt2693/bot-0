#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Deploy Hermes Agent files to Android Termux via ADB (USB) or SSH/WiFi.
.PARAMETER Ip
    Phone IP for SSH/rsync deployment. Omit to use ADB automatically.
.PARAMETER User
    Termux username (SSH). Default: u0_aXXX (auto-detected from adb).
.EXAMPLE
    .\deploy_android.ps1                    # ADB (USB) only
    .\deploy_android.ps1 -Ip 192.168.1.100 # SSH/rsync
#>

param(
    [string]$Ip = "",
    [string]$User = "u0_a1"
)

$REPO_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$PHONE_DIR = "~/hermes-bot"

$FILES = @(
    "android_bot.py", "tg_voice.py", "voice_relay.py",
    "telegram_bot.py", "config.py", "hermes_bridge.py",
    "composio_mcp.py", "memory_store.py", "scheduler.py",
    "relay.py", "healthcheck.py", "app.py",
    "setup_android.sh", "start_android.sh"
)

Set-Location $REPO_DIR

if ($Ip) {
    # ─── SSH deploy ────────────────────────────────────────────
    Write-Host "==> Deploying via SSH (WiFi) to ${User}@${Ip}" -ForegroundColor Cyan
    $target = "${User}@${Ip}:${PHONE_DIR}/"
    ssh "${User}@${Ip}" "mkdir -p $PHONE_DIR" 2>&1 | Out-Null
    rsync -avz --include="*/" --include="*.py" --include="*.sh" --include="requirements*.txt" --exclude="*" -e "ssh" "$REPO_DIR/" "$target"
    Write-Host "  [OK] Files transferred" -ForegroundColor Green
} else {
    # ─── ADB deploy ────────────────────────────────────────────
    Write-Host "==> Deploying via ADB (USB)" -ForegroundColor Cyan
    adb shell "mkdir -p $PHONE_DIR" 2>&1 | Out-Null
    foreach ($f in $FILES) {
        $local = Join-Path $REPO_DIR $f
        if (Test-Path $local) {
            Write-Host "  pushing $f ... " -NoNewline
            $null = adb push "$local" "$PHONE_DIR/$f" 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "OK" -ForegroundColor Green
            } else {
                Write-Host "FAIL" -ForegroundColor Red
            }
        }
    }
    Get-ChildItem $REPO_DIR -Filter "requirements*.txt" | ForEach-Object {
        Write-Host "  pushing $($_.Name) ... " -NoNewline
        adb push "$($_.FullName)" "$PHONE_DIR/$($_.Name)" 2>&1 | Out-Null
        Write-Host "OK" -ForegroundColor Green
    }
    Write-Host "  [OK] Files transferred via ADB" -ForegroundColor Green
}