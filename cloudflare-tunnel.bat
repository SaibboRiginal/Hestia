@echo off
cd /d "%~dp0"

echo ============================================================
echo   Hestia - Cloudflare Tunnel for WebUI
echo   Target: http://localhost:19015
echo ============================================================
echo.

:: ── Prerequisites ──────────────────────────────────────────────

if not exist "cloudflared.exe" (
    echo [FAIL] cloudflared.exe not found in %~dp0
    echo.
    echo Download it from:
    echo   https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
    echo.
    echo Place the .exe in the Hestia root folder and re-run this script.
    pause
    exit /b 1
)

curl -s -o nul http://localhost:19015/health 2>nul
if errorlevel 1 (
    echo [FAIL] WebUI not reachable at http://localhost:19015/health
    echo Run up-all.bat first to start the Docker services.
    pause
    exit /b 1
)

:: ── Start cloudflared in background ────────────────────────────

if not exist "data" mkdir "data"
set "TUNNEL_LOG=%CD%\data\tunnel.log"

echo [OK] Prerequisites met.
echo [..] Starting cloudflared tunnel (logs: data\tunnel.log)...

:: cloudflared writes its logs to stderr; capture to file, discard stdout
start /b "" cloudflared.exe tunnel --url http://localhost:19015 2>"%TUNNEL_LOG%" 1>nul

:: ── Wait for tunnel URL & register with WebUI ──────────────────

echo [..] Waiting for Cloudflare to assign tunnel URL...
echo.

:: Single PowerShell call — deliberately avoids | (pipe) chars inside the
:: batch double-quoted string to prevent cmd.exe parsing issues.
powershell -ExecutionPolicy Bypass -Command "$log='%TUNNEL_LOG%'; for($i=0;$i -lt 60;$i++){Start-Sleep 1; if(Test-Path $log){$c=Get-Content $log -Raw -EA 0; if($c -match 'https://[a-z0-9-]+\.trycloudflare\.com'){$url=$matches[0]; Write-Host '============================================================'; Write-Host '  Tunnel URL:' $url; Write-Host '============================================================'; try{$body=ConvertTo-Json -InputObject @{url=$url}; $h=@{}; if($env:WEBUI_ADMIN_SECRET){$h['X-WebUI-Admin-Secret']=$env:WEBUI_ADMIN_SECRET}; $null=Invoke-RestMethod 'http://localhost:19015/api/webui/admin/public-url' -Method Post -Body $body -ContentType 'application/json' -Headers $h; Write-Host '  [OK] URL registered with WebUI.'}catch{Write-Host '  [WARN] Could not register URL - WebUI may still be starting.'; Write-Host '         The tunnel is running; try /webui_token in a moment.'}; Write-Host ''; Write-Host '  Run /webui_token in Telegram to get a login link.'; Write-Host '============================================================'; Write-Host ''; Write-Host 'Press any key in this window to stop the tunnel.'; exit 0}}}; Write-Host '[FAIL] Tunnel URL not detected after 60 seconds.'; Write-Host 'Check data\tunnel.log for cloudflared output.'; Write-Host ''; Write-Host 'If the tunnel is running, manually POST the URL to:'; Write-Host '  http://localhost:19015/api/webui/admin/public-url'; exit 1"

if errorlevel 1 (
    echo.
    pause
    exit /b 1
)

echo.
echo Tunnel is running. Press any key to stop.

:: ── Hecate OAuth tunnel (port 19003) ─────────────────────────────
:: Start a second cloudflared instance so Google OAuth callbacks can
:: reach Hecate from any device (phone, tablet, etc.).  The public URL
:: is written to a file that Hecate reads at runtime.
curl -s -o nul http://localhost:19003/health 2>nul
if not errorlevel 1 (
    echo.
    echo [..] Starting Cloudflare tunnel for Hecate OAuth ^(port 19003^)...
    set "HECATE_TUNNEL_LOG=%CD%\Hestia-Hecate\data\tunnel-url.txt"

    start /b "" cloudflared.exe tunnel --url http://localhost:19003 2>"%CD%\Hestia-Hecate\data\tunnel-hecate.log" 1>nul

    powershell -ExecutionPolicy Bypass -Command "$log='%CD%\Hestia-Hecate\data\tunnel-hecate.log'; $out='%CD%\Hestia-Hecate\data\tunnel-url.txt'; for($i=0;$i -lt 60;$i++){Start-Sleep 1; if(Test-Path $log){$c=Get-Content $log -Raw -EA 0; if($c -match 'https://[a-z0-9-]+\.trycloudflare\.com'){$url=$matches[0]; Write-Host '============================================================'; Write-Host '  Hecate OAuth URL:' $url; Write-Host '============================================================'; $url | Out-File -Encoding utf8 $out; Write-Host '  [OK] Hecate tunnel URL written for auto-detection.'; Write-Host ''; exit 0}}}; Write-Host '[WARN] Hecate tunnel URL not detected after 60s'; exit 0"
    echo [OK] Hecate OAuth tunnel started ^(Google auth works from phone now^).
) else (
    echo [WARN] Hecate not reachable at http://localhost:19003 - OAuth tunnel skipped.
    echo        Google auth will only work from desktop ^(localhost^) or by pasting the final URL in Telegram.
)

echo.
echo Press any key to stop the tunnels.
pause >nul
taskkill /im cloudflared.exe /f >nul 2>&1
if exist "Hestia-Hecate\data\tunnel-url.txt" del "Hestia-Hecate\data\tunnel-url.txt"
echo Tunnels stopped.
