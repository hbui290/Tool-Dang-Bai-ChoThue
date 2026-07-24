# Phân tích & Audit — Tool Đăng Bài Cho Thuê (FB Group Auto-Poster)

> Báo cáo read-only. Không sửa file code nào. Ngày lập: 2026-07-22.
> Gồm 2 phần: (A) Audit lỗi sâu, (B) Research đối thủ cùng ngách + định hướng thương mại hoá.

---

## Tổng quan tool

Python + Playwright tự động đăng tin cho thuê/bán căn hộ lên nhiều nhóm Facebook.
Luồng: `login.py` (đăng nhập 1 lần, lưu profile) → `find_groups.py`/`open_groups.py`/`check_joined.py`
(tìm & join nhóm) → `src/worker.py` (chạy nền đăng theo lịch) → `dashboard/app.py` (Flask theo dõi).

Điểm mạnh kỹ thuật: anti-detection (gõ như người, `--disable-blink-features=AutomationControlled`),
phân biệt rate-limit/checkpoint/logout, **verifier bằng nick thứ 2** xác nhận bài lên công khai,
proxy support, dashboard self-contained có dark mode + biểu đồ 14 ngày.

**Sạch về an toàn:** không có network call ra ngoài (mọi traffic qua browser tới facebook.com),
không backdoor/exfiltration. Chỉ 1 `urllib.parse.quote` để build URL search FB.

---

# PHẦN A — AUDIT LỖI

## Đính chính (2 giả định ban đầu sai)

- **`store._write_json` GHI NGUYÊN TỬ** (tempfile + `os.replace`) → mọi ghi phía worker
  (posted_log, status, control, commands) an toàn. Không có race "verify clobber log".
  Worker đơn luồng, chỉ 1 nơi ghi `posted_log.json`.
- **`check_joined.py` biểu thức precedence CHẠY ĐÚNG**: `and` bind chặt hơn `or`
  → `enabled or (không-phải-nhóm-mẫu)`, đúng ý.
- ⇒ Ghi KHÔNG nguyên tử chỉ nằm ở **dashboard** (`groups.json`, `config.json`) và dead code `scheduler.append_log`.

## 🔴 P1 — làm worker chết / lỗ hổng bảo mật

