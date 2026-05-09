param(
  [string]$Subject = "CN=Jenan Biz Platform",
  [string]$PfxPath = ".\.certs\JenanBiz-CodeSign.pfx",
  [int]$ValidYears = 2,
  [string]$Password
)

$ErrorActionPreference = 'Stop'

if (-not $Password) {
  throw 'Please provide -Password to protect the PFX file.'
}

$securePassword = ConvertTo-SecureString -String $Password -AsPlainText -Force

$pfxFull = Resolve-Path (Split-Path -Parent $PfxPath) -ErrorAction SilentlyContinue
if (-not $pfxFull) {
  New-Item -ItemType Directory -Path (Split-Path -Parent $PfxPath) -Force | Out-Null
}

$cert = New-SelfSignedCertificate `
  -Type CodeSigningCert `
  -Subject $Subject `
  -KeyAlgorithm RSA `
  -KeyLength 3072 `
  -HashAlgorithm SHA256 `
  -KeyExportPolicy Exportable `
  -CertStoreLocation 'Cert:\CurrentUser\My' `
  -NotAfter (Get-Date).AddYears($ValidYears)

Export-PfxCertificate `
  -Cert $cert `
  -FilePath $PfxPath `
  -Password $securePassword | Out-Null

Write-Host "Created code-sign cert PFX: $PfxPath"
Write-Host "Thumbprint: $($cert.Thumbprint)"