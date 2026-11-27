# Hestia installer for Windows 10/11 (PowerShell 5.1+). Double-click Install-Hestia.cmd, or in PowerShell:
#   irm https://raw.githubusercontent.com/SaibboRiginal/Hestia/main/install.ps1 | iex
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/SaibboRiginal/Hestia/main/install.ps1))) -Dir D:\Hestia
#   ... -Join 123456 -Central 192.168.1.10     this PC becomes a satellite of the central one (code: System -> Machines)
#   ... -Role all|central|satellite
#
# Every step checks before acting, retries (2/4/8 s), has a fallback, and records where it got to: running it again
# resumes or repairs (also by itself after the WSL2 reboot). When it truly cannot go on it stops with one sentence
# saying what to do. It never prints or logs secrets, never overwrites an existing .env value (only the machine link
# keys HUB_UPSTREAM_URL, HUB_NODE_TOKEN, HUB_NODE_ADDRESS, on -Join or a role change), never deletes data without -Purge. Windows asks for administrator confirmation only for WSL2 and Docker Desktop.
# ASCII only on purpose: PowerShell 5.1 reads a BOM-less file as ANSI, and a BOM breaks `irm | iex`. Messages here are
# English with << >> for the quotes (Expand-Text turns them back at print time); translations come from a UTF-8 file.
# SPEC: docs/work/2026-10-30-one-click-setup
[CmdletBinding()]
param(
    [string]$Dir = '',                 # empty = where it is launched (see below)
    [string]$Channel = 'stable',      # stable | latest (checked below: no ValidateSet, see the note after param)
    [switch]$Update,
    [switch]$Repair,
    [switch]$Uninstall,
    [switch]$Purge,
    [switch]$DryRun,
    [switch]$NoBrowser,
    [switch]$Resume,
    [string]$Role = '',                # all | central | satellite | empty = keep / all
    [string]$Join = '',
    [string]$Central = '',
    [string]$Lang = ''                 # a language code (en, it...) | empty = the language of Windows
)

# No [ValidateSet] in param: with `irm | iex` the block runs as plain statements and an attribute on a variable
# without a value (Role) fails at once (the Italian Windows message says the Role variable could become invalid). Checked here instead.
if ($env:HESTIA_INSTALL_DRY_RUN -eq '1') { $DryRun = [switch]$true; $NoBrowser = [switch]$true }   # CI: iex has no arguments
# Language: messages are English, in the language of Windows (or -Lang / HESTIA_LANG) when Hestia has a catalog for
# it: Hestia-Shared/hestia_common/locales/<code>/installer.tsv, one line <<English<TAB>translation>>, values as {0} {1}.
# Read next to this script, else downloaded from the same repository; no catalog -> English. A new language = one new
# file, no change here. Every message is written (T 'english {0}' $value).
$script:Lang = if ($Lang) { $Lang } elseif ($env:HESTIA_LANG) { $env:HESTIA_LANG } else {
    try { (Get-UICulture).TwoLetterISOLanguageName } catch { try { (Get-Culture).TwoLetterISOLanguageName } catch { 'en' } } }
$script:Lang = ([string]$script:Lang).ToLowerInvariant()
$script:Lang = if ($script:Lang -match '^[a-z]{2}') { $script:Lang.Substring(0, 2) } else { 'en' }
$script:Texts = New-Object 'System.Collections.Generic.Dictionary[string,string]'
if ($script:Lang -ne 'en') {
    $rel = "Hestia-Shared/hestia_common/locales/$($script:Lang)/installer.tsv"
    $raw = if ($env:HESTIA_RAW_URL) { $env:HESTIA_RAW_URL } else { 'https://raw.githubusercontent.com/SaibboRiginal/Hestia/main' }
    $tsv = $null
    try {
        $local = @($PSScriptRoot, (Get-Location).ProviderPath) | Where-Object { $_ } | ForEach-Object { Join-Path $_ $rel } |
            Where-Object { Test-Path $_ } | Select-Object -First 1   # a copy of the repository: next to it or here
        if ($local) { $tsv = [IO.File]::ReadAllText($local, [Text.Encoding]::UTF8) }
        else { $tsv = [Text.Encoding]::UTF8.GetString((New-Object Net.WebClient).DownloadData("$raw/$rel")) }
    } catch { $tsv = $null }   # no catalog for this language or no network yet: English
    if ($tsv) {
        foreach ($line in ($tsv -split "`r?`n")) {
            $cut = $line.IndexOf("`t")
            if ($cut -gt 0 -and -not $script:Texts.ContainsKey($line.Substring(0, $cut))) { $script:Texts[$line.Substring(0, $cut)] = $line.Substring($cut + 1) }
        }
    }
}
function T([string]$En) {
    $text = $En
    if ($script:Texts.ContainsKey($En)) { $text = $script:Texts[$En] }
    for ($i = 0; $i -lt $args.Count; $i++) { $text = $text.Replace('{' + $i + '}', [string]$args[$i]) }
    return $text
}
# Folder: where it is launched. A Hestia folder (it has docker-compose.global.yml) is used as it is, otherwise Hestia goes
# in a "Hestia" folder inside it. Launched from a system folder (an administrator PowerShell opens in System32) or a
# drive root: the user's folder instead.
if (-not $Dir) {
    $here = (Get-Location).ProviderPath
    $system = @($env:windir, $env:ProgramFiles, ${env:ProgramFiles(x86)}) | Where-Object { $_ }
    if (Test-Path (Join-Path $here 'docker-compose.global.yml')) { $Dir = $here }
    elseif (($system | Where-Object { $here -like "$_*" }) -or ($here -match '^[A-Za-z]:\\?$')) { $Dir = Join-Path $env:USERPROFILE 'Hestia' }
    else { $Dir = Join-Path $here 'Hestia' }
}
# 'latest' is the name people type for the news channel.
$Channel = switch ($Channel) { 'stable' { 'stable' } 'latest' { 'news' } default { $Channel } }
if (@('stable', 'news') -notcontains $Channel) { Write-Host (T 'Unknown channel: {0}. Use stable or latest.' $Channel); return }
if ($Role -and @('all', 'central', 'satellite') -notcontains $Role) { Write-Host (T 'Unknown role: {0}. Use all, central or satellite.' $Role); return }