| # | file:line | Lỗi | Kích hoạt | Cách vá |
|---|-----------|-----|-----------|---------|
| 1 | src/worker.py (vòng lặp `while True`, ~186-236) | Chỉ `except RateLimitError`/`CheckpointError` → **mọi lỗi khác giết worker vĩnh viễn**. Gốc rễ của các P1 khác | Bất kỳ exception ngoài dự kiến | Bọc thân loop bằng `except Exception` → log rồi `continue` |
| 2 | dashboard/app.py:49-50 `save_groups` | Ghi `groups.json` bằng `write_text` không nguyên tử; worker đọc mỗi 45s (scheduler.py:17-18) | Bấm toggle nhóm đúng lúc worker đọc → `JSONDecodeError` → chết worker | Ghi qua `store._write_json` |
| 3 | src/worker.py:32-33 (try ở :47) | `pick_content()`/`pick_images()` gọi TRƯỚC try của do_post → exception thoát ra loop chính | Hộp mặc định `images/` chỉ có file `.txt` placeholder → `RuntimeError("Không tìm thấy ảnh")` → chết worker ngay bài đầu | Đưa 2 lời gọi vào trong try; lỗi thì `continue` |
| 4 | dashboard/app.py:124-128 `update_config` | Lưu 4 key config KHÔNG validate; worker dùng để tính toán | `posting_hours_start="7am"`/`""` → `_parse_hhmm` ValueError; `max_posts_per_day` là string → TypeError → chết worker | Validate type/format trước khi lưu |
| 5 | dashboard/app.py:151 + auth.json:3 | Bind `0.0.0.0` + Basic Auth HTTP (không TLS) + pass mặc định `DOI_MAT_KHAU_NAY_DI` | Mọi host trong mạng/VPS điều khiển được (pause/post/đọc screenshot) | Bind `127.0.0.1` hoặc sau TLS proxy; ép đổi pass lúc khởi động |
| 6 | dashboard/app.py:127-128 `update_config` | Ghi `config.json` không nguyên tử (cùng loại #2) | Bấm Lưu config đúng lúc worker đọc → JSONDecodeError → chết worker | Ghi qua `store._write_json` |

## 🟡 P2 — hỏng tính năng

| # | file:line | Lỗi | Cách vá |
|---|-----------|-----|---------|
| 7 | src/scheduler.py:96-100 `pick_content` | Glob TẤT CẢ `*.txt` + `random.choice` → **đăng nhầm file hướng dẫn `content/_HUONG_DAN.txt` như bài rao thật** lên nhóm FB | `glob("[!_]*.txt")` để loại file `_`-prefix |
| 8 | src/scheduler.py:113 `pick_images` | Đọc `config["images_per_post_min"]`/`["images_per_post_max"]` bằng bracket nhưng 2 key KHÔNG có trong config.json | Bật `use_all_images:false` → KeyError → (qua #3) chết worker | Thêm key vào config hoặc `.get(...)` |
| 9 | src/worker.py:80-83 `verify_public` | `datetime.fromisoformat(e["time"])` + `e["group_name"]` chạy NGOÀI try per-group (:96) | 1 entry log `time` lỗi → chết worker | Guard `.get` + try/except từng entry |
| 10 | src/poster.py:131 + src/worker.py:101-102 | Câu trả lời duyệt nhóm & verify đều nhúng `contact_phone`. Quên đổi số → verify LUÔN báo pending + trả lời nhóm bằng placeholder (lộ bot). Text đóng băng lúc import → đổi số phải **restart worker** | Fail loudly nếu `contact_phone` còn placeholder; đọc số động |
| 11 | src/poster.py:215-224 `get_user_id` | Regex FB HTML; FB đổi markup → uid rỗng → `verify_public` early-return (worker.py:76) → mọi bài kẹt "unverified" | Log warning + retry khi uid rỗng |

## 🟢 P3 — chất lượng / vận hành

| # | file:line | Lỗi |
|---|-----------|-----|
| 12 | poster.py:59-66 | `state/screenshots/` không dọn → phình đĩa; lại public qua `/screenshots` |
| 13 | store.py:87-100 | `posted_log.json` không trim; full read+rewrite mỗi 45s + mỗi bài → I/O O(n) |
| 14 | scheduler.py:123-126 `in_posting_hours` | Dùng `start <= m < end`, KHÔNG qua nửa đêm (khung 22:00-06:00 không đăng, âm thầm) |
| 15 | store.py, scheduler.py | `datetime.now()` naive; đúng-sai phụ thuộc TZ máy (comment ghi VPS Asia/Ho_Chi_Minh). Test trên macOS lệch "hôm nay"/quota/khung giờ |
| 16 | store.py:114,198; scheduler.py:36 | Bracket `e["time"]`/`e["status"]` → 1 entry lỗi → 500 ở `/api/stats`, `/api/groups` |
| 17 | dashboard/app.py:108,135 | `request.json.get(...)` không guard → body không phải JSON → 500 AttributeError |
| 18 | login.py:31 | Thiếu `--no-sandbox` (worker/verifier có) → chỉ ảnh hưởng VPS Linux root |
| 19 | scheduler.py:28-31,129 | Dead code `append_log` (ghi không nguyên tử) + `next_delay_seconds` không dùng |

## Top 3 vá đầu tiên (chặn ~90% rủi ro)

1. **Thêm `except Exception` bọc thân vòng lặp worker** (worker.py ~186-236): log rồi `continue`.
   Một tay dập #1, #3, #4, #9. Khác biệt giữa "1 bài fail" và "ngừng đăng cả ngày không ai biết".
2. **Cho toàn bộ ghi của dashboard đi qua `store._write_json`** (đã có sẵn): `save_groups` + `update_config`.
   Hết race #2, #6.
3. **Sửa đường đăng lần đầu** (#3 + #7 + #8): đưa `pick_content`/`pick_images` vào try;
   `glob("[!_]*.txt")` để khỏi đăng nhầm file hướng dẫn; xử lý ảnh rỗng; validate config #4.

---

# PHẦN B — RESEARCH ĐỐI THỦ CÙNG NGÁCH

Đa số repo cùng ngách là **script 1 tài khoản, Selenium, bỏ hoang** (2017-2022), thiếu tính năng vận hành.
Chỉ 2 đối thủ vừa active vừa mạnh: Tigerzplace/FAP (Chrome extension) và k3c0t (AI caption Gemini).

## Repo đáng chú ý (đã xác minh URL)

| Repo | Sao | Cách làm | Điểm riêng | Trạng thái |
|---|---|---|---|---|
| [adar2/Facebook-Posts-Automation](https://github.com/adar2/Facebook-Posts-Automation) | ~135 | Selenium + PyQt5 GUI | Multi-user, SQLite, keyring | Chết 2021, **GPL-3.0** |
| [Tigerzplace/FAP](https://github.com/Tigerzplace/FAP-FacebookAutoPoster) | ~40 | Chrome extension | Cài 1-click, save/load campaign, đã thương mại hoá | **Active 2026**, no license |
| [k3c0t/...Terjadwal](https://github.com/k3c0t/Facebook-Auto-Posting-Terjadwal) | ~28 | undetected-chromedriver | **AI caption (Gemini)**, VPS headless | **Active 2026**, no license |
| [ethanXWL/...auto-poster](https://github.com/ethanXWL/Python-Selenium-Facebook-group-auto-poster) | ~60 | Selenium | Script cổ điển image+text | Chết 2019, no license |
| [Mahdi-hasan-shuvo/facebook-automation-python](https://github.com/Mahdi-hasan-shuvo/facebook-automation-python) | ~25 | requests + BS4 | Toolkit (delete/invite/scrape) | Active, **GPL-3.0** |

Repo MIT (mượn code được, kèm ghi nguồn): [RootDev4/Facebook-Toolkit](https://github.com/RootDev4/Facebook-Toolkit),
[dylandjian/Facebook-group-bot](https://github.com/dylandjian/Facebook-group-bot),
[younes3334/marketplace-...Poster](https://github.com/younes3334/marketplace-facebook-group-Poster).

## Ma trận: nơi tool này DẪN / THIẾU

**DẪN (moat thật):**
- ✅ **Verifier bằng nick thứ 2 xác nhận bài lên công khai — KHÔNG đối thủ nào có.** Điểm bán mạnh nhất.
- ✅ Scheduler vận hành đầy đủ (interval/nhóm + khung giờ + giãn cách ngẫu nhiên) — đối thủ chỉ có delay đơn giản.
- ✅ Phát hiện rate-limit + checkpoint; proxy sẵn.
- ✅ Dashboard Flask + biểu đồ 14 ngày.
- ✅ Tìm nhóm + trợ giúp join (phần thu hút).

**THIẾU (nên bổ sung, xếp theo lợi/công):**
| Ưu tiên | Thiếu | Công / Lợi |
|---|---|---|
| 1 | Spintax `{chào\|hi\|alo}` chống trùng nội dung | Thấp / Cao |
| 2 | AI sinh nội dung (Claude/Gemini) | Thấp-TB / Cao |
| 3 | Đóng gói 1-click (PyInstaller/Docker) | TB / Cao |
| 4 | Multi-account + proxy rotation | Cao / Cao (mở gói agency) |
| 5 | Campaign save/load presets | Thấp / TB |

(CAPTCHA solving: cả ngách đều không có → parity, không phải gap.)

## Thương mại hoá

**Pháp lý (quan trọng):**
- ❌ KHÔNG copy code từ repo **GPL-3.0** (adar2, Mahdi, mig1984) → buộc mã nguồn mở, chết sản phẩm bán.
- ❌ Repo **"no license"** = all rights reserved → chỉ đọc lấy ý tưởng, KHÔNG copy code.
- ✅ Chỉ repo **MIT** mới mượn code được (kèm ghi nguồn). Giữ codebase clean-room.

**Mô hình kiếm tiền hợp tool:** thuê bao SaaS panel (hợp dashboard sẵn có) hoặc **dịch vụ managed/cho thuê theo tháng**
cho môi giới BĐS không tự cài. Bán bằng 3 điểm: "verified-live", "an toàn tài khoản" (safety engine), chuyên ngách BĐS.

**⚠️ Rủi ro phải nói thật với khách:** cả tool này lẫn ~toàn bộ đối thủ **vi phạm ToS Facebook** → rủi ro khóa nick.
Graph API "hợp lệ" nhưng KHÔNG cho đăng vào nhóm bất kỳ (đó là lý do ai cũng dùng browser automation).
Đừng bao giờ quảng cáo "không thể phát hiện / miễn khóa".

---

# ROADMAP đề xuất

- **GĐ1 — Ổn định (bắt buộc trước khi giao khách):** vá Top 3 + P1 còn lại. Worker không được chết âm thầm.
- **GĐ2 — Đóng gói:** script macOS/Windows 1-click thay `.bat`; ép đổi mật khẩu dashboard; bind `127.0.0.1` mặc định.
- **GĐ3 — Nâng cấp bán được:** Spintax → AI caption → gói agency multi-account + proxy rotation.

## Chuẩn bị để chạy (nhắc nhanh)
Python3 + venv + `playwright install chromium` · nick FB phụ đã join nhóm · ảnh vào `images/` ·
5-8 mẫu bài vào `content/` · đổi `contact_phone` (config.json) + đổi pass (dashboard/auth.json) ·
máy/VPS chạy nền liên tục (VPS cần proxy dân cư/4G VN).
⚠️ Máy Boss là **macOS** → `.bat` không chạy, phải gõ `venv/bin/python ...` thủ công hoặc chờ GĐ2.
