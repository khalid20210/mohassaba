param(
  [string]$Version = "1.0.1",
  [string]$CertPath = $env:JENAN_SIGN_CERT_PATH,
  [string]$CertPassword = $env:JENAN_SIGN_CERT_PASSWORD
)

$ErrorActionPreference = 'Stop'

Set-Location (Join-Path $PSScriptRoot '..\..')

if (-not (Test-Path '.venv\Scripts\python.exe')) {
  throw 'Missing .venv\Scripts\python.exe. Create virtualenv and install requirements first.'
}

$python = '.\.venv\Scripts\python.exe'
$installerExe = '.\dist\installer\JenanBiz.exe'
$setupExe = ".\dist\setup\JenanBiz-Setup-$Version.exe"
$portableZip = ".\dist\setup\JenanBiz-Portable-$Version.zip"
$versionFile = '.\packaging\windows\version_info.txt'

function New-VersionInfoFile {
  param([string]$Path, [string]$AppVersion)

  $parts = $AppVersion.Split('.')
  while ($parts.Count -lt 4) { $parts += '0' }
  $v1 = [int]$parts[0]
  $v2 = [int]$parts[1]
  $v3 = [int]$parts[2]
  $v4 = [int]$parts[3]

  $content = @"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($v1, $v2, $v3, $v4),
    prodvers=($v1, $v2, $v3, $v4),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          u'040904B0',
          [
            StringStruct(u'CompanyName', u'Jenan Biz'),
            StringStruct(u'FileDescription', u'Jenan Biz Desktop Launcher'),
            StringStruct(u'FileVersion', u'$AppVersion'),
            StringStruct(u'InternalName', u'JenanBiz'),
            StringStruct(u'LegalCopyright', u'Copyright (c) Jenan Biz'),
            StringStruct(u'OriginalFilename', u'JenanBiz.exe'),
            StringStruct(u'ProductName', u'Jenan Biz'),
            StringStruct(u'ProductVersion', u'$AppVersion')
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"@

  Set-Content -Path $Path -Value $content -Encoding ascii
}

function Get-SignToolPath {
  $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }

  $candidates = @(
    'C:\Program Files (x86)\Windows Kits\10\bin\x64\signtool.exe',
    'C:\Program Files\Windows Kits\10\bin\x64\signtool.exe'
  )
  foreach ($p in $candidates) {
    if (Test-Path $p) { return $p }
  }
  return $null
}

function Sign-IfPossible {
  param([string]$TargetFile)

  if (-not $CertPath -or -not (Test-Path $CertPath)) {
    Write-Warning "Signing skipped: certificate not configured."
    return
  }

  $signtool = Get-SignToolPath
  if (-not $CertPassword) {
    Write-Warning "Signing skipped: certificate password not configured."
    return
  }

  if ($signtool) {
    & $signtool sign /f $CertPath /p $CertPassword /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 $TargetFile
    if ($LASTEXITCODE -ne 0) {
      throw "Code signing failed for $TargetFile"
    }
    return
  }

  # Fallback: PowerShell Authenticode signing when signtool is unavailable.
  $securePass = ConvertTo-SecureString -String $CertPassword -AsPlainText -Force
  $imported = Import-PfxCertificate -FilePath $CertPath -CertStoreLocation 'Cert:\CurrentUser\My' -Password $securePass -Exportable
  $cert = $imported | Select-Object -First 1
  if (-not $cert) {
    throw "Unable to load certificate from $CertPath"
  }

  $result = Set-AuthenticodeSignature -FilePath $TargetFile -Certificate $cert -HashAlgorithm SHA256 -TimestampServer "http://timestamp.digicert.com"
  if ($result.Status -notin @('Valid', 'UnknownError')) {
    throw "Authenticode signing failed for $TargetFile. Status: $($result.Status)"
  }
}

Write-Host '[1/6] Clean previous build output...'
if (Test-Path '.\build') { Remove-Item '.\build' -Recurse -Force }
if (Test-Path '.\dist\JenanBiz') { Remove-Item '.\dist\JenanBiz' -Recurse -Force }
if (Test-Path '.\dist\installer') { Remove-Item '.\dist\installer' -Recurse -Force }

Write-Host '[2/6] Install build dependencies...'
& $python -m pip install --upgrade pip
& $python -m pip install pyinstaller

Write-Host '[3/6] Build portable EXE (PyInstaller)...'
New-VersionInfoFile -Path $versionFile -AppVersion $Version
& $python -m PyInstaller `
  --noconfirm `
  --windowed `
  --name JenanBiz `
  --icon "static\icons\app_icon.ico" `
  --version-file $versionFile `
  --add-data "templates;templates" `
  --add-data "static;static" `
  --add-data "migrations;migrations" `
  --add-data "database;database" `
  --add-data "modules;modules" `
  launcher.py

Write-Host '[4/6] Prepare installer staging...'
New-Item -ItemType Directory -Path '.\dist\installer' -Force | Out-Null
Copy-Item '.\dist\JenanBiz\JenanBiz.exe' $installerExe -Force

if (Test-Path '.\packaging\windows\INSTALL_README.txt') {
  Copy-Item '.\packaging\windows\INSTALL_README.txt' '.\dist\installer\INSTALL_README.txt' -Force
}

Write-Host '[5/6] Build setup via Inno Setup (if installed)...'
$inno = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
if (Test-Path $inno) {
  & $inno "/DMyAppVersion=$Version" '.\packaging\windows\JenanBiz.iss'
  if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup compile failed with exit code $LASTEXITCODE"
  }
  Write-Host "Setup created: $setupExe"
} else {
  Write-Warning 'Inno Setup not found. Install Inno Setup 6, then run this script again to generate installer.'
}

Write-Host '[6/6] Optional code-sign and checksum...'
if (Test-Path $installerExe) { Sign-IfPossible -TargetFile $installerExe }
if (Test-Path $setupExe) { Sign-IfPossible -TargetFile $setupExe }

if (Test-Path $setupExe) {
  $hash = Get-FileHash -Path $setupExe -Algorithm SHA256
  "$($hash.Algorithm): $($hash.Hash)  $($hash.Path)" | Set-Content -Path ".\dist\setup\JenanBiz-Setup-$Version.sha256.txt" -Encoding ascii
}

if (Test-Path $installerExe) {
  if (Test-Path $portableZip) { Remove-Item $portableZip -Force }
  Compress-Archive -Path $installerExe, '.\dist\installer\INSTALL_README.txt' -DestinationPath $portableZip -CompressionLevel Optimal
  $zipHash = Get-FileHash -Path $portableZip -Algorithm SHA256
  "$($zipHash.Algorithm): $($zipHash.Hash)  $($zipHash.Path)" | Set-Content -Path ".\dist\setup\JenanBiz-Portable-$Version.sha256.txt" -Encoding ascii
}

Write-Host 'Done.'
