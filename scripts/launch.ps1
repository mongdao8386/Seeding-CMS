# Bat/tat toan bo he thong bang mot lan bam.
#
# Truoc day: mo Docker Desktop, doi, roi ba cua so terminal go ba lenh khac nhau, roi
# tu mo trinh duyet. Bon buoc de quen mot, va quen buoc nao cung ra mot loi khac nhau
# ma khong lien quan gi den nguyen nhan that.
#
# Script nay lam dung thu tu do va DUNG LAI khi mot buoc hong, thay vi chay tiep. Bat
# API len khi Postgres chua song thi loi bao ra la "connection refused" o mot cho cach
# nguyen nhan that ba tang.
#
# Ba cua so terminal van con - co y. Log cua API, worker va dashboard la ba dong khac
# nhau, tron vao mot cua so thi luc co su co khong doc duoc gi.

[CmdletBinding()]
param(
    # Tat thay vi bat.
    [switch]$Stop,
    # Chay dashboard o che do dev (hot reload). Cham hon, dung khi dang sua giao dien.
    [switch]$Dev,
    # Bat lai tu dau: dung het roi bat.
    [switch]$Restart
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $root '.venv\Scripts\python.exe'

$API_PORT = 8000
$WEB_PORT = 3000
# Signer ky X-Bogus/X-Gnarly cho buoc dang bai TikTok (tools	iktok-signer).
$SIGNER_PORT = 8080

# ------------------------------------------------------------------ tien ich

function Say($text)  { Write-Host "  $text" }
function Step($text) { Write-Host ""; Write-Host "> $text" -ForegroundColor Cyan }
function Ok($text)   { Write-Host "  OK  $text" -ForegroundColor Green }
function Warn($text) { Write-Host "  !   $text" -ForegroundColor Yellow }

# Goi mot chuong trinh ngoai (docker, npm, alembic).
#
# PowerShell 5.1 co mot bay rieng: khi $ErrorActionPreference = 'Stop', moi dong ma
# chuong trinh ngoai ghi ra stderr deu bi boc thanh ErrorRecord va NEM ra nhu loi that.
# Docker ghi tien do ("Container ... Starting") ra stderr, npm ghi canh bao ra stderr -
# nen ca hai deu lam script chet giua chung du chung chay dung.
#
# Vi vay o day ha ve 'Continue' va chi tin vao MA THOAT, la thu duy nhat noi that.
function Native {
    param(
        [Parameter(Mandatory)][string]$Exe,
        [string[]]$Arguments = @(),
        # Nuot dau ra. Van giu lai de in khi that bai.
        [switch]$Quiet
    )
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $Exe @Arguments 2>&1
        $code = $LASTEXITCODE
        if (-not $Quiet -or $code -ne 0) {
            $output | ForEach-Object { Write-Host "      $_" -ForegroundColor DarkGray }
        }
        return $code
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Die($text, $fix) {
    Write-Host ""
    Write-Host "  DUNG LAI: $text" -ForegroundColor Red
    if ($fix) {
        Write-Host ""
        Write-Host "  Cach sua:" -ForegroundColor Yellow
        foreach ($line in $fix) { Write-Host "    $line" }
    }
    Write-Host ""
    Write-Host "  Nhan Enter de dong..."
    [void](Read-Host)
    exit 1
}

# Nhan dang cua so cua he thong nay. Dat trong dong lenh cua cmd.exe nen tim lai duoc
# ma khong phai nho PID qua cac lan chay.
$WINDOW_TAG = 'title Seeding - '


function KillTree($processId) {
    # Giet ca cay tien trinh.
    #
    # Windows KHONG tu giet tien trinh con khi cha chet. Chi Stop-Process cai cmd.exe thi
    # uvicorn / node ben trong van song va van giu cong - roi lan bat sau bao "da chay
    # san" trong khi cua so da bien mat.
    & taskkill /PID $processId /T /F 2>&1 | Out-Null
}


function SeedingWindows {
    Get-CimInstance Win32_Process -Filter "Name = 'cmd.exe'" |
        Where-Object { $_.CommandLine -like "*$WINDOW_TAG*" }
}


function IsOrphan($processId) {
    # Cua so con do nhung tien trinh ben trong da chet.
    #
    # conhost.exe khong tinh: no la cai khung console, luon di kem moi cua so cmd va
    # khong noi len dieu gi ve viec ben trong con chay hay khong.
    $kids = @(
        Get-CimInstance Win32_Process -Filter "ParentProcessId = $processId" |
            Where-Object { $_.Name -ne 'conhost.exe' }
    )
    return $kids.Count -eq 0
}


function CloseOrphanWindows {
    # Don nhung cua so rong con sot lai tu cac lan chay truoc.
    #
    # Cua so mo bang /k de khi tien trinh sap thi loi con doc duoc - do la co y. Nhung
    # neu khong ai don, moi lan bat/tat lai de lai mot cai vo rong, va sau muoi lan thi
    # thanh tac vu day nhung cua so giong het nhau ma khong cai nao chay gi.
    $orphans = @(SeedingWindows | Where-Object { IsOrphan $_.ProcessId })
    foreach ($o in $orphans) { KillTree $o.ProcessId }
    if ($orphans.Count) {
        Say "don $($orphans.Count) cua so rong tu lan chay truoc"
    }
}


function PortOwner($port) {
    try {
        $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop
        return ($conn | Select-Object -First 1).OwningProcess
    } catch {
        return $null
    }
}

function WaitFor($what, $seconds, $probe) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if (& $probe) {
            Ok $what
            return $true
        }
        Start-Sleep -Milliseconds 700
    }
    return $false
}

