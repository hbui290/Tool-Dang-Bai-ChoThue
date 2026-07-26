# SCOPE — Tool Đăng Bài Cho Thuê (FB Group Auto-Poster)

> Tài liệu phạm vi + kiến trúc. Đọc kèm: [README.md](README.md) (hướng dẫn dùng),
> [PHAN-TICH-AUDIT.md](PHAN-TICH-AUDIT.md) (audit lỗi + research đối thủ),
> [KE-HOACH-HOAN-THIEN.md](KE-HOACH-HOAN-THIEN.md) (roadmap thi công).

---

## 1. Goal — Mục tiêu dự án

Tự động đăng tin **cho thuê / bán căn hộ** vào **nhiều nhóm Facebook** cùng lúc, thay cho
việc copy–paste thủ công, với 3 ràng buộc bắt buộc:

| Mục tiêu | Đo bằng |
|---|---|
| **Đăng đều, không bị coi là spam** | Mỗi nhóm 1 đồng hồ riêng (`repost_interval`), giãn cách + nhiễu, spintax đổi câu, mô phỏng người thật |
| **Chạy nền không chết âm thầm** | Worker sống qua lỗi bất kỳ (catch-all), tự pause khi hỏng, có heartbeat để dashboard biết còn sống |
| **An toàn tài khoản** | Dừng ngay khi checkpoint/mất session; backoff khi bị giới hạn tần suất; cap bài/ngày |
| **Số liệu trung thực** | Không tự nhận "đã lên"; kiểm chứng công khai bằng **nick phụ** mới tính `live` |

---

## 2. Scope — Trong / Ngoài phạm vi

**TRONG phạm vi:**
- Đăng text + ảnh vào nhóm đã tham gia; trả lời câu hỏi vào nhóm (chủ nhà/khách thuê).
- Lên lịch, giãn cách, quota ngày, xoay vòng nội dung.
- Dashboard web theo dõi + điều khiển (pause/resume/đăng ngay/kiểm chứng).
- Bộ script phụ trợ tìm & xác nhận nhóm đã join.

**NGOÀI phạm vi (cố ý):**
- **Không tự bấm "Tham gia nhóm"** — người dùng tự join tay (tránh FB hạn chế).
- **Không vượt captcha / checkpoint** — gặp là dừng, chờ người xử lý.
- **Không đảm bảo bài được duyệt** — phụ thuộc admin từng nhóm.
- Ưu tiên **Windows** (`.bat`); máy khác chạy `python` trực tiếp là được.

> ⚠️ **Rủi ro nền tảng:** tự động đăng vi phạm ToS Facebook → tài khoản có thể bị hạn chế.
> Nên dùng nick phụ + proxy dân cư/4G VN. Đây là rủi ro vận hành, không phải lỗi code.

---

## 3. Có bao nhiêu thành phần? — Đếm cấu tạo

**Tổng: 6 module lõi + 4 script setup + 1 dashboard + 5 launcher + data/config + 5 tài liệu.**

### 3.1 — Lõi xử lý (`src/`, 6 module · ~1.500 dòng)

| # | Module | Vai trò |
|---|---|---|
| 1 | [`worker.py`](src/worker.py) | **Bộ não.** Vòng lặp nền 45s: sở hữu trình duyệt, điều phối đăng bài theo lịch, nhận lệnh từ dashboard, định kỳ kiểm chứng công khai. Chứa circuit breaker + backoff. |
| 2 | [`poster.py`](src/poster.py) | **Tay đăng bài.** Đăng 1 bài (text+ảnh) vào 1 nhóm bằng Playwright; mở composer, upload ảnh, trả lời câu hỏi nhóm, phát hiện `Checkpoint`/`NotLoggedIn`/`RateLimit`. |
| 3 | [`scheduler.py`](src/scheduler.py) | **Bộ lịch.** Chọn nhóm quá hạn lâu nhất, quota ngày, giãn cách, chọn content/ảnh, near-dup check (Jaccard trigram). |
| 4 | [`store.py`](src/store.py) | **Bộ nhớ chung.** Đọc/ghi state (status/control/commands/log) an toàn liên tiến trình: `flock` + atomic rename. Hàm thống kê cho dashboard. |
| 5 | [`spintax.py`](src/spintax.py) | **Máy sinh biến thể.** Cú pháp `{a\|b\|c}` (lồng nhau) → mỗi bài 1 câu chữ khác nhau, giảm trùng lặp. |
| 6 | [`humanize.py`](src/humanize.py) | **Lớp giả người.** Di chuột đường cong (wind-mouse), gõ phím có nhịp + gõ sai/xóa, cuộn trang trước khi đăng. |

