# === init_db.py (Cập nhật theo Kế hoạch 29.4_2 - Phần 1) ===

import sqlite3
import os

# Tên file cơ sở dữ liệu
DB_NAME = 'database.db'

# Xóa file DB cũ nếu tồn tại để tạo mới (cẩn thận khi dùng trong thực tế)
# Bỏ comment dòng này nếu bạn muốn tạo lại DB từ đầu mỗi lần chạy script
# if os.path.exists(DB_NAME):
#     print(f"Đang xóa cơ sở dữ liệu cũ: {DB_NAME}")
#     os.remove(DB_NAME)

# Kết nối đến cơ sở dữ liệu (sẽ tạo file nếu chưa có)
conn = sqlite3.connect(DB_NAME)
# Kích hoạt hỗ trợ Foreign Key Constraints (QUAN TRỌNG cho trigger)
# Thực hiện ngay sau khi kết nối
conn.execute("PRAGMA foreign_keys = ON")
print(f"Đã kết nối tới cơ sở dữ liệu: {DB_NAME} và bật Foreign Keys.")

cursor = conn.cursor()


# --- Bảng records (Giữ nguyên cấu trúc chính) ---
cursor.execute('''
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mac_address TEXT NOT NULL UNIQUE,
    ip_address TEXT,
    username TEXT,
    device_type TEXT,
    status TEXT,
    record_date DATE,
    details TEXT
)
''')
print("Đã kiểm tra/tạo bảng 'records'.")

# --- Bảng images (Giữ nguyên cấu trúc chính) ---
cursor.execute('''
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id INTEGER NOT NULL,
    image_path TEXT NOT NULL,
    FOREIGN KEY (record_id) REFERENCES records (id) ON DELETE CASCADE
)
''')
print("Đã kiểm tra/tạo bảng 'images'.")

# --- Bảng work_logs (Giữ nguyên cấu trúc chính) ---
cursor.execute('''
CREATE TABLE IF NOT EXISTS work_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    log_date DATE NOT NULL,
    activity_type TEXT NOT NULL,
    description TEXT,
    device_identifier TEXT,
    cost REAL DEFAULT 0.0,
    technician TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
''')
print("Đã kiểm tra/tạo bảng 'work_logs'.")


# === PHẦN BỔ SUNG TỪ KẾ HOẠCH ===

# 1. Thêm Bảng Audit Log [cite: 3, 4]
cursor.execute('''
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ip_address TEXT,       -- Địa chỉ IP của người dùng thực hiện
    action TEXT,           -- Hành động (ví dụ: 'add_record', 'update_record', 'delete_record', 'login', 'logout')
    target_table TEXT,     -- Bảng bị ảnh hưởng (ví dụ: 'records', 'images', 'work_logs')
    target_id INTEGER,     -- ID của bản ghi bị ảnh hưởng (nếu có)
    details TEXT           -- Chi tiết thêm về hành động (ví dụ: "Added record with MAC X", "Deleted image Y from record Z")
);
''')
print("Đã kiểm tra/tạo bảng 'audit_logs'.")

# Tạo chỉ mục cho bảng audit_logs [cite: 5]
cursor.execute('CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs (timestamp);')
print("Đã tạo chỉ mục cho bảng 'audit_logs'.")


# 2. Thêm Trigger Tự động Xóa Dữ liệu Liên quan [cite: 7, 8]
cursor.execute('''
CREATE TRIGGER IF NOT EXISTS delete_related_data
AFTER DELETE ON records
BEGIN
    -- Xóa work logs liên quan bằng MAC address của bản ghi vừa xóa (OLD.mac_address)
    DELETE FROM work_logs
    WHERE device_identifier = OLD.mac_address;

    -- Xóa ảnh đính kèm trong DB bằng record_id (là OLD.id)
    -- Lưu ý: Việc xóa file ảnh vật lý sẽ được xử lý trong code Flask (route delete_record)
    DELETE FROM images
    WHERE record_id = OLD.id;
END;
''')
print("Đã kiểm tra/tạo trigger 'delete_related_data'.")


# 3. Đảm bảo Index cần thiết [cite: 9, 10]
print("Kiểm tra/tạo các chỉ mục cần thiết...")
# Index cho foreign key trong 'images'
cursor.execute("CREATE INDEX IF NOT EXISTS idx_images_record_id ON images (record_id)")
# Index cho tìm kiếm/join trong 'work_logs'
cursor.execute('CREATE INDEX IF NOT EXISTS idx_work_logs_log_date ON work_logs (log_date);')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_work_logs_device_identifier ON work_logs (device_identifier);')
# Index cho việc tìm kiếm trong 'records' (UNIQUE trên mac_address đã tạo index ngầm)
cursor.execute("CREATE INDEX IF NOT EXISTS idx_records_date ON records (record_date)")
print("-> Đã kiểm tra/tạo xong các chỉ mục.")

# === KẾT THÚC PHẦN BỔ SUNG ===


# Lưu thay đổi và đóng kết nối
conn.commit()
conn.close()
print("Đã đóng kết nối cơ sở dữ liệu.")
print("-" * 30)
print("Khởi tạo/Cập nhật cơ sở dữ liệu hoàn tất!")
print(f"File cơ sở dữ liệu '{DB_NAME}' đã được cập nhật theo kế hoạch.")