# Kế hoạch hoàn thiện — Tool Đăng Bài Cho Thuê (FB Group Auto-Poster)

> Bản thiết kế thi công. Lập 2026-07-22. Nguồn: audit lỗi (read-only) + research đối thủ + research kỹ thuật.
> Đọc kèm: [PHAN-TICH-AUDIT.md](./PHAN-TICH-AUDIT.md).
> Nguyên tắc: (1) không "enterprise hoá" tool 1 nick; (2) không đổi fingerprint/trình duyệt cho nick già đã login; (3) mỗi thay đổi đều có bước verify; (4) không đụng logic đăng bài trừ khi task yêu cầu.

---

## 1. Mục tiêu

| Mục tiêu | Đo bằng |
|---|---|
| Tool chạy nền **không chết âm thầm** | Worker sống qua ≥48h liên tục dù có lỗi lẻ; lỗi 1 bài không dừng cả tiến trình |
| **Khó bị Facebook gắn cờ bot** hơn | Vá lỗ CDP; có di chuyển chuột; nội dung không trùng lặp |
| **An toàn tài khoản** | Circuit breaker dừng khi lỗi liên tiếp; backoff khi checkpoint; cap/ngày |
| **Bán/cho thuê được** | Đóng gói 1-click; dashboard bảo mật; codebase clean-room (không dính GPL) |

Phạm vi: **1 tài khoản** (multi-account để dành, ngoài scope). Nền tảng đích: Windows (bán) + macOS (Boss dev).

---

## 2. Trạng thái hiện tại (tóm tắt)

- **Stack:** Python + Playwright `launch_persistent_context` (headed, profile lưu sẵn), Flask dashboard, state = JSON files.
- **Điểm mạnh giữ nguyên:** verifier bằng nick 2 (moat), scheduler theo nhóm, phát hiện rate-limit/checkpoint, proxy, dashboard + biểu đồ.
- **Sạch bảo mật:** không network call ra ngoài, không backdoor.
- **Yếu chí mạng:** vòng lặp worker chỉ bắt 2 loại lỗi → mọi lỗi khác giết tiến trình. Dashboard ghi JSON không nguyên tử → race. Đăng nhầm file hướng dẫn. Lỗ CDP chưa vá. Không có di chuyển chuột. `.bat` Windows-only.

---

## 3. Kiến trúc đích

```
                    ┌─────────────────────────────┐
                    │  dashboard/app.py (Flask)    │
                    │  - ghi state QUA store._write_json (atomic)
                    │  - bind 127.0.0.1 mặc định   │
                    │  - SSE thay polling (P3)     │
                    └──────────────┬──────────────┘
                                   │ đọc/ghi (atomic)
        state/ (JSON nhỏ: config, groups, control, commands)
        state/posted_log → SQLite WAL khi >vài nghìn dòng (P3)
                                   │
                    ┌──────────────┴──────────────┐
                    │  src/worker.py               │
                    │  while True:                 │
                    │    try: <thân loop>          │
                    │    except Exception: log+continue   ← catch-all
                    │    - circuit breaker (K fails → pause)
                    │    - backoff+jitter khi checkpoint  │
                    │    - cap/ngày                │
                    └──────────────┬──────────────┘
                                   │ dùng
     ┌─────────────┬──────────────┼───────────────┬──────────────┐
  poster.py     scheduler.py   humanize.py     content/        Patchright
  (Patchright)  (spintax,      (mouse bezier,  (spintax +      (thay Playwright,
  getByRole     dedup, cap)    typing thật)    AI fallback)    vá lỗ CDP)
```

Thay đổi cốt lõi: **Playwright → Patchright** (drop-in), **JSON ghi nguyên tử toàn bộ**, **worker có catch-all + circuit breaker + backoff**, **content có spintax**, **humanize có di chuyển chuột**.

---

## 4. Roadmap thi công

Ký hiệu effort: L (≤1h), M (nửa ngày), H (≥1 ngày). Mỗi task ghi rõ **file đụng** và **verify**.