### 3.2 — Script setup nhóm (4, chạy tay 1 lần)

| # | Script | Vai trò |
|---|---|---|
| 1 | [`login.py`](login.py) | Mở Chrome để tự đăng nhập FB → lưu session vào `state/browser_profile`. |
| 2 | [`find_groups.py`](find_groups.py) | Tìm nhóm theo `KEYWORDS` → `groups_found.json` (sắp theo số thành viên). |
| 3 | [`open_groups.py`](open_groups.py) | Mở loạt nhóm để người dùng tự bấm "Tham gia". |
| 4 | [`check_joined.py`](check_joined.py) | Quét "Nhóm của bạn" → thêm nhóm đã join vào `groups.json` (`enabled:true`). |

### 3.3 — Dashboard (Flask, 1 app)

- [`dashboard/app.py`](dashboard/app.py) — REST API + Basic Auth. Route: `/api/status`, `/api/stats`, `/api/groups`, `/api/posts`, `/api/config`, `/api/command`, `/api/groups/toggle`, `/screenshots/*`. Từ chối mở ra ngoài nếu mật khẩu còn mặc định.
- `dashboard/templates/index.html` — giao diện xem số liệu + nút điều khiển.
- `dashboard/auth.json` — user / password / port (gitignored).

### 3.4 — Launcher Windows (5 `.bat`)
`login.bat` · `find_groups.bat` · `open_groups.bat` · `check_joined.bat` · `run.bat` — set UTF-8, `cd` về thư mục tool, gọi `venv\Scripts\python.exe`.

### 3.5 — Cấu hình & dữ liệu

| File / thư mục | Vai trò |
|---|---|
| `config.json` (runtime, gitignored) · [`config.json.example`](config.json.example) | Toàn bộ tham số: giờ đăng, interval, quota, số ảnh, proxy, verifier, backoff… |
| `groups.json` | Nhóm đang bật đăng bài (`enabled`). |
| `groups_shortlist.json` / `groups_found.json` | Dữ liệu workflow tìm & chọn nhóm (sinh ra khi dùng). |
| `content/*.txt` | 5–8 mẫu bài (có spintax); `_HUONG_DAN.txt` là hướng dẫn. |
| `images/` | Ảnh căn hộ đính kèm. |
| `state/` | `status.json`, `control.json`, `commands.json`, `posted_log.json`, `screenshots/`, `deadletter_posts.jsonl`, `browser_profile/`, `trace-*.zip`. |

### 3.6 — Tài liệu (5)
[`README.md`](README.md) · [`PHAN-TICH-AUDIT.md`](PHAN-TICH-AUDIT.md) · [`KE-HOACH-HOAN-THIEN.md`](KE-HOACH-HOAN-THIEN.md) · [`Tool-Dang-Bai-prompt.md`](Tool-Dang-Bai-prompt.md) · [`docs/PLAN-2.4-selector-2.5-tracing.md`](docs/PLAN-2.4-selector-2.5-tracing.md).

---

## 4. Cấu trúc — Kiến trúc 2 tiến trình

Hai tiến trình chạy song song, **không gọi trực tiếp nhau**, chỉ giao tiếp qua **file JSON
trong `state/`** với khoá liên-tiến-trình (`flock`) + ghi nguyên tử (atomic rename).

