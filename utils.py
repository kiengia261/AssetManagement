# === utils.py ===

import re
import os
import logging
from datetime import datetime, date
import locale # Cần thiết cho currency_format nếu bạn di chuyển nó sau này
from os.path import join, exists # exists được dùng trong delete_physical_files

# --- Cấu hình cơ bản (Sao chép từ app.py nếu cần cho các hàm sau này) ---
# Ví dụ: nếu bạn di chuyển hàm allowed_file/allowed_import_file sau này
# ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
# ALLOWED_EXTENSIONS_IMPORT = {'xlsx'}

# --- Các Hàm Tiện Ích Đã Di Chuyển ---

def normalize_mac(mac_string, separator='-'):
    """Chuẩn hóa địa chỉ MAC về dạng chữ hoa, phân cách bằng separator."""
    if not isinstance(mac_string, str): return None
    # Xóa các ký tự không phải hexa, chuyển thành chữ hoa
    mac_clean = re.sub(r'[^0-9A-F]', '', mac_string.strip().upper())
    # Nếu đúng 12 ký tự hexa, định dạng lại với dấu phân cách
    if len(mac_clean) == 12:
        return separator.join(mac_clean[i:i+2] for i in range(0, 12, 2))
    return None # Trả về None nếu không hợp lệ

def format_date_for_storage(date_str_input):
    """
    Định dạng ngày từ chuỗi đầu vào (nhiều định dạng)
    sang đối tượng date để lưu vào CSDL.
    """
    if not date_str_input: return None
    # Nếu đã là datetime hoặc date object, trả về phần date
    if isinstance(date_str_input, datetime): return date_str_input.date()
    if isinstance(date_str_input, date): return date_str_input

    try:
        date_str_input = str(date_str_input).strip()
        # Các định dạng ngày tháng được hỗ trợ
        supported_formats = ['%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%d/%m/%y', '%d-%m-%y', '%Y/%m/%d']
        for fmt in supported_formats:
            try:
                # Thử chuyển đổi theo từng định dạng
                return datetime.strptime(date_str_input, fmt).date()
            except ValueError:
                continue # Nếu lỗi, thử định dạng tiếp theo

        # Thử xử lý nếu là timestamp (số nguyên)
        if date_str_input.isdigit():
             try:
                 ts = int(date_str_input)
                 # Phân biệt timestamp giây và mili giây (ước lượng)
                 if ts > 253402300799: # Lớn hơn năm 9999 (ms)
                     return datetime.fromtimestamp(ts / 1000).date()
                 else: # Nhỏ hơn (s)
                     return datetime.fromtimestamp(ts).date()
             except (ValueError, OSError):
                 pass # Bỏ qua nếu lỗi chuyển đổi timestamp

        # Nếu không định dạng nào phù hợp
        logging.warning(f"Định dạng ngày '{date_str_input}' không được hỗ trợ hoặc không hợp lệ.")
        return None
    except (ValueError, TypeError) as e:
        # Bắt lỗi chung khi xử lý chuỗi
        logging.error(f"Lỗi format ngày đầu vào '{date_str_input}': {e}")
        return None

def allowed_file(filename, allowed_extensions={'png', 'jpg', 'jpeg', 'gif'}):
    """Kiểm tra phần mở rộng file ảnh được phép."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions

def allowed_import_file(filename, allowed_extensions_import={'xlsx'}):
    """Kiểm tra phần mở rộng file import (Excel) được phép."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions_import

def delete_physical_files(image_paths_list, upload_folder_abs):
    """
    Xóa danh sách các file ảnh vật lý trong thư mục uploads.

    Args:
        image_paths_list (list): Danh sách tên file ảnh cần xóa.
        upload_folder_abs (str): Đường dẫn tuyệt đối đến thư mục uploads.

    Returns:
        tuple: (số file xóa thành công, số file xóa lỗi)
    """
    deleted_count = 0
    error_count = 0
    if not image_paths_list:
        return 0, 0 # Không có gì để xóa

    logging.info(f"Bắt đầu xóa {len(image_paths_list)} file ảnh vật lý...")
    for filename in image_paths_list:
        if not filename: # Bỏ qua tên file rỗng
            continue
        try:
            file_path = join(upload_folder_abs, filename) # Đảm bảo join đã được import
            if exists(file_path): # Đảm bảo exists đã được import
                os.remove(file_path)
                deleted_count += 1
                logging.info(f"Đã xóa file vật lý: {file_path}")
            else:
                # Ghi log nếu file không tồn tại nhưng vẫn được yêu cầu xóa
                logging.warning(f"Không tìm thấy file vật lý để xóa: {file_path}")
        except OSError as e: # Bắt lỗi hệ điều hành (vd: không có quyền)
            error_count += 1
            logging.error(f"Lỗi khi xóa file vật lý {filename}: {e}", exc_info=True)
        except Exception as e: # Bắt các lỗi khác
            error_count += 1
            logging.error(f"Lỗi không xác định khi xóa file {filename}: {e}", exc_info=True)

    logging.info(f"Hoàn tất xóa file vật lý: Xóa thành công {deleted_count}, Lỗi {error_count}.")
    return deleted_count, error_count

# Lưu ý: Các hàm query DB (như get_ip_stats, find_available_ips, build_filters...)
# và các hàm liên quan đến Flask context (log_audit_action, template_filters)
# tạm thời vẫn để ở app.py để giữ sự đơn giản ban đầu.
# Nếu muốn di chuyển chúng sau này, cần truyền thêm các đối tượng (db, models, request)
# hoặc sử dụng các kỹ thuật khác như dependency injection.