"""Thao tác giống người thật: di chuột theo đường cong, gõ phím có nhịp, nghỉ giữa bước."""
import math
import random
import time

# Vị trí chuột ước lượng gần nhất (page.mouse không expose vị trí hiện tại)
_last_mouse = {"x": None, "y": None}


def pause(min_s: float = 1.2, max_s: float = 3.5):
    """Nghỉ ngẫu nhiên giữa hai thao tác (chậm hơn, giống người)."""
    time.sleep(random.uniform(min_s, max_s))


def wind_mouse_path(x0, y0, x1, y1, G=9.0, W=3.0, M=15.0, D=12.0):
    """Sinh đường đi chuột kiểu người thật (wind-mouse: gió + trọng lực hút về đích).
    Trả về list các điểm (x, y) liên tục, cong tự nhiên. Thuật toán tự cài."""
    pts = []
    vx = vy = wx = wy = 0.0
    cx, cy = float(x0), float(y0)
    sqrt3, sqrt5 = math.sqrt(3), math.sqrt(5)
    dist = math.hypot(x1 - cx, y1 - cy)
    guard = 0
    while dist >= 2 and guard < 1500:
        guard += 1
        w = min(W, dist)
        if dist >= D:
            wx = wx / sqrt3 + (2 * random.random() - 1) * w / sqrt5
            wy = wy / sqrt3 + (2 * random.random() - 1) * w / sqrt5
        else:
            wx /= sqrt3
            wy /= sqrt3
        vx += wx + G * (x1 - cx) / dist
        vy += wy + G * (y1 - cy) / dist
        vmag = math.hypot(vx, vy)
        if vmag > M:
            vclip = M / 2 + random.random() * M / 2
            vx = vx / vmag * vclip
            vy = vy / vmag * vclip
        cx += vx
        cy += vy
        pts.append((cx, cy))
        dist = math.hypot(x1 - cx, y1 - cy)
    pts.append((float(x1), float(y1)))
    return pts


def move_mouse(page, x, y):
    """Di chuột tới (x, y) theo đường cong wind-mouse (không nhảy thẳng)."""
    x0, y0 = _last_mouse["x"], _last_mouse["y"]
    if x0 is None:                       # chưa biết vị trí → xuất phát lệch ngẫu nhiên
        x0 = x + random.randint(-250, 250)
        y0 = y + random.randint(-180, 180)
    path = wind_mouse_path(x0, y0, x, y)
    # Mỗi page.mouse.move là 1 lệnh CDP; path có thể tới hàng nghìn điểm → treo trên VPS.
    # Lấy mẫu đều tối đa MAX_STEPS điểm (chuột vẫn cong tự nhiên), luôn giữ điểm cuối = đích.
    MAX_STEPS = 24
    if len(path) > MAX_STEPS:
        step = len(path) / MAX_STEPS
        path = [path[int(i * step)] for i in range(MAX_STEPS)] + [path[-1]]
    for px, py in path:
        page.mouse.move(px, py)
        time.sleep(random.uniform(0.004, 0.02))   # nhịp giữa các bước → chuột không "nhảy" tức thì
    _last_mouse["x"], _last_mouse["y"] = x, y


def human_click(locator):
    """Di chuột cong tới 1 điểm ngẫu nhiên bên trong element rồi click."""
    page = locator.page
    # Cuộn element vào tầm nhìn trước (click theo toạ độ tĩnh sẽ hụt nếu element
    # nằm ngoài viewport — locator.click() tự làm việc này, mouse.click() thì không).
    try:
        locator.scroll_into_view_if_needed(timeout=5000)
    except Exception:
        pass
    box = locator.bounding_box()
    if not box:
        locator.click()                  # fallback nếu không lấy được toạ độ
        return
    tx = box["x"] + box["width"] * random.uniform(0.3, 0.7)
    ty = box["y"] + box["height"] * random.uniform(0.35, 0.65)
    move_mouse(page, tx, ty)
    pause(0.08, 0.35)
    page.mouse.click(tx, ty)


_TYPO_KEYS = "qwertyuiopasdfghjklzxcvbnm"


def type_text(locator, text: str):
    """Gõ text vào một element như người thật: nhịp theo cụm từ, thỉnh thoảng gõ
    sai rồi backspace, hay dừng "suy nghĩ" ở ranh giới từ. Giảm bị FB gắn cờ bot."""
    page = locator.page
    locator.click()
    pause(0.8, 1.8)
    for line in text.split("\n"):
        words = line.split(" ")
        for wi, word in enumerate(words):
            for ch in word:
                # ~2% gõ sai 1 phím rồi xóa đi (rất người)
                if random.random() < 0.02:
                    page.keyboard.type(random.choice(_TYPO_KEYS), delay=random.uniform(60, 140))
                    time.sleep(random.uniform(0.10, 0.30))
                    page.keyboard.press("Backspace")
                    time.sleep(random.uniform(0.05, 0.15))
                page.keyboard.type(ch, delay=random.uniform(45, 150))
            if wi < len(words) - 1:
                page.keyboard.type(" ", delay=random.uniform(40, 90))
            # ~10% dừng "suy nghĩ" ở ranh giới từ
            if random.random() < 0.10:
                time.sleep(random.uniform(0.4, 1.3))
        page.keyboard.down("Shift")
        page.keyboard.press("Enter")
        page.keyboard.up("Shift")
        time.sleep(random.uniform(0.2, 0.6))


def scroll_a_bit(page):
    """Cuộn trang nhẹ vài lần như người đang xem, rồi cuộn về đầu."""
    for _ in range(random.randint(1, 3)):
        page.mouse.wheel(0, random.randint(200, 600))
        pause(0.5, 1.5)
    page.mouse.wheel(0, -3000)
    pause(0.5, 1.0)