```
        ┌──────────────────────────┐          ┌───────────────────────────┐
        │   WORKER  (run.bat)      │          │   DASHBOARD (app.py)      │
        │   vòng lặp nền 45s       │          │   Flask + Basic Auth      │
        ├──────────────────────────┤          ├───────────────────────────┤
        │ ghi: status.json ────────┼───────▶  │ đọc → hiển thị heartbeat  │
        │      posted_log.json ────┼───────▶  │ đọc → /api/stats,/groups  │
        │ đọc: control.json  ◀─────┼──────────┼─ ghi: pause / resume      │
        │      commands.json ◀─────┼──────────┼─ ghi: post_now/refresh    │
        │      config.json   ◀─────┼───┬──────┼─ ghi: chỉnh (đã validate) │
        └───────────┬──────────────┘   │      └───────────────────────────┘
                    │ sở hữu             │ dùng chung (chỉ đọc)
                    ▼                    ▼
        ┌──────────────────────┐   ┌──────────────────┐
        │ Chrome (Patchright)  │   │  config.json     │
        │ state/browser_profile│   │  groups.json     │
        └──────────┬───────────┘   └──────────────────┘
                   ▼
             facebook.com/groups/*
```

**Luồng đăng 1 bài (worker):**
`load_config` → `handle_commands` → `pick_overdue_group` (nhóm tới hạn) →
`pick_unique_content` + `pick_images` → `poster.post_to_group`
(goto → composer → gõ text kiểu người → upload ảnh → Đăng → trả lời câu hỏi nhóm) →
ghi `posted_log.json` → tính giãn cách → hẹn bài kế.

**Luồng kiểm chứng công khai (định kỳ/khi rảnh):**
Mở **nick phụ** (`verifier_profile`) → vào trang bài của nick chính trong nhóm →
thấy SĐT liên hệ = `live`, không thấy = `pending`. Đây là nguồn số liệu **trung thực** duy nhất.

---

## 5. Vì sao "mượt / hoàn thiện" — Các cơ chế an toàn

Đã có sau Sprint 1 (xem [KE-HOACH-HOAN-THIEN.md](KE-HOACH-HOAN-THIEN.md)):

| Cơ chế | Chống điều gì | Ở đâu |
|---|---|---|
| **Catch-all vòng lặp** | 1 lỗi lạ giết cả worker | `worker.loop_once` |
| **Circuit breaker** | Đăng lỗi liên tiếp âm thầm → tự pause + alert sau N lần | `worker` + `max_consecutive_fails` |
| **Backoff + Equal Jitter** | Bị giới hạn tần suất → nghỉ dài dần, có nhiễu | `worker` (`RateLimitError`) |
| **Dừng khi checkpoint / mất session** | Cố thử tiếp làm nick nặng thêm | `poster._check_account_state` |
| **Atomic write + `flock`** | Race giữa 2 tiến trình, đọc file dở | `store._write_json`, `_file_lock` |
| **Dead-letter** | Mất record bài đã đăng → đăng trùng | `worker._safe_append` |
| **Humanize + spintax + near-dup + proxy** | Bị FB gắn cờ bot / trùng nội dung | `humanize`, `spintax`, `scheduler` |
| **Verify bằng nick phụ** | Tự nhận "đã lên" sai sự thật | `worker.verify_public` |

**Trạng thái worker** (dashboard đọc từ `status.json`):
`running` · `posting` · `idle` (ngoài giờ) · `paused` · `rate_limited` · `checkpoint` · `warning` · `error`.

---

## 6. Tình trạng hiện tại & việc còn lại

Đợt rà soát này vá **25 lỗi** qua 2 vòng review độc lập, kiểm chứng bằng
[`verify.py`](verify.py) — 30 mục, chạy lại được, tự gọi
[`verify_dashboard.py`](verify_dashboard.py) (11 test hành vi HTTP thật) khi có venv+Flask.

