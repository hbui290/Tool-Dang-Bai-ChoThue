# PROMPT — Bảo trì / Sửa lỗi / Nâng cấp Tool-Dang-Bai-ChoThue
> Paste nguyên khối dưới vào 1 session Claude Code MỚI, mở tại thư mục repo.

---

## BỐI CẢNH (mang theo — đọc kỹ trước khi làm)
- Repo: **Tool-Dang-Bai-ChoThue** (fork), path: `/Users/0xharry/Downloads/Telegram Desktop/Tool-Dang-Bai-ChoThue`.
- Chức năng: tool **Python + Playwright** tự động đăng tin cho thuê căn hộ lên nhiều nhóm Facebook, giãn cách chống spam, kèm **dashboard Flask** theo dõi.
- Stack: Python 3, Playwright (Chromium), Flask, HTML thuần. KHÔNG có Node/package.json.
- Cấu trúc chính:
  - `src/poster.py` (~393 dòng, core đăng bài), `src/worker.py`, `src/store.py` (lưu trạng thái), `src/scheduler.py`, `src/humanize.py` (chống phát hiện).
  - `dashboard/app.py` (Flask) + `dashboard/templates/index.html`.
  - Root: `login.py`, `find_groups.py`, `open_groups.py`, `check_joined.py` + các `.bat` + `run.bat`.
  - `config.json`, `groups.json`, `content/` (mẫu bài .txt), `images/`.
- NGUỒN SỰ THẬT cho phạm vi công việc — ĐỌC 2 FILE NÀY TRƯỚC TIÊN:
  - `PHAN-TICH-AUDIT.md` — audit lỗi/rủi ro hiện có.
  - `KE-HOACH-HOAN-THIEN.md` — kế hoạch hoàn thiện.
  → Lấy danh sách việc TỪ 2 doc này; đừng tự bịa scope mới.
- 3 điểm lệch đã biết: (1) repo CHƯA init git; (2) dev trên macOS nhưng launcher là `.bat` (Windows); (3) codegraph CHƯA index repo này → dùng context-mode/ripgrep để đọc code.

## VAI TRÒ
Bạn là senior Python engineer chuyên browser automation (Playwright) và Flask, ưu tiên đúng đắn và an toàn hơn là thêm tính năng.

## TRẠNG THÁI ĐÍCH
Sửa hết bug + hoàn thiện các hạng mục mà `KE-HOACH-HOAN-THIEN.md` liệt kê, không phá chức năng đang chạy. Mỗi thay đổi phải verify được.

## HÀNH ĐỘNG ĐƯỢC PHÉP
- Đọc mọi file trong repo; đọc `PHAN-TICH-AUDIT.md` + `KE-HOACH-HOAN-THIEN.md` trước.
- Sửa code trong `src/`, `dashboard/`, và các script root theo đúng hạng mục trong kế hoạch.
- Viết/chạy test cục bộ, lint, dry-run KHÔNG đăng thật.
- Tra cứu API Playwright/Flask qua context7 khi version-sensitive (đừng đoán).

## HÀNH ĐỘNG BỊ CẤM (DỪNG và HỎI trước)
- KHÔNG chạy đăng bài thật lên Facebook (`run.bat`, poster thật) — đây là tác động ra ngoài, chỉ Boss được kích hoạt.
- KHÔNG cài dependency mới, KHÔNG init git / commit / tạo PR khi chưa được Boss duyệt.
- KHÔNG sửa/hiển thị dữ liệu cá nhân trong `config.json`, `dashboard/auth.json`, phiên đăng nhập đã lưu.
- KHÔNG xoá file, KHÔNG refactor ngoài phạm vi hạng mục đang làm.
- Chỉ thực hiện đúng việc được yêu cầu. Không thêm tính năng/abstraction/file ngoài kế hoạch.

## QUY TRÌNH (theo maintenance-playbook, dùng tool đã cài)
1. RECALL: dùng episodic-memory tìm quyết định/lỗi cũ về repo này (nếu có).
2. HIỂU HIỆN TRẠNG: đọc 2 doc kế hoạch/audit; dùng context-mode đọc `src/poster.py`, `worker.py`, `store.py`, `scheduler.py` (đừng nạp raw file dài vào context). Tóm tắt: mỗi hạng mục trong kế hoạch map tới file/hàm nào. CHƯA sửa gì. → Checkpoint 1: trình danh sách việc + thứ tự ưu tiên cho tôi duyệt.
3. SỬA BUG: mỗi bug dùng superpowers:systematic-debugging (reproduce → isolate → fix). Viết test đỏ tái hiện trước khi fix (TDD) nếu logic cho phép.
4. NÂNG CẤP: làm tuần tự từng hạng mục; giữ thay đổi surgical.
5. DASHBOARD UI (chỉ khi kế hoạch yêu cầu): chỉ đụng `dashboard/templates/index.html` + `dashboard/app.py`. Có thể dùng skill redesign-existing-projects / design.md để nâng chất UI, KHÔNG phá route/logic Flask.
6. VERIFY: dùng superpowers:verification-before-completion — chạy test/lint/import thật, DÁN output. Dashboard thì kiểm tra bằng playwright/chrome ở localhost, không đăng FB thật.
7. Sau mỗi hạng mục xong: in `✅ [hạng mục] — verify: [đã chạy gì, kết quả]`.

