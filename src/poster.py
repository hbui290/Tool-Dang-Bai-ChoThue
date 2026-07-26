"""Đăng 1 bài (text + ảnh) vào 1 nhóm Facebook bằng Playwright."""
import re
import time
from datetime import datetime
from pathlib import Path

from patchright.sync_api import TimeoutError as PWTimeout

import humanize

ROOT = Path(__file__).resolve().parent.parent
SCREENSHOT_DIR = ROOT / "state" / "screenshots"

# Các mẫu text/aria-label theo cả giao diện tiếng Việt và English
COMPOSER_TRIGGER_TEXTS = [
    "Bạn viết gì đi",
    "Viết gì đó",
    "Write something",
    "What's on your mind",
]
PHOTO_BUTTON_LABELS = ["Ảnh/video", "Photo/video", "Ảnh/Video"]
POST_BUTTON_LABELS = ["Đăng", "Post"]
PENDING_TEXTS = [
    "đang chờ quản trị",
    "đang chờ được phê duyệt",
    "chờ phê duyệt",
    "pending approval",
    "waiting for approval",
]


def group_id_from_url(url: str) -> str:
    m = re.search(r"/groups/([^/?#]+)", url)
    return m.group(1) if m else url


class CheckpointError(Exception):
    """Facebook đòi xác minh tài khoản — phải dừng toàn bộ ngay."""


class NotLoggedInError(Exception):
    """Chưa đăng nhập Facebook — cần chạy login.py."""


class RateLimitError(Exception):
    """Facebook cảnh báo giới hạn tần suất — cần lùi nhịp, KHÔNG cố thử tiếp."""


# Chuỗi Facebook hiện khi bị giới hạn tần suất (spam throttle)
RATE_LIMIT_TEXTS = [
    "giới hạn tần suất",
    "để bảo vệ cộng đồng khỏi spam",
    "bạn có thể thử lại sau",
    "we limit how often",
    "try again later",
]


SCREENSHOT_KEEP = 300      # giữ tối đa N ảnh debug gần nhất


def _prune_screenshots(keep: int = SCREENSHOT_KEEP):
    """Xoá ảnh debug cũ vượt hạn mức.

    Worker chạy nền vô hạn (VPS, nhiều tháng) và MỌI lỗi đăng đều sinh 1 PNG mới;
    không dọn thì 1 nhóm lỗi liên tục đủ làm đầy đĩa → mọi ghi file sau đó (kể cả
    posted_log.json / status.json) bắt đầu lỗi, sinh hành vi bất định.
    """
    try:
        shots = sorted(SCREENSHOT_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime)
        for old in (shots[:-keep] if len(shots) > keep else []):
            old.unlink(missing_ok=True)
    except Exception as e:
        print(f"[screenshot prune fail] {e}", flush=True)   # dọn lỗi không được chặn đăng bài


def _screenshot(page, tag: str) -> str:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOT_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{tag}.png"
    try:
        page.screenshot(path=str(path), full_page=False)
    except Exception as e:
        print(f"[screenshot fail] {tag}: {e}", flush=True)
        return ""
    _prune_screenshots()
    return str(path)


def _check_account_state(page):
    url = page.url
    if "checkpoint" in url or ("/login" in url and "next" in url):
        _screenshot(page, "checkpoint")
        raise CheckpointError(f"Facebook chuyển hướng tới: {url}")
    if page.locator("input[name='pass']").count() > 0:
        raise NotLoggedInError("Thấy form đăng nhập — session đã mất, chạy lại login.py")


def _find_composer_trigger(page):
    """Tìm ô 'Bạn viết gì đi...' / 'What's on your mind' ở đầu nhóm.

    Dùng tham số has_text (không nhúng chuỗi vào CSS) để chuỗi chứa dấu nháy
    đơn như "What's" không làm hỏng selector.
    """
    for text in COMPOSER_TRIGGER_TEXTS:
        # 2.4 — ưu tiên get_by_role (auto-wait, khớp accessible name, bền hơn khi FB
        # đổi cấu trúc DOM); nếu trượt thì fallback locator+has_text cũ (không regression).
        try:
            loc = page.get_by_role("button", name=text).first
            loc.wait_for(state="visible", timeout=3000)
            return loc
        except PWTimeout:
            pass
        loc = page.locator("div[role='button']", has_text=text).first
        try:
            loc.wait_for(state="visible", timeout=2500)
            return loc
        except PWTimeout:
            continue
    return None