**Chặn ngay khi clone (P0) — 4:** thiếu `config.json.example`; thiếu `images/.gitkeep`;
README bảo mở `config.json` / `dashboard/auth.json` mà clone mới không có 2 file đó
(`app.py` đọc `auth.json` lúc import → `FileNotFoundError`); dead-letter không có nơi
đọc lại → mất record bài **đã đăng** làm `pick_overdue_group` coi nhóm "chưa từng đăng"
và đăng trùng sau ~45–90s (nay `_safe_append` thất bại thì tự pause + alert).

**Làm sập / báo sai số liệu (P1) — 12:** bracket-access log gây 500
(`scheduler`/`store`/`worker`); `request.json`=None gây 500 (dashboard);
`pick_images` ném `ValueError` khi số ảnh ít hơn `images_per_post_min` (mọi lượt đăng
lỗi → circuit breaker tự pause ngày đầu); screenshot/video/trace phình vô hạn → đầy đĩa
(nay giữ tối đa 300 ảnh, 20 video, 10 trace gần nhất); retry lúc khởi động `break` vô điều kiện nên `uid`
rỗng làm verify tắt âm thầm cả vòng đời tiến trình; 1 lệnh dashboard lỗi cuốn theo các
lệnh còn lại đã bị pop khỏi hàng đợi; `n_fail` không reset khi Resume → chỉ 1 lỗi mới là
tự pause lại; race read-modify-write ở dashboard `toggle`/`config`; `check_joined.py` ghi
`groups.json` bằng snapshot cũ → đè mất thay đổi từ dashboard; bảng theo-nhóm hiện `0`
tương tác thay vì "—" (chưa đo) → kết luận sai về hiệu quả nội dung; `verify.py` hardcode
ngày → FAIL giả từ hôm sau; `verify.py` đếm chuỗi bề mặt thay vì kiểm `or {}` thật.

**Nhỏ hơn (P2) — 6:** `check_joined.py` lệch stealth → đồng bộ `patchright`; regex
`group_id` lệch giữa `open_groups`/`check_joined` và `poster` (link FB mobile có `?ref=`
→ nhận diện "đã join" sai); so mật khẩu dashboard không hằng-thời-gian; `compare_digest`
trên `str` non-ASCII ném `TypeError` → mật khẩu tiếng Việt làm mọi request 500;
`post_now` thiếu `group_url` bị nuốt im lặng dù UI báo "đã gửi lệnh"; README trỏ
`content/bai-mau-1.txt` không tồn tại.

**Vòng review thứ 2 (soát chính các bản vá trên) — 3:** alert "mất record bài đã đăng"
bị `write_status` cuối `loop_once` **ghi đè xoá mất** ngay trong cùng lượt (vì cờ `paused`
đọc từ đầu vòng; `write_status` ghi đè nguyên file, không merge) → nay đọc lại
`store.is_paused()` trước khi ghi; nhánh tự-pause thất bại thì `except: pass` nuốt im
lặng khiến cơ chế chống-đăng-trùng hỏng mà không ai biết → nay log rõ; `pick_images`
âm thầm bỏ qua `images_per_post_min` khi cấu hình gõ nhầm `max < min` (trước đây crash
nên lộ lỗi ngay) → nay cảnh báo.

**Dead code — ĐÃ XOÁ (Boss quyết):** 3 hàm (`scheduler.next_delay_seconds`,
`poster.read_engagement`, `poster.find_user_post_in_group`) — giá trị tính năng thấp,
không kiểm chứng được vì cần session Facebook thật; cần lại thì lấy từ git history.

**Dọn video/trace debug:** lúc khởi động, worker giữ tối đa 20 video
(`state/debug_video/*.webm`) và 10 trace (`state/trace-*.zip`) gần nhất — bật debug
quên tắt không làm đầy đĩa VPS.
