"""Worker chạy nền: sở hữu trình duyệt, đăng bài theo lịch, nhận lệnh từ dashboard,
định kỳ quét tương tác (like/comment) các bài đã được duyệt.

Chạy: venv/bin/python src/worker.py
Chạy đăng 1 nhóm rồi thoát (test): python src/worker.py --one <url>
"""
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from patchright.sync_api import sync_playwright

import poster
import scheduler
import store

ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = ROOT / "state" / "browser_profile"

LOOP_SECONDS = 45              # nhịp vòng lặp (để phản hồi lệnh nhanh)
METRIC_REFRESH_HOURS = 2       # chu kỳ kiểm chứng công khai
METRIC_MAX_PER_CYCLE = 6       # số bài quét mỗi lần (tránh hoạt động dồn dập)
MAX_CONSECUTIVE_FAILS = 3      # circuit breaker: tự dừng sau N lần đăng lỗi liên tiếp
RL_BASE_MINUTES = 15           # backoff rate-limit: nghỉ cơ sở (phút)
RL_CAP_MINUTES = 120           # backoff rate-limit: trần thời gian nghỉ (phút)
VIDEO_KEEP = 20                # giữ tối đa N video debug (.webm) gần nhất
TRACE_KEEP = 10                # giữ tối đa N file trace (trace-*.zip) gần nhất


def log_print(msg: str):
    print(f"[{datetime.now():%m-%d %H:%M:%S}] {msg}", flush=True)


def _prune_dir(folder: Path, pattern: str, keep: int):
    """Giữ tối đa `keep` file khớp `pattern` mới nhất trong `folder`, xoá phần cũ hơn."""
    try:
        files = sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime)
        for old in (files[:-keep] if len(files) > keep else []):
            old.unlink(missing_ok=True)
    except Exception as e:
        print(f"[debug prune fail] {folder}/{pattern}: {e}", flush=True)   # dọn lỗi không được giết worker


def _prune_debug_artifacts():
    """Xoá video/trace debug cũ vượt hạn mức — chạy MỘT LẦN lúc khởi động.

    Worker chạy VPS nhiều tháng; bật debug_video/debug_trace rồi quên tắt thì
    .webm + trace-*.zip phình vô hạn → đầy đĩa, mọi ghi file sau đó bắt đầu lỗi
    (cùng lý do dọn screenshot ở poster._prune_screenshots).
    """
    _prune_dir(ROOT / "state" / "debug_video", "*.webm", VIDEO_KEEP)
    _prune_dir(ROOT / "state", "trace-*.zip", TRACE_KEEP)


def do_post(page, config, group: dict, uid: str) -> str:
    """Đăng 1 bài, ghi log đầy đủ. Trả về status.

    1.2 — pick_content/pick_images nằm TRONG try: nếu thiếu content/ảnh thì ghi
    entry status=error rồi trả về, KHÔNG ném lỗi ra vòng lặp (worker vẫn sống)."""
    entry = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "group_name": group["name"],
        "group_url": group["url"],
        "content_file": None,
        "images": [],
        "permalink": None,
        "approval_status": None,
        "reactions": None,
        "comments": None,
        "last_checked": None,
    }
    try:
        recent = store.recent_texts_for_group(group["url"])
        content_name, content = scheduler.pick_unique_content(recent)
        images = scheduler.pick_images(config)
        entry["content_file"] = content_name
        entry["posted_text"] = content          # lưu để near-dup check lần sau
        entry["images"] = [Path(i).name for i in images]
        log_print(f"Đăng vào: {group['name']} | {content_name} | {len(images)} ảnh")
        result = poster.post_to_group(page, group["url"], content, images, uid=uid)
        entry["status"] = "success"
        entry["approval_status"] = result.get("approval_status")
        entry["permalink"] = result.get("permalink")
        log_print(f"  → Thành công ✔ ({result.get('approval_status')})")
        status = "success"
    except poster.CheckpointError:
        entry["status"] = "checkpoint"
        _safe_append(entry)
        raise
    except poster.RateLimitError:
        # Không ghi thành lỗi nhóm (nhóm chưa thực sự thử được) — để vòng lặp lùi nhịp
        log_print("  → Bị giới hạn tần suất, sẽ tạm nghỉ.")
        raise
    except poster.NotLoggedInError:
        # Session chết → dừng NGAY như checkpoint, không đếm vào circuit breaker.
        entry["status"] = "not_logged_in"
        _safe_append(entry)
        raise
    except Exception as e:
        entry["status"] = "error"
        entry["error"] = str(e)
        log_print(f"  → LỖI: {e}")
        status = "error"
    _safe_append(entry)
    return status


