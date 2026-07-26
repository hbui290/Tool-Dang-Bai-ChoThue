"""Chọn nhóm đến hạn đăng, kiểm soát quota ngày và giãn cách giữa các bài."""
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

import spintax

ROOT = Path(__file__).resolve().parent.parent
GROUPS_FILE = ROOT / "groups.json"
LOG_FILE = ROOT / "state" / "posted_log.json"
CONTENT_DIR = ROOT / "content"


def load_config() -> dict:
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def load_groups() -> list:
    groups = json.loads(GROUPS_FILE.read_text(encoding="utf-8"))
    return [g for g in groups if g.get("enabled", True)]


def load_log() -> list:
    if LOG_FILE.exists():
        return json.loads(LOG_FILE.read_text(encoding="utf-8"))
    return []


def posts_today(log: list) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    # .get() an toàn: 1 entry log hỏng/thiếu key không được làm crash thống kê.
    return sum(1 for e in log
               if str(e.get("time", "")).startswith(today) and e.get("status") == "success")


def last_success_time(log: list, group_url: str):
    times = [e["time"] for e in log
             if e.get("group_url") == group_url and e.get("status") == "success" and e.get("time")]
    return max(times) if times else None


def last_attempt_time(log: list, group_url: str):
    """Lần đăng gần nhất bất kể thành công hay lỗi (để nhóm lỗi cũng nghỉ 1 chu kỳ,
    tránh worker kẹt retry mãi 1 nhóm)."""
    times = [e["time"] for e in log if e.get("group_url") == group_url and e.get("time")]
    return max(times) if times else None


_cap_notice_date = None


def _notify_cap_reached(cap: int):
    """In cảnh báo chạm cap đúng 1 lần mỗi ngày (pick_overdue_group gọi mỗi nhịp)."""
    global _cap_notice_date
    today = datetime.now().strftime("%Y-%m-%d")
    if _cap_notice_date != today:
        print(f"[{datetime.now():%m-%d %H:%M:%S}] Đã đạt cap {cap} bài/ngày — "
              f"dừng đăng tới ngày mai.", flush=True)
        _cap_notice_date = today


def pick_overdue_group(config: dict):
    """Chọn nhóm quá hạn lâu nhất để đăng lại.

    Mỗi nhóm có "đồng hồ riêng": được đăng lại khi đã qua repost_interval_minutes
    kể từ lần đăng thành công gần nhất (hoặc chưa từng đăng). Trả về 1 nhóm quá
    hạn lâu nhất, hoặc None nếu không nhóm nào tới hạn.

    Van an toàn: nếu max_posts_per_day > 0 và đã đạt trong ngày thì trả None.
    """
    log = load_log()
    cap = config.get("max_posts_per_day", 0)
    if cap and posts_today(log) >= cap:
        _notify_cap_reached(cap)   # log rõ 1 lần/ngày khi chạm cap
        return None

    interval = timedelta(minutes=config.get("repost_interval_minutes", 120))
    now = datetime.now()
    candidates = []
    for g in load_groups():
        last = last_attempt_time(log, g["url"])           # tính cả lần lỗi để nhóm lỗi nghỉ 1 chu kỳ
        if last is None:
            candidates.append((datetime.min, g))          # chưa từng đăng → ưu tiên nhất
        else:
            last_dt = datetime.fromisoformat(last)
            if now - last_dt >= interval:
                candidates.append((last_dt, g))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])                     # quá hạn lâu nhất trước
    return candidates[0][1]


def count_enabled() -> int:
    return len(load_groups())


def post_spacing_seconds(config: dict, num_enabled: int) -> int:
    """Giãn cách giữa 2 bài để trải đều: interval / số nhóm, kẹp ≥90s, nhiễu ±15%."""
    interval_s = config.get("repost_interval_minutes", 120) * 60
    base = interval_s / max(1, num_enabled)
    base = max(90, base)
    return int(base * random.uniform(0.85, 1.15))


def pick_content() -> tuple:
    """Chọn ngẫu nhiên 1 biến thể content. Trả về (tên file, nội dung)."""
    files = sorted(CONTENT_DIR.glob("[!_]*.txt"))   # bỏ file _-prefix (vd _HUONG_DAN.txt)
    if not files:
        raise RuntimeError(f"Chưa có file content nào trong {CONTENT_DIR}")
    f = random.choice(files)
    raw = f.read_text(encoding="utf-8").strip()
    return f.name, spintax.spin(raw)   # spin ra 1 biến thể để giảm trùng lặp


DUP_THRESHOLD = 0.9   # Jaccard ≥ ngưỡng = coi như gần trùng, cần spin lại


def _trigrams(s: str) -> set:
    s = " ".join(s.lower().split())     # chuẩn hoá khoảng trắng/hoa thường
    return {s[i:i + 3] for i in range(len(s) - 2)} if len(s) >= 3 else {s}


def text_similarity(a: str, b: str) -> float:
    """Độ giống 2 đoạn text theo Jaccard trên tập trigram (0..1). Chỉ stdlib."""
    ta, tb = _trigrams(a), _trigrams(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def pick_unique_content(recent_texts=None, max_tries: int = 8) -> tuple:
    """Chọn biến thể content KHÁC hẳn các bài gần đây cùng nhóm (near-dup check).
    Spin lại tối đa max_tries lần nếu quá giống; hết lượt thì trả bản cuối."""
    recent_texts = recent_texts or []
    name, text = pick_content()
    for _ in range(max_tries):
        if all(text_similarity(text, r) < DUP_THRESHOLD for r in recent_texts):
            return name, text
        name, text = pick_content()     # quá giống → spin biến thể khác
    return name, text


def pick_images(config: dict) -> list:
    """Lấy ảnh cho bài đăng. use_all_images=true → toàn bộ ảnh trong thư mục."""
    img_dir = Path(config["images_dir"])
    images = sorted(
        p for p in img_dir.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png")
    )
    if not images:
        raise RuntimeError(f"Không tìm thấy ảnh trong {img_dir}")
    if config.get("use_all_images", False):
        return [str(p) for p in images]
    # Kẹp CẢ min lẫn max theo số ảnh có thật: nếu chỉ có 1-2 ảnh mà cấu hình đòi min=3
    # thì random.randint(3, 1) ném ValueError → mọi lượt đăng lỗi → circuit breaker
    # tự pause ngay ngày đầu, với thông báo không nói rõ nguyên nhân là thiếu ảnh.
    if config["images_per_post_max"] < config["images_per_post_min"]:
        # Cấu hình gõ nhầm (max < min): trước đây crash ngay nên lộ lỗi, giờ kẹp lại thì
        # chạy êm và âm thầm bỏ qua min → phải cảnh báo, đừng để sai lặng lẽ.
        print(f"[cấu hình sai] images_per_post_max ({config['images_per_post_max']}) < "
              f"images_per_post_min ({config['images_per_post_min']}) — đang dùng theo max.",
              flush=True)
    lo = min(config["images_per_post_min"], len(images))
    hi = min(config["images_per_post_max"], len(images))
    n = random.randint(min(lo, hi), hi)
    return [str(p) for p in random.sample(images, n)]


def _parse_hhmm(s: str) -> int:
    """'07:30' → số phút từ 0h."""
    h, m = str(s).split(":") if ":" in str(s) else (s, 0)
    return int(h) * 60 + int(m)


def in_posting_hours(config: dict) -> bool:
    now = datetime.now()
    minutes = now.hour * 60 + now.minute
    return _parse_hhmm(config["posting_hours_start"]) <= minutes < _parse_hhmm(config["posting_hours_end"])
