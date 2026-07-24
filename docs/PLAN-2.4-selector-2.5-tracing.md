# Plan — Sprint 2.4 (selector bền) + 2.5 (tracing debug)

Ngày: 2026-07-24. Scope chốt với Boss: chỉ 2.4 + 2.5. **Bỏ** verifier (Item 3) và Sprint 3.
Công cụ: viết plan theo superpowers, review bằng ECC python-reviewer.

## Bối cảnh (đã kiểm chứng)
- `poster.py` (418 dòng) đã bán-bền: dùng `div[role='button']` + `has_text`, `aria-label`, song ngữ VN/EN;
  đã có `get_by_role("button")` ở nhánh submit câu hỏi (dòng 225).
- `config.json` có `debug_trace` + `debug_video` nhưng **chưa wire** vào worker.
- QA runtime Sprint 1+2 đã PASS; worker systemd chạy 24/7 (paused).

## Mục tiêu & tiêu chí
Selector then chốt ổn định hơn (auto-wait) và có công cụ soi lỗi checkpoint, **không đổi hành vi đăng**.

## Các bước

### 2.4 — Selector bền hơn (poster.py)
1. Ô composer trigger `_find_composer_trigger`: thêm nhánh `page.get_by_role("button", name=<text>)`
   thử trước, fallback về `locator("div[role='button']", has_text=…)` cũ.
   → verify: đăng test vẫn mở được composer (VN UI).
2. Nút Ảnh/video + nút Đăng: ưu tiên `get_by_role("button", name=…)` / `get_by_label`, giữ fallback cũ.
   → verify: bài test đính ảnh + bấm Đăng thành công.
- Nguyên tắc: **thêm nhánh ưu tiên, GIỮ fallback cũ** → không regression nếu get_by_role trượt.

### 2.5 — Tracing/video debug (worker.py main)
3. Trong `main()` lúc `launch_persistent_context`: nếu `config.debug_video` → thêm `record_video_dir`.
   Sau khi mở context: nếu `config.debug_trace` → `context.tracing.start(screenshots=True, snapshots=True)`.
   Khi thoát/lỗi checkpoint → `context.tracing.stop(path=state/trace_<ts>.zip)`.
   → verify: bật `debug_trace=true` chạy 1 nhịp → có file trace trong state/.

### Kiểm chứng cuối
4. scp poster.py + worker.py lên VPS, `python -m py_compile`.
5. Đăng lại 1 bài [TEST] (Boss đã cho phép) → xác minh selector mới OK, dialog đóng (A1).
6. ECC `python-reviewer` soi diff.
7. Khôi phục config debug về false, worker về paused.

## Rủi ro
- get_by_role trượt do FB đổi accessible name → fallback cũ đỡ. Không regression.
- Test đăng tạo thêm 1 post [TEST] trong nhóm QA (Boss xoá sau).