def _safe_append(entry: dict):
    """Ghi log bài; nếu ghi thất bại thì đẩy dead-letter + cảnh báo, không để mất dấu
    (mất record bài đã đăng → nguy cơ đăng trùng vòng sau)."""
    try:
        store.append_post(entry)
    except Exception as e:
        log_print(f"  ⚠ GHI LOG THẤT BẠI ({e}) — ghi tạm dead-letter.")
        try:
            import json as _json
            dl = ROOT / "state" / "deadletter_posts.jsonl"
            dl.parent.mkdir(parents=True, exist_ok=True)
            with open(dl, "a", encoding="utf-8") as f:
                f.write(_json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass
        # Dead-letter KHÔNG có nơi nào đọc lại (chỉ có chỗ ghi này) → với bài ĐÃ ĐĂNG
        # thành công, posted_log.json không còn dấu vết; pick_overdue_group coi nhóm đó
        # "chưa từng đăng" (datetime.min = ưu tiên cao nhất) và đăng LẠI sau ~45-90s.
        # Tự dừng thay vì đăng trùng — lỗi ghi (đĩa đầy/quyền) không tự khỏi.
        if entry.get("status") == "success":
            try:
                store.set_paused(True)
                log_print("⛔ Tự dừng: mất record bài ĐÃ ĐĂNG → nguy cơ đăng trùng. "
                          "Sửa lỗi ghi file rồi bấm Resume.")
                store.write_status({
                    "state": "paused",
                    "alert": "Ghi posted_log.json THẤT BẠI cho 1 bài đã đăng "
                             "(xem state/deadletter_posts.jsonl). Đã tự tạm dừng để "
                             "tránh đăng trùng vào cùng nhóm. Kiểm tra dung lượng đĩa/quyền ghi."})
            except Exception as e2:
                # Nếu chính set_paused/write_status cũng lỗi (rất dễ: cùng nguyên nhân
                # đĩa đầy) thì cơ chế chống-đăng-trùng đã THẤT BẠI — phải nói ra, không
                # được im lặng tuyệt đối.
                log_print(f"  ⛔ KHÔNG tự dừng được ({e2}) — NGUY CƠ ĐĂNG TRÙNG. "
                          f"Tắt worker bằng tay ngay.")


def verify_public(p, config, poster_uid: str, limit: int = 15):
    """Kiểm chứng TRUNG THỰC: dùng nick khác (verifier_profile) mở trang bài của
    poster_uid trong nhóm — thấy bài = công khai thật; không thấy = còn chờ duyệt.
    Không tin vào mắt chính nick đăng."""
    vp = config.get("verifier_profile")
    if not vp or not poster_uid:
        return
    log = store.load_log()
    now = datetime.now()
    # Guard từng entry: entry log hỏng/thiếu key hoặc "time" sai định dạng không được
    # làm sập cả lượt verify (chỉ bỏ qua entry đó).
    recent = []
    for e in log:
        if e.get("status") != "success" or e.get("public") is True:
            continue
        if e.get("group_name") == "(test)" or not e.get("group_url"):
            continue
        t = e.get("time")
        if not t:
            continue
        try:
            if (now - datetime.fromisoformat(t)) >= timedelta(days=2):
                continue
        except ValueError:
            continue
        recent.append(e)
    if not recent:
        return
    gids = {}
    for e in recent:
        gids.setdefault(poster.group_id_from_url(e["group_url"]), []).append(e)
    log_print(f"Kiểm chứng công khai {len(gids)} nhóm (nick verifier)...")
    try:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=vp, channel="chrome",
            headless=config.get("headless", False), no_viewport=True)
    except Exception as e:
        # Profile verifier hỏng/đang khoá → báo lỗi thật, không để finally ctx.close() ném NameError.
        log_print(f"⚠ Không mở được profile verifier (bỏ qua lượt kiểm chứng): {e}")
        return
    vpage = ctx.pages[0] if ctx.pages else ctx.new_page()
    try:
        for gid, entries in list(gids.items())[:limit]:
            try:
                vpage.goto(f"https://www.facebook.com/groups/{gid}/user/{poster_uid}/",
                           wait_until="domcontentloaded", timeout=60000)
                vpage.wait_for_timeout(4500)
                body = vpage.locator("body").inner_text()
                _mk = (config.get("contact_phone") or "").strip()
                pub = bool(_mk and _mk in body) and ("chưa có bài viết" not in body.lower())
                for e in entries:
                    e["public"] = bool(pub)
                    e["approval_status"] = "live" if pub else "pending"
                    e["last_checked"] = now.isoformat(timespec="seconds")
            except Exception as ex:
                log_print(f"  verify lỗi: {ex}")
            time.sleep(2)
    finally:
        ctx.close()
    store.save_log(log)


