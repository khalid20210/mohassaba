# Jenan Biz v1.0.1 Release Notes

## Summary
- Professional Windows packaging pipeline finalized.
- Installer and portable distribution artifacts standardized.
- Optional code-signing flow integrated for trusted delivery.

## What's New
- Added polished Windows build script with:
  - Clean rebuild lifecycle.
  - Versioned outputs.
  - SHA256 checksums for integrity validation.
  - Optional digital signing using PFX certificate.
- Added Inno Setup installer configuration improvements:
  - Versioned setup filename.
  - App icon and publisher/support metadata.
  - 64-bit compatible installation settings.
- Added portable ZIP artifact generation.
- Added GitHub Actions workflow for release automation.
- Added Docker runtime packaging path for network-hosted operation.

## Security & Trust
- Build pipeline supports Authenticode signing.
- SHA256 files are generated for setup and portable artifacts.
- Unsinged builds remain possible, but signed builds are recommended for external distribution.

## Distribution Artifacts
- `JenanBiz-Setup-1.0.1.exe`
- `JenanBiz-Setup-1.0.1.sha256.txt`
- `JenanBiz-Portable-1.0.1.zip`
- `JenanBiz-Portable-1.0.1.sha256.txt`

## Upgrade Notes
- Existing data stays in user-local runtime storage path.
- No schema-breaking migration introduced in this release.