### SPRINT 1 — Ổn định + an toàn (ưu tiên tuyệt đối, ~nửa ngày)
> Mục tiêu: worker không chết, không đăng nhầm, đóng lỗ bot lớn nhất, nội dung không trùng. Không đụng luồng đăng.

| # | Task | File đụng | Verify | Effort |
|---|------|-----------|--------|--------|
| 1.1 | **Catch-all vòng lặp worker**: bọc thân `while True` bằng `except Exception` → `log_print` + `time.sleep(LOOP_SECONDS)` + `continue`. Giữ nguyên nhánh `RateLimitError`/`CheckpointError` | src/worker.py (~186-236) | Inject lỗi giả (đổi 1 group url rác) → worker log lỗi rồi chạy tiếp, không thoát | L |
| 1.2 | **Đưa `pick_content`/`pick_images` vào trong try của do_post**; lỗi → ghi status error + `continue`, không ném ra loop | src/worker.py:32-33,47 | Xoá hết ảnh trong `images/` → worker báo lỗi 1 nhịp, vẫn sống | L |
| 1.3 | **Loại file `_`-prefix khỏi template picker**: `CONTENT_DIR.glob("[!_]*.txt")` | src/scheduler.py:96 | `pick_content()` chạy 50 lần không bao giờ trả `_HUONG_DAN.txt` | L |
| 1.4 | **Ghi nguyên tử ở dashboard**: `save_groups` + `update_config` gọi `store._write_json` thay `write_text` | dashboard/app.py:49-50,127-128 | Vòng lặp bấm toggle + Lưu config 100 lần trong khi worker chạy → không JSONDecodeError | L |
| 1.5 | **Validate `update_config`**: kiểm tra `posting_hours_*` đúng `HH:MM`, `max_posts_per_day`/`repost_interval_minutes` là int ≥0; sai → trả 400, không ghi | dashboard/app.py:124-128 | POST `posting_hours_start="7am"` → 400, config không đổi, worker không chết | L |
| 1.6 | **Patchright drop-in**: `pip install patchright && patchright install chrome`; đổi import ở 3 chỗ (`login.py`, `worker.py`, `find_groups.py`, `open_groups.py`) sang `from patchright.sync_api import sync_playwright`; thêm `channel="chrome"`; **bỏ** custom user-agent nếu có; **bỏ `--no-sandbox`** trên desktop | login.py, src/worker.py, find_groups.py, open_groups.py, requirements.txt | Mở https://bot.sannysoft.com hoặc test CDP `Runtime.enable` → không lộ webdriver/CDP; login FB vẫn vào được profile cũ | L-M |
| 1.7 | **Spintax tự viết** (~30 dòng đệ quy `{a\|b\|c}`, hỗ trợ lồng nhau) trong `src/spintax.py`; `pick_content` spin nội dung trước khi trả | src/spintax.py (mới), src/scheduler.py | Unit test: `spin("{a\|b}")` ra 'a' hoặc 'b'; template lồng ra đúng số biến thể | L |
| 1.8 | **Circuit breaker**: đếm fail liên tiếp; ≥K (mặc định 3) → `store.set_paused(True)` + alert dashboard, dừng đăng chờ resume tay | src/worker.py | Giả lập 3 lỗi liên tiếp → worker tự pause, dashboard hiện cảnh báo | L |
| 1.9 | **Backoff + jitter thay sleep cứng**: khi checkpoint/rate-limit, nghỉ = `min(base*2^n, cap)` với **Equal Jitter** (không Full Jitter); reset khi 1 bài thành công | src/worker.py (nhánh RateLimit/Checkpoint) | Log cho thấy lần nghỉ tăng dần theo số lần liên tiếp, có nhiễu | L |
| 1.10 | **Cap/ngày cứng**: nếu `max_posts_per_day>0` và đạt → dừng đăng tới hôm sau (đã có van, kiểm lại + log rõ) | src/scheduler.py:61-63 | Set cap=2 → đăng đúng 2 bài/ngày rồi nghỉ | L |
| 1.11 | **Ép đổi mật khẩu + bind localhost**: dashboard mặc định `host=127.0.0.1`; nếu `auth.json` còn pass mặc định → in cảnh báo đỏ, chặn bind `0.0.0.0` | dashboard/app.py:151, auth.json | Chạy với pass mặc định → tool từ chối mở public, hướng dẫn đổi | L |