def handle_commands(p, page, config, uid: str):
    """Thực thi các lệnh một-lần từ dashboard."""
    # pop_all_commands() đọc VÀ XOÁ cả hàng đợi trong 1 lock → từ đây các lệnh đã
    # "tiêu thụ", không thể lấy lại. Vì vậy mỗi lệnh phải được bọc riêng: 1 lệnh lỗi
    # không được cuốn theo (làm mất vĩnh viễn) các lệnh còn lại.
    cmds = store.pop_all_commands()
    for i, cmd in enumerate(cmds):
        action = cmd.get("action")
        args = cmd.get("args", {})
        try:
            if action == "post_now":
                url = args.get("group_url")
                name = args.get("group_name", "(đăng ngay)")
                if url:
                    log_print(f"[LỆNH] Đăng ngay: {name}")
                    do_post(page, config, {"name": name, "url": url}, uid)
                else:
                    # Dashboard đã báo "đã gửi lệnh" cho người dùng → im lặng bỏ qua là
                    # nói dối. Ít nhất phải để lại dấu vết trong log worker.
                    log_print(f"[LỆNH] post_now thiếu group_url, bỏ qua: {cmd}")
            elif action == "refresh_metrics":
                log_print("[LỆNH] Kiểm chứng công khai ngay")
                verify_public(p, config, uid)
            else:
                log_print(f"[LỆNH] Bỏ qua lệnh lạ: {action}")
        except (poster.CheckpointError, poster.NotLoggedInError, poster.RateLimitError):
            # Các lỗi này PHẢI nổi lên (thiết kế: dừng/lùi nhịp ngay), nhưng nói rõ
            # lệnh nào bị bỏ thay vì để mất âm thầm.
            dropped = [c.get("action") for c in cmds[i + 1:]]
            if dropped:
                log_print(f"⚠ Bỏ {len(dropped)} lệnh còn lại do phải dừng ngay: {dropped}")
            raise
        except Exception as e:
            log_print(f"⚠ Lệnh '{action}' lỗi ({e}) — bỏ qua, chạy tiếp lệnh sau.")


def write_status(config, state: str, next_post_time, extra=None):
    log = store.load_log()
    st = {
        "state": state,                       # running | paused | posting | idle | checkpoint
        "paused": store.is_paused(),
        "posts_today": scheduler.posts_today(log),
        "quota": config.get("max_posts_per_day"),
        "next_post_time": next_post_time.isoformat(timespec="seconds") if next_post_time else None,
        "posting_hours": f"{config.get('posting_hours_start')}-{config.get('posting_hours_end')}",
    }
    if extra:
        st.update(extra)
    store.write_status(st)


