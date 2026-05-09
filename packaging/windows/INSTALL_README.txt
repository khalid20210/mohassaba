Jenan Biz - Windows Installer Notes

1) After installation, run "Jenan Biz" from Start Menu.
2) App data is stored per-user in:
   %LOCALAPPDATA%\JenanBiz
3) Default URL:
   http://127.0.0.1:5001
4) To allow LAN access, create environment variable before launch:
   JENAN_HOST=0.0.0.0
   Then open from another device using:
   http://<YOUR_PC_IP>:5001
5) If port 5001 is busy, set:
   JENAN_PORT=5010

Security note:
- Open firewall port only on trusted/private networks.