# Continue, not Stop: on Windows PowerShell 5.1 any stderr line of a native program (docker, git, winget) would
# otherwise become a terminating error. Native calls are checked by exit code; cmdlets that must stop say -ErrorAction Stop.
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is 10x slower with the progress bar on 5.1
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }

$RepoUrl    = if ($env:HESTIA_REPO_URL) { $env:HESTIA_REPO_URL } else { 'https://github.com/SaibboRiginal/Hestia.git' }
$ZipUrl     = 'https://codeload.github.com/SaibboRiginal/Hestia/zip/refs/heads/main'
$ScriptUrl  = 'https://raw.githubusercontent.com/SaibboRiginal/Hestia/main/install.ps1'
$DockerUrl  = 'https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe'
$OllamaUrl  = 'https://ollama.com/download/OllamaSetup.exe'
$WebUiUrl   = 'http://localhost:19015'
$SetupUrl   = "$WebUiUrl/setup"
$HubUrl     = 'http://localhost:19001'
$Project    = 'hestia'
$StateDir   = Join-Path $env:LOCALAPPDATA 'Hestia\install'
$LogFile    = Join-Path $StateDir 'install.log'
$SavedScript = Join-Path $StateDir 'install.ps1'
$script:Notes = New-Object System.Collections.Generic.List[string]
$script:VersionTag = ''
$script:RamGb = 0
$script:FreeGb = 0
$script:Role = $Role        # all (one machine) - central (always on, no heavy modules) - satellite (voice + training)
$script:LanIp = ''
$SatelliteServices = @('hub', 'echo', 'metis')
$HeavyServices = @('echo', 'metis')

New-Item -ItemType Directory -Force -Path $StateDir | Out-Null