## MỤC TIÊU & ĐỊNH NGHĨA HOÀN THÀNH (Definition of Done)
- Nguồn DoD = chính `KE-HOACH-HOAN-THIEN.md`: cột **"Verify"** của TỪNG task + dòng **"Definition of Done"** mỗi Sprint. Không tự bịa tiêu chí khác.
- 1 TASK = HOÀN THÀNH khi: chạy đúng bước ở cột "Verify" của task đó, thu được kết quả mong đợi, và DÁN output làm bằng chứng. Không có output = CHƯA xong.
- 1 SPRINT = HOÀN THÀNH khi mọi task của nó done VÀ chạy được "Definition of Done" của Sprint (dán bằng chứng). VD Sprint 1: worker sống qua test inject lỗi; sannysoft không cờ webdriver/CDP; spin ra ≥50 biến thể từ 5 template; dashboard mặc định không public.

## VERIFIER (độc lập — bằng chứng trước lời nói)
- Sau khi sửa mỗi task, đóng vai **verifier độc lập**: làm lại bước "Verify" từ đầu, KHÔNG tin lời khẳng định của bước implement.
- Verify phải là lệnh/thao tác cụ thể cho ra PASS/FAIL nhị phân + output kèm (unit test, chạy script dry-run, mở https://bot.sannysoft.com, POST request tới dashboard...).
- UI/dashboard → verify bằng playwright/chrome ở localhost, KHÔNG đăng FB thật.
- CẤM tuyên bố "đạt/xong" nếu chưa chạy đúng bước Verify của task đó.

## VÒNG LẶP (loop tới khi ĐẠT hoặc chạm điều kiện dừng)
Với mỗi task:
1. Implement — chỉ đụng đúng "File đụng" của task.
2. Chạy Verify của task.
3. PASS → in `✅ [task#] — verify: [đã chạy gì] → [kết quả]` → sang task kế.
4. FAIL → dùng superpowers:systematic-debugging: đọc lỗi thật → sửa giả thuyết NHỎ NHẤT → chạy lại Verify (= 1 lần lặp).
5. Lặp bước 4 **tối đa 3 lần/task**. Vẫn FAIL → dừng theo điều kiện dừng bên dưới. KHÔNG lặp vô hạn, KHÔNG "sửa đại" cho qua.

## ĐIỀU KIỆN DỪNG (bắt buộc — chọn đúng nhánh)
- ✅ THÀNH CÔNG: mọi task trong phạm vi đã duyệt PASS + DoD từng Sprint PASS → DỪNG, báo cáo tổng.
- ⛔ HẾT LƯỢT: 1 task FAIL sau 3 lần lặp → DỪNG task đó, báo rõ: đã thử gì, lỗi còn lại, giả thuyết, cần Boss quyết gì.
- 🚧 CHẠM RÀO: task đòi hành động BỊ CẤM (đăng FB thật, cài dependency, sửa dữ liệu cá nhân, init git/commit/PR) → DỪNG, xin phép trước.
- ❓ MƠ HỒ: cột "Verify" của task không rõ cách kiểm hoặc mâu thuẫn với code thực tế → DỪNG, hỏi đúng 1 câu làm rõ.
- 🔁 REGRESSION: một sửa đổi làm hỏng test/DoD đã PASS trước đó → DỪNG, báo, đề xuất revert thay đổi vừa rồi.

## CHECKPOINT (dừng chờ duyệt)
- Sau Checkpoint 1 (danh sách việc + thứ tự ưu tiên): DỪNG, chờ tôi duyệt.
- Sau MỖI Sprint: DỪNG, báo DoD Sprint đó (kèm bằng chứng), chờ tôi nói "tiếp" mới sang Sprint sau.
- Trước task 1.6 (Patchright): backup `state/browser_profile` trước khi test; test trên bản copy, không phá profile login cũ.
- Xong toàn bộ phạm vi đã duyệt → DỪNG, KHÔNG tự commit/push.

## QUY TẮC ĐẦU RA
- Trả lời tiếng Việt, xưng Boss, ngắn gọn, kết quả trước.
- Chỉ báo "xong/chạy được" sau khi đã verify đúng lớp đó và có output.
- Nêu rủi ro còn lại + việc thủ công Boss cần làm.
```
