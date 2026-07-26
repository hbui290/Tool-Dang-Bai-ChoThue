#!/usr/bin/env python3
"""Verifier độc lập — kiểm chứng lại các sửa lỗi + tính toàn vẹn, chạy lại được.

Nguyên tắc: KHÔNG tin output của bước build/sửa; tự đọc lại state và tái hiện check.
Ưu tiên kiểm HÀNH VI (gọi hàm thật, so kết quả) hơn là grep chuỗi. Chỗ nào buộc phải
kiểm mã nguồn (cần trình duyệt/Facebook mới chạy được) thì ghi rõ "[src]" trong tên check.

Pass criteria = từng mục dưới đây. Stop condition = exit 1 ngay khi có mục FAIL.

Chạy:  python verify.py     (exit 0 = PASS, 1 = FAIL)
"""
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

fails = []
total = 0


def check(name, cond, detail=""):
    global total
    total += 1
    print(("  OK   " if cond else "  FAIL ") + name + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


# ── 1) Compile toàn bộ .py (bắt syntax/indent error) ────────────────────────────
py_files = list(ROOT.glob("*.py")) + list(SRC.glob("*.py")) + list((ROOT / "dashboard").glob("*.py"))
r = subprocess.run([sys.executable, "-m", "py_compile", *map(str, py_files)],
                   capture_output=True, text=True)
check("py_compile toàn bộ", r.returncode == 0, r.stderr.strip())

# ── 2) config.json.example đủ hard key (thiếu config → FileNotFoundError khi clone) ──
HARD = ["images_dir", "images_per_post_min", "images_per_post_max",
        "posting_hours_start", "posting_hours_end"]
cfg = {}
try:
    cfg = json.loads((ROOT / "config.json.example").read_text(encoding="utf-8"))
    miss = [k for k in HARD if k not in cfg]
    check("config.json.example đủ hard key", not miss, f"thiếu {miss}")
except Exception as e:
    check("config.json.example đọc được", False, str(e))

import scheduler  # noqa: E402
import store       # noqa: E402

GROUPS = [{"name": "N1", "url": "https://facebook.com/groups/abc", "enabled": True}]
# Ngày phải sinh ĐỘNG: hardcode "2026-07-26" làm check posts_today FAIL giả từ hôm sau,
# và FAIL giả lặp lại khiến người vận hành quen tay bỏ qua, che mất 1 FAIL thật.
NOW_ISO = datetime.now().isoformat(timespec="seconds")
GOOD = {"time": NOW_ISO, "status": "success",
        "group_url": GROUPS[0]["url"], "group_name": "N1", "public": True}
BAD = {"foo": "bar"}                       # thiếu time/status/group_url/group_name


def use_log(entries):
    store.load_log = lambda: list(entries)
    scheduler.load_log = lambda: list(entries)


# ── 3) Entry log HỎNG không được làm crash thống kê (bracket-access → 500) ──────
LOG = [GOOD, BAD]
use_log(LOG)
ok, err = True, ""
for fn in (lambda: scheduler.posts_today(LOG),
           lambda: scheduler.last_attempt_time(LOG, GROUPS[0]["url"]),
           lambda: store.stats_summary(cfg or {"max_posts_per_day": 0}, 1),
           lambda: store.posts_per_day(14),
           lambda: store.per_group_stats(GROUPS)):
    try:
        fn()
    except Exception as e:
        ok, err = False, f"{type(e).__name__}: {e}"
        break
check("entry log hỏng không crash", ok, err)
check("posts_today đếm đúng (bỏ entry hỏng)", scheduler.posts_today(LOG) == 1)

# ── 4) pick_images: số ảnh THẬT ít hơn images_per_post_min → không được ném ValueError ──
with tempfile.TemporaryDirectory() as td:
    (Path(td) / "a.jpg").write_bytes(b"")          # chỉ 1 ảnh, cấu hình đòi min=3
    few = {"images_dir": td, "use_all_images": False,
           "images_per_post_min": 3, "images_per_post_max": 6}
    try:
        got = scheduler.pick_images(few)
        check("pick_images: 1 ảnh < min=3 vẫn chạy", len(got) == 1, f"trả {len(got)} ảnh")
    except Exception as e:
        check("pick_images: 1 ảnh < min=3 vẫn chạy", False, f"{type(e).__name__}: {e}")

# ── 5) per_group_stats: CHƯA ĐO ≠ 0 (0 giả làm người vận hành kết luận sai) ─────
use_log([GOOD])
row = store.per_group_stats(GROUPS)[0]
check("per_group_stats: chưa đo → None (không phải 0)",
      row["reactions"] is None and row["comments"] is None,
      f"reactions={row['reactions']!r} comments={row['comments']!r}")
use_log([{**GOOD, "reactions": 3, "comments": 1}])
row2 = store.per_group_stats(GROUPS)[0]
check("per_group_stats: đã đo → cộng đúng", row2["reactions"] == 3 and row2["comments"] == 1,
      f"reactions={row2['reactions']!r} comments={row2['comments']!r}")

# ── 6) group_id: cùng regex ở cả 3 nơi + loại đúng ?query của link FB mobile ────
PAT = r"/groups/([^/?#]+)"
m = re.search(PAT, "https://facebook.com/groups/123456789?ref=share_x")
check("regex group_id loại được ?query", bool(m) and m.group(1) == "123456789",
      m.group(1) if m else "không khớp")
srcs = {f: (ROOT / f).read_text(encoding="utf-8")
        for f in ("open_groups.py", "check_joined.py", "src/poster.py")}
bad_pat = [f for f, s in srcs.items() if PAT not in s or r"/groups/([^/]+)" in s]
check("group_id đồng bộ regex ở 3 file", not bad_pat, f"lệch: {bad_pat}")

# ── 7) dashboard: MỌI get_json(silent=True) phải có `or {}` (None → 500) ────────
app = (ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
safe = app.count("get_json(silent=True) or {}")
bare = len(re.findall(r"get_json\(silent=True\)(?!\s*or\s*\{\})", app))
check("dashboard: get_json(silent) luôn có `or {}`", safe >= 3 and bare == 0,
      f"có-guard={safe} thiếu-guard={bare}")

# ── 8) dashboard: so mật khẩu hằng-thời-gian ───────────────────────────────────
check("dashboard: dùng hmac.compare_digest",
      "hmac.compare_digest" in app and "import hmac" in app
      and 'p == AUTH.get("password")' not in app)
# compare_digest trên str non-ASCII ném TypeError → phải so trên bytes, nếu không
# mật khẩu tiếng Việt làm mọi request dashboard 500. Kiểm bằng hành vi thật.
_pw = "mậtkhẩu-tiếngviệt"
try:
    import hmac as _h
    _h.compare_digest(_pw, _pw)
    _str_ok = True                      # Python này cho phép str non-ASCII
except TypeError:
    _str_ok = False
check("dashboard: compare_digest so trên bytes (mật khẩu tiếng Việt)",
      _str_ok or app.count('.encode("utf-8")') >= 4,
      "compare_digest gọi trên str → mật khẩu non-ASCII sẽ 500")

# ── 9) stealth: check_joined.py dùng patchright, không lẫn playwright ───────────
check("check_joined.py dùng patchright",
      "from patchright" in srcs["check_joined.py"] and "from playwright" not in srcs["check_joined.py"])

# ── 10) check_joined.py ghi groups.json có khoá + đọc lại (chống lost update) ───
cj = srcs["check_joined.py"]
check("check_joined.py: ghi groups.json trong _file_lock + đọc lại",
      'store._file_lock("groups")' in cj and "store._write_json(GROUPS" in cj
      and "GROUPS.write_text" not in cj)

# ── 11) dashboard: read-modify-write nằm trong khoá ────────────────────────────
check("dashboard: toggle/config có _file_lock",
      'store._file_lock("groups")' in app and 'store._file_lock("config")' in app)

# ── 12) [src] worker: retry startup không break khi uid rỗng ───────────────────
w = (SRC / "worker.py").read_text(encoding="utf-8")
check("[src] worker: startup retry guard `if uid:`",
      "uid = poster.get_user_id(page)" in w and "if uid:" in w
      and not re.search(r"get_user_id\(page\)\s*\n\s*break", w))

# ── 13) [src] worker: mỗi lệnh dashboard bọc try riêng (1 lệnh lỗi ≠ mất lệnh sau) ──
check("[src] worker: handle_commands bọc từng lệnh",
      "cmds = store.pop_all_commands()" in w and "cmds[i + 1:]" in w
      and "Lệnh '{action}' lỗi" in w)

# ── 14) [src] worker: post_now thiếu group_url phải có dấu vết trong log ───────
check("[src] worker: post_now thiếu url có log", "post_now thiếu group_url" in w)

# ── 15) [src] worker: reset n_fail khi Resume ──────────────────────────────────
check("[src] worker: reset n_fail khi Resume",
      'st.get("prev_paused")' in w and 'st["prev_paused"] = paused' in w)

# ── 16) [src] worker: mất record bài ĐÃ ĐĂNG → tự pause (chống đăng trùng) ─────
check("[src] worker: _safe_append thất bại → set_paused",
      'if entry.get("status") == "success":' in w and "deadletter" in w
      and w.count("store.set_paused(True)") >= 2)

# ── 17) [src] poster: có dọn screenshot (chống đầy đĩa khi chạy dài) ───────────
p_src = srcs["src/poster.py"]
check("[src] poster: có _prune_screenshots + được gọi",
      "def _prune_screenshots" in p_src and "_prune_screenshots()" in p_src
      and "unlink" in p_src)

# ── 18) dashboard UI: bảng theo-nhóm phân biệt "chưa đo" ──────────────────────
html = (ROOT / "dashboard" / "templates" / "index.html").read_text(encoding="utf-8")
check("index.html: bảng nhóm dùng ??\"—\" (không ||0)",
      'x.reactions??"—"' in html and "x.reactions||0" not in html)

# ── 19) (tùy) graph.json toàn vẹn nếu đã chạy graphify ─────────────────────────
g = ROOT / "graphify-out" / "graph.json"
if g.exists():
    G = json.loads(g.read_text(encoding="utf-8"))
    ids = {n["id"] for n in G["nodes"]}
    dangling = sum(1 for e in G["links"] if e.get("source") not in ids or e.get("target") not in ids)
    check("graph.json: nodes>0 & 0 dangling", len(G["nodes"]) > 0 and dangling == 0,
          f"nodes={len(G['nodes'])} dangling={dangling}")

# ── 20) Khoá liên-tiến-trình CHẠY THẬT: 2 tiến trình read-modify-write, không mất update ──
# Đây là nền tảng của mọi fix race ở dashboard/check_joined — phải chứng minh bằng
# tiến trình thật, không chỉ đọc mã.
CHILD = (
    "import json, sys\n"
    "from pathlib import Path\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import store\n"
    "tgt = Path(sys.argv[2])\n"
    "for _ in range(25):\n"
    "    with store._file_lock('verify_race'):\n"
    "        d = json.loads(tgt.read_text(encoding='utf-8'))\n"
    "        d['n'] += 1\n"
    "        store._write_json(tgt, d)\n"
)
try:
    with tempfile.TemporaryDirectory() as td:
        tgt = Path(td) / "counter.json"
        tgt.write_text('{"n": 0}', encoding="utf-8")
        child = Path(td) / "child.py"
        child.write_text(CHILD, encoding="utf-8")
        procs = [subprocess.Popen([sys.executable, str(child), str(SRC), str(tgt)])
                 for _ in range(2)]
        for pr in procs:
            pr.wait(timeout=120)
        got = json.loads(tgt.read_text(encoding="utf-8"))["n"]
        check("khoá liên-tiến-trình: 2×25 tăng, không mất update", got == 50, f"đếm được {got}/50")
except Exception as e:
    check("khoá liên-tiến-trình: 2×25 tăng, không mất update", False, f"{type(e).__name__}: {e}")

# ── 21) README hướng dẫn copy .example (thiếu → clone mới crash) ────────────────
rd = (ROOT / "README.md").read_text(encoding="utf-8")
check("README có bước copy config/auth từ .example",
      "config.json.example` thành `config.json" in rd
      and "auth.json.example` thành `dashboard/auth.json" in rd)

# ── 22) write_status GHI ĐÈ (không merge) → loop_once buộc phải đọc lại paused ──
# Đây là nguyên nhân gốc làm alert "mất record bài đã đăng" bị xoá ngay trong cùng lượt.
_status = ROOT / "state" / "status.json"
_ctrl = ROOT / "state" / "control.json"
_bak = {f: f.read_bytes() for f in (_status, _ctrl) if f.exists()}
try:
    store.write_status({"state": "paused", "alert": "GIU-ALERT"})
    store.write_status({"state": "running"})
    check("store.write_status ghi đè cả file (không merge)",
          "alert" not in store.read_status(),
          "nếu đã merge thì bỏ được guard paused_now ở loop_once")
finally:
    for f in (_status, _ctrl):
        if f in _bak:
            f.write_bytes(_bak[f])
        else:
            f.unlink(missing_ok=True)

# ── 23) [src] loop_once đọc lại paused trước write_status cuối (giữ alert) ──────
check("[src] loop_once đọc lại paused trước write_status",
      "paused_now = store.is_paused()" in w and "if paused_now and not paused:" in w)

# ── 24) [src] _safe_append: nhánh tự-pause lỗi phải LOG, không `pass` im lặng ───
check("[src] _safe_append: không nuốt im lặng lỗi tự-pause",
      "KHÔNG tự dừng được" in w)

# ── 25) pick_images cảnh báo khi config max < min (trước đây crash nên lộ lỗi) ──
import contextlib  # noqa: E402
import io  # noqa: E402
with tempfile.TemporaryDirectory() as td:
    for nm in ("a.jpg", "b.jpg", "c.jpg"):
        (Path(td) / nm).write_bytes(b"")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        got = scheduler.pick_images({"images_dir": td, "use_all_images": False,
                                     "images_per_post_min": 6, "images_per_post_max": 2})
    out = buf.getvalue()
    check("pick_images cảnh báo khi max < min", "cấu hình sai" in out and len(got) == 2,
          f"stdout={out.strip()!r} n={len(got)}")

# ── 26) Hành vi THẬT của dashboard (cần Flask → chạy bằng venv nếu có) ─────────
vpy = ROOT / "venv" / "bin" / "python"
vpy = vpy if vpy.exists() else (ROOT / "venv" / "Scripts" / "python.exe")
if vpy.exists() and (ROOT / "verify_dashboard.py").exists():
    d = subprocess.run([str(vpy), str(ROOT / "verify_dashboard.py")],
                       capture_output=True, text=True, timeout=300)
    for line in d.stdout.strip().splitlines():
        if line.strip().startswith(("OK", "FAIL")):
            print("  " + line.strip())
    check("hành vi dashboard (verify_dashboard.py)", d.returncode == 0,
          (d.stdout + d.stderr).strip()[-400:])
else:
    print("  SKIP hành vi dashboard — chưa có venv/Flask "
          "(chạy: python -m venv venv && venv/bin/pip install -r requirements.txt)")

# ── 27) Dead code đã xoá (Boss quyết) không còn trong bất kỳ .py nào (cho phép ở .md) ──
DEAD_NAMES = ["next_delay_seconds", "read_engagement", "find_user_post_in_group"]
_self = Path(__file__).resolve()
leftover = []
for pf in py_files:                    # py_files: toàn bộ *.py gốc + src/ + dashboard/ (mục 1)
    if Path(pf).resolve() == _self:
        continue                       # verify.py được phép chứa tên (chính danh sách DEAD_NAMES này)
    s = Path(pf).read_text(encoding="utf-8")
    leftover += [f"{Path(pf).name}:{n}" for n in DEAD_NAMES if n in s]
check("dead code: 3 hàm đã xoá khỏi mọi .py", not leftover, f"còn {leftover}")

# ── 28) HÀNH VI: worker._prune_dir giữ đúng N file MỚI NHẤT (dọn video/trace) ───
# worker.py import patchright ở module level; verify chạy python hệ thống có thể chưa
# cài → stub module chỉ đủ để import được (không đụng trình duyệt thật).
import os     # noqa: E402
import types  # noqa: E402
try:
    import patchright  # noqa: F401
except ImportError:
    _pr = types.ModuleType("patchright")
    _sa = types.ModuleType("patchright.sync_api")
    _sa.sync_playwright = None
    _sa.TimeoutError = type("TimeoutError", (Exception,), {})
    _pr.sync_api = _sa
    sys.modules["patchright"] = _pr
    sys.modules["patchright.sync_api"] = _sa
import worker  # noqa: E402

with tempfile.TemporaryDirectory() as td:
    d = Path(td)
    # 7 video + 5 trace, mtime tăng theo chỉ số (chỉ số lớn = file mới hơn)
    for i in range(7):
        f = d / f"v{i}.webm"
        f.write_bytes(b"")
        os.utime(f, (1_700_000_000 + i,) * 2)
    for i in range(5):
        f = d / f"trace-{i}.zip"
        f.write_bytes(b"")
        os.utime(f, (1_700_000_100 + i,) * 2)
    worker._prune_dir(d, "*.webm", 3)
    worker._prune_dir(d, "trace-*.zip", 2)
    vids = sorted(p.name for p in d.glob("*.webm"))
    traces = sorted(p.name for p in d.glob("trace-*.zip"))
    check("prune video: giữ đúng 3 file mới nhất",
          vids == ["v4.webm", "v5.webm", "v6.webm"], f"còn {vids}")
    check("prune trace: giữ đúng 2 file mới nhất",
          traces == ["trace-3.zip", "trace-4.zip"], f"còn {traces}")
# Regex bắt LỜI GỌI ở vị trí statement (dòng thụt đầu): chuỗi "_prune_debug_artifacts()"
# trần khớp luôn cả dòng `def _prune_debug_artifacts():` → xoá mất lời gọi thật trong
# main() thì check vẫn OK — đúng kiểu check tự dối đã bị bắt ở vòng review trước.
check("[src] worker: _prune_debug_artifacts được gọi lúc khởi động",
      bool(re.search(r"^\s+_prune_debug_artifacts\(\)", w, re.MULTILINE))
      and "VIDEO_KEEP" in w and "TRACE_KEEP" in w)

print()
if fails:
    print(f"KẾT QUẢ: FAIL ({len(fails)}/{total} mục): " + ", ".join(fails))
    sys.exit(1)
print(f"KẾT QUẢ: PASS — {total}/{total} kiểm chứng đạt.")
sys.exit(0)