**Definition of Done Sprint 1:** worker sống qua test chạy 24h có inject lỗi; sannysoft không cờ webdriver/CDP; spin ra ≥50 biến thể từ 5 template; dashboard không public khi pass mặc định.

### SPRINT 2 — Hành vi người thật hơn (~nửa ngày → 1 ngày)
> Mục tiêu: giảm tín hiệu bot hành vi mà FB soi mạnh nhất.

| # | Task | File đụng | Verify | Effort |
|---|------|-----------|--------|--------|
| 2.1 | **Di chuyển chuột bezier**: dùng `python-ghost-cursor` (sync PW) hoặc thuật toán wind-mouse; mọi click quan trọng = move-then-click | src/humanize.py, src/poster.py | Ghi video (PW `record_video`) → thấy cursor di chuyển cong trước khi click | M |
| 2.2 | **Gõ phím thật hơn**: cụm nhanh + dừng ở ranh giới từ + ~2% gõ sai rồi backspace; đọc `contact_phone` động (không đóng băng lúc import) | src/humanize.py, src/poster.py:131 | Đổi số điện thoại lúc worker đang chạy → bài sau dùng số mới, không cần restart | M |
| 2.3 | **Thay `wait_for_timeout` cố định** bằng `expect(locator).to_be_visible()` / auto-wait ở các bước then chốt | src/poster.py | Chạy đăng test → không còn sleep cứng ở bước tìm composer/dialog/nút Đăng | M |
| 2.4 | **Selector bền hơn**: chuyển `has_text` sang `get_by_role()`/`get_by_label` chỗ nào FB hỗ trợ | src/poster.py | Test đăng vẫn tìm được composer khi đổi ngôn ngữ UI VN↔EN | M |
| 2.5 | **Debug switch**: cờ bật `context.tracing`/`record_video` để soi lỗi checkpoint | src/worker.py, config.json | Bật cờ → có file trace/video khi lỗi | L |
| 2.6 | **Near-dup check**: trước khi đăng, so text ứng viên với `posted_log` gần đây (trigram + Jaccard, stdlib); trùng cao → spin lại | src/scheduler.py, src/store.py | Ép 2 lần cùng text vào 1 nhóm → lần 2 bị spin khác đi | M |

### SPRINT 3 — Đóng gói bán + nâng chất lượng (~1-2 ngày)
> Mục tiêu: sản phẩm bán/cho thuê được cho khách không rành tech.

| # | Task | File đụng | Verify | Effort |
|---|------|-----------|--------|--------|
| 3.1 | **Script chạy đa nền tảng**: `.command`/`.sh` cho macOS + giữ `.bat` Windows; hoặc 1 `run.py` menu | * (mới) | Trên macOS double-click `.command` chạy được login/worker/dashboard | M |
| 3.2 | **Đóng gói PyInstaller + Inno Setup** (Windows): `PLAYWRIGHT_BROWSERS_PATH=0` để bundle Chromium; wrap installer double-click | build/ (mới) | Cài trên máy Windows sạch (không Python) → chạy được | M-H |
| 3.3 | **SQLite (WAL) cho `posted_log`** khi log lớn; config/groups giữ JSON | src/store.py | Worker ghi + dashboard đọc đồng thời không khoá; query "hôm nay" nhanh | M |
| 3.4 | **Dashboard: SSE thay polling 20s** (Flask `text/event-stream`) + **Chart.js/uPlot** thay bar CSS | dashboard/app.py, templates/index.html | Log/status cập nhật tức thì; biểu đồ có tooltip | M |
| 3.5 | **AI caption (tuỳ chọn)**: sinh biến thể qua Claude/Gemini; **spintax là fallback** khi thiếu/lỗi key | src/content_ai.py (mới), config.json | Có key → caption AI; xoá key → tự động dùng spintax, không lỗi | M |
| 3.6 | **pywebview** (tuỳ chọn) mở dashboard trong cửa sổ native thay vì bảo khách mở trình duyệt | run.py | Double-click → cửa sổ app hiện dashboard | L |

