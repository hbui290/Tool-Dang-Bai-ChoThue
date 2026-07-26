"""Kiểm tra tài khoản đã vào được những nhóm nào, tự cập nhật groups.json.

Đọc trang "Nhóm của bạn" trên Facebook, đối chiếu với groups_shortlist.json,
rồi thêm các nhóm đã join vào groups.json (enabled: true).
Các nhóm đã có sẵn trong groups.json được giữ nguyên.

Cách chạy: check_joined.bat
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

sys.path.insert(0, str(ROOT / "src"))
import store  # noqa: E402  — dùng chung khoá liên-tiến-trình + ghi nguyên tử với worker/dashboard

EXTRACT_JS = """
() => {
  const out = [];
  document.querySelectorAll("a[href*='/groups/']").forEach(a => {
    const href = a.href.split('?')[0].replace(/\\/$/, '');
    const m = href.match(/facebook\\.com\\/groups\\/([^\\/]+)$/);
    if (!m) return;
    const name = (a.textContent || '').trim();
    if (!name || name.length < 3) return;
    out.push({ id: m[1], name: name, url: href });
  });
  return out;
}
"""

SKIP_IDS = {"search", "feed", "discover", "joins", "create"}


def group_id(url: str) -> str:
    # Loại ?query / #fragment giống poster.py: link copy từ app FB mobile thường có
    # dạng /groups/123?ref=share_... — nếu giữ nguyên query thì ID không bao giờ khớp
    # với ID trích từ trang thật → nhận diện "đã join" sai, thêm trùng vào groups.json.
    m = re.search(r"/groups/([^/?#]+)", url)
    return m.group(1) if m else url


def main():
    if not PROFILE_DIR.exists():
        print("Chưa đăng nhập Facebook. Chạy login.bat trước.")
        sys.exit(1)

    joined = {}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",        # đồng bộ stealth với login/find/open_groups
            headless=False,
            no_viewport=True,        # KHÔNG set viewport/UA/flags custom (khuyến nghị Patchright)
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.facebook.com/groups/joins/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        if page.locator("input[name='pass']").count() > 0:
            print("Phiên đăng nhập đã mất. Chạy lại login.bat.")
            ctx.close()
            sys.exit(1)

        for _ in range(8):
            page.mouse.wheel(0, 1500)
            page.wait_for_timeout(1500)

        for item in page.evaluate(EXTRACT_JS):
            if item["id"] not in SKIP_IDS:
                joined[item["id"]] = item
        ctx.close()

    print(f"Tài khoản đang là thành viên của {len(joined)} nhóm (theo trang 'Nhóm của bạn').\n")

    shortlist = json.loads(SHORTLIST.read_text(encoding="utf-8"))
    existing = json.loads(GROUPS.read_text(encoding="utf-8")) if GROUPS.exists() else []
    existing_ids = {group_id(g["url"]) for g in existing}

    matched = [g for g in shortlist if group_id(g["url"]) in joined]
    new = [g for g in matched if group_id(g["url"]) not in existing_ids]

    print(f"Trong đó {len(matched)} nhóm nằm trong shortlist, {len(new)} nhóm chưa có trong groups.json:\n")
    for g in matched:
        mark = "MỚI" if g in new else "đã có"
        print(f"  [{mark:>5}] Tier {g['tier']} | {g['name']}")

    if not new:
        print("\nKhông có nhóm mới để thêm. Nếu bạn vừa bấm Tham gia, có thể admin chưa duyệt.")
        return

    # Bọc đọc-sửa-ghi trong khoá và ĐỌC LẠI groups.json: `existing` ở trên được đọc
    # TRƯỚC vài chục giây automation trình duyệt — ghi bằng snapshot cũ sẽ đè mất mọi
    # thay đổi từ dashboard (/api/groups/toggle) xảy ra trong lúc đó, không báo lỗi.
    with store._file_lock("groups"):
        current = json.loads(GROUPS.read_text(encoding="utf-8")) if GROUPS.exists() else []
        current_ids = {group_id(g["url"]) for g in current}
        # Giữ lại các nhóm ví dụ chỉ khi người dùng đã bật enabled
        kept = [g for g in current if g.get("enabled") or "XXXXXXXXXX" not in g["url"] and "YYYYYYYYYY" not in g["url"]]
        added = [g for g in new if group_id(g["url"]) not in current_ids]
        kept.extend({"name": g["name"], "url": g["url"], "enabled": True} for g in added)
        store._write_json(GROUPS, kept)      # ghi nguyên tử
    print(f"\nĐã cập nhật groups.json: tổng {len(kept)} nhóm, {len(added)} nhóm mới bật enabled.")


if __name__ == "__main__":
    main()
