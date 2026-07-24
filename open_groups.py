"""Mở sẵn các nhóm trong groups_shortlist.json thành nhiều tab để bạn bấm "Tham gia nhóm".

Dùng đúng tài khoản Facebook đã đăng nhập ở login.bat.

Cách chạy:
    open_groups.bat            → mở 8 nhóm Tier 1 đầu tiên chưa join
    open_groups.bat 2          → mở 8 nhóm Tier 2
    open_groups.bat 1 5        → mở 5 nhóm Tier 1

Sau khi bấm Tham gia xong hết, đóng cửa sổ trình duyệt.
Nhóm nào được duyệt vào rồi thì copy sang groups.json và đổi "enabled": true.
"""
import json
import re
import sys
from pathlib import Path

from patchright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
PROFILE_DIR = ROOT / "state" / "browser_profile"
SHORTLIST = ROOT / "groups_shortlist.json"
GROUPS = ROOT / "groups.json"

tier = int(sys.argv[1]) if len(sys.argv) > 1 else 1
count = int(sys.argv[2]) if len(sys.argv) > 2 else 8

if not PROFILE_DIR.exists():
    print("Chưa đăng nhập Facebook. Chạy login.bat trước.")
    sys.exit(1)


def group_id(url: str) -> str:
    m = re.search(r"/groups/([^/]+)", url)
    return m.group(1) if m else url


# Bỏ qua các nhóm đã có trong groups.json (đã join rồi)
joined = set()
if GROUPS.exists():
    joined = {group_id(g["url"]) for g in json.loads(GROUPS.read_text(encoding="utf-8"))}

groups = [
    g for g in json.loads(SHORTLIST.read_text(encoding="utf-8"))
    if g["tier"] == tier and group_id(g["url"]) not in joined
]
batch = groups[:count]

if not batch:
    print(f"Tier {tier}: đã join hết các nhóm trong shortlist. Thử tier khác.")
    sys.exit(0)

print(f"Mở {len(batch)} nhóm Tier {tier}. Bấm 'Tham gia nhóm' ở từng tab, xong thì đóng trình duyệt.\n")
for i, g in enumerate(batch, 1):
    print(f"  {i}. {g['name']}")

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        channel="chrome",
        headless=False,
        no_viewport=True,
    )
    pages = []
    for g in batch:
        page = ctx.new_page()
        page.goto(g["url"], wait_until="domcontentloaded", timeout=60000)
        pages.append(page)

    if ctx.pages and ctx.pages[0] not in pages:
        ctx.pages[0].close()

    print("\nĐang chờ... Bấm Tham gia ở các tab rồi ĐÓNG CỬA SỔ trình duyệt khi xong.")
    try:
        pages[0].wait_for_event("close", timeout=0)
    except Exception:
        pass

print("Xong. Nhóm nào đã được duyệt vào thì thêm vào groups.json với enabled: true.")