# -- output -------------------------------------------------------------------------------------------------------
$R = '[' + [char]::ConvertFromUtf32(0x1F504) + ']'   # recovery marker of the log convention
function Expand-Text([string]$Text) {
    # Pairs, not a hashtable: hashtable keys ignore case, and ~e (grave) and ~E (acute) must both exist.
    $pairs = @(@('~e', 0xE8), @('~E', 0xE9), @('~a', 0xE0), @('~o', 0xF2), @('~u', 0xF9), @('~i', 0xEC), @('<<', 0xAB), @('>>', 0xBB))
    foreach ($p in $pairs) { $Text = $Text.Replace($p[0], [string][char]$p[1]) }
    return $Text
}
function Write-Log([string]$Text) {
    try { Add-Content -Path $LogFile -Value ("{0} event={1}" -f (Get-Date).ToUniversalTime().ToString('s'), $Text) -Encoding UTF8 } catch { }
}
function Say([string]$Text)  { Write-Host (Expand-Text "[Hestia] $Text") -ForegroundColor Yellow; Write-Log "say msg=`"$Text`"" }
function Ok([string]$Text)   { Write-Host (Expand-Text "[Hestia] $Text") -ForegroundColor Green;  Write-Log "ok msg=`"$Text`"" }
function Note([string]$Text) { $script:Notes.Add($Text) }
function Stop-Install([string]$Reason) {
    Write-Host ''
    Write-Host (Expand-Text ("[Hestia] " + (T 'I stopped: ') + $Reason)) -ForegroundColor Red
    Write-Host (T '         Run the same command again when done: I pick up from here.')
    Write-Host ((T '         Details: ') + $LogFile)
    Write-Log "install_failed reason=`"$Reason`""
    if (Test-Interactive) { Read-Host (T 'Press Enter to close') | Out-Null }
    exit 1
}

function Test-Interactive { return ([Environment]::UserInteractive -and -not [Console]::IsInputRedirected -and $Host.Name -eq 'ConsoleHost') }

# -- helpers ------------------------------------------------------------------------------------------------------
function Test-Command([string]$Name) { return [bool](Get-Command $Name -ErrorAction SilentlyContinue) }

function Invoke-Step {  # run an external program; output to the log; $true on exit code 0. -DryRun only prints.
    param([string]$File, [string[]]$Arguments = @(), [switch]$Elevated)
    $line = "$File $($Arguments -join ' ')"
    if ($DryRun) { Write-Host "  [dry-run] $line"; return $true }
    Write-Log "run cmd=`"$line`" elevated=$([bool]$Elevated)"
    if (-not (Test-Command $File) -and -not (Test-Path $File)) { Write-Log "$R run_missing cmd=`"$File`""; return $false }
    try {
        if ($Elevated) {
            $p = Start-Process -FilePath $File -ArgumentList $Arguments -Verb RunAs -Wait -PassThru -ErrorAction Stop
            return ($p.ExitCode -eq 0)
        }
        $out = & $File @Arguments 2>&1
        $out | ForEach-Object { Write-Log "  | $_" }
        return ($LASTEXITCODE -eq 0)
    } catch {
        Write-Log "$R run_error cmd=`"$line`" error=`"$($_.Exception.Message)`""
        return $false
    }
}

function Invoke-Retry {  # Invoke-Retry 'what' { scriptblock returning $true/$false }: 3 tries, backoff 2/4/8 s
    param([string]$What, [scriptblock]$Action)
    $delay = 2
    for ($i = 1; $i -le 3; $i++) {
        $result = $false
        try { $result = [bool](& $Action) } catch { Write-Log "$R retry_error what=`"$What`" error=`"$($_.Exception.Message)`"" }
        if ($result) { return $true }
        if ($i -lt 3) {
            Write-Log "$R retry what=`"$What`" attempt=$i next_in=${delay}s"
            Say (T '{0}: did not work, retrying in {1}s...' ${What} ${delay})
            Start-Sleep -Seconds $delay
            $delay *= 2
        }
    }
    return $false
}

function Update-PathFromRegistry {  # programs installed a moment ago are not on this session's PATH yet
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
    foreach ($extra in @("$env:ProgramFiles\Docker\Docker\resources\bin", "$env:ProgramFiles\Git\cmd",
                         "$env:LOCALAPPDATA\Programs\Ollama")) {
        if ((Test-Path $extra) -and ($env:Path -notlike "*$extra*")) { $env:Path += ";$extra" }
    }
}

function Get-File([string]$Url, [string]$Target) {
    if ($DryRun) { Write-Host "  [dry-run] download $Url"; return $true }
    Write-Log "download url=$Url"
    Invoke-WebRequest -ErrorAction Stop -Uri $Url -OutFile $Target -UseBasicParsing
    return (Test-Path $Target)
}

function Install-Winget([string]$Id, [string]$Override = '') {
    if (-not (Test-Command 'winget')) { return $false }
    $wingetArgs = @('install', '-e', '--id', $Id, '--silent', '--accept-package-agreements', '--accept-source-agreements')
    if ($Override) { $wingetArgs += @('--override', $Override) }
    $ok = Invoke-Step 'winget' $wingetArgs
    Update-PathFromRegistry
    return $ok
}

function Test-StepDone([string]$Name) { return ((Test-Path "$StateDir\state") -and ((Get-Content "$StateDir\state") -contains $Name)) }
function Set-StepDone([string]$Name) {
    if ($DryRun -or (Test-StepDone $Name)) { return }
    Add-Content -Path "$StateDir\state" -Value $Name
}

function Invoke-Docker { & docker @args 2>&1 | ForEach-Object { Write-Log "  | $_" }; return ($LASTEXITCODE -eq 0) }
function Test-Docker { try { & docker info 2>&1 | Out-Null; return ($LASTEXITCODE -eq 0) } catch { return $false } }

function Invoke-Compose {
    $files = @('-f', 'docker-compose.global.yml')
    if ($script:VersionTag -and (Test-Path (Join-Path $Dir 'docker-compose.images.yml'))) { $files += @('-f', 'docker-compose.images.yml') }
    if ($DryRun) { Write-Host "  [dry-run] docker compose $($args -join ' ')"; return $true }
    $env:HESTIA_VERSION = $script:VersionTag.TrimStart('v')
    Push-Location $Dir
    try {
        Write-Log "compose args=`"$($args -join ' ')`""
        & docker compose -p $Project @files @args 2>&1 | ForEach-Object { Write-Log "  | $_" }
        return ($LASTEXITCODE -eq 0)
    } finally { Pop-Location }
}

# The download of the ready-made modules takes minutes: every module that arrives is shown (name, done/total), so a
# slow line never looks frozen. The full compose output still goes to the log.
function Invoke-ComposePull {
    $files = @('-f', 'docker-compose.global.yml')
    if ($script:VersionTag -and (Test-Path (Join-Path $Dir 'docker-compose.images.yml'))) { $files += @('-f', 'docker-compose.images.yml') }
    if ($DryRun) { Write-Host "  [dry-run] docker compose pull $($args -join ' ')"; return $true }
    $env:HESTIA_VERSION = $script:VersionTag.TrimStart('v')
    $script:PullSeen = @{}; $script:PullDone = @{}
    Push-Location $Dir
    try {
        Write-Log "compose args=`"pull $($args -join ' ')`""
        & docker compose -p $Project @files pull @args 2>&1 | ForEach-Object {
            $line = [string]$_
            # Layer progress (Downloading/Extracting ... many lines a second) stays out of the log: writing each one slowed
            # the download itself on Windows and buried what matters.
            if ($line -match '^\s*[0-9a-f]{12}\s+(Downloading|Extracting|Waiting|Verifying)') { return }
            Write-Log "  | $line"
            if ($line -match '(\S+)\s+(Pulling|Pulled|Error)\b' -and $Matches[1] -notmatch '^[0-9a-f]{12}$') {
                $raw = $Matches[1]; $what = $Matches[2]     # an image (ghcr.io/x/hestia:hub-1.0.0, postgres:16) or a service
                $name = if ($raw -match ':([a-z0-9]+)-\d+\.\d+\.\d+') { $Matches[1] } else { ($raw -replace ':.*$', '') -replace '^.*/', '' }
                $script:PullSeen[$name] = $true
                if ($what -ne 'Pulling' -and -not $script:PullDone.ContainsKey($name)) {
                    $script:PullDone[$name] = $true
                    $mark = if ($what -eq 'Pulled') { T 'ready' } else { T 'not downloaded' }
                    Write-Host ("         {0} {1} ({2}/{3})" -f $name, $mark, $script:PullDone.Count, $script:PullSeen.Count)
                }
            }
        }
        return ($LASTEXITCODE -eq 0)
    } finally { Pop-Location }
}

# -- 0. preflight -------------------------------------------------------------------------------------------------
function Test-Preflight {
    Say (T 'Checking the computer...')
    $ramGb = [math]::Floor((Get-CimInstance -ErrorAction Stop Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
    $drive = (Split-Path -Qualifier $Dir).TrimEnd(':')
    $freeGb = [math]::Floor((Get-PSDrive -ErrorAction Stop $drive).Free / 1GB)
    $script:RamGb = $ramGb; $script:FreeGb = $freeGb
    Write-Log "preflight ram_gb=$ramGb free_gb=$freeGb"
    if ($ramGb -lt 8) { Note (T 'You have {0} GB of RAM: Hestia works, but local models need at least 16. Use cloud models.' $ramGb) }
    if ($freeGb -lt 20) { Stop-Install (T 'at least 20 GB free (better 30) are needed on drive {0}:, there are {1}. Free some space.' ${drive} $freeGb) }
    if ($freeGb -lt 30) { Note (T 'Free space: {0} GB. Enough for Hestia; it may not be enough for large local models.' $freeGb) }
    $probe = "$($RepoUrl -replace '\.git$', '').git/info/refs?service=git-upload-pack"
    $online = Invoke-Retry (T 'Internet connection') { (Invoke-WebRequest -ErrorAction Stop -Uri $probe -UseBasicParsing -TimeoutSec 15).StatusCode -eq 200 }
    if (-not $online) { Stop-Install (T 'I cannot reach github.com: check the internet connection.') }
    $cpu = Get-CimInstance -ErrorAction Stop Win32_Processor | Select-Object -First 1
    $hyperv = (Get-CimInstance -ErrorAction Stop Win32_ComputerSystem).HypervisorPresent
    if (-not $hyperv -and -not $cpu.VirtualizationFirmwareEnabled) {
        Stop-Install (T 'virtualization is off in the BIOS/UEFI: restart, enter the BIOS and turn on <<Intel VT-x>> or <<AMD-V / SVM>>, then run again.')
    }
}

# A busy port is named with what holds it. Another Hestia (its containers, from another folder or an older install)
# is offered to be stopped, so the user never hunts for it; any other program is named so they know what to close.
function Get-PortHolder([int]$Port) {
    if (Test-Docker) {
        foreach ($row in @(& docker ps --format '{{.Names}}|{{.Ports}}' 2>$null)) {
            $cut = ([string]$row).IndexOf('|')
            if ($cut -gt 0 -and ([string]$row).Substring($cut + 1) -match (":$Port->")) { return @{ container = ([string]$row).Substring(0, $cut) } }
        }
    }
    $conn = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
    $proc = if ($conn) { Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue } else { $null }
    return @{ program = $(if ($proc) { $proc.ProcessName } else { '' }) }
}

function Test-Ports {
    if ((Test-Docker) -and ((& docker ps --format '{{.Names}}' 2>$null) -contains 'hestia_hub')) { return }
    $busy = @(); $hestia = @(); $others = @()
    $ports = if ($script:Role -eq 'satellite') { @(19001, 19021, 19014) } else { @(19001, 19002, 19015, 5432) }
    foreach ($port in $ports) {
        if (-not (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)) { continue }
        $busy += $port
        $holder = Get-PortHolder $port
        if ($holder.container -like 'hestia_*') { $hestia += $holder.container }
        elseif ($holder.container) { $others += "$port ($($holder.container))" }
        elseif ($holder.program) { $others += "$port ($($holder.program))" }
        else { $others += "$port" }
    }
    Write-Log "ports_busy ports=`"$($busy -join ',')`" hestia=`"$($hestia -join ',')`" others=`"$($others -join ',')`""
    if ($others.Count) { Stop-Install (T 'these ports are already used by another program: {0}. Close it and run again.' ($others -join ', ')) }
    if (-not $hestia.Count) { return }
    # Another Hestia is on: stop all of its containers (they start again with docker start; data stays in its volumes).
    $first = $hestia[0]
    $where = [string](& docker inspect -f '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' $first 2>$null)
    $running = @(& docker ps --format '{{.Names}}' 2>$null | Where-Object { $_ -like 'hestia_*' })
    $place = if ($where.Trim()) { $where.Trim() } else { T 'another folder' }
    Say (T 'Another Hestia is already on ({0}) and holds the ports Hestia needs.' $place)
    $answer = if (Test-Interactive) { Read-Host (T '[Hestia] Stop it and go on? [Y/n]') } else { 'n' }
    if ($answer -match '^[nN]') { Stop-Install (T 'stop the other Hestia first (Docker Desktop, Containers, Stop), then run again.') }
    if (-not $DryRun) { & docker stop @running 2>&1 | ForEach-Object { Write-Log "  | $_" } }
    Write-Log "other_hestia_stopped where=`"$place`" containers=$($running.Count)"
    Ok (T 'Other Hestia stopped: its data stays where it was.')
}

# -- 1. git -------------------------------------------------------------------------------------------------------
function Install-GitIfMissing {
    if (Test-Command 'git') { return }
    Say (T 'Installing git...')
    if (-not (Invoke-Retry (T 'Installing git') { Install-Winget 'Git.Git' })) {
        Note (T 'git did not install: I download Hestia as an archive (updates will use git once it is there).')
    }
}

# -- 2-3. WSL2 + Docker Desktop -----------------------------------------------------------------------------------
function Register-Resume {
    if ($DryRun) { return }
    if ($PSCommandPath -and (Test-Path $PSCommandPath)) { Copy-Item -ErrorAction Stop $PSCommandPath $SavedScript -Force }
    else { try { Get-File $ScriptUrl $SavedScript | Out-Null } catch { Write-Log "$R resume_download_failed" } }
    $cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$SavedScript`" -Resume -Dir `"$Dir`" -Channel $Channel -Lang $($script:Lang)"
    if ($script:Role) { $cmd += " -Role $($script:Role)" }
    if ($Join) { $cmd += " -Join $Join -Central $Central" }
    Set-ItemProperty -ErrorAction Stop -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce' -Name 'HestiaInstall' -Value $cmd
    Write-Log 'resume_registered'
}

function Install-Wsl {
    $ready = $false
    try { & wsl.exe --status 2>&1 | Out-Null; $ready = ($LASTEXITCODE -eq 0) } catch { }
    if ($ready -or (Test-StepDone 'wsl')) { return }
    Say (T 'Turning on WSL2 (Docker needs it). Windows asks for administrator confirmation.')
    $ok = Invoke-Retry (T 'Turning on WSL2') { Invoke-Step 'wsl.exe' @('--install', '--no-distribution') -Elevated }
    if (-not $ok) { Stop-Install (T 'WSL2 does not turn on. Open PowerShell as administrator, run <<wsl --install>> and run this again.') }
    Set-StepDone 'wsl'
    Register-Resume
    Say (T 'WSL2 needs a restart to finish. After the restart the install resumes by itself.')
    $answer = if (Test-Interactive) { Read-Host (T '[Hestia] Restart now? [Y/n]') } else { 'n' }
    if ($answer -notmatch '^[nN]') { if (-not $DryRun) { Restart-Computer -Force } }
    exit 0
}

function Install-DockerIfMissing {
    Update-PathFromRegistry
    if (Test-Docker) { return }
    $exe = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path $exe)) {
        Install-Wsl
        Say (T 'Installing Docker Desktop (a few minutes). Windows asks for administrator confirmation.')
        $ok = Invoke-Retry (T 'Installing Docker Desktop') { Install-Winget 'Docker.DockerDesktop' 'install --quiet --accept-license' }
        if (-not $ok) {
            Write-Log "$R docker_fallback via=direct_installer"
            $installer = Join-Path $env:TEMP 'DockerDesktopInstaller.exe'
            $ok = (Invoke-Retry (T 'Downloading Docker Desktop') { Get-File $DockerUrl $installer }) -and
                  (Invoke-Step $installer @('install', '--quiet', '--accept-license') -Elevated)
        }
        if (-not $ok) { Stop-Install (T 'Docker Desktop does not install: download it from https://docker.com/products/docker-desktop, install it and run again.') }
        Update-PathFromRegistry
        Note (T 'Docker Desktop starts by itself with the computer: leave it so, Hestia comes back with it.')
    }
    if ($DryRun) { return }
    Say (T 'Starting Docker Desktop: if it is the first time, accept the terms in its window.')
    Start-Process $exe | Out-Null
    $waited = 0
    while (-not (Test-Docker)) {
        if ($waited -ge 300) { Stop-Install (T 'Docker Desktop does not answer: open it, wait for <<Engine running>> and run again. If it asks you to sign out of Windows and back in, do it.') }
        Start-Sleep -Seconds 5; $waited += 5
        if ($waited % 30 -eq 0) { Say (T '...still waiting for Docker ({0} s)' $waited) }
    }
    if (-not ((& docker compose version 2>$null) -match 'version')) { Stop-Install (T '<<docker compose>> is missing: update Docker Desktop and run again.') }
}

# -- 5. Ollama (native: uses the GPU without extra setup) --------------------------------------------------------
function Test-Ollama { try { return ((Invoke-WebRequest -ErrorAction Stop 'http://127.0.0.1:11434/api/version' -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) } catch { return $false } }

function Install-OllamaIfMissing {
    Update-PathFromRegistry
    if ((Test-Command 'ollama') -or (Test-Ollama)) { if (-not (Test-Ollama)) { Start-OllamaApp }; Get-DefaultModels; return }
    Say (T 'Installing Ollama (the models on your computer)...')
    $ok = Invoke-Retry (T 'Installing Ollama') { Install-Winget 'Ollama.Ollama' }
    if (-not $ok) {
        Write-Log "$R ollama_fallback via=direct_installer"
        $installer = Join-Path $env:TEMP 'OllamaSetup.exe'
        $ok = (Invoke-Retry (T 'Downloading Ollama') { Get-File $OllamaUrl $installer }) -and (Invoke-Step $installer @('/VERYSILENT', '/NORESTART'))
    }
    if (-not $ok) { Note (T 'Ollama did not install: Hestia will use cloud models. You can install it later from https://ollama.com.'); return }
    Start-OllamaApp
    if ($script:Role -eq 'satellite') { Set-OllamaOnLan }
    Get-DefaultModels
}

# On a satellite the central one's brain uses this graphics card: Ollama must listen on the home network too.
function Set-OllamaOnLan {
    if ($DryRun) { Write-Host '  [dry-run] OLLAMA_HOST=0.0.0.0 (user)'; return }
    if ([Environment]::GetEnvironmentVariable('OLLAMA_HOST', 'User') -eq '0.0.0.0') { return }
    [Environment]::SetEnvironmentVariable('OLLAMA_HOST', '0.0.0.0', 'User')
    $env:OLLAMA_HOST = '0.0.0.0'
    Get-Process -Name 'ollama*' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Start-OllamaApp
    Write-Log 'ollama_bind_all reason=satellite'
    Note (T 'Ollama now listens on the home network (port 11434): if Windows asks to allow it on private networks, answer Allow. Do not open that port on the router.')
}

# Oracle's default chains (llm_chains.py): the embedding model is needed for memory, the chat one for local answers.
$DefaultModels = @('qwen3-embedding:0.6b', 'gemma4:e4b')

function Get-DefaultModels {
    Update-PathFromRegistry
    if (-not (Test-Command 'ollama')) { return }
    $have = @()
    if (-not $DryRun) { $have = @(& ollama list 2>$null | ForEach-Object { ($_ -split '\s+')[0] }) }
    foreach ($model in $DefaultModels) {
        if ($have -contains $model) { continue }
        Say (T 'Downloading the model {0} (only once)...' $model)
        if (-not (Invoke-Retry (T 'Downloading {0}' $model) { Invoke-Step 'ollama' @('pull', $model) })) {
            Note (T 'The model {0} did not download: run again later, meanwhile Hestia uses the cloud if you have a key.' $model)
        }
    }
}

function Start-OllamaApp {
    if ($DryRun -or (Test-Ollama)) { return }
    $app = "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"
    if (Test-Path $app) { Start-Process $app | Out-Null } elseif (Test-Command 'ollama') { Start-Process 'ollama' -ArgumentList 'serve' -WindowStyle Hidden | Out-Null }
    Start-Sleep -Seconds 3
}

# -- 6. Hestia code -----------------------------------------------------------------------------------------------
function Get-Code {
    if (Test-Path (Join-Path $Dir '.git')) {
        $origin = (& git -C $Dir remote get-url origin 2>$null)
        if ($origin -notmatch 'hestia') { Stop-Install (T '{0} exists but is not Hestia. Choose another folder with -Dir.' $Dir) }
        if (-not (Invoke-Retry (T 'Updating the code') { Invoke-Step 'git' @('-C', $Dir, 'fetch', '--tags', '--prune', 'origin') })) {
            Note (T 'I could not download the code changes: I use the version already here.')
        }
    } elseif (Test-Path (Join-Path $Dir 'docker-compose.global.yml')) {
        Write-Log "code_existing_without_git dir=$Dir"
    } elseif ((Test-Path $Dir) -and (Get-ChildItem $Dir -Force | Select-Object -First 1)) {
        Stop-Install (T '{0} exists and is not empty. Choose another folder with -Dir.' $Dir)
    } else {
        Say (T 'Downloading Hestia into {0}...' $Dir)
        if (Test-Command 'git') {
            $ok = Invoke-Retry (T 'Downloading Hestia') { Invoke-Step 'git' @('clone', '--quiet', '-c', 'core.autocrlf=false', $RepoUrl, $Dir) }
        } else {
            Write-Log "$R code_zip reason=no_git"
            $zip = Join-Path $env:TEMP 'hestia-main.zip'
            $ok = Invoke-Retry (T 'Downloading Hestia') { Get-File $ZipUrl $zip }
            if ($ok -and -not $DryRun) {
                $tmp = Join-Path $env:TEMP 'hestia-main'
                Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
                Expand-Archive -ErrorAction Stop $zip $tmp -Force
                Move-Item -ErrorAction Stop (Get-ChildItem $tmp | Select-Object -First 1).FullName $Dir
            }
        }
        if (-not $ok) { Stop-Install (T 'I cannot download Hestia from GitHub. Check the connection.') }
    }
    Select-Version
}

function Select-Version {
    $script:VersionTag = ''
    if (-not (Test-Path (Join-Path $Dir '.git'))) { return }
    if (& git -C $Dir status --porcelain --untracked-files=no 2>$null) {
        Note (T 'The Hestia folder has local changes: I did not change the code version.')
        $script:VersionTag = [string](& git -C $Dir describe --tags --exact-match 2>$null)
        return
    }
    if ($Channel -eq 'stable') {
        $tag = & git -C $Dir tag -l 'v*.*.*' --sort=-v:refname | Select-Object -First 1
        if ($tag) {
            Invoke-Step 'git' @('-C', $Dir, '-c', 'advice.detachedHead=false', 'checkout', '--quiet', $tag) | Out-Null
            $script:VersionTag = $tag
            Ok (T 'Version {0}' $tag)
            return
        }
        Note (T 'There is no published version yet: I install the latest development one and build it here (slower, only once).')
    }
    $branch = & git -C $Dir rev-parse --abbrev-ref HEAD
    if ($branch -eq 'HEAD') { Invoke-Step 'git' @('-C', $Dir, 'checkout', '--quiet', 'main') | Out-Null; $branch = 'main' }
    if (-not (Invoke-Step 'git' @('-C', $Dir, 'pull', '--quiet', '--ff-only', 'origin', $branch))) {
        Note (T 'The local code no longer follows GitHub: I left it as it is.')
    }
}

# What the guided setup shows (<<16 GB graphics card>>) and uses to suggest models: git-ignored, no personal data.
function Write-Hardware {
    if ($DryRun) { return }
    $gpu = ''; $vram = 0
    if (Test-Command 'nvidia-smi') {
        $line = (& nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>$null | Select-Object -First 1)
        if ($line -match '^(.+),\s*(\d+)\s*$') { $gpu = $Matches[1].Trim(); $vram = [math]::Floor([int]$Matches[2] / 1024) }
    }
    $dirInfo = Join-Path $Dir '.hestia-install'
    New-Item -ItemType Directory -Force -Path $dirInfo | Out-Null
    $json = @{ os = 'windows'; ram_gb = $script:RamGb; free_gb = $script:FreeGb; gpu = $gpu; vram_gb = $vram
               role = $script:Role; lan_ip = $script:LanIp } | ConvertTo-Json -Compress
    Set-Content -Path (Join-Path $dirInfo 'hardware.json') -Value $json -Encoding ASCII
    Write-Log "hardware gpu=`"$gpu`" vram_gb=$vram role=$($script:Role) lan_ip=$($script:LanIp)"
}

# -- machines: role, LAN address, link to the central one (docs/work/2026-10-30-one-click-setup 4.0) -------------
function Resolve-Role {
    if ($Join) {
        if ($script:Role -and $script:Role -ne 'satellite') { Stop-Install (T '-Join is only for a satellite.') }
        $script:Role = 'satellite'
        if (-not $Central) { Stop-Install (T '-Join also needs -Central (the address of the central home, e.g. 192.168.1.10).') }
    }
    if (-not $script:Role) {   # a re-run keeps the role chosen before
        $hw = Join-Path $Dir '.hestia-install\hardware.json'
        if (Test-Path $hw) { try { $script:Role = [string](Get-Content $hw -Raw | ConvertFrom-Json).role } catch { } }
        if (-not $script:Role) { $script:Role = 'all' }
    }
    $envFile = Join-Path $Dir '.env'
    $linked = (Test-Path $envFile) -and [bool](Select-String -Path $envFile -Pattern '^HUB_NODE_TOKEN=.+' -Quiet)
    if ($script:Role -eq 'satellite' -and -not $Join -and -not $linked) {
        Stop-Install (T 'to link this PC you need the code: on the central home open System -> Machines -> Link a machine, then run again with -Join CODE -Central ADDRESS.')
    }
    try {
        $script:LanIp = [string](Get-NetIPConfiguration -ErrorAction Stop | Where-Object { $_.IPv4DefaultGateway } |
            Select-Object -First 1).IPv4Address.IPAddress
    } catch { $script:LanIp = '' }
    Write-Log "role role=$($script:Role) lan_ip=$($script:LanIp)"
}

function Get-CentralUrl {   # 192.168.1.10 -> http://192.168.1.10:19001
    $url = $Central.Trim().TrimEnd('/')
    if ($url.EndsWith('/api')) { $url = $url.Substring(0, $url.Length - 4) }
    if ($url -notmatch '^https?://') { $url = "http://$url" }
    if (($url -replace '^https?://', '') -notmatch ':') { $url = "${url}:19001" }
    return $url
}

function Set-RootEnv([string]$Key, [string]$Value) {   # the value is never printed or logged
    if ($DryRun) { Write-Host "  [dry-run] .env $Key=..."; return }
    $file = Join-Path $Dir '.env'
    $lines = @()
    if (Test-Path $file) { $lines = @(Get-Content $file | Where-Object { $_ -notmatch "^$Key=" }) }
    $lines += "$Key=$Value"
    [IO.File]::WriteAllLines($file, [string[]]$lines)
    Write-Log "env_set key=$Key"
}

function Connect-Machine {
    $envFile = Join-Path $Dir '.env'
    if ($script:Role -ne 'satellite') {
        # Not (or no longer) a satellite: its Hub is the central one again.
        if ((Test-Path $envFile) -and [bool](Select-String -Path $envFile -Pattern '^HUB_UPSTREAM_URL=.+' -Quiet)) {
            Write-Log "$R machine_unlink reason=role_$($script:Role)"
            Set-RootEnv 'HUB_UPSTREAM_URL' ''; Set-RootEnv 'HUB_NODE_TOKEN' ''; Set-RootEnv 'HUB_NODE_ADDRESS' ''
        }
        return
    }
    if (-not $Join) { return }   # already linked (re-run): keep the token
    if (-not $script:LanIp) { Stop-Install (T 'I cannot find this PC''s address on the home network: connect it to Wi-Fi or cable and run again.') }
    $url = Get-CentralUrl
    Say (T 'Linking this PC to the central home ({0})...' $url)
    if ($DryRun) { Write-Host "  [dry-run] POST $url/api/nodes/join"; return }
    $name = ($env:COMPUTERNAME -replace '[^A-Za-z0-9 ._-]', '')
    $body = @{ code = ($Join -replace '[^0-9]', ''); name = $name; address = $script:LanIp } | ConvertTo-Json -Compress
    $status = 0; $token = ''
    try {
        $resp = Invoke-RestMethod -ErrorAction Stop -Method Post -Uri "$url/api/nodes/join" -ContentType 'application/json' -Body $body -TimeoutSec 15
        $status = 200; $token = [string]$resp.token
    } catch {
        if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
    }
    Write-Log "machine_join status=$status"
    if ($status -eq 0) { Stop-Install (T 'I cannot reach the central home at {0}: check that it is on and on the same network.' ${url}) }
    if ($status -eq 403) { Stop-Install (T 'the code is wrong or expired: ask the central home for a new one (System -> Machines).') }
    if ($status -ne 200) { Stop-Install (T 'the central home refused the link (error {0}).' $status) }
    if (-not $token) { Stop-Install (T 'the central home gave no link key: ask for a new code and run again.') }
    Set-RootEnv 'HUB_UPSTREAM_URL' "$url/api"
    Set-RootEnv 'HUB_NODE_TOKEN' $token
    Set-RootEnv 'HUB_NODE_ADDRESS' $script:LanIp
    $token = ''
    Ok (T 'Linked to the central home.')
}

function Get-RoleServices {   # empty = all of them
    if ($script:Role -eq 'satellite') { return $SatelliteServices }
    if ($script:Role -ne 'central' -or $DryRun) { return @() }
    Push-Location $Dir; $all = & docker compose -f docker-compose.global.yml config --services; Pop-Location
    return @($all | Where-Object { $HeavyServices -notcontains $_ })
}

# -- 7. .env files with generated secrets (python in a throwaway container: none needed on Windows) -------------
function Initialize-Env {
    $envArgs = @('--generate-secrets')
    & docker volume inspect "${Project}_hestia_archive_pgdata" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { $envArgs += '--new-db' }
    $dockerArgs = @('run', '--rm', '-v', "${Dir}:/w", '-w', '/w', 'python:3.12-slim', 'python', 'tools/init_env.py') + $envArgs
    if (Invoke-Retry (T 'Preparing the configuration') { Invoke-Step 'docker' $dockerArgs }) { return }
    Write-Log "$R env_host_python reason=container_failed"
    if ((Test-Command 'py') -and (Invoke-Step 'py' (@('-3', (Join-Path $Dir 'tools\init_env.py')) + $envArgs))) { return }
    Stop-Install (T 'I cannot prepare the configuration files (.env).')
}

# -- 8-9. images, start, health -----------------------------------------------------------------------------------
function Test-TelegramConfigured {  # the value is never read into a variable or printed
    $file = Join-Path $Dir 'Hestia-Telegram\app\.env'
    return ((Test-Path $file) -and [bool](Select-String -Path $file -Pattern '^TELEGRAM_BOT_TOKEN=.+' -Quiet))
}

function Start-Stack {
    & docker network inspect hestia_net 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0 -and -not (Invoke-Step 'docker' @('network', 'create', 'hestia_net'))) { Stop-Install (T 'I cannot create the Docker network hestia_net.') }
    $roleServices = @(Get-RoleServices)
    if ($script:VersionTag) {
        Say (T 'Downloading the ready-made modules of version {0}...' ($script:VersionTag))
        if (-not (Invoke-Retry (T 'Downloading the modules') { Invoke-ComposePull --ignore-pull-failures @roleServices })) { Note (T 'Some modules did not download: I build them here.') }
    } else {
        Say (T 'Building the modules (the first time takes a while, then it is quick)...')
        if (-not (Invoke-Retry (T 'Building the modules') { Invoke-Compose build @roleServices })) {
            $bad = @()
            $services = $roleServices
            if (-not $services.Count) { Push-Location $Dir; $services = & docker compose -f docker-compose.global.yml config --services; Pop-Location }
            foreach ($svc in $services) {
                if (Invoke-Compose build $svc) { continue }
                Write-Log "$R build_no_cache service=$svc"
                if (-not (Invoke-Compose build --no-cache $svc)) { $bad += $svc }
            }
            if ($bad.Count) { Stop-Install (T 'I cannot build: {0}. See {1}.' ($bad -join ', ') $LogFile) }
        }
    }
    Say (T 'Starting Hestia...')
    if ($script:Role -eq 'satellite') {
        # Only the satellite's own modules: everything else (memory, settings, the WebUI) lives on the central one.
        if (-not $DryRun) {
            Push-Location $Dir; $all = & docker compose -f docker-compose.global.yml config --services; Pop-Location
            $others = @($all | Where-Object { $SatelliteServices -notcontains $_ })
            if ($others.Count) { Invoke-Compose stop @others | Out-Null }
        }
        $satArgs = @('up', '-d', '--no-deps', '--remove-orphans') + $SatelliteServices
        if (-not (Invoke-Retry (T 'Starting the modules') { Invoke-Compose @satArgs })) { Stop-Install (T 'the modules do not start. See {0} or run again.' $LogFile) }
        return
    }
    if ($script:Role -eq 'central') { Invoke-Compose stop @HeavyServices | Out-Null }
    $upArgs = @('up', '-d', '--remove-orphans') + $roleServices
    if (-not $DryRun -and -not (Test-TelegramConfigured)) {
        # No bot token yet: Telegram would only crash-loop. Its container is created, not started: the guided
        # setup writes the token and starts it.
        $services = $roleServices
        if (-not $services.Count) { Push-Location $Dir; $services = & docker compose -f docker-compose.global.yml config --services; Pop-Location }
        $upArgs = @('up', '-d', '--remove-orphans') + @($services | Where-Object { $_ -ne 'telegram' })
        Note (T 'Telegram is linked in the guided setup that opens in the browser.')
    }
    if (-not (Invoke-Retry (T 'Starting the modules') { Invoke-Compose @upArgs })) { Stop-Install (T 'the modules do not start. See {0} or run again.' $LogFile) }
    if (-not $DryRun -and -not (Test-TelegramConfigured)) { Invoke-Compose create telegram | Out-Null }
}

function Wait-Healthy {
    if ($DryRun) { return }
    Say (T 'Waiting for every module to answer...')
    $waited = 0
    while ($true) {
        try { if ((Invoke-WebRequest -ErrorAction Stop "$HubUrl/health" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) { break } } catch { }
        if ($waited -ge 300) { Stop-Install (T 'the heart of Hestia (Hub) does not answer after 5 minutes.') }
        Start-Sleep -Seconds 5; $waited += 5
    }
    $waited = 0
    while ($true) {
        $down = @(& docker ps -a --filter 'name=hestia_' --format '{{.Names}} {{.Status}}' | Where-Object { $_ -notmatch ' (Up|Created)' } | ForEach-Object { ($_ -split ' ')[0] } |
            Where-Object {   # the containers this machine's role keeps stopped on purpose
                $svc = $_ -replace '^hestia_', ''
                if ($script:Role -eq 'satellite') { $SatelliteServices -contains $svc } elseif ($script:Role -eq 'central') { $HeavyServices -notcontains $svc } else { $true }
            })
        $webui = ($script:Role -eq 'satellite')
        if (-not $webui) { try { $webui = ((Invoke-WebRequest -ErrorAction Stop $WebUiUrl -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) } catch { } }
        if (-not $down.Count -and $webui) { Ok (T 'Every module is on.'); return }
        if ($waited -ge 600) {
            foreach ($c in $down) { Write-Log "container_down name=$c"; & docker logs --tail 20 $c 2>&1 | ForEach-Object { Write-Log "  | $_" } }
            Note (T 'These modules did not start: {0} (last lines in {1}). Hestia works without them anyway.' ($down -join ', ') $LogFile)
            return
        }
        Start-Sleep -Seconds 10; $waited += 10
    }
}

# -- 10. browser + shortcut ---------------------------------------------------------------------------------------
function Complete-Install {
    if ($script:Role -eq 'satellite') {
        Write-Host ''
        Ok (T 'This PC is a satellite of {0}: voice and training run here.' (Get-CentralUrl))
        Write-Host (Expand-Text (T '         You manage it from the central home: System -> Machines (also <<Use its graphics card>>).'))
        foreach ($n in $script:Notes) { Write-Host (Expand-Text "         - $n") }
        Write-Log "install_done role=satellite notes=$($script:Notes.Count)"
        return
    }
    if (-not $DryRun) {
        $desktop = [Environment]::GetFolderPath('Desktop')
        Set-Content -Path (Join-Path $desktop 'Hestia.url') -Value "[InternetShortcut]`r`nURL=$WebUiUrl" -Encoding ASCII
        if (-not $NoBrowser) { Start-Process $SetupUrl | Out-Null }
    }
    Write-Host ''
    Ok (T 'Hestia is ready: {0} (the guided setup is at {1})' $WebUiUrl $SetupUrl)
    foreach ($n in $script:Notes) { Write-Host (Expand-Text "         - $n") }
    Write-Host (T '         To update or repair: run this same command again (or Install-Hestia.cmd).')
    Write-Log "install_done version=$(if ($script:VersionTag) { $script:VersionTag } else { 'dev' }) notes=$($script:Notes.Count)"
}

# -- uninstall ----------------------------------------------------------------------------------------------------
function Remove-Hestia {
    if (-not (Test-Path (Join-Path $Dir 'docker-compose.global.yml'))) { Stop-Install (T 'I cannot find Hestia in {0} (use -Dir).' $Dir) }
    if (-not (Test-Docker)) { Stop-Install (T 'Docker does not answer: start Docker Desktop and run again.') }
    if ($Purge) {
        Say (T 'WARNING: I delete Hestia AND ALL ITS DATA (memories, chats, settings). There is no way back.')
        $word = T 'DELETE'
        $typed = if (Test-Interactive) { Read-Host (T '[Hestia] Type {0} to confirm' $word) } else { '' }
        if ($typed -cne $word) { Stop-Install (T 'I deleted nothing (no confirmation).') }
        Invoke-Compose down -v --remove-orphans | Out-Null
        if (-not $DryRun) { Remove-Item $Dir -Recurse -Force; Remove-Item $StateDir -Recurse -Force -ErrorAction SilentlyContinue }
        Ok (T 'Hestia and its data have been deleted.')
    } else {
        Invoke-Compose down --remove-orphans | Out-Null
        Ok (T 'Hestia is off and the containers removed. The data stay (folder {0} and Docker volumes); -Purge to delete them.' $Dir)
    }
}

# -- main ---------------------------------------------------------------------------------------------------------
Write-Log "install_start uninstall=$([bool]$Uninstall) channel=$Channel dry_run=$([bool]$DryRun) resume=$([bool]$Resume)"
if ($Uninstall) { Remove-Hestia; exit 0 }
if ($Resume) { Say (T 'Resuming the install after the restart...') }
Say (T 'Installing Hestia in {0} (channel {1}).' $Dir $Channel)
Test-Preflight
Resolve-Role
Install-GitIfMissing;    Set-StepDone 'git'
Install-DockerIfMissing; Set-StepDone 'docker'
Test-Ports
Install-OllamaIfMissing; Set-StepDone 'ollama'
Get-Code;                Set-StepDone 'code'
Write-Hardware
Initialize-Env;          Set-StepDone 'env'
Connect-Machine
Start-Stack;             Set-StepDone 'started'
Wait-Healthy;            Set-StepDone 'healthy'
Complete-Install