def _find_composer_dialog(page, timeout_ms: int = 12000):
    """Facebook mở 2 div[role=dialog]: một vỏ rỗng tên 'Tạo bài viết' và một
    chứa nội dung thật. Chọn dialog nào thực sự có ô nhập text."""
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        dialogs = page.locator("div[role='dialog']")
        for i in range(dialogs.count()):
            d = dialogs.nth(i)
            if d.is_visible() and d.locator("div[contenteditable='true']").count() > 0:
                return d
        page.wait_for_timeout(500)
    return None


def _find_in_dialog_by_label(dialog, labels: list, role: str = "button"):
    for label in labels:
        # 2.4 — ưu tiên get_by_role trong phạm vi dialog (exact=True để "Đăng" không
        # dính "Đăng nhập"); fallback aria-label CSS cũ nếu accessible name không khớp.
        try:
            loc = dialog.get_by_role(role, name=label, exact=True).first
            if loc.count() > 0 and loc.is_visible():
                return loc
        except Exception:
            pass
        loc = dialog.locator(f"div[aria-label='{label}'][role='{role}']").first
        if loc.count() > 0 and loc.is_visible():
            return loc
    return None


# Ưu tiên trả lời câu hỏi "khách hàng hay môi giới" khi đăng
POST_QUESTION_ANSWERS = ["chủ nhà", "khách thuê", "cư dân", "chính chủ"]
POST_QUESTION_MARKERS = ["xem xét quyền tham gia", "khách hàng hay môi giới",
                         "trả lời", "câu hỏi", "môi giới"]
SUBMIT_LABELS = ["Gửi", "Trả lời", "Đăng", "Gửi câu trả lời", "Xong"]


def _contact_phone():
    try:
        import json as _json
        return _json.loads((ROOT / "config.json").read_text(encoding="utf-8")).get("contact_phone", "")
    except Exception:
        return ""


def _question_answer_text():
    """Đọc contact_phone ĐỘNG mỗi lần đăng (không đóng băng lúc import module)."""
    phone = _contact_phone()
    if not phone:
        print("[CẢNH BÁO] contact_phone rỗng/không đọc được — câu trả lời câu hỏi nhóm sẽ thiếu SĐT.", flush=True)
    return f"Mình là chính chủ, cần cho thuê căn hộ đang có. Liên hệ: {phone}"


