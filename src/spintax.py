"""Spintax tự viết (không phụ thuộc thư viện ngoài → license sạch).

Cú pháp: {a|b|c} chọn ngẫu nhiên 1 nhánh; hỗ trợ lồng nhau {x{1|2}|y}.
Ký tự '{', '}', '|' không nằm trong cặp ngoặc hợp lệ được giữ nguyên như văn bản.
"""
import random


def _match_brace(s: str, start: int) -> int:
    """Từ '{' tại vị trí `start`, trả index của '}' khớp (cùng độ sâu); -1 nếu thiếu."""
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _split_top(s: str):
    """Tách theo '|' ở cấp ngoài cùng, bỏ qua '|' nằm trong {} lồng."""
    parts, depth, cur = [], 0, []
    for ch in s:
        if ch == "{":
            depth += 1
            cur.append(ch)
        elif ch == "}":
            depth -= 1
            cur.append(ch)
        elif ch == "|" and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


def spin(text: str, rng: random.Random = random) -> str:
    """Trả về 1 biến thể ngẫu nhiên của `text`."""
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "{":
            j = _match_brace(text, i)
            if j == -1:                       # ngoặc thiếu đóng → giữ nguyên
                out.append(ch)
                i += 1
                continue
            options = _split_top(text[i + 1:j])
            out.append(spin(rng.choice(options), rng))
            i = j + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def count_variants(text: str) -> int:
    """Tổng số biến thể có thể sinh ra (tích các nhóm nối tiếp, cộng trong 1 nhóm)."""
    i, n, total = 0, len(text), 1
    while i < n:
        ch = text[i]
        if ch == "{":
            j = _match_brace(text, i)
            if j == -1:
                i += 1
                continue
            options = _split_top(text[i + 1:j])
            total *= sum(count_variants(o) for o in options)
            i = j + 1
        else:
            i += 1
    return total
