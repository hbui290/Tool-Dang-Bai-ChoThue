#!/usr/bin/env python3
"""Kiểm chứng HÀNH VI THẬT của dashboard/app.py (không grep mã nguồn).

Cần Flask: chạy bằng venv/bin/python verify_dashboard.py
File này tự backup rồi restore groups.json / config.json / dashboard/auth.json,
nên chạy được nhiều lần mà không làm bẩn repo.

exit 0 = PASS, 1 = FAIL.
"""
import base64
import json
import shutil
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GROUPS = ROOT / "groups.json"
CONFIG = ROOT / "config.json"
AUTH = ROOT / "dashboard" / "auth.json"

fails, total = [], 0
# Mật khẩu CÓ ký tự tiếng Việt: compare_digest trên str sẽ ném TypeError → mọi request 500.
USER, PW = "admin", "mật-khẩu-tiếng-việt"
HDR = {"Authorization": "Basic " + base64.b64encode(f"{USER}:{PW}".encode()).decode()}
G1 = "https://facebook.com/groups/111111111"
G2 = "https://facebook.com/groups/222222222"
TWO_GROUPS = json.dumps([{"name": "N1", "url": G1, "enabled": True},
                         {"name": "N2", "url": G2, "enabled": True}], ensure_ascii=False)


def check(name, cond, detail=""):
    global total
    total += 1
    print(("  OK   " if cond else "  FAIL ") + name + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


backups = {f: f.read_bytes() for f in (GROUPS, CONFIG, AUTH) if f.exists()}

try:
    # ---- dựng state tối thiểu như một người dùng thật đã setup ----
    AUTH.write_text(json.dumps({"user": USER, "password": PW, "port": 8088}, ensure_ascii=False),
                    encoding="utf-8")
    shutil.copyfile(ROOT / "config.json.example", CONFIG)
    GROUPS.write_text(TWO_GROUPS, encoding="utf-8")

    sys.path.insert(0, str(ROOT / "dashboard"))
    import app as dash                                  # đọc auth.json ngay lúc import
    dash.app.config["TESTING"] = True
    c = dash.app.test_client()

    # 1) Basic Auth với mật khẩu tiếng Việt phải VÀO ĐƯỢC (không 500)
    r = c.get("/api/status", headers=HDR)
    check("auth mật khẩu tiếng Việt → 200 (không TypeError/500)", r.status_code == 200,
          f"status={r.status_code}")

    # 2) Sai mật khẩu → 401, không 500
    bad = {"Authorization": "Basic " + base64.b64encode(b"admin:sai").decode()}
    r = c.get("/api/status", headers=bad)
    check("mật khẩu sai → 401", r.status_code == 401, f"status={r.status_code}")

    # 3) POST không có body → KHÔNG được 500 (bug request.json=None)
    for path, want in (("/api/groups/toggle", (404, 400)),
                       ("/api/config", (200, 400)),
                       ("/api/command", (400,))):
        r = c.post(path, headers=HDR)
        check(f"POST {path} body rỗng → không 500", r.status_code in want,
              f"status={r.status_code} body={r.get_data(as_text=True)[:120]}")

    # 4) POST /api/config giá trị sai → 400 và KHÔNG được ghi vào config.json
    before = CONFIG.read_text(encoding="utf-8")
    r = c.post("/api/config", headers=HDR, json={"max_posts_per_day": "abc",
                                                 "posting_hours_start": "99:99"})
    check("config sai → 400", r.status_code == 400, f"status={r.status_code}")
    check("config sai → KHÔNG ghi file", CONFIG.read_text(encoding="utf-8") == before)

    # 5) POST /api/config giá trị đúng → ghi thật, đọc lại thấy
    r = c.post("/api/config", headers=HDR, json={"max_posts_per_day": 7})
    saved = json.loads(CONFIG.read_text(encoding="utf-8")).get("max_posts_per_day")
    check("config đúng → ghi được", r.status_code == 200 and saved == 7,
          f"status={r.status_code} saved={saved!r}")

    # 6) /api/stats + /api/groups với entry log HỎNG → 200, không 500
    log = ROOT / "state" / "posted_log.json"
    log_bak = log.read_bytes() if log.exists() else None
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps([{"foo": "bar"},
                               {"time": "khong-phai-ngay", "status": "success"}]), encoding="utf-8")
    try:
        r = c.get("/api/stats", headers=HDR)
        check("/api/stats với log hỏng → 200", r.status_code == 200,
              f"status={r.status_code} {r.get_data(as_text=True)[:150]}")
        r = c.get("/api/groups", headers=HDR)
        rows = r.get_json() if r.status_code == 200 else []
        check("/api/groups với log hỏng → 200 & reactions=None (chưa đo)",
              r.status_code == 200 and bool(rows) and rows[0]["reactions"] is None,
              f"status={r.status_code} rows={str(rows)[:150]}")
    finally:
        if log_bak is None:
            log.unlink(missing_ok=True)
        else:
            log.write_bytes(log_bak)

    # 7) RACE THẬT: 2 thread toggle 2 nhóm khác nhau, mỗi nhóm 15 lần (số lẻ → phải đảo).
    #    Mất update = parity của nhóm đó sai. Flask app.run mặc định threaded nên đây
    #    đúng là điều kiện chạy thật.
    GROUPS.write_text(TWO_GROUPS, encoding="utf-8")

    def spam(url, n=15):
        cl = dash.app.test_client()
        for _ in range(n):
            cl.post("/api/groups/toggle", headers=HDR, json={"url": url})

    ts = [threading.Thread(target=spam, args=(G1,)), threading.Thread(target=spam, args=(G2,))]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=120)
    final = {g["url"]: g["enabled"] for g in json.loads(GROUPS.read_text(encoding="utf-8"))}
    check("race toggle 2 thread × 15 lần → không mất update",
          final.get(G1) is False and final.get(G2) is False,
          f"kỳ vọng cả 2 = False (15 lần = lẻ), thực tế {final}")

finally:
    for f in (GROUPS, CONFIG, AUTH):
        if f in backups:
            f.write_bytes(backups[f])
        else:
            f.unlink(missing_ok=True)

print()
if fails:
    print(f"KẾT QUẢ: FAIL ({len(fails)}/{total} mục): " + ", ".join(fails))
    sys.exit(1)
print(f"KẾT QUẢ: PASS — {total}/{total} kiểm chứng hành vi dashboard đạt.")
sys.exit(0)
