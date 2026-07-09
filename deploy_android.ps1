#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Deploy Hermes Agent files to Android Termux via ADB (USB) or SSH/WiFi.

.DESCRIPTION
    Transfers all needed files to the phone, then optionally runs
    setup_android.sh and start_android.sh in Termux.

    Two methods:
      1. ADB (USB) — automatic if device detected
      2. SSH/rsync — fallback, prompts for phone IP

    Run this from the repo root (bot-0/).
#>

$REPO_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$PHONE_DIR = "~/hermes-bot"

# Files to transfer (all .py + .sh, plus requirements.txt)
$FILES = @(
    "android_bot.py",
    "tg_voice.py",
    "voice_relay.py",
    "telegram_bot.py",
    "config.py",
    "hermes_bridge.py",
    "composio_mcp.py",
    "memory_store.py",
    "scheduler.py",
    "relay.py",
    "healthcheck.py",
    "app.py",
    "setup_android.sh",
    "start_android.sh"
)

$EXTRA_GLOBS = @(
    "*.py",
    "*.sh",
    "requirements.txt",
    "requirements-android.txt"
)

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "  ✓ $msg" -ForegroundColor Green }
function Write-Err($msg)  { Write-Host "  ✗ $msg" -ForegroundColor Red }

# ─── detect ADB ───────────────────────────────────────────────────────
function Test-ADBAvailable {
    try {
        $null = Get-Command adb -ErrorAction Stop
        $devices = adb devices
        if ($devices -match "^[a-f0-9]+\s+device") {
            return $true
        }
    } catch {}
    return $false
}

# ─── ADB deploy ───────────────────────────────────────────────────────
function Deploy-ADB {
    Write-Step "Deploying via ADB (USB)"

    # Create remote dir
    adb shell "mkdir -p $PHONE_DIR"
    Write-OK "Remote directory ready"

    # Push each file
    foreach ($f in $FILES) {
        $local = Join-Path $REPO_DIR $f
        if (Test-Path $local) {
            Write-Host "  pushing $f ..." -NoNewline
            $out = adb push "$local" "$PHONE_DIR/$f" 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host " OK" -ForegroundColor Green
            } else {
                Write-Host " FAIL" -ForegroundColor Red
                Write-Err "$out"
            }
        }
    }

    # Also push requirements*.txt
    Get-ChildItem $REPO_DIR -Filter "requirements*.txt" | ForEach-Object {
        Write-Host "  pushing $($_.Name) ..." -NoNewline
        adb push "$($_.FullName)" "$PHONE_DIR/$($_.Name)" 2>&1 | Out-Null
        Write-Host " OK" -ForegroundColor Green
    }

    # Push start script
    adb push (Join-Path $REPO_DIR "start_android.sh") "$PHONE_DIR/start_android.sh" 2>&1 | Out-Null

    Write-OK "Files transferred via ADB"
    return $true
}

# ─── SSH/rsync deploy ────────────────────────────────────────────────
function Deploy-SSH {
    Write-Step "Deploying via SSH/rsync (WiFi)"
    $ip = Read-Host "Enter phone IP (e.g., 192.168.1.100)"
    $user = Read-Host "Termux username [u0_aXXX]"

    $target = "${user}@${ip}:${PHONE_DIR}/"
    Write-Host "Syncing to $target ..."

    # Detect rsync or scp
    $useRsync = $null -ne (Get-Command rsync -ErrorAction SilentlyContinue)

    if ($useRsync) {
        $src = "$REPO_DIR/"
        rsync -avz --progress --include="*/" --include="*.py" --include="*.sh" `
            --include="requirements*.txt" --exclude="*" `
            -e "ssh" "$src" "$target"
        if ($LASTEXITCODE -eq 0) {
            Write-OK "rsync complete"
            return $true
        }
        Write-Err "rsync failed"
        return $false
    } else {
        # fallback: scp each file
        foreach ($f in $FILES) {
            $local = Join-Path $REPO_DIR $f
            if (Test-Path $local) {
                Write-Host "  scp $f ..." -NoNewline
                scp "$local" "${user}@${ip}:${PHONE_DIR}/${f}" 2>&1 | Out-Null
                if ($LASTEXITCODE -eq 0) {
                    Write-Host " OK" -ForegroundColor Green
                } else {
                    Write-Host " FAIL" -ForegroundColor Red
                }
            }
        }
        # requirements
        Get-ChildItem $REPO_DIR -Filter "requirements*.txt" | ForEach-Object {
            scp "$($_.FullName)" "${user}@${ip}:${PHONE_DIR}/$($_.Name)" 2>&1 | Out-Null
        }
        Write-OK "Files transferred via scp"
        return $true
    }
}

# ─── post-transfer: run setup + start ────────────────────────────────
function Run-Setup {
    param([string]$Method)

    $runSetup = Read-Host "`nRun setup_android.sh on phone now? (y/n) [y]"
    if ($runSetup -ne "n" -and $runSetup -ne "N") {
        switch ($Method) {
            "adb" {
                Write-Step "Running setup via ADB shell"
                adb shell "cd $PHONE_DIR && bash setup_android.sh"
            }
            "ssh" {
                $ip = Read-Host "Phone IP again"
                $user = Read-Host "Termux username again"
                ssh "${user}@${ip}" "cd $PHONE_DIR && bash setup_android.sh"
            }
        }
    }

    $runStart = Read-Host "`nStart the bot now? (y/n) [y]"
    if ($runStart -ne "n" -and $runStart -ne "N") {
        switch ($Method) {
            "adb" {
                Write-Step "Starting bot via ADB shell"
                adb shell "cd $PHONE_DIR && bash start_android.sh"
                Write-OK "Bot started! Attach via: tmux attach -t hermes"
            }
            "ssh" {
                $ip = Read-Host "Phone IP again"
                $user = Read-Host "Termux username again"
                ssh "${user}@${ip}" "cd $PHONE_DIR && bash start_android.sh"
                Write-OK "Bot started via SSH"
            }
        }
    }
}

# ─── main ─────────────────────────────────────────────────────────────
[Console]::ForegroundColor = [ConsoleColor]::Magenta
Write-Host "╔═══════════════════════════════════════╗"
Write-Host "║  Hermes Agent - Android Deploy Tool  ║"
Write-Host "╚═══════════════════════════════════════╝"
Write-Host ""
[Console]::ResetColor()

cd $REPO_DIR

if (Test-ADBAvailable) {
    Write-OK "ADB device detected — using USB"
    $method = "adb"
    Deploy-ADB
} else {
    Write-Host "  ⚠ No ADB device found." -ForegroundColor Yellow
    Write-Host "    Connect USB with USB debugging enabled, or use SSH/WiFi."
    $choice = Read-Host "`nUse SSH/WiFi instead? (y/n) [y]"
    if ($choice -eq "n" -or $choice -eq "N") {
        Write-Host "Aborted." -ForegroundColor Red
        exit 1
    }
    $method = "ssh"
    $ok = Deploy-SSH
    if (-not $ok) {
        Write-Err "SSH deploy failed"
        exit 1
    }
}

Write-OK "All files transferred to ${PHONE_DIR}"

Run-Setup -Method $method

[Console]::ForegroundColor = [ConsoleColor]::Cyan
Write-Host ""
Write-Host "Done! Quick reference:"
Write-Host "  Attach to bot:   tmux attach -t hermes"
Write-Host "  View logs:       cat ~/hermes-bot/logs/bot.log"
Write-Host "  Restart bot:     ~/hermes-bot/start_android.sh"
Write-Host "  Manual deploy:   $PSCommandPath"
[Console]::ResetColor()
