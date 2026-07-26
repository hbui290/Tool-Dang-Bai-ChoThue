"""Dashboard web quản lý & theo dõi hệ thống đăng bài Facebook.

Chạy: venv/bin/python dashboard/app.py
Cấu hình cổng + mật khẩu trong dashboard/auth.json:
  {"user": "admin", "password": "...", "port": 8088}
"""
import hmac
import json
import re
import sys
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import scheduler  # noqa: E402
import store      # noqa: E402

AUTH = json.loads((Path(__file__).resolve().parent / "auth.json").read_text(encoding="utf-8"))
GROUPS_FILE = ROOT / "groups.json"
SCREENSHOT_DIR = ROOT / "state" / "screenshots"
TEMPLATES = Path(__file__).resolve().parent / "templates"

app = Flask(__name__)


def check_auth(u, p):
    # compare_digest: so sánh hằng-thời-gian. `==` trên str dừng ở byte lệch đầu tiên →
    # thời gian phản hồi rò rỉ số ký tự đúng, brute-force được từng ký tự nếu dashboard
    # mở ra ngoài mạng (README có kịch bản đó sau khi đổi mật khẩu).
    # Phải encode sang bytes: compare_digest trên str ném TypeError nếu có ký tự
    # ngoài ASCII → mật khẩu tiếng Việt/emoji sẽ làm MỌI request 500.
    return (hmac.compare_digest((u or "").encode("utf-8"), (AUTH.get("user") or "").encode("utf-8"))
            and hmac.compare_digest((p or "").encode("utf-8"), (AUTH.get("password") or "").encode("utf-8")))


def requires_auth(f):
    @wraps(f)
    def wrapped(*a, **k):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response(
                "Cần đăng nhập", 401,
                {"WWW-Authenticate": 'Basic realm="FB Poster Dashboard"'})
        return f(*a, **k)
    return wrapped


def all_groups() -> list:
    return json.loads(GROUPS_FILE.read_text(encoding="utf-8"))


def save_groups(groups: list):
    store._write_json(GROUPS_FILE, groups)   # ghi nguyên tử, tránh worker đọc phải file dở


# ---------- trang chính ----------
@app.route("/")
@requires_auth
def index():
    return (TEMPLATES / "index.html").read_text(encoding="utf-8")


# ---------- API đọc ----------
@app.route("/api/status")
@requires_auth
def api_status():
    st = store.read_status()
    # worker còn sống nếu heartbeat < 3 phút
    alive = False
    hb = st.get("heartbeat")
    if hb:
        alive = (datetime.now() - datetime.fromisoformat(hb)).total_seconds() < 180
    st["worker_alive"] = alive
    return jsonify(st)


@app.route("/api/stats")
@requires_auth
def api_stats():
    config = scheduler.load_config()
    num_enabled = sum(1 for g in all_groups() if g.get("enabled", True))
    return jsonify({
        "summary": store.stats_summary(config, num_enabled),
        "per_day": store.posts_per_day(14),
        "config": config,
    })


@app.route("/api/groups")
@requires_auth
def api_groups():
    return jsonify(store.per_group_stats(all_groups()))


@app.route("/api/posts")
@requires_auth
def api_posts():
    return jsonify(store.recent_posts(80))


@app.route("/screenshots/<path:name>")
@requires_auth
def screenshots(name):
    return send_from_directory(SCREENSHOT_DIR, name)


# ---------- API điều khiển ----------
@app.route("/api/groups/toggle", methods=["POST"])
@requires_auth
def toggle_group():
    url = (request.get_json(silent=True) or {}).get("url")
    # Khoá quanh read-modify-write: Flask app.run mặc định threaded → 2 request
    # toggle đồng thời sẽ làm mất update của nhau (cùng đọc bản cũ rồi ghi đè).
    with store._file_lock("groups"):
        groups = all_groups()
        for g in groups:
            if g["url"] == url:
                g["enabled"] = not g.get("enabled", True)
                save_groups(groups)
                return jsonify({"ok": True, "enabled": g["enabled"]})
    return jsonify({"ok": False, "error": "không tìm thấy nhóm"}), 404


_HHMM = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")


def _valid_hhmm(v) -> bool:
    return isinstance(v, str) and bool(_HHMM.match(v.strip()))


def _as_nonneg_int(v):
    """int ≥ 0 hoặc chuỗi số ≥ 0 → int; ngược lại None (loại cả bool)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v if v >= 0 else None
    if isinstance(v, str) and v.strip().lstrip("+").isdigit():
        return int(v.strip())
    return None


def _validate_config_updates(payload):
    """Lọc key cho phép + kiểm giá trị. Trả (validated: dict, errors: list[str])."""
    allowed = {"repost_interval_minutes", "max_posts_per_day",
               "posting_hours_start", "posting_hours_end"}
    validated, errors = {}, []
    for k, v in (payload or {}).items():
        if k not in allowed:
            continue
        if k in ("posting_hours_start", "posting_hours_end"):
            if _valid_hhmm(v):
                validated[k] = v.strip()
            else:
                errors.append(f"{k} phải dạng HH:MM (00:00–23:59), nhận {v!r}")
        else:
            iv = _as_nonneg_int(v)
            if iv is None:
                errors.append(f"{k} phải là số nguyên ≥ 0, nhận {v!r}")
            else:
                validated[k] = iv
    return validated, errors


@app.route("/api/config", methods=["POST"])
@requires_auth
def update_config():
    validated, errors = _validate_config_updates(request.get_json(silent=True) or {})
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400   # sai → 400, KHÔNG ghi
    # Khoá quanh read-modify-write: 2 request chỉnh config đồng thời không ghi đè
    # nhau (đọc lại config BÊN TRONG khoá mới thấy update của request trước).
    with store._file_lock("config"):
        config = scheduler.load_config()
        config.update(validated)
        store._write_json(ROOT / "config.json", config)   # ghi nguyên tử
    return jsonify({"ok": True, "config": config})


@app.route("/api/command", methods=["POST"])
@requires_auth
def command():
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    args = body.get("args", {})
    if action == "pause":
        store.set_paused(True)
        return jsonify({"ok": True, "paused": True})
    if action == "resume":
        store.set_paused(False)
        return jsonify({"ok": True, "paused": False})
    if action in ("post_now", "refresh_metrics"):
        cid = store.push_command(action, args)
        return jsonify({"ok": True, "command_id": cid})
    return jsonify({"ok": False, "error": "lệnh không hợp lệ"}), 400


DEFAULT_PASSWORD = "DOI_MAT_KHAU_NAY_DI"


def _resolve_host():
    """Mặc định bind 127.0.0.1. Nếu mật khẩu vẫn là mặc định → cảnh báo đỏ và
    TỪ CHỐI mở ra ngoài (ép về localhost) cho tới khi đổi mật khẩu."""
    want = AUTH.get("host", "127.0.0.1")
    if AUTH.get("password") == DEFAULT_PASSWORD:
        red, rst = "\033[91m", "\033[0m"
        print(f"{red}⚠ CẢNH BÁO: mật khẩu dashboard vẫn là mặc định. "
              f"Đổi 'password' trong dashboard/auth.json trước khi mở ra ngoài.{rst}", flush=True)
        if want != "127.0.0.1":
            print(f"{red}→ Từ chối bind {want}; chỉ mở 127.0.0.1 tới khi đổi mật khẩu.{rst}", flush=True)
        return "127.0.0.1"
    return want


if __name__ == "__main__":
    port = int(AUTH.get("port", 8088))
    app.run(host=_resolve_host(), port=port)