def _handle_post_question(page) -> bool:
    """Sau khi bấm Đăng, một số nhóm hiện 'Xem xét quyền tham gia' với câu hỏi
    (nút chọn khách thuê/môi giới/chủ nhà, HOẶC ô trả lời tự do). Trả lời rồi Gửi.
    Trả về True nếu đã xử lý một hộp thoại câu hỏi."""
    page.wait_for_timeout(3500)
    dlg = None
    dialogs = page.locator("div[role='dialog']")
    for i in range(dialogs.count()):
        d = dialogs.nth(i)
        if not d.is_visible():
            continue
        txt = (d.inner_text() or "").lower()
        has_input = (d.locator("div[role='radio'], input[type='radio']").count() > 0
                     or d.locator("textarea, div[contenteditable='true'], input[type='text']").count() > 0)
        # Nhận diện qua tiêu đề/markers, KHÔNG bắt buộc có nút chọn
        if has_input and any(m in txt for m in POST_QUESTION_MARKERS):
            dlg = d
            break
    if dlg is None:
        return False

    # 1) chọn nút (radio) nếu có
    radios = dlg.locator("div[role='radio'], input[type='radio']")
    picked = False
    for want in POST_QUESTION_ANSWERS:
        for i in range(radios.count()):
            r = radios.nth(i)
            try:
                label = (r.evaluate(
                    "e => { let n=e; for(let k=0;k<4&&n;k++){n=n.parentElement; "
                    "if(n && n.innerText && n.innerText.trim()) return n.innerText;} return ''; }"
                ) or "").lower()
                if want in label:
                    r.click()
                    picked = True
                    break
            except Exception:
                continue
        if picked:
            break
    if not picked and radios.count() > 0:
        # KHÔNG chọn bừa: click nhầm "môi giới" trong nhóm cấm môi giới → bài bị từ chối.
        # Dừng rõ ràng để worker ghi lỗi + tự dừng, thay vì đăng sai âm thầm.
        shot = _screenshot(page, "question_no_match")
        raise RuntimeError(
            f"Câu hỏi nhóm không khớp đáp án cấu hình (POST_QUESTION_ANSWERS). "
            f"Dừng để tránh chọn nhầm vai. Bổ sung đáp án phù hợp. Screenshot: {shot}"
        )
    page.wait_for_timeout(600)

    # 2) điền ô trả lời tự do (textarea / contenteditable / input)
    answer = _question_answer_text()   # đọc contact_phone động ngay lúc đăng
    boxes = dlg.locator("textarea, div[contenteditable='true'], input[type='text']")
    n_boxes = 0
    filled = 0
    for i in range(boxes.count()):
        b = boxes.nth(i)
        try:
            if not b.is_visible():
                continue
            n_boxes += 1
            tag = b.evaluate("e => e.tagName")
            b.click()
            page.wait_for_timeout(200)
            if tag in ("TEXTAREA", "INPUT"):
                b.fill(answer)
            else:
                page.keyboard.type(answer, delay=15)
            filled += 1
            page.wait_for_timeout(400)
        except Exception:
            continue
    # Có ô trả lời hiển thị nhưng không điền được ô nào → đừng bấm Gửi (sẽ gửi rỗng → bị từ chối).
    if n_boxes > 0 and filled == 0:
        shot = _screenshot(page, "question_fill_failed")
        raise RuntimeError(f"Có ô trả lời câu hỏi nhóm nhưng không điền được — dừng để tránh gửi rỗng. Screenshot: {shot}")

    page.wait_for_timeout(700)

    # 3) bấm Gửi
    submit = _find_in_dialog_by_label(dlg, SUBMIT_LABELS)
    if submit and submit.get_attribute("aria-disabled") not in ("true", "1"):
        submit.click()
    else:
        for lbl in SUBMIT_LABELS:
            b = dlg.get_by_role("button", name=lbl).first
            if b.count() and b.is_visible():
                b.click()
                break
    # Xác nhận hộp thoại câu hỏi ĐÃ ĐÓNG (đã gửi thật). Nếu còn treo → câu trả lời chưa
    # gửi được: báo lỗi rõ thay vì để post_to_group tưởng đăng xong (composer gốc đã đóng trước đó).
    try:
        dlg.wait_for(state="hidden", timeout=15000)
    except PWTimeout:
        shot = _screenshot(page, "question_not_submitted")
        raise RuntimeError(f"Đã trả lời câu hỏi nhóm nhưng hộp thoại không đóng — có thể chưa gửi. Screenshot: {shot}")
    return True


def get_user_id(page) -> str:
    """Lấy user id số của tài khoản đang đăng nhập."""
    try:
        uid = page.evaluate(
            "() => { const m = document.documentElement.innerHTML.match(/\"USER_ID\":\"(\\d+)\"/) "
            "|| document.documentElement.innerHTML.match(/\"userID\":\"(\\d+)\"/); return m ? m[1] : null; }"
        )
        return uid or ""
    except Exception:
        return ""


def _detect_approval(page) -> str:
    """Sau khi bấm Đăng: 'pending' nếu thấy banner chờ duyệt, còn lại 'submitted'
    (ĐÃ GỬI — chưa chắc công khai; phải kiểm chứng bằng nick khác mới biết 'live').
    Không bao giờ tự nhận 'approved' từ mắt của chính nick đăng."""
    try:
        body = page.locator("body").inner_text().lower()
    except Exception:
        return "submitted"
    for t in PENDING_TEXTS:
        if t in body:
            return "pending"
    return "submitted"


def _to_int(s: str):
    s = s.strip().replace(".", "").replace(",", "")
    try:
        return int(s)
    except ValueError:
        return None


