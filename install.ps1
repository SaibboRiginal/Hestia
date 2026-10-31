# Hestia installer for Windows 10/11 (PowerShell 5.1+). Double-click Installa-Hestia.cmd, or in PowerShell:
#   irm https://raw.githubusercontent.com/SaibboRiginal/Hestia/main/install.ps1 | iex
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/SaibboRiginal/Hestia/main/install.ps1))) -Dir D:\Hestia
#
# Every step checks before acting, retries (2/4/8 s), has a fallback, and records where it got to: running it again
# resumes or repairs (also by itself after the WSL2 reboot). When it truly cannot go on it stops with one sentence
# saying what to do. It never prints or logs secrets, never overwrites an existing .env value, never deletes data
# without -Purge. Windows asks for administrator confirmation only for WSL2 and Docker Desktop.
# ASCII only on purpose: PowerShell 5.1 reads a BOM-less file as ANSI, and a BOM breaks `irm | iex`. Accented letters
# in messages are written ~e ~a ~o ~u ~i ~E (e/a/o/u/i with grave accent, e acute) and << >> (Italian quotes);
# Expand-Text turns them back at print time.
# SPEC: docs/work/2026-10-30-setup-un-click
[CmdletBinding()]
param(
    [string]$Dir = (Join-Path $env:USERPROFILE 'Hestia'),
    [ValidateSet('stabile', 'novita')][string]$Channel = 'stabile',
    [switch]$Update,
    [switch]$Repair,
    [switch]$Uninstall,
    [switch]$Purge,
    [switch]$DryRun,
    [switch]$NoBrowser,
    [switch]$Resume
)

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
$SetupUrl   = "$WebUiUrl/benvenuto"
$HubUrl     = 'http://localhost:19001'
$Project    = 'hestia'
$StateDir   = Join-Path $env:LOCALAPPDATA 'Hestia\install'
$LogFile    = Join-Path $StateDir 'install.log'
$SavedScript = Join-Path $StateDir 'install.ps1'
$script:Notes = New-Object System.Collections.Generic.List[string]
$script:VersionTag = ''
$script:RamGb = 0
$script:FreeGb = 0

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
    Write-Host (Expand-Text "[Hestia] Mi sono fermato: $Reason") -ForegroundColor Red
    Write-Host '         Rilancia lo stesso comando quando hai fatto: riprendo da qui.'
    Write-Host "         Dettagli: $LogFile"
    Write-Log "install_failed reason=`"$Reason`""
    if (Test-Interactive) { Read-Host 'Premi Invio per chiudere' | Out-Null }
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
            Say "${What}: non ~e andata, riprovo tra ${delay}s..."
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

# -- 0. preflight -------------------------------------------------------------------------------------------------
function Test-Preflight {
    Say 'Controllo il computer...'
    $ramGb = [math]::Floor((Get-CimInstance -ErrorAction Stop Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
    $drive = (Split-Path -Qualifier $Dir).TrimEnd(':')
    $freeGb = [math]::Floor((Get-PSDrive -ErrorAction Stop $drive).Free / 1GB)
    $script:RamGb = $ramGb; $script:FreeGb = $freeGb
    Write-Log "preflight ram_gb=$ramGb free_gb=$freeGb"
    if ($ramGb -lt 8) { Note "Hai $ramGb GB di RAM: Hestia funziona, ma per i modelli locali ne servono almeno 16. Usa i modelli nel cloud." }
    if ($freeGb -lt 20) { Stop-Install "servono almeno 20 GB liberi (meglio 30) sul disco ${drive}:, ce ne sono $freeGb. Libera spazio." }
    if ($freeGb -lt 30) { Note "Spazio libero: $freeGb GB. Basta per Hestia; per i modelli locali grandi potrebbe non bastare." }
    $probe = "$($RepoUrl -replace '\.git$', '').git/info/refs?service=git-upload-pack"
    $online = Invoke-Retry 'Connessione a internet' { (Invoke-WebRequest -ErrorAction Stop -Uri $probe -UseBasicParsing -TimeoutSec 15).StatusCode -eq 200 }
    if (-not $online) { Stop-Install 'non riesco a raggiungere github.com: controlla la connessione a internet.' }
    $cpu = Get-CimInstance -ErrorAction Stop Win32_Processor | Select-Object -First 1
    $hyperv = (Get-CimInstance -ErrorAction Stop Win32_ComputerSystem).HypervisorPresent
    if (-not $hyperv -and -not $cpu.VirtualizationFirmwareEnabled) {
        Stop-Install "la virtualizzazione ~e spenta nel BIOS/UEFI: riavvia, entra nel BIOS e attiva <<Intel VT-x>> o <<AMD-V / SVM>>, poi rilancia."
    }
}

function Test-Ports {
    if ((Test-Docker) -and ((& docker ps --format '{{.Names}}' 2>$null) -contains 'hestia_hub')) { return }
    $busy = @()
    foreach ($port in 19001, 19002, 19015, 5432) {
        if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) { $busy += $port }
    }
    if ($busy.Count) { Stop-Install "queste porte sono gi~a occupate da un altro programma: $($busy -join ', '). Chiudilo e rilancia." }
}

# -- 1. git -------------------------------------------------------------------------------------------------------
function Install-GitIfMissing {
    if (Test-Command 'git') { return }
    Say 'Installo git...'
    if (-not (Invoke-Retry 'Installazione di git' { Install-Winget 'Git.Git' })) {
        Note 'git non si ~e installato: scarico Hestia come archivio (gli aggiornamenti useranno git quando ci sar~a).'
    }
}

# -- 2-3. WSL2 + Docker Desktop -----------------------------------------------------------------------------------
function Register-Resume {
    if ($DryRun) { return }
    if ($PSCommandPath -and (Test-Path $PSCommandPath)) { Copy-Item -ErrorAction Stop $PSCommandPath $SavedScript -Force }
    else { try { Get-File $ScriptUrl $SavedScript | Out-Null } catch { Write-Log "$R resume_download_failed" } }
    $cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$SavedScript`" -Resume -Dir `"$Dir`" -Channel $Channel"
    Set-ItemProperty -ErrorAction Stop -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce' -Name 'HestiaInstall' -Value $cmd
    Write-Log 'resume_registered'
}

function Install-Wsl {
    $ready = $false
    try { & wsl.exe --status 2>&1 | Out-Null; $ready = ($LASTEXITCODE -eq 0) } catch { }
    if ($ready -or (Test-StepDone 'wsl')) { return }
    Say 'Attivo WSL2 (serve a Docker). Windows ti chiede conferma di amministratore.'
    $ok = Invoke-Retry 'Attivazione di WSL2' { Invoke-Step 'wsl.exe' @('--install', '--no-distribution') -Elevated }
    if (-not $ok) { Stop-Install "WSL2 non si attiva. Apri PowerShell come amministratore, lancia <<wsl --install>> e rilancia." }
    Set-StepDone 'wsl'
    Register-Resume
    Say 'Per finire WSL2 serve un riavvio. Dopo il riavvio l''installazione riparte da sola.'
    $answer = if (Test-Interactive) { Read-Host '[Hestia] Riavvio adesso? [S/n]' } else { 'n' }
    if ($answer -notmatch '^[nN]') { if (-not $DryRun) { Restart-Computer -Force } }
    exit 0
}

function Install-DockerIfMissing {
    Update-PathFromRegistry
    if (Test-Docker) { return }
    $exe = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path $exe)) {
        Install-Wsl
        Say 'Installo Docker Desktop (qualche minuto). Windows ti chiede conferma di amministratore.'
        $ok = Invoke-Retry 'Installazione di Docker Desktop' { Install-Winget 'Docker.DockerDesktop' 'install --quiet --accept-license' }
        if (-not $ok) {
            Write-Log "$R docker_fallback via=direct_installer"
            $installer = Join-Path $env:TEMP 'DockerDesktopInstaller.exe'
            $ok = (Invoke-Retry 'Download di Docker Desktop' { Get-File $DockerUrl $installer }) -and
                  (Invoke-Step $installer @('install', '--quiet', '--accept-license') -Elevated)
        }
        if (-not $ok) { Stop-Install 'Docker Desktop non si installa: scaricalo da https://docker.com/products/docker-desktop, installalo e rilancia.' }
        Update-PathFromRegistry
        Note 'Docker Desktop parte da solo quando accendi il computer: lascialo cos~i, Hestia si riaccende con lui.'
    }
    if ($DryRun) { return }
    Say 'Avvio Docker Desktop: se ~e la prima volta, accetta le condizioni nella sua finestra.'
    Start-Process $exe | Out-Null
    $waited = 0
    while (-not (Test-Docker)) {
        if ($waited -ge 300) { Stop-Install 'Docker Desktop non risponde: aprilo, aspetta che dica <<Engine running>> e rilancia. Se chiede di uscire e rientrare in Windows, fallo.' }
        Start-Sleep -Seconds 5; $waited += 5
        if ($waited % 30 -eq 0) { Say "...aspetto ancora Docker ($waited s)" }
    }
    if (-not ((& docker compose version 2>$null) -match 'version')) { Stop-Install 'manca <<docker compose>>: aggiorna Docker Desktop e rilancia.' }
}

# -- 5. Ollama (native: uses the GPU without extra setup) --------------------------------------------------------
function Test-Ollama { try { return ((Invoke-WebRequest -ErrorAction Stop 'http://127.0.0.1:11434/api/version' -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) } catch { return $false } }

function Install-OllamaIfMissing {
    Update-PathFromRegistry
    if ((Test-Command 'ollama') -or (Test-Ollama)) { if (-not (Test-Ollama)) { Start-OllamaApp }; Get-DefaultModels; return }
    Say 'Installo Ollama (i modelli sul tuo computer)...'
    $ok = Invoke-Retry 'Installazione di Ollama' { Install-Winget 'Ollama.Ollama' }
    if (-not $ok) {
        Write-Log "$R ollama_fallback via=direct_installer"
        $installer = Join-Path $env:TEMP 'OllamaSetup.exe'
        $ok = (Invoke-Retry 'Download di Ollama' { Get-File $OllamaUrl $installer }) -and (Invoke-Step $installer @('/VERYSILENT', '/NORESTART'))
    }
    if (-not $ok) { Note 'Ollama non si ~e installato: Hestia user~a i modelli nel cloud. Puoi installarlo dopo da https://ollama.com.'; return }
    Start-OllamaApp
    Get-DefaultModels
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
        Say "Scarico il modello $model (una volta sola)..."
        if (-not (Invoke-Retry "Download di $model" { Invoke-Step 'ollama' @('pull', $model) })) {
            Note "Il modello $model non si ~e scaricato: rilancia pi~u tardi, nel frattempo Hestia usa il cloud se hai una chiave."
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
        if ($origin -notmatch 'hestia') { Stop-Install "$Dir esiste ma non ~e Hestia. Scegli un'altra cartella con -Dir." }
        if (-not (Invoke-Retry 'Aggiornamento del codice' { Invoke-Step 'git' @('-C', $Dir, 'fetch', '--tags', '--prune', 'origin') })) {
            Note 'Non ho potuto scaricare le novit~a del codice: uso la versione che c''~e.'
        }
    } elseif (Test-Path (Join-Path $Dir 'docker-compose.global.yml')) {
        Write-Log "code_existing_without_git dir=$Dir"
    } elseif ((Test-Path $Dir) -and (Get-ChildItem $Dir -Force | Select-Object -First 1)) {
        Stop-Install "$Dir esiste e non ~e vuota. Scegli un'altra cartella con -Dir."
    } else {
        Say "Scarico Hestia in $Dir..."
        if (Test-Command 'git') {
            $ok = Invoke-Retry 'Download di Hestia' { Invoke-Step 'git' @('clone', '--quiet', '-c', 'core.autocrlf=false', $RepoUrl, $Dir) }
        } else {
            Write-Log "$R code_zip reason=no_git"
            $zip = Join-Path $env:TEMP 'hestia-main.zip'
            $ok = Invoke-Retry 'Download di Hestia' { Get-File $ZipUrl $zip }
            if ($ok -and -not $DryRun) {
                $tmp = Join-Path $env:TEMP 'hestia-main'
                Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
                Expand-Archive -ErrorAction Stop $zip $tmp -Force
                Move-Item -ErrorAction Stop (Get-ChildItem $tmp | Select-Object -First 1).FullName $Dir
            }
        }
        if (-not $ok) { Stop-Install 'non riesco a scaricare Hestia da GitHub. Controlla la connessione.' }
    }
    Select-Version
}

function Select-Version {
    $script:VersionTag = ''
    if (-not (Test-Path (Join-Path $Dir '.git'))) { return }
    if (& git -C $Dir status --porcelain --untracked-files=no 2>$null) {
        Note 'Nella cartella di Hestia ci sono modifiche locali: non ho cambiato versione del codice.'
        $script:VersionTag = [string](& git -C $Dir describe --tags --exact-match 2>$null)
        return
    }
    if ($Channel -eq 'stabile') {
        $tag = & git -C $Dir tag -l 'v*.*.*' --sort=-v:refname | Select-Object -First 1
        if ($tag) {
            Invoke-Step 'git' @('-C', $Dir, '-c', 'advice.detachedHead=false', 'checkout', '--quiet', $tag) | Out-Null
            $script:VersionTag = $tag
            Ok "Versione $tag"
            return
        }
        Note 'Non c''~e ancora una versione pubblicata: installo l''ultima di sviluppo e la costruisco qui (pi~u lento, una volta sola).'
    }
    $branch = & git -C $Dir rev-parse --abbrev-ref HEAD
    if ($branch -eq 'HEAD') { Invoke-Step 'git' @('-C', $Dir, 'checkout', '--quiet', 'main') | Out-Null; $branch = 'main' }
    if (-not (Invoke-Step 'git' @('-C', $Dir, 'pull', '--quiet', '--ff-only', 'origin', $branch))) {
        Note 'Il codice locale non segue pi~u quello di GitHub: l''ho lasciato com''~e.'
    }
}

# What the guided setup shows (<<Scheda video da 16 GB>>) and uses to suggest models: git-ignored, no personal data.
function Write-Hardware {
    if ($DryRun) { return }
    $gpu = ''; $vram = 0
    if (Test-Command 'nvidia-smi') {
        $line = (& nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>$null | Select-Object -First 1)
        if ($line -match '^(.+),\s*(\d+)\s*$') { $gpu = $Matches[1].Trim(); $vram = [math]::Floor([int]$Matches[2] / 1024) }
    }
    $dirInfo = Join-Path $Dir '.hestia-install'
    New-Item -ItemType Directory -Force -Path $dirInfo | Out-Null
    $json = @{ os = 'windows'; ram_gb = $script:RamGb; free_gb = $script:FreeGb; gpu = $gpu; vram_gb = $vram } | ConvertTo-Json -Compress
    Set-Content -Path (Join-Path $dirInfo 'hardware.json') -Value $json -Encoding ASCII
    Write-Log "hardware gpu=`"$gpu`" vram_gb=$vram"
}

