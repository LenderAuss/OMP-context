param(
    [string]$Prefix,
    [string]$BinDir,
    [ValidateSet('yolo', 'write', 'always-ask')][string]$Permissions = 'yolo',
    [switch]$NoPath,
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
if ($DryRun) {
    Write-Output "Would install pinned uv, Python 3.12, OMP and Graphify in a dedicated user directory. Permissions: $Permissions. No changes made."
    return
}
if ($env:OS -ne 'Windows_NT') { throw 'Use install.sh on macOS/Linux.' }
# x64 binaries also run on Windows ARM64 through the Windows x64 compatibility layer.
$Lock = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'versions.lock.json') | ConvertFrom-Json
$Asset = $Lock.uv.assets.'uv-x86_64-pc-windows-msvc.zip'
$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('omp-kit-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $TempRoot | Out-Null
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $Archive = Join-Path $TempRoot 'uv.zip'
    Invoke-WebRequest -UseBasicParsing -Uri $Asset.url -OutFile $Archive
    $Actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Archive).Hash.ToLowerInvariant()
    if ($Actual -ne $Asset.sha256) { throw 'uv SHA-256 mismatch; bootstrap stopped.' }
    Expand-Archive -LiteralPath $Archive -DestinationPath (Join-Path $TempRoot 'uv')
    $Uv = (Get-ChildItem -LiteralPath (Join-Path $TempRoot 'uv') -Filter uv.exe -Recurse | Select-Object -First 1).FullName
    if (-not $Uv) { throw 'Verified uv archive did not contain uv.exe.' }
    $Arguments = @('run', '--no-project', '--no-config', '--python', '3.12', (Join-Path $PSScriptRoot 'install.py'), '--uv', $Uv, '--permissions', $Permissions)
    if ($Prefix) { $Arguments += @('--prefix', $Prefix) }
    if ($BinDir) { $Arguments += @('--bin-dir', $BinDir) }
    if ($NoPath) { $Arguments += '--no-path' }
    & $Uv @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Installer exited with code $LASTEXITCODE." }
} finally {
    Remove-Item -LiteralPath $TempRoot -Recurse -Force
}
