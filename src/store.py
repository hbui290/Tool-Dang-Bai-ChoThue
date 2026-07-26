"""Đọc/ghi trạng thái dùng chung giữa worker và dashboard, và các hàm thống kê.

Các file trạng thái (trong state/):
- status.json   : nhịp tim worker (worker ghi, dashboard đọc)
- control.json  : cờ điều khiển bền vững, vd {"paused": false} (dashboard ghi, worker đọc)
- commands.json : hàng đợi lệnh một-lần [{id, action, args}] (dashboard đẩy, worker lấy)
- posted_log.json : lịch sử đăng bài (đã có sẵn)
"""
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
STATUS_FILE = STATE / "status.json"
CONTROL_FILE = STATE / "control.json"
COMMANDS_FILE = STATE / "commands.json"
LOG_FILE = STATE / "posted_log.json"


@contextmanager
def _file_lock(name: str):
    """Khoá liên-tiến-trình (worker ↔ dashboard) quanh read-modify-write để không
    mất lệnh/cờ khi cả hai ghi cùng lúc. Khoá trên file .lock riêng (Unix flock)."""
    STATE.mkdir(parents=True, exist_ok=True)
    f = open(STATE / f"{name}.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write_json(path: Path, data):
    """Ghi nguyên tử: ghi file tạm rồi đổi tên, tránh đọc phải file dở."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# ---------- status ----------
def read_status() -> dict:
    return _read_json(STATUS_FILE, {})


def write_status(d: dict):
    d = dict(d)
    d["heartbeat"] = datetime.now().isoformat(timespec="seconds")
    _write_json(STATUS_FILE, d)


# ---------- control (paused) ----------
def read_control() -> dict:
    return _read_json(CONTROL_FILE, {"paused": False})


def set_paused(paused: bool):
    with _file_lock("control"):
        c = read_control()
        c["paused"] = bool(paused)
        _write_json(CONTROL_FILE, c)


def is_paused() -> bool:
    return bool(read_control().get("paused", False))


# ---------- commands ----------
def push_command(action: str, args: dict = None) -> str:
    cid = f"{datetime.now():%Y%m%d%H%M%S%f}"
    with _file_lock("commands"):
        cmds = _read_json(COMMANDS_FILE, [])
        cmds.append({"id": cid, "action": action, "args": args or {}, "ts": datetime.now().isoformat(timespec="seconds")})
        _write_json(COMMANDS_FILE, cmds)
    return cid


def pop_all_commands() -> list:
    # Đọc + xoá trong CÙNG khoá → lệnh dashboard đẩy vào giữa chừng không bị mất (TOCTOU).
    with _file_lock("commands"):
        cmds = _read_json(COMMANDS_FILE, [])
        if cmds:
            _write_json(COMMANDS_FILE, [])
    return cmds


# ---------- posted log ----------
def load_log() -> list:
    return _read_json(LOG_FILE, [])


def save_log(log: list):
    _write_json(LOG_FILE, log)


def append_post(entry: dict) -> str:
    log = load_log()
    entry.setdefault("id", f"{datetime.now():%Y%m%d%H%M%S%f}")
    log.append(entry)
    save_log(log)
    return entry["id"]


def update_post(post_id: str, **fields):
    log = load_log()
    for e in log:
        if e.get("id") == post_id:
            e.update(fields)
            break
    save_log(log)


# ---------- thống kê (giờ VN vì VPS đã đặt Asia/Ho_Chi_Minh) ----------
def _date(e):
    # .get() an toàn: entry log hỏng/thiếu "time" không được gây 500 ở /api/stats.
    return str(e.get("time", ""))[:10]


def _parse_hhmm(s: str) -> int:
    h, m = str(s).split(":") if ":" in str(s) else (s, 0)
    return int(h) * 60 + int(m)


def estimated_per_day(config: dict, num_enabled: int) -> int:
    """Ước tính số bài/ngày = số nhóm × (số phút khung giờ ÷ interval mỗi nhóm)."""
    interval = config.get("repost_interval_minutes", 120)
    window = _parse_hhmm(config.get("posting_hours_end", "23:30")) - \
        _parse_hhmm(config.get("posting_hours_start", "07:00"))
    if interval <= 0 or window <= 0:
        return 0
    return round(num_enabled * (window / interval))


def stats_summary(config: dict, num_enabled: int = 0) -> dict:
    log = load_log()
    today = datetime.now().strftime("%Y-%m-%d")
    succ_today = sum(1 for e in log if _date(e) == today and e.get("status") == "success")
    by_status_today = Counter(e.get("status") for e in log if _date(e) == today)
    approval = Counter(e.get("approval_status") for e in log if e.get("status") == "success")
    content_usage = Counter(e.get("content_file") for e in log if e.get("status") == "success")
    total_reactions = sum(e.get("reactions") or 0 for e in log)
    total_comments = sum(e.get("comments") or 0 for e in log)
    cap = config.get("max_posts_per_day", 0)
    real = [e for e in log if e.get("status") == "success"]
    # Con so TRUNG THUC (public=True do verifier bang nick khac xac nhan)
    public_live = sum(1 for e in real if e.get("public") is True)
    pending = sum(1 for e in real if e.get("public") is False)
    unverified = sum(1 for e in real if e.get("public") is None)
    return {
        "today": today,
        "posts_today": succ_today,
        "quota": cap,                              # 0 = không giới hạn
        "estimated_per_day": estimated_per_day(config, num_enabled),
        "repost_interval_minutes": config.get("repost_interval_minutes", 120),
        "today_by_status": dict(by_status_today),
        "approval": dict(approval),
        "content_usage": dict(content_usage),
        "total_reactions": total_reactions,
        "total_comments": total_comments,
        "total_posts": len(real),
        # trung thuc:
        "public_live": public_live,       # da cong khai (nguoi ngoai thay)
        "pending": pending,               # cho duyet (chua ai thay)
        "unverified": unverified,         # da gui, chua kiem chung
    }


def posts_per_day(days: int = 14) -> list:
    """[{date, success, error, pending}] cho N ngày gần nhất."""
    log = load_log()
    start = (datetime.now() - timedelta(days=days - 1)).date()
    buckets = {}
    for i in range(days):
        d = (start + timedelta(days=i)).strftime("%Y-%m-%d")
        buckets[d] = {"date": d, "success": 0, "error": 0, "pending": 0}
    for e in log:
        d = _date(e)
        if d in buckets:
            if e.get("status") == "success":
                buckets[d]["success"] += 1
                if e.get("approval_status") == "pending":
                    buckets[d]["pending"] += 1
            elif e.get("status") == "error":
                buckets[d]["error"] += 1
    return list(buckets.values())


def per_group_stats(groups: list) -> list:
    """Cho mỗi nhóm: đăng hôm nay, 7 ngày qua, tổng, lần cuối, like/comment."""
    log = load_log()
    today = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=6)).date()
    by_url = defaultdict(list)
    for e in log:
        by_url[e.get("group_url")].append(e)
    def _sum_measured(entries, key):
        vals = [e[key] for e in entries if e.get(key) is not None]
        return sum(vals) if vals else None

    rows = []
    for g in groups:
        entries = [e for e in by_url.get(g["url"], []) if e.get("status") == "success"]
        today_n = sum(1 for e in entries if _date(e) == today)
        week_n = sum(1 for e in entries
                     if e.get("time") and datetime.fromisoformat(e["time"]).date() >= week_ago)
        last = max((e["time"] for e in entries if e.get("time")), default=None)
        rows.append({
            "name": g["name"],
            "url": g["url"],
            "enabled": g.get("enabled", True),
            "today": today_n,
            "week": week_n,
            "total": len(entries),
            "last": last,
            # None = CHƯA ĐO, khác hẳn 0 = đã đo và thật sự không có tương tác.
            # Hiện chưa có nơi nào ghi reactions/comments, nếu trả 0 thì dashboard hiện
            # "0" vĩnh viễn và người vận hành sẽ kết luận sai là nội dung không hiệu quả.
            "reactions": _sum_measured(entries, "reactions"),
            "comments": _sum_measured(entries, "comments"),
        })
    return rows


def recent_posts(limit: int = 50) -> list:
    log = load_log()
    return list(reversed(log))[:limit]


def recent_texts_for_group(group_url: str, limit: int = 10) -> list:
    """Các đoạn text đã đăng gần nhất vào 1 nhóm (để near-dup check tránh lặp)."""
    log = load_log()
    texts = [e["posted_text"] for e in reversed(log)
             if e.get("group_url") == group_url and e.get("posted_text")]
    return texts[:limit]
