# === config.py ===

import os
from os.path import abspath, dirname, join

# Lấy đường dẫn thư mục gốc của dự án (nơi chứa file config.py này)
basedir = abspath(dirname(__file__))

class Config:
    """Lớp cấu hình cơ sở."""

    # --- Cài đặt chung ---
    # Lấy SECRET_KEY từ biến môi trường, nếu không có thì dùng key mặc định (CHỈ DÙNG CHO DEVELOPMENT)
    # !!! QUAN TRỌNG: Thay đổi key mặc định và KHÔNG commit key thật lên Git.
    SECRET_KEY = os.environ.get('SECRET_KEY', 'kienhp123')

    # Lấy mật khẩu xóa từ biến môi trường, nếu không có thì dùng mật khẩu mặc định (CHỈ DÙNG CHO DEVELOPMENT)
    # !!! QUAN TRỌNG: Thay đổi mật khẩu mặc định và KHÔNG commit mật khẩu thật lên Git.
    DELETE_PASSWORD = os.environ.get('DELETE_PASSWORD', 'kienhp123')

    # --- Cài đặt Database ---
    DB_NAME = 'database.db'
    # Đường dẫn tuyệt đối đến file SQLite
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL',
                                           f'sqlite:///{join(basedir, DB_NAME)}')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- Cài đặt Upload ---
    # Chỉ định tên thư mục upload (để các phần khác dùng)
    UPLOAD_FOLDER = 'uploads'
    # UPLOAD_FOLDER_ABSOLUTE sẽ được tính toán và thêm vào app.config trong app.py
    # vì nó cần app.root_path

    # --- Cài đặt File tĩnh ---
    STATIC_FOLDER = 'static'

    # --- Cài đặt Phân trang ---
    RECORDS_PER_PAGE = 5
    LOGS_PER_PAGE = 5

    # --- Cài đặt File cho phép ---
    # Lưu ý: Các hàm trong utils.py đang dùng giá trị mặc định bên trong hàm.
    # Nếu muốn quản lý tập trung ở đây, cần sửa utils.py để nhận tham số
    # hoặc import current_app trong utils.py (phức tạp hơn).
    # Giữ ở đây để tham khảo, nhưng hiện tại chưa ảnh hưởng trực tiếp đến utils.py.
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    ALLOWED_EXTENSIONS_IMPORT = {'xlsx'}

# Có thể tạo các lớp kế thừa cho các môi trường khác nhau nếu cần
# class DevelopmentConfig(Config):
#     DEBUG = True

# class ProductionConfig(Config):
#     DEBUG = False
#     # Ví dụ: Lấy DATABASE_URL từ biến môi trường cho production
#     SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') # Bắt buộc có DATABASE_URL cho production