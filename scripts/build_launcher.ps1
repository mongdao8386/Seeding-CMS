# Build Seeding.exe (nut bam co icon de ghim vao taskbar) tu launcher/Seeding.cs.
#
# Dung csc.exe cua .NET Framework 4.x co san trong moi ban Windows 10/11 - khong cai gi them.
# Icon: launcher/seeding.ico (sinh boi scripts/make_icon.py, chay lai khi muon doi hinh).
#
#     powershell -ExecutionPolicy Bypass -File scripts\build_launcher.ps1

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path $csc)) { $csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe' }
if (-not (Test-Path $csc)) { throw "Khong thay csc.exe (.NET Framework 4.x). Windows 10/11 mac dinh co san." }

$src = Join-Path $root 'launcher\Seeding.cs'
$ico = Join-Path $root 'launcher\seeding.ico'
$out = Join-Path $root 'Seeding.exe'
if (-not (Test-Path $ico)) {
    & (Join-Path $root '.venv\Scripts\python.exe') (Join-Path $root 'scripts\make_icon.py')
}

& $csc /nologo /target:winexe /optimize+ /out:$out /win32icon:$ico `
    /reference:System.dll /reference:System.Windows.Forms.dll $src
if ($LASTEXITCODE -ne 0) { throw "csc that bai ($LASTEXITCODE)" }
Write-Host "OK  $out ($([math]::Round((Get-Item $out).Length / 1KB)) KB)"
Write-Host "    Chuot phai Seeding.exe -> 'Ghim vao thanh tac vu' (Windows 11: 'Hien them tuy chon' truoc)."
