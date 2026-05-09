# Client Release Checklist (Jenan Biz v1.0.1)

## 1) Build & Sign
1. Confirm release artifacts exist:
   - dist/setup/JenanBiz-Setup-1.0.1.exe
   - dist/setup/JenanBiz-Setup-1.0.1.sha256.txt
   - dist/setup/JenanBiz-Portable-1.0.1.zip
   - dist/setup/JenanBiz-Portable-1.0.1.sha256.txt
2. Verify file integrity:
   - Get-FileHash -Algorithm SHA256 dist/setup/JenanBiz-Setup-1.0.1.exe
   - Compare with dist/setup/JenanBiz-Setup-1.0.1.sha256.txt
3. Verify signature info:
   - Get-AuthenticodeSignature dist/setup/JenanBiz-Setup-1.0.1.exe

## 2) Pre-Delivery Validation
1. Install on a clean Windows test machine.
2. Launch from Start Menu.
3. Confirm app opens at http://127.0.0.1:5001.
4. Confirm data directory created in %LOCALAPPDATA%\JenanBiz.
5. Run health checks:
   - /healthz
   - /readyz

## 3) Network Readiness (Optional)
1. Set JENAN_HOST=0.0.0.0 if LAN access is needed.
2. Open firewall port for private network only.
3. Validate access from second device using host IP.

## 4) Delivery Package
1. Deliver setup file + checksum file together.
2. Include installation notes from packaging/windows/INSTALL_README.txt.
3. Include support contact and release notes.

## 5) Post-Delivery Controls
1. Keep backup of signed artifacts in immutable storage.
2. Record release hash and timestamp in internal log.
3. Track client feedback/issues for hotfix planning.
