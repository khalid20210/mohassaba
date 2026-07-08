import sys, os
sys.path.insert(0, r"C:\Users\JEN21\mohassaba")
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(r"C:\Users\JEN21\mohassaba\.env"), override=False)

for p in ["google", "microsoft", "apple"]:
    cid = os.environ.get(f"{p.upper()}_OAUTH_CLIENT_ID", "")
    cse = os.environ.get(f"{p.upper()}_OAUTH_CLIENT_SECRET", "")
    status = "مفعّل" if (cid and cse) else "غير مضبوط"
    short = (cid[:12] + "...") if cid else "فارغ"
    print(f"{p}: {status} | client_id={short}")

public = os.environ.get("PUBLIC_BASE_URL", "")
print("PUBLIC_BASE_URL:", public or "(فارغ)")
print()
print("Callback URLs المطلوبة:")
base = public or "http://127.0.0.1:5001"
for p in ["google", "microsoft", "apple"]:
    print(f"  {p}: {base}/auth/social/{p}/callback")
