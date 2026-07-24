# Tool tự động đăng bài cho thuê căn hộ lên nhóm Facebook

Tool giúp tự động đăng tin cho thuê/bán căn hộ vào nhiều nhóm Facebook, giãn cách
hợp lý để tránh spam, kèm dashboard theo dõi. **Bản này đã được lọc sạch thông tin
cá nhân của người chia sẻ — bạn tự điền thông tin của mình vào.**

## 1. Chuẩn bị (làm 1 lần)
1. Cài **Python 3** (python.org) — nhớ tích "Add Python to PATH".
2. Mở PowerShell tại thư mục này, chạy lần lượt:
   ```
   python -m venv venv
   venv\Scripts\pip install -r requirements.txt
   venv\Scripts\python -m playwright install chromium
   ```
3. **Bỏ ảnh căn hộ** của bạn (.jpg/.png) vào thư mục `images/`.
4. **Viết bài rao** của bạn vào thư mục `content/` (mỗi file .txt là 1 mẫu; nên 5-8 mẫu).
   Xem `content/bai-mau-1.txt` làm ví dụ.
5. Mở `config.json`, sửa `"contact_phone"` = **số điện thoại của bạn** (số này dùng để
   kiểm tra bài đã lên công khai chưa). Chỉnh khung giờ đăng nếu muốn.

## 2. Đăng nhập Facebook (làm 1 lần)
- Double-click **`login.bat`** → cửa sổ Chrome mở → tự tay đăng nhập tài khoản Facebook
  CỦA BẠN → khi vào được trang chủ thì đóng cửa sổ. Phiên đăng nhập được lưu lại.
- **Nên dùng tài khoản phụ đã dùng lâu**, đừng dùng tài khoản chính quan trọng.

## 3. Tìm & tham gia nhóm
1. Double-click **`find_groups.bat`** → tool quét các nhóm cho thuê (sửa từ khoá trong
   `find_groups.py` theo khu vực/dự án của bạn) → lưu vào `groups_found.json`.
2. Double-click **`open_groups.bat`** để mở các nhóm → tự tay bấm **Tham gia**
   (5-10 nhóm/ngày thôi, tránh bị Facebook hạn chế).
3. Double-click **`check_joined.bat`** để cập nhật nhóm đã vào vào `groups.json`.

## 4. Chạy đăng bài
- Double-click **`run.bat`**. Tool tự đăng lần lượt vào các nhóm theo lịch trong `config.json`.
  Đóng cửa sổ / tắt máy = dừng.

## 5. Dashboard theo dõi (tuỳ chọn)
- Đổi mật khẩu trong `dashboard/auth.json` trước.
- Chạy: `venv\Scripts\python dashboard\app.py` → mở trình duyệt vào `http://<IP>:8088`.

## Lưu ý quan trọng
- **Đừng đăng quá dày.** Facebook giới hạn tần suất; đăng ~250 bài/ngày sẽ bị chặn.
  Mức an toàn: mỗi nhóm 1 lần/ngày (đặt `repost_interval_minutes` cao). Bắt đầu từ từ.
- **Chạy trên VPS nước ngoài sẽ dễ bị Facebook chặn** (IP data center). Nếu chạy VPS,
  nên gắn **proxy dân cư/4G Việt Nam** — điền vào `config.json` mục `"proxy"`:
  `{"server":"http://IP:PORT","username":"...","password":"..."}`.
- Tự động đăng bài vi phạm điều khoản Facebook, tài khoản có thể bị hạn chế. Tự cân nhắc.

Chúc bạn sớm cho thuê/bán được nhà!