# Doc mot khoa tu .env. Khong dung dotenv de script chay duoc ca khi venv chua san sang.
function EnvValue($name) {
    $path = Join-Path $root '.env'
    if (-not (Test-Path $path)) { return $null }
    foreach ($line in (Get-Content $path)) {
        if ($line -match "^\s*$name\s*=\s*(.*)$") {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return $null
}

# --------------------------------------------------------------------- TAT

function StopEverything {
    Step "Dung cac tien trinh"

    # Dong tu CUA SO tro xuong, khong phai tu cong tro len.
    #
    # Ban dau ham nay giet tien trinh dang giu cong 8000/3000. No dung nhung khong du:
    # cua so cmd boc ngoai khong chet theo, va no o lai nhu mot cai vo rong. Sau muoi
    # lan bat/tat, thanh tac vu day nhung cua so "Seeding - API" giong het nhau ma
    # khong cai nao chay gi.
    $windows = @(SeedingWindows)
    foreach ($w in $windows) { KillTree $w.ProcessId }
    if ($windows.Count) {
        Ok "dong $($windows.Count) cua so (ke ca tien trinh ben trong)"
    } else {
        Say "khong co cua so nao cua he thong dang mo"
    }

    # Cac tien trinh chay ngoai launcher - vd ban tu go lenh trong terminal rieng.
    foreach ($item in @(@{ Name = 'API'; Port = $API_PORT }, @{ Name = 'Dashboard'; Port = $WEB_PORT }, @{ Name = 'Signer'; Port = $SIGNER_PORT })) {
        $owner = PortOwner $item.Port
        if ($owner) {
            KillTree $owner
            Ok "$($item.Name) (cong $($item.Port)) da dung"
        }
    }

    $workers = @(
        Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
            Where-Object { $_.CommandLine -like '*WorkerSettings*' }
    )
    foreach ($w in $workers) { KillTree $w.ProcessId }
    if ($workers.Count) { Ok "worker da dung" }

    Step "Dung Postgres va Redis"
    # `stop` chu khong phai `down`: `down` xoa container, va mot lan go nham -v la mat
    # sach database. Du lieu o day la cookie jar cua tung tai khoan.
    Push-Location $root
    $code = Native docker @('compose', 'stop') -Quiet
    Pop-Location
    if ($code -eq 0) {
        Ok "container da dung (du lieu con nguyen)"
    } else {
        Warn "Docker khong phan hoi - co the no da tat san"
    }
}

if ($Stop) {
    Write-Host ""
    Write-Host "  Seeding CMS - tat" -ForegroundColor White
    StopEverything
    Write-Host ""
    Write-Host "  Xong." -ForegroundColor Green
    Start-Sleep -Seconds 2
    exit 0
}

if ($Restart) { StopEverything; Start-Sleep -Seconds 2 }

# --------------------------------------------------------------------- BAT

Write-Host ""
Write-Host "  Seeding CMS" -ForegroundColor White
Write-Host "  $root"

# --- 1. Kiem tra truoc khi dung den bat ky thu gi ---------------------------

Step "Kiem tra cai dat"

if (-not (Test-Path $venvPython)) {
    Die "Khong thay moi truong Python o .venv" @(
        'py -3.14 -m venv .venv',
        '.\.venv\Scripts\pip install -e ".[dev]"'
    )
}
Ok "Python"

if (-not (Test-Path (Join-Path $root '.env'))) {
    Die "Khong co file .env" @(
        'Copy-Item .env.example .env',
        '.\.venv\Scripts\python scripts\gen_vault_key.py',
        '.\.venv\Scripts\python scripts\gen_api_token.py',
        'roi dan hai gia tri do vao .env'
    )
}

$token = EnvValue 'API_TOKEN'
$vault = EnvValue 'VAULT_KEY'

if (-not $vault) {
    Die "VAULT_KEY trong .env dang rong" @(
        '.\.venv\Scripts\python scripts\gen_vault_key.py',
        '',
        'Khoa nay ma hoa toan bo cookie jar. Sinh khoa moi khi da co tai khoan',
        'dang chay nghia la MAT HET phien dang nhap, khong khoi phuc duoc.'
    )
}
Ok "VAULT_KEY"

if (-not $token) {
    Die "API_TOKEN trong .env dang rong - API se tu choi moi request" @(
        '.\.venv\Scripts\python scripts\gen_api_token.py'
    )
}
Ok "API_TOKEN"

if (-not (Test-Path (Join-Path $root 'web\node_modules'))) {
    Step "Cai phu thuoc cho dashboard (lan dau, vai phut)"
    Push-Location (Join-Path $root 'web')
    $installCode = Native 'npm.cmd' @('install')
    Pop-Location
    if ($installCode -ne 0) {
        Die "npm install that bai" @('Kiem tra da cai Node.js chua: node --version')
    }
    Ok "node_modules"
} else {
    Ok "node_modules"
}

$webEnv = Join-Path $root 'web\.env.local'
if (-not (Test-Path $webEnv)) {
    $sample = Join-Path $root 'web\.env.local.example'
    if (Test-Path $sample) {
        Copy-Item $sample $webEnv
        Ok "tao web\.env.local tu file mau"
    }
}

# --- 2. Docker ---------------------------------------------------------------

Step "Postgres va Redis"

$dockerOk = (Native docker @('info') -Quiet) -eq 0

if (-not $dockerOk) {
    Say "Docker chua chay - dang bat Docker Desktop..."
    $desktop = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $desktop) {
        Start-Process $desktop | Out-Null
    } else {
        Die "Khong tim thay Docker Desktop" @(
            'Cai tai https://www.docker.com/products/docker-desktop',
            'hoac tu bat no roi chay lai script nay.'
        )
    }

    Say "Doi Docker san sang (co the mat mot phut)..."
    $up = WaitFor "Docker" 180 {
        return ((Native docker @('info') -Quiet) -eq 0)
    }
    if (-not $up) {
        Die "Docker khong san sang sau 3 phut" @('Mo Docker Desktop bang tay roi chay lai.')
    }
} else {
    Ok "Docker"
}

Push-Location $root
$composeCode = Native docker @('compose', 'up', '-d') -Quiet
Pop-Location
if ($composeCode -ne 0) {
    Die "docker compose up that bai" @('Chay tay de xem loi: docker compose up')
}

# Doi den khi Postgres thuc su nhan ket noi. `up -d` tra ve ngay khi container chay,
# con Postgres thi con vai giay nua moi mo cong - bat API vao giua khoang do thi no
# chet voi "connection refused" o mot cho cach nguyen nhan that ba tang.
$pgUp = WaitFor "Postgres" 90 {
    Push-Location $root
    $code = Native docker @('compose', 'exec', '-T', 'postgres', 'pg_isready', '-U', 'seeding') -Quiet
    Pop-Location
    return ($code -eq 0)
}
if (-not $pgUp) {
    Die "Postgres khong len sau 90 giay" @('docker compose logs postgres')
}

$redisUp = WaitFor "Redis" 30 {
    Push-Location $root
    $code = Native docker @('compose', 'exec', '-T', 'redis', 'redis-cli', 'ping') -Quiet
    Pop-Location
    return ($code -eq 0)
}
if (-not $redisUp) {
    Die "Redis khong len sau 30 giay" @('docker compose logs redis')
}

# --- 3. Migration ------------------------------------------------------------

# Chay moi lan bat. Schema cu hon code la loi kho doan nhat trong ca he thong: no
# khong hong luc khoi dong, no hong o mot cot thieu giua chien dich dang chay.
Step "Cap nhat schema database"
Push-Location $root
$migrateCode = Native (Join-Path $root '.venv\Scripts\alembic.exe') @('upgrade', 'head') -Quiet
Pop-Location
if ($migrateCode -ne 0) {
    Die "alembic upgrade that bai" @('.\.venv\Scripts\alembic upgrade head')
}
Ok "schema moi nhat"

# --- 4. Ba tien trinh --------------------------------------------------------

function StartWindow($title, $command) {
    # /k chu khong phai /c: tien trinh chet thi cua so O LAI kem thong bao loi. Voi /c
    # no dong ngay va ban chi thay mot cua so nhap nhay roi bien mat.
    Start-Process -FilePath 'cmd.exe' `
        -ArgumentList '/k', "title $title && cd /d `"$root`" && $command" `
        -WindowStyle Minimized | Out-Null
}

# Don vo rong truoc khi bat them. Cua so con tien trinh song thi khong dung den.
CloseOrphanWindows

Step "Bat API"
if (PortOwner $API_PORT) {
    Ok "da chay san (cong $API_PORT)"
} else {
    # -Dev bat --reload cho ca API: dang sua code thi khoi phai tat/bat tay moi lan.
    # Mac dinh tat, vi --reload sinh tien trinh con va lam viec dung/khoi dong kem on dinh.
    $reload = ''
    if ($Dev) { $reload = ' --reload' }
    StartWindow 'Seeding - API' "`"$venvPython`" -m uvicorn seeding.api.main:app --host 127.0.0.1 --port $API_PORT$reload"
    $apiUp = WaitFor "API" 60 {
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:$API_PORT/health" -TimeoutSec 3 -UseBasicParsing
            return ($r.StatusCode -eq 200)
        } catch { return $false }
    }
    if (-not $apiUp) {
        Die "API khong len sau 60 giay" @('Xem cua so "Seeding - API" de biet loi.')
    }
}

Step "Bat signer (ky request dang bai TikTok)"
$signerDir = Join-Path $root 'tools\tiktok-signer'
if (PortOwner $SIGNER_PORT) {
    Ok "da chay san (cong $SIGNER_PORT)"
} else {
    if (-not (Test-Path (Join-Path $signerDir 'node_modules'))) {
        Say "Cai goi cho signer (mot lan, ~3 phut)..."
        Push-Location $signerDir
        $code = Native 'npm.cmd' @('ci', '--no-audit', '--no-fund') -Quiet
        Pop-Location
        if ($code -ne 0) { Die "npm ci cho signer that bai" @('cd tools\tiktok-signer', 'npm ci') }
        Ok "cai xong"
    }

    # .env la cua tung may (duong dan Chrome), khong nam trong git. Sinh lan dau.
    # Puppeteer trong goi ghim Chrome 148 con cache tai 152 -> lech phien ban, init
    # hong; tro thang vao Chrome/Edge cua may cho chac.
    $envFile = Join-Path $signerDir '.env'
    if (-not (Test-Path $envFile)) {
        $chrome = @(
            "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
            "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
            "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
            "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
        ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
        if (-not $chrome) {
            Die "Khong tim thay Chrome hay Edge cho signer" @(
                'Cai Google Chrome, hoac dat PUPPETEER_EXECUTABLE_PATH trong tools\tiktok-signer\.env')
        }
        Set-Content -Path $envFile -Encoding ascii -Value @(
            "PORT=$SIGNER_PORT",
            "PROXY_ENABLED=false",
            "PUPPETEER_EXECUTABLE_PATH=$chrome"
        )
        Ok "tao tools\tiktok-signer\.env (Chrome: $chrome)"
    }

    StartWindow 'Seeding - Signer' "npm --prefix tools\tiktok-signer start"
    $signerUp = WaitFor "Signer" 120 {
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:$SIGNER_PORT/health" -TimeoutSec 3 -UseBasicParsing
            return ($r.Content -match '"ready":true')
        } catch { return $false }
    }
    if (-not $signerUp) {
        Die "Signer khong san sang sau 120 giay" @('Xem cua so "Seeding - Signer" de biet loi.')
    }
    Ok "san sang"
}

Step "Bat worker"
$running = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like '*WorkerSettings*' }
if ($running) {
    Ok "da chay san"
} else {
    StartWindow 'Seeding - Worker' "`"$venvPython`" -m arq seeding.worker.settings.WorkerSettings"
    Ok "dang khoi dong (day la thu that su dang bai)"
}

Step "Bat dashboard"
if (PortOwner $WEB_PORT) {
    Ok "da chay san (cong $WEB_PORT)"
} else {
    if ($Dev) {
        StartWindow 'Seeding - Dashboard (dev)' 'npm run dev --prefix web'
    } else {
        # Build khi ma nguon moi hon ban build. Che do dev bien dich lai moi lan mo
        # trang, cham thay ro khi ngoi lam viec that ca buoi.
        $buildId = Join-Path $root 'web\.next\BUILD_ID'
        $needsBuild = $true
        if (Test-Path $buildId) {
            $builtAt = (Get-Item $buildId).LastWriteTime
            $newest = Get-ChildItem (Join-Path $root 'web\src') -Recurse -File |
                Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($newest -and $newest.LastWriteTime -lt $builtAt) { $needsBuild = $false }
        }

        if ($needsBuild) {
            Say "Ma nguon giao dien moi hon ban build - dang build lai (mot lan, ~1 phut)..."
            Push-Location (Join-Path $root 'web')
            $buildCode = Native 'npm.cmd' @('run', 'build') -Quiet
            Pop-Location
            if ($buildCode -ne 0) {
                Die "npm run build that bai" @('cd web; npm run build')
            }
            Ok "build xong"
        }

        StartWindow 'Seeding - Dashboard' 'npm start --prefix web'
    }

    $webUp = WaitFor "Dashboard" 120 {
        return ($null -ne (PortOwner $WEB_PORT))
    }
    if (-not $webUp) {
        Die "Dashboard khong len sau 2 phut" @('Xem cua so "Seeding - Dashboard" de biet loi.')
    }
}

# --- 5. Xong -----------------------------------------------------------------

Write-Host ""
Write-Host "  ================================================" -ForegroundColor Green
Write-Host "   Da chay xong" -ForegroundColor Green
Write-Host "  ================================================" -ForegroundColor Green
Write-Host ""
Write-Host "   Dashboard   http://127.0.0.1:$WEB_PORT"
Write-Host "   API docs    http://127.0.0.1:$API_PORT/docs"
Write-Host ""
Write-Host "   Token de dan vao lan dau (moi trinh duyet mot lan):"
Write-Host "   $token" -ForegroundColor Yellow
Write-Host ""
Write-Host "   Ba cua so terminal dang thu nho duoi thanh tac vu."
Write-Host "   Co su co thi mo cua so tuong ung ra doc log."
Write-Host ""
Write-Host "   Tat tat ca: bam Stop.cmd"
Write-Host ""

Start-Process "http://127.0.0.1:$WEB_PORT" | Out-Null
Start-Sleep -Seconds 3