# -- 7. .env files with generated secrets (python in a throwaway container: none needed on Windows) -------------
function Initialize-Env {
    $envArgs = @('--generate-secrets')
    & docker volume inspect "${Project}_hestia_archive_pgdata" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { $envArgs += '--new-db' }
    $dockerArgs = @('run', '--rm', '-v', "${Dir}:/w", '-w', '/w', 'python:3.12-slim', 'python', 'tools/init_env.py') + $envArgs
    if (Invoke-Retry 'Preparazione della configurazione' { Invoke-Step 'docker' $dockerArgs }) { return }
    Write-Log "$R env_host_python reason=container_failed"
    if ((Test-Command 'py') -and (Invoke-Step 'py' (@('-3', (Join-Path $Dir 'tools\init_env.py')) + $envArgs))) { return }
    Stop-Install 'non riesco a preparare i file di configurazione (.env).'
}

# -- 8-9. images, start, health -----------------------------------------------------------------------------------
function Test-TelegramConfigured {  # the value is never read into a variable or printed
    $file = Join-Path $Dir 'Hestia-Telegram\app\.env'
    return ((Test-Path $file) -and [bool](Select-String -Path $file -Pattern '^TELEGRAM_BOT_TOKEN=.+' -Quiet))
}

function Start-Stack {
    & docker network inspect hestia_net 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0 -and -not (Invoke-Step 'docker' @('network', 'create', 'hestia_net'))) { Stop-Install 'non riesco a creare la rete Docker hestia_net.' }
    if ($script:VersionTag) {
        Say "Scarico i moduli pronti della versione $($script:VersionTag)..."
        if (-not (Invoke-Retry 'Download dei moduli' { Invoke-Compose pull --ignore-pull-failures })) { Note 'Alcuni moduli non si sono scaricati: li costruisco qui.' }
    } else {
        Say 'Costruisco i moduli (la prima volta ci vuole un po'', poi ~e veloce)...'
        if (-not (Invoke-Retry 'Costruzione dei moduli' { Invoke-Compose build })) {
            $bad = @()
            Push-Location $Dir; $services = & docker compose -f docker-compose.global.yml config --services; Pop-Location
            foreach ($svc in $services) {
                if (Invoke-Compose build $svc) { continue }
                Write-Log "$R build_no_cache service=$svc"
                if (-not (Invoke-Compose build --no-cache $svc)) { $bad += $svc }
            }
            if ($bad.Count) { Stop-Install "non riesco a costruire: $($bad -join ', '). Guarda $LogFile." }
        }
    }
    Say 'Avvio Hestia...'
    $upArgs = @('up', '-d', '--remove-orphans')
    if (-not $DryRun -and -not (Test-TelegramConfigured)) {
        # No bot token yet: Telegram would only crash-loop. Its container is created, not started: the guided
        # setup writes the token and starts it.
        Push-Location $Dir; $services = & docker compose -f docker-compose.global.yml config --services; Pop-Location
        $upArgs += ($services | Where-Object { $_ -ne 'telegram' })
        Note 'Telegram si collega nel setup guidato che si apre nel browser.'
    }
    if (-not (Invoke-Retry 'Avvio dei moduli' { Invoke-Compose @upArgs })) { Stop-Install "i moduli non partono. Guarda $LogFile o rilancia." }
    if (-not $DryRun -and -not (Test-TelegramConfigured)) { Invoke-Compose create telegram | Out-Null }
}

