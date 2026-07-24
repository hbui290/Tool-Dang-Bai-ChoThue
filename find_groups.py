"""Tìm nhóm Facebook về cho thuê chung cư (sửa KEYWORDS bên dưới theo khu vực/dự án của bạn).

Dùng tính năng tìm kiếm nhóm của Facebook qua phiên đăng nhập đã lưu.
Kết quả ghi vào groups_found.json — bạn duyệt, TỰ TAY join các nhóm ưng ý,
rồi copy những nhóm đã join sang groups.json và đổi "enabled": true.

Cách chạy: double-click find_groups.bat (cần chạy login.bat trước).
"""
import json
import re
import sys
import urllib.parse
from pathlib import Path

from patchright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
import humanize  # noqa: E402

PROFILE_DIR = ROOT / "state" / "browser_profile"
OUT_FILE = ROOT / "groups_found.json"

# SỬA danh sách này theo dự án / khu vực của bạn (thêm tên tòa nhà, quận...)
KEYWORDS = [
    "cho thuê căn hộ",
    "cho thuê chung cư",
    "cho thuê căn hộ [khu vực của bạn]",
    "cho thuê [tên dự án của bạn]",
]

EXTRACT_JS = """
() => {
  const out = [];
  document.querySelectorAll("a[href*='/groups/']").forEach(a => {
    const href = a.href.split('?')[0].replace(/\\/$/, '');
    const m = href.match(/facebook\\.com\\/groups\\/([^\\/]+)$/);
    if (!m) return;
    const name = (a.textContent || '').trim();
    if (!name || name.length < 3) return;
    let el = a;
    for (let i = 0; i < 6 && el.parentElement; i++) el = el.parentElement;
    out.push({ id: m[1], name: name, url: href, info: (el.textContent || '').slice(0, 400) });
  });
  return out;
}
"""


def parse_members(info: str):
    """'45K thành viên' / '1,2M members' → số gần đúng để sắp xếp."""
    m = re.search(r"([\d.,]+)\s*(K|M|k|m)?\s*(thành viên|members)", info)
    if not m:
        return None
    num = float(m.group(1).replace(",", "."))
    unit = (m.group(2) or "").upper()
    if unit == "K":
        num *= 1_000
    elif unit == "M":
        num *= 1_000_000
    return int(num)


def check_logged_in(page) -> bool:
    page.goto("https://www.facebook.com", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    return page.locator("input[name='pass']").count() == 0


def main():
    if not PROFILE_DIR.exists():
        print("Chưa đăng nhập Facebook. Hãy chạy login.bat trước rồi chạy lại file này.")
        sys.exit(1)

    found = {}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            no_viewport=True,
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        if not check_logged_in(page):
            print("Phiên đăng nhập đã mất. Hãy chạy login.bat đăng nhập lại rồi thử lại.")
            ctx.close()
            sys.exit(1)

        for kw in KEYWORDS:
            print(f"\nĐang tìm: \"{kw}\" ...")
            url = "https://www.facebook.com/search/groups?q=" + urllib.parse.quote(kw)
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)

            # Cuộn để load thêm kết quả
            for _ in range(5):
                page.mouse.wheel(0, 1500)
                humanize.pause(1.5, 3.0)

            for item in page.evaluate(EXTRACT_JS):
                gid = item["id"]
                if gid in ("search", "feed", "discover", "joins"):
                    continue
                members = parse_members(item["info"])
                if gid not in found or (members and not found[gid].get("members")):
                    found[gid] = {
                        "name": item["name"],
                        "url": item["url"],
                        "enabled": False,
                        "members": members,
                    }
            print(f"  → tổng cộng đã gom được {len(found)} nhóm")
            humanize.pause(3, 6)

        ctx.close()

    results = sorted(found.values(), key=lambda g: g.get("members") or 0, reverse=True)
    OUT_FILE.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 80)
    print(f"TÌM ĐƯỢC {len(results)} NHÓM — đã lưu vào groups_found.json")
    print("=" * 80)
    for g in results:
        mem = f"{g['members']:,}".replace(",", ".") if g.get("members") else "?"
        print(f"{mem:>12} tv | {g['name'][:55]:<55} | {g['url']}")
    print("=" * 80)
    print("Tiếp theo: mở từng link, TỰ TAY bấm Tham gia nhóm với các nhóm phù hợp.")
    print("Sau khi được duyệt vào nhóm, copy nhóm đó từ groups_found.json sang groups.json")
    print('và đổi "enabled": false thành true (xóa dòng "members" hoặc để nguyên đều được).')


if __name__ == "__main__":
    main()