def loop_once(p, page, uid, st):
    """Một nhịp vòng lặp worker. Tách riêng để test được sức chịu lỗi mà không cần
    trình duyệt thật. `st` là dict trạng thái giữ qua các vòng
    (next_post_time, last_metric, rate_limited_until)."""
    config = None
    try:
        config = scheduler.load_config()
        handle_commands(p, page, config, uid)

        now = datetime.now()
        paused = store.is_paused()
        # Resume trên dashboard chỉ set paused=False; n_fail nằm trong RAM worker nên
        # vẫn giữ giá trị cũ (= ngưỡng) → chỉ 1 lỗi mới là circuit breaker kích hoạt lại
        # ngay, kèm thông báo sai số lần. Đặt lại bộ đếm khi paused chuyển True→False.
        if st.get("prev_paused") and not paused:
            st["n_fail"] = 0
            st["rl_streak"] = 0
            log_print("▶ Resume — đặt lại bộ đếm lỗi liên tiếp.")
        st["prev_paused"] = paused
        in_hours = scheduler.in_posting_hours(config)

        # Đăng bài: mỗi nhóm có đồng hồ riêng (repost_interval_minutes)
        if not paused and in_hours and now >= st["next_post_time"] and now >= st["rate_limited_until"]:
            group = scheduler.pick_overdue_group(config)
            if group:
                write_status(config, "posting", st["next_post_time"])
                status = do_post(page, config, group, uid)
                # 1.8 — circuit breaker: đếm lỗi liên tiếp, tự dừng nếu chạm ngưỡng
                if status == "success":
                    st["n_fail"] = 0
                    st["rl_streak"] = 0
                else:
                    st["n_fail"] = st.get("n_fail", 0) + 1
                    limit = config.get("max_consecutive_fails", MAX_CONSECUTIVE_FAILS)
                    if st["n_fail"] >= limit:
                        store.set_paused(True)
                        log_print(f"⛔ Tự dừng: {st['n_fail']} lần đăng lỗi liên tiếp — chờ xử lý tay.")
                        write_status(config, "paused", None,
                                     {"alert": f"Đã TỰ TẠM DỪNG sau {st['n_fail']} lần đăng lỗi "
                                               f"liên tiếp. Kiểm tra tài khoản/nội dung rồi bấm Resume."})
                spacing = scheduler.post_spacing_seconds(
                    config, scheduler.count_enabled())
                st["next_post_time"] = datetime.now() + timedelta(seconds=spacing)
                log_print(f"Bài kế tiếp lúc {st['next_post_time']:%H:%M} (cách {spacing//60}p)")
            else:
                # chưa nhóm nào tới hạn → kiểm tra lại sau 90s
                st["next_post_time"] = now + timedelta(seconds=90)

        # Kiểm chứng công khai định kỳ khi rảnh (dùng nick verifier)
        if (not paused
                and (now - st["last_metric"]) > timedelta(hours=METRIC_REFRESH_HOURS)
                and (not in_hours or now < st["next_post_time"])):
            verify_public(p, config, uid)
            st["last_metric"] = now

        if now < st["rate_limited_until"]:
            write_status(config, "rate_limited", st["rate_limited_until"],
                         {"alert": f"Facebook giới hạn tần suất — tạm nghỉ đăng tới "
                                   f"{st['rate_limited_until']:%H:%M}. Tài khoản KHÔNG bị khóa (throttle mềm)."})
        else:
            # Đọc LẠI cờ paused: circuit breaker / _safe_append có thể vừa TỰ pause ngay
            # trong lượt này và đã ghi alert giải thích. write_status ghi đè NGUYÊN file
            # status.json, nên nếu dùng biến `paused` đọc từ đầu vòng thì alert vừa ghi
            # bị xoá và state ("running") mâu thuẫn với paused=true.
            paused_now = store.is_paused()
            if paused_now and not paused:
                pass                    # vừa tự pause trong lượt này → giữ nguyên alert
            else:
                state = "paused" if paused_now else ("idle" if not in_hours else "running")
                write_status(config, state, st["next_post_time"])
    except poster.RateLimitError:
        # 1.9 — lùi theo cấp số nhân + Equal Jitter: nghỉ dài dần khi bị giới hạn
        # liên tiếp, có nhiễu để không thành khuôn máy móc. Reset khi 1 bài thành công.
        cfg = config or {}
        st["rl_streak"] = st.get("rl_streak", 0) + 1
        base = cfg.get("rate_limit_base_minutes", RL_BASE_MINUTES)
        cap = cfg.get("rate_limit_cap_minutes", RL_CAP_MINUTES)
        raw = min(base * (2 ** (st["rl_streak"] - 1)), cap)
        delay = raw / 2 + random.uniform(0, raw / 2)   # Equal Jitter: [raw/2, raw]
        st["rate_limited_until"] = datetime.now() + timedelta(minutes=delay)
        st["next_post_time"] = st["rate_limited_until"]
        log_print(f"⏸ Giới hạn tần suất lần {st['rl_streak']} — nghỉ ~{delay:.0f}p tới {st['rate_limited_until']:%H:%M}.")
        write_status(config, "rate_limited", st["rate_limited_until"],
                     {"alert": f"Facebook giới hạn tần suất (lần {st['rl_streak']}) — tạm nghỉ đăng tới "
                               f"{st['rate_limited_until']:%H:%M}. Tài khoản KHÔNG bị khóa, đây là throttle mềm."})
    except poster.CheckpointError as e:
        log_print("⚠ CHECKPOINT — dừng đăng, chờ xử lý.")
        store.set_paused(True)
        write_status(config, "checkpoint", None, {"alert": str(e)})
    except poster.NotLoggedInError as e:
        log_print("⚠ CHƯA ĐĂNG NHẬP — session mất, dừng đăng. Chạy lại login.py rồi Resume.")
        store.set_paused(True)
        write_status(config, "checkpoint", None,
                     {"alert": "Session Facebook đã mất — chạy lại login.py rồi bấm Resume. " + str(e)})
    except Exception as e:
        # 1.1 — BẤT KỲ lỗi lạ nào cũng không được làm sập vòng lặp: log rồi chạy tiếp.
        log_print(f"⚠ Lỗi ngoài dự kiến trong vòng lặp (bỏ qua, chạy tiếp): {e}")
        try:
            write_status(config or scheduler.load_config(), "error",
                         st.get("next_post_time"), {"alert": str(e)})
        except Exception:
            pass


