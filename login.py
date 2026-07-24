"""Chạy 1 lần để đăng nhập Facebook. Session được lưu vào state/browser_profile.

Cách dùng: double-click login.bat (hoặc: venv\\Scripts\\python.exe login.py)
→ Cửa sổ Chrome mở ra → tự tay đăng nhập Facebook (cả 2FA nếu có)
→ Khi đã vào được trang chủ Facebook thì ĐÓNG cửa sổ trình duyệt là xong.
"""
import json
from pathlib import Path

from patchright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
PROFILE_DIR = ROOT / "state" / "browser_profile"

# Dùng cùng proxy với worker (nếu có) để đăng nhập cùng IP với lúc đăng bài
try:
    _proxy = json.loads((ROOT / "config.json").read_text(encoding="utf-8")).get("proxy") or None
    if _proxy and not _proxy.get("server"):
        _proxy = None
except Exception:
    _proxy = None
if _proxy:
    print("Đăng nhập qua proxy:", _proxy.get("server"))

print("Đang mở trình duyệt... Hãy đăng nhập Facebook rồi đóng cửa sổ khi xong.")
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        channel="chrome",        # Patchright: dùng Google Chrome thật, không Chromium
        headless=False,
        no_viewport=True,        # tránh detect theo viewport; KHÔNG set UA/flags custom
        proxy=_proxy,
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://www.facebook.com")
    # Chờ tới khi người dùng đóng trình duyệt
    try:
        page.wait_for_event("close", timeout=0)
    except Exception:
        pass

print("Đã lưu phiên đăng nhập vào state/browser_profile. Giờ có thể chạy run.bat.")