function Wait-Healthy {
    if ($DryRun) { return }
    Say 'Aspetto che tutti i moduli rispondano...'
    $waited = 0
    while ($true) {
        try { if ((Invoke-WebRequest -ErrorAction Stop "$HubUrl/health" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) { break } } catch { }
        if ($waited -ge 300) { Stop-Install 'il centro di Hestia (Hub) non risponde dopo 5 minuti.' }
        Start-Sleep -Seconds 5; $waited += 5
    }
    $waited = 0
    while ($true) {
        $down = @(& docker ps -a --filter 'name=hestia_' --format '{{.Names}} {{.Status}}' | Where-Object { $_ -notmatch ' (Up|Created)' } | ForEach-Object { ($_ -split ' ')[0] })
        $webui = $false
        try { $webui = ((Invoke-WebRequest -ErrorAction Stop $WebUiUrl -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) } catch { }
        if (-not $down.Count -and $webui) { Ok 'Tutti i moduli sono accesi.'; return }
        if ($waited -ge 600) {
            foreach ($c in $down) { Write-Log "container_down name=$c"; & docker logs --tail 20 $c 2>&1 | ForEach-Object { Write-Log "  | $_" } }
            Note "Questi moduli non sono partiti: $($down -join ', ') (ultime righe in $LogFile). Hestia funziona lo stesso senza di loro."
            return
        }
        Start-Sleep -Seconds 10; $waited += 10
    }
}

# -- 10. browser + shortcut ---------------------------------------------------------------------------------------
function Complete-Install {
    if (-not $DryRun) {
        $desktop = [Environment]::GetFolderPath('Desktop')
        Set-Content -Path (Join-Path $desktop 'Hestia.url') -Value "[InternetShortcut]`r`nURL=$WebUiUrl" -Encoding ASCII
        if (-not $NoBrowser) { Start-Process $SetupUrl | Out-Null }
    }
    Write-Host ''
    Ok "Hestia ~e pronta: $WebUiUrl (il setup guidato ~e su $SetupUrl)"
    foreach ($n in $script:Notes) { Write-Host (Expand-Text "         - $n") }
    Write-Host '         Per aggiornare o riparare: rilancia questo stesso comando (o Installa-Hestia.cmd).'
    Write-Log "install_done version=$(if ($script:VersionTag) { $script:VersionTag } else { 'dev' }) notes=$($script:Notes.Count)"
}

# -- uninstall ----------------------------------------------------------------------------------------------------
function Remove-Hestia {
    if (-not (Test-Path (Join-Path $Dir 'docker-compose.global.yml'))) { Stop-Install "non trovo Hestia in $Dir (usa -Dir)." }
    if (-not (Test-Docker)) { Stop-Install 'Docker non risponde: avvia Docker Desktop e rilancia.' }
    if ($Purge) {
        Say 'ATTENZIONE: cancello Hestia E TUTTI I SUOI DATI (memorie, chat, impostazioni). Non si torna indietro.'
        $typed = if (Test-Interactive) { Read-Host '[Hestia] Scrivi CANCELLA per confermare' } else { '' }
        if ($typed -cne 'CANCELLA') { Stop-Install 'non ho cancellato niente (conferma non data).' }
        Invoke-Compose down -v --remove-orphans | Out-Null
        if (-not $DryRun) { Remove-Item $Dir -Recurse -Force; Remove-Item $StateDir -Recurse -Force -ErrorAction SilentlyContinue }
        Ok 'Hestia e i suoi dati sono stati cancellati.'
    } else {
        Invoke-Compose down --remove-orphans | Out-Null
        Ok "Hestia ~e spenta e i container rimossi. I dati restano (cartella $Dir e volumi Docker); -Purge per cancellarli."
    }
}

# -- main ---------------------------------------------------------------------------------------------------------
Write-Log "install_start uninstall=$([bool]$Uninstall) channel=$Channel dry_run=$([bool]$DryRun) resume=$([bool]$Resume)"
if ($Uninstall) { Remove-Hestia; exit 0 }
if ($Resume) { Say 'Riprendo l''installazione dopo il riavvio...' }
Say "Installo Hestia in $Dir (canale $Channel)."
Test-Preflight
Install-GitIfMissing;    Set-StepDone 'git'
Install-DockerIfMissing; Set-StepDone 'docker'
Test-Ports
Install-OllamaIfMissing; Set-StepDone 'ollama'
Get-Code;                Set-StepDone 'code'
Write-Hardware
Initialize-Env;          Set-StepDone 'env'
Start-Stack;             Set-StepDone 'started'
Wait-Healthy;            Set-StepDone 'healthy'
Complete-Install