def main():
    single_url = None
    if len(sys.argv) >= 3 and sys.argv[1] == "--one":
        single_url = sys.argv[2]

    if not PROFILE_DIR.exists():
        log_print("Chưa có profile trình duyệt. Chạy login trước.")
        sys.exit(1)

    _cfg = scheduler.load_config()
    _proxy = _cfg.get("proxy") or None
    if _proxy and not _proxy.get("server"):
        _proxy = None
    if _proxy:
        log_print(f"Dùng proxy: {_proxy.get('server')}")
    _video_dir = str(ROOT / "state" / "debug_video") if _cfg.get("debug_video") else None
    _prune_debug_artifacts()   # dọn video/trace cũ 1 lần lúc khởi động (không đặt trong vòng lặp nóng)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",        # Patchright: Google Chrome thật
            headless=_cfg.get("headless", False),
            no_viewport=True,        # KHÔNG set viewport/UA/flags custom (khuyến nghị stealth)
            proxy=_proxy,
            record_video_dir=_video_dir,   # 2.5 — quay video khi debug_video bật
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # 2.5 — bật tracing để soi lỗi checkpoint (chỉ khi debug_trace)
        if _cfg.get("debug_trace"):
            try:
                ctx.tracing.start(screenshots=True, snapshots=True, sources=True)
                log_print("🔍 debug_trace BẬT — sẽ lưu state/trace-*.zip khi worker thoát.")
            except Exception as e:
                log_print(f"Không bật được tracing: {e}")

        try:
            # C1 — startup có retry: 1 blip mạng lúc boot KHÔNG được giết cả tiến trình.
            uid = ""
            for attempt in range(1, 6):
                try:
                    page.goto("https://www.facebook.com", wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(3000)
                    uid = poster.get_user_id(page)
                    if uid:
                        break
                    # get_user_id NUỐT exception và trả "" (không raise) → nếu break vô
                    # điều kiện thì retry vô nghĩa: 1 lần load chậm là uid rỗng vĩnh viễn
                    # cả vòng đời tiến trình, verify công khai tắt âm thầm.
                    log_print(f"Khởi động lần {attempt}: chưa lấy được user id"
                              f"{'; thử lại sau 15s...' if attempt < 5 else ' (hết lượt thử).'}")
                except Exception as e:
                    log_print(f"Khởi động lần {attempt} lỗi ({e})"
                              f"{'; thử lại sau 15s...' if attempt < 5 else ' (hết lượt thử).'}")
                if attempt < 5:
                    time.sleep(15)
            if not uid:
                # A3 — uid rỗng làm verify (nick phụ) tắt âm thầm → đẩy cảnh báo nổi bật.
                log_print("⚠ KHÔNG lấy được user id — verify công khai sẽ tắt. Kiểm tra login/mạng/DOM Facebook.")
                try:
                    store.write_status({"state": "warning",
                                        "alert": "Không lấy được user id lúc khởi động — cơ chế verify công khai đang TẮT."})
                except Exception:
                    pass
            log_print(f"Worker khởi động. user id: {uid or '?'}")

            if single_url:
                do_post(page, scheduler.load_config(), {"name": "(test)", "url": single_url}, uid)
                return

            st = {
                "next_post_time": datetime.now(),
                "last_metric": datetime.min,
                "rate_limited_until": datetime.min,
                "n_fail": 0,
                "rl_streak": 0,
            }
            while True:
                loop_once(p, page, uid, st)
                time.sleep(LOOP_SECONDS)
        finally:
            try:
                if _cfg.get("debug_trace"):
                    tp = ROOT / "state" / f"trace-{datetime.now():%Y%m%d_%H%M%S}.zip"
                    ctx.tracing.stop(path=str(tp))
                    log_print(f"🔍 Đã lưu trace: {tp}  (mở bằng: playwright show-trace <file>)")
            except Exception:
                pass
            ctx.close()


if __name__ == "__main__":
    main()