def post_to_group(page, group_url: str, content: str, image_paths: list, uid: str = "") -> dict:
    """Đăng bài vào nhóm. Raise exception nếu thất bại (kèm screenshot).

    Trả về dict: {approval_status, permalink}.
    """
    page.goto(group_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    _check_account_state(page)

    # Cuộn nhẹ như người thật rồi quay lại đầu trang
    humanize.scroll_a_bit(page)

    trigger = _find_composer_trigger(page)
    if trigger is None:
        shot = _screenshot(page, "no_composer")
        raise RuntimeError(
            f"Không tìm thấy ô soạn bài trong nhóm (có thể chưa vào nhóm, nhóm chặn đăng, "
            f"hoặc giao diện đổi). Screenshot: {shot}"
        )
    humanize.human_click(trigger)

    # Chờ dialog soạn bài mở (dialog chứa ô nhập text, không phải vỏ ngoài)
    dialog = _find_composer_dialog(page)
    if dialog is None:
        shot = _screenshot(page, "no_dialog")
        raise RuntimeError(f"Dialog soạn bài không mở. Screenshot: {shot}")
    humanize.pause(1.0, 2.0)

    # Gõ nội dung vào ô contenteditable
    editor = dialog.locator("div[contenteditable='true']").first
    try:
        editor.wait_for(state="visible", timeout=8000)
    except PWTimeout:
        shot = _screenshot(page, "no_editor")
        raise RuntimeError(f"Không tìm thấy ô nhập text trong dialog. Screenshot: {shot}")
    humanize.type_text(editor, content)
    humanize.pause(1.0, 2.0)

    # Đính ảnh: ưu tiên input[type=file] có sẵn trong dialog, nếu không thì bấm nút Ảnh/video
    file_input = dialog.locator("input[type='file']").first
    if file_input.count() == 0:
        photo_btn = _find_in_dialog_by_label(dialog, PHOTO_BUTTON_LABELS)
        if photo_btn is None:
            shot = _screenshot(page, "no_photo_button")
            raise RuntimeError(f"Không tìm thấy nút Ảnh/video. Screenshot: {shot}")
        humanize.human_click(photo_btn)
        humanize.pause(1.0, 2.0)
        file_input = dialog.locator("input[type='file']").first
        try:
            file_input.wait_for(state="attached", timeout=8000)
        except PWTimeout:
            shot = _screenshot(page, "no_file_input")
            raise RuntimeError(f"Không tìm thấy input file sau khi bấm Ảnh/video. Screenshot: {shot}")
    file_input.set_input_files(image_paths)

    # Chờ ảnh upload: nút Đăng bị disable (aria-disabled) khi đang upload
    page.wait_for_timeout(3000 + 2000 * len(image_paths))

    post_btn = _find_in_dialog_by_label(dialog, POST_BUTTON_LABELS)
    if post_btn is None:
        shot = _screenshot(page, "no_post_button")
        raise RuntimeError(f"Không tìm thấy nút Đăng. Screenshot: {shot}")

    # Chờ nút Đăng hết disable (upload xong) — 10 ảnh cần thời gian, tối đa 240s
    deadline = time.time() + 240
    while time.time() < deadline:
        if post_btn.get_attribute("aria-disabled") not in ("true", "1"):
            break
        time.sleep(2)
    else:
        shot = _screenshot(page, "upload_stuck")
        raise RuntimeError(f"Ảnh upload quá lâu, nút Đăng vẫn disable. Screenshot: {shot}")

    humanize.pause(1.0, 2.0)
    humanize.human_click(post_btn)

    # Một số nhóm hiện câu hỏi "khách thuê/môi giới/chủ nhà" trước khi đăng → trả lời
    _handle_post_question(page)

    # Chờ dialog đóng = đăng thành công (hoặc bài chờ duyệt)
    try:
        dialog.wait_for(state="hidden", timeout=30000)
    except PWTimeout:
        _check_account_state(page)
        # Phân biệt: bị giới hạn tần suất (lùi nhịp) vs lỗi thật
        try:
            dtext = dialog.inner_text().lower()
        except Exception:
            dtext = ""
        if any(t in dtext for t in RATE_LIMIT_TEXTS):
            _screenshot(page, "rate_limit")
            raise RateLimitError("Facebook cảnh báo giới hạn tần suất — cần tạm nghỉ.")
        shot = _screenshot(page, "dialog_not_closed")
        raise RuntimeError(f"Đã bấm Đăng nhưng dialog không đóng. Screenshot: {shot}")

    page.wait_for_timeout(4000)
    _check_account_state(page)

    # Trạng thái thật: pending (thấy banner) hoặc submitted (đã gửi, chưa rõ công khai).
    # KHÔNG tự nhận "đã lên" — phải verifier bằng nick khác mới biết. public=None ở đây.
    approval = _detect_approval(page)
    return {"approval_status": approval, "permalink": None, "public": None}