---

## 5. Chi tiết kỹ thuật các thay đổi cốt lõi

**Patchright (1.6):** bản Playwright vá lỗ CDP `Runtime.enable` — thứ `--disable-blink-features=AutomationControlled` KHÔNG vá (nó chỉ giấu `navigator.webdriver`). Drop-in, giữ nguyên `launch_persistent_context`. **Giữ persistent context, KHÔNG đổi sang `storage_state`** (profile đầy đủ làm nick trông thật).

**KHÔNG làm về fingerprint:** không camoufox/nodriver/undetected-chromedriver, không randomize UA/canvas/WebGL. Nick già đã login → đổi fingerprint là tự bắn vào chân.

**Circuit breaker + backoff (1.8-1.9):** state machine đơn giản, không cần lib (`pybreaker` overkill). Backoff dùng **Equal Jitter** hoặc **Decorrelated Jitter**, tránh **Full Jitter** (có thể tụt về ~0 đúng lúc cần nghỉ lâu). Nguồn: AWS "Exponential Backoff and Jitter".

**Ghi nguyên tử (1.4):** `store._write_json` đã có sẵn (tempfile + `os.replace`) — chỉ cần dashboard dùng nó. Worker vốn đã an toàn.

---

## 6. Rủi ro & License (quan trọng khi bán)

| Rủi ro | Xử lý |
|---|---|
| **Lib spintax GPL** (AceLewis) làm "nhiễm" GPL sản phẩm bán | **Tự viết ~30 dòng**, không import lib GPL |
| Copy code từ repo GPL (adar2/mig1984/Mahdi) | Tuyệt đối không copy; chỉ đọc lấy ý tưởng |
| Repo "no license" | All rights reserved → chỉ tham khảo, không copy code |
| Lib dùng an toàn | Patchright (Apache-2.0), ghost-cursor (MIT), Chart.js/uPlot (MIT), sqlite3 (stdlib) ✅ |
| FB đổi UI phá selector | Sprint 2.4 (getByRole) + 2.5 (tracing) giảm rủi ro |
| Vi phạm ToS FB → khóa nick | Không phải lỗi tool; disclaim với khách; dùng nick phụ + proxy dân cư; **không quảng cáo "miễn khóa"** |
| Patchright login lại/mất profile | Test 1.6 trên profile copy trước; giữ backup `state/browser_profile` |

---

## 7. Ngoài phạm vi (cố ý KHÔNG làm)

Token/leaky bucket · FastAPI (Flask đủ) · multi-account (chờ business cần) · Electron/Tauri (đã có Chromium) · lib datasketch/pybreaker (tự viết 15-30 dòng) · đổi fingerprint/camoufox/nodriver · Graph API (không cho đăng nhóm bất kỳ).

---

## 8. Thứ tự khuyến nghị

1. **Backup** `state/browser_profile` + toàn repo trước khi sửa.
2. **Sprint 1** trọn gói (ổn định + an toàn) — lợi cao nhất, rủi ro thấp, không đụng luồng đăng.
3. Chạy thử 24-48h giám sát → xác nhận worker sống + không bị flag.
4. **Sprint 2** (hành vi người) khi Sprint 1 ổn định.
5. **Sprint 3** khi quyết định thương mại hoá.

Mỗi Sprint làm trên nhánh/bản copy riêng, verify xong mới gộp. Không chạy sản xuất trên nick chính.
