# --- Import Thư viện ---
import os
import math
import io
import csv
import pandas as pd
import re
import logging
import subprocess
import platform
import locale
import config # THÊM DÒNG NÀY
import requests
import xml.etree.ElementTree as ET
import uuid
from werkzeug.routing import BuildError
from functools import wraps
from decimal import Decimal, InvalidOperation
import logging # Sử dụng logging đã cấu hình
from flask import send_file, current_app # flash, redirect, url_for, render_template, request đã có
from os.path import abspath, join, exists
from flask import (
    Flask, render_template, request, redirect, url_for, g,
    send_from_directory, flash, abort, Response, jsonify, send_file, current_app, session # <<< THÊM session VÀO ĐÂY
)
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy import desc, or_, case, func, and_
from werkzeug.utils import secure_filename
from datetime import datetime, date, timedelta, timezone, time
from dateutil.relativedelta import relativedelta
from markupsafe import Markup
# --- THÊM DÒNG NÀY ---
from utils import (
    normalize_mac, format_date_for_storage, allowed_file,
    allowed_import_file, delete_physical_files
)
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user, login_required, current_user
)
from werkzeug.security import check_password_hash, generate_password_hash # Cần cho route login và CLI
import click # Cần cho việc tạo lệnh CLI
from models import (
    db, Record, Image, WorkLog, AuditLog, WorkLogImage,
    StockTransaction, User, PerformanceData, StockForeignDailyData, # <<< THÊM StockForeignDailyData
    format_date_for_display, CardRecord
)



# --- TÍCH HỢP FLASK-LOGIN ---

# Import thư viện XIRR (TẠM THỜI VÔ HIỆU HÓA ĐỂ UNBLOCK MIGRATION)
xirr_function_to_use = None
logging.warning("TẠM THỜI VÔ HIỆU HÓA IMPORT XIRR/IRR TỪ NUMPY_FINANCIAL ĐỂ DEBUG MIGRATION.")
logging.warning("Logic tính toán XIRR sẽ cần được xem xét và sửa lại sau khi migration thành công.")

# Định nghĩa hằng số toàn cục
BUY_FEE_RATE = Decimal('0.0015')
SELL_FEE_RATE = Decimal('0.0010')

# --- Cấu hình Logging ---
logging.basicConfig(level=logging.INFO, filename='app_errors.log', filemode='a',
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

# --- Cấu hình Locale ---
try:
    # Ưu tiên locale tiếng Việt
    locale.setlocale(locale.LC_ALL, 'vi_VN.UTF-8') # Thêm .UTF-8 để rõ ràng hơn
    logging.info(f"Đã đặt locale thành công: {locale.getlocale()}")
except locale.Error as e_vn:
    try:
        # Nếu không được, thử locale mặc định hệ thống
        locale.setlocale(locale.LC_ALL, '')
        logging.info(f"Đặt locale vi_VN thất bại ({e_vn}). Đã đặt locale mặc định hệ thống: {locale.getlocale()}")
    except locale.Error as e_sys:
         # Nếu cả hai đều lỗi
         logging.warning(f"Không thể đặt locale vi_VN ({e_vn}) hoặc locale hệ thống ({e_sys}). Sử dụng locale C mặc định: {locale.getlocale()}.")

# Khởi tạo ứng dụng Flask
app = Flask(__name__)
app.config.from_object(config.Config)
# --- TÍNH TOÁN VÀ ĐẶT LẠI UPLOAD_FOLDER_ABSOLUTE ---
# Phải đặt sau from_object vì cần app.root_path và app.config['UPLOAD_FOLDER']
app.config['UPLOAD_FOLDER_ABSOLUTE'] = abspath(join(app.root_path, app.config['UPLOAD_FOLDER']))
# ----------------------------------------------------
# === KHỞI TẠO FLASK-LOGIN ===
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' # Tên của view function xử lý trang đăng nhập
login_manager.login_message = "Vui lòng đăng nhập để truy cập trang này."
login_manager.login_message_category = "info" # Loại flash message
# === KẾT THÚC KHỞI TẠO FLASK-LOGIN ===

# Define ALLOWED_EXTENSIONS here
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}  # Thêm dòng này

# Import models SAU KHI app được tạo
from models import db, Record, Image, WorkLog, AuditLog, WorkLogImage, StockTransaction, User, PerformanceData, format_date_for_display

# Khởi tạo db và migrate
db.init_app(app)
migrate = Migrate(app, db)

# === USER LOADER CALLBACK ===
@login_manager.user_loader
def load_user(user_id):
    """Callback để tải người dùng từ user ID."""
    try:
        return db.session.get(User, int(user_id))
    except Exception as e:
        logging.error(f"Lỗi khi tải user ID {user_id}: {e}", exc_info=True)
        return None
# === KẾT THÚC USER LOADER ===



# === ROUTES ĐĂNG NHẬP / ĐĂNG XUẤT ===
@app.route('/login', methods=['GET', 'POST'])
def login():
    """Xử lý trang và quá trình đăng nhập."""
    if current_user.is_authenticated:
        # Nếu đã đăng nhập và là card_user, chuyển hướng đến trang thẻ
        if current_user.role == 'card_user':
            return redirect(url_for('card_management_index'))
        return redirect(url_for('index')) # Các role khác về trang chủ
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = True if request.form.get('remember') else False
        if not username or not password:
            flash('Vui lòng nhập tên đăng nhập và mật khẩu.', 'warning')
            return redirect(url_for('login'))
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user, remember=remember)
            flash('Đăng nhập thành công!', 'success')
            next_page = request.args.get('next')
            # Ghi log audit trước khi redirect
            log_audit_action('login_success', target_table='users', target_id=user.id, details=f"User '{username}' logged in.")
            # Ưu tiên trang 'next' nếu có và an toàn
            if next_page and next_page.startswith('/'):
                return redirect(next_page)
            if user.role == 'card_user':
                return redirect(url_for('card_management_index'))
            else:
                return redirect(url_for('index'))
        else:
            flash('Tên đăng nhập hoặc mật khẩu không đúng.', 'danger')
            log_audit_action('login_failed', details=f"Failed login attempt for username '{username}'.")
            return redirect(url_for('login'))
    return render_template('login.html')
@app.route('/logout')
@login_required # Chỉ người đã đăng nhập mới có thể logout
def logout():
    """Đăng xuất người dùng."""
    user_id = current_user.id if current_user else None
    username = current_user.username if current_user else 'N/A'
    logout_user()
    flash('Bạn đã đăng xuất.', 'info')
    log_audit_action('logout', target_table='users', target_id=user_id, details=f"User '{username}' logged out.")
    return redirect(url_for('login'))
# === KẾT THÚC ROUTES ĐĂNG NHẬP / ĐĂNG XUẤT ===


# --- Tạo thư mục cần thiết ---
# Đảm bảo thư mục static tồn tại (ĐÃ SỬA)
# Đọc STATIC_FOLDER từ config và tính đường dẫn tuyệt đối
static_folder_path = abspath(join(app.root_path, app.config['STATIC_FOLDER']))
if not os.path.exists(static_folder_path):
    os.makedirs(static_folder_path) # Sử dụng đường dẫn tuyệt đối đã tính
    logging.info(f"Đã tạo thư mục static: {static_folder_path}") # Log đường dẫn tuyệt đối


# === CONTEXT PROCESSOR ===

# Gửi biến 'now' (thời gian hiện tại GMT+7) cho mọi template
@app.context_processor
def inject_current_time():
    utc_now = datetime.now(timezone.utc)
    gmt7 = timezone(timedelta(hours=7))
    now_gmt7 = utc_now.astimezone(gmt7)
    return {'now': now_gmt7}

# === KIỂM TRA ENDPOINT ===
@app.context_processor 
def utility_processor():
    """
    Cung cấp các hàm tiện ích cho templates.
    """
    def endpoint_exists(endpoint_name):
        """
        Kiểm tra xem một endpoint có tồn tại trong ứng dụng hay không.
        """
        if endpoint_name is None: 
            return False
        try:
            # Thử xây dựng URL cho endpoint.
            url_for(endpoint_name) # Dòng này sẽ raise BuildError nếu endpoint không tồn tại
            return True
        except BuildError: # BuildError nên được nhận diện ở đây nếu đã import đúng
            return False
    return dict(endpoint_exists=endpoint_exists)
# =========================================================

# === KẾT THÚC CONTEXT PROCESSOR ===


# === CÁC HÀM TRỢ GIÚP ===
# Filter Jinja2: Chuyển đổi ký tự xuống dòng thành thẻ <br>
@app.template_filter('nl2br')
def nl2br(value):
    if value is None: return ''
    return Markup(str(value).replace('\n', '<br>'))

# Filter Jinja2: Định dạng số thành tiền tệ Việt Nam (₫)
@app.template_filter('currency_format')
def currency_format(value, precision=0):  # Thêm precision với giá trị mặc định là 0
    if value is None:
        # Trả về chuỗi có số thập phân phù hợp nếu precision > 0
        if precision > 0:
            return f"0.{'0'*precision} ₫"
        return "0 ₫"
    try:
        numeric_value = float(value)
        # Sử dụng precision trong chuỗi định dạng
        format_string = f"%.{precision}f"
        formatted_number = locale.format_string(format_string, numeric_value, grouping=True)
        return f"{formatted_number} ₫"
    except (ValueError, TypeError):
        logging.warning(f"Không thể định dạng tiền tệ cho giá trị: '{value}' với precision={precision}")
        return str(value)

# === MODULE QUẢN LÝ THẺ ===
def build_card_filters_orm(keyword, department, status, issue_date_start_str, issue_date_end_str):
    """
    Xây dựng danh sách các điều kiện lọc SQLAlchemy cho CardRecord.
    """
    filters = []
    if keyword:
        keyword_like = f"%{keyword}%"
        filters.append(or_(
            CardRecord.card_number.ilike(keyword_like),
            CardRecord.department.ilike(keyword_like),
            CardRecord.user_id_assigned.ilike(keyword_like),
            CardRecord.user_name_assigned.ilike(keyword_like),
            CardRecord.details.ilike(keyword_like)
        ))
    if department:
        filters.append(CardRecord.department == department)
    if status:
        filters.append(CardRecord.status == status)

    issue_date_start_db = format_date_for_storage(issue_date_start_str)
    issue_date_end_db = format_date_for_storage(issue_date_end_str)

    if issue_date_start_db:
        filters.append(CardRecord.issue_date >= issue_date_start_db)
    elif issue_date_start_str: # Báo lỗi nếu định dạng ngày sai nhưng vẫn có giá trị
        flash(f'Định dạng "Từ ngày cấp" ({issue_date_start_str}) không hợp lệ.', 'warning')

    if issue_date_end_db:
        filters.append(CardRecord.issue_date <= issue_date_end_db)
    elif issue_date_end_str: # Báo lỗi nếu định dạng ngày sai nhưng vẫn có giá trị
        flash(f'Định dạng "Đến ngày cấp" ({issue_date_end_str}) không hợp lệ.', 'warning')
        
    if issue_date_start_db and issue_date_end_db and issue_date_start_db > issue_date_end_db:
        flash("Ngày bắt đầu không thể sau ngày kết thúc cho bộ lọc ngày cấp.", "warning")
        # Có thể reset lại ngày ở đây nếu muốn, hoặc để người dùng tự sửa
        # filters.remove(CardRecord.issue_date >= issue_date_start_db) # Ví dụ cách xóa filter nếu cần
        # filters.remove(CardRecord.issue_date <= issue_date_end_db)

    return filters

def get_card_stats_for_charts():
    """
    Lấy dữ liệu thống kê thẻ cho biểu đồ.
    ĐÃ CẬP NHẬT để bao gồm trạng thái 'Lost'.
    """
    stats = {
        'overall': {'total': 0, 'using': 0, 'available': 0, 'lost': 0},
        'Customer': {'total': 0, 'using': 0, 'available': 0, 'lost': 0},
        'Employee': {'total': 0, 'using': 0, 'available': 0, 'lost': 0},
        'Temp_Worker': {'total': 0, 'using': 0, 'available': 0, 'lost': 0},
        # Bạn có thể thêm các bộ phận khác nếu cần
    }
    try:
        status_using_lower = 'using'
        status_available_lower = 'available'
        status_lost_lower = 'lost' # Trạng thái mới

        # Tổng quan
        stats['overall']['total'] = db.session.query(func.count(CardRecord.id)).scalar() or 0
        stats['overall']['using'] = db.session.query(func.count(CardRecord.id)).filter(
            func.lower(CardRecord.status) == status_using_lower
        ).scalar() or 0
        stats['overall']['available'] = db.session.query(func.count(CardRecord.id)).filter(
            func.lower(CardRecord.status) == status_available_lower
        ).scalar() or 0
        stats['overall']['lost'] = db.session.query(func.count(CardRecord.id)).filter(
            func.lower(CardRecord.status) == status_lost_lower # Đếm thẻ Lost
        ).scalar() or 0

        # Thống kê theo từng bộ phận
        departments_map = { 
            'Customer': 'customer',
            'Employee': 'employee',
            'Temp_Worker': 'temp_worker'
        }

        for dept_display_name, dept_lower_name in departments_map.items():
            stats[dept_display_name]['total'] = db.session.query(func.count(CardRecord.id)).filter(
                func.lower(CardRecord.department) == dept_lower_name
            ).scalar() or 0
            stats[dept_display_name]['using'] = db.session.query(func.count(CardRecord.id)).filter(
                func.lower(CardRecord.department) == dept_lower_name, 
                func.lower(CardRecord.status) == status_using_lower
            ).scalar() or 0
            stats[dept_display_name]['available'] = db.session.query(func.count(CardRecord.id)).filter(
                func.lower(CardRecord.department) == dept_lower_name, 
                func.lower(CardRecord.status) == status_available_lower
            ).scalar() or 0
            stats[dept_display_name]['lost'] = db.session.query(func.count(CardRecord.id)).filter(
                func.lower(CardRecord.department) == dept_lower_name, 
                func.lower(CardRecord.status) == status_lost_lower # Đếm thẻ Lost cho từng bộ phận
            ).scalar() or 0
            
    except Exception as e:
        logging.error(f"Lỗi khi lấy thống kê thẻ cho biểu đồ (có 'Lost'): {e}", exc_info=True)
        # Reset stats nếu có lỗi
        stats = {key: {'total': 0, 'using': 0, 'available': 0, 'lost': 0} for key in stats.keys()}
    return stats




# === HÀM TÍNH HIỆU SUẤT THEO MÃ (Cập nhật) ===
def calculate_performance_for_listed_symbols(symbols_to_analyze, all_user_stock_transactions, current_market_prices):
    """
    Tính toán hiệu suất đầu tư chi tiết cho danh sách mã cổ phiếu được chỉ định.

    Args:
        symbols_to_analyze (list): Danh sách các mã cổ phiếu cần phân tích.
        all_user_stock_transactions (list): Danh sách TẤT CẢ các đối tượng StockTransaction của người dùng.
        current_market_prices (dict): Dictionary chứa giá thị trường hiện tại {symbol: Decimal(price)}.

    Returns:
        dict: Dictionary với key là mã cổ phiếu, value là một dictionary chứa các chỉ số hiệu suất.
    """
    performance_results = {}

    logging.debug(f"Bắt đầu tính hiệu suất cho các mã: {symbols_to_analyze}")
    logging.debug(f"Sử dụng giá thị trường: {current_market_prices}")

    for symbol_key in symbols_to_analyze:
        if not symbol_key:
            continue

        transactions_for_symbol = [t for t in all_user_stock_transactions if t.symbol == symbol_key]

        if not transactions_for_symbol:
            performance_results[symbol_key] = {
                'symbol': symbol_key,
                'total_investment': Decimal('0.0'), # Tổng vốn đã bỏ ra cho mã này (tính cả phí)
                'realized_pl': Decimal('0.0'),
                'unrealized_pl': Decimal('0.0'),
                'total_pl': Decimal('0.0'),
                'percent_pl': Decimal('0.0'),
                'quantity_opened': Decimal('0.0'),
                'avg_buy_price_opened': None,
                'cost_basis_opened': Decimal('0.0'), # Vốn gốc của các lệnh mở (đã tính phí mua)
                'market_value_opened': Decimal('0.0'),
                'market_price': current_market_prices.get(symbol_key),
                'original_value_opened': Decimal('0.0'), # THÊM MỚI: Tổng giá trị gốc lệnh mở
                'status_message': 'Không có giao dịch'
            }
            continue

        total_cost_basis_all_buys_gross = Decimal('0')
        total_fees_all_buys = Decimal('0')
        total_quantity_bought = Decimal('0')
        realized_pl_from_closed_buys = Decimal('0')
        
        cost_basis_of_opened_buys_gross = Decimal('0')
        fees_of_opened_buys = Decimal('0')
        current_quantity_held_opened = Decimal('0')
        
        # THÊM MỚI: Biến để tính tổng giá trị gốc của các lệnh mua đang mở
        original_value_of_opened_positions = Decimal('0.0')

        for trans in transactions_for_symbol:
            if trans.transaction_type == 'BUY':
                if trans.quantity is None or trans.price is None:
                    logging.warning(f"Giao dịch BUY mã {symbol_key} ID {trans.id} thiếu số lượng hoặc giá. Bỏ qua.")
                    continue
                
                buy_order_value = trans.quantity * trans.price
                buy_fee = buy_order_value * BUY_FEE_RATE 
                
                total_cost_basis_all_buys_gross += buy_order_value
                total_fees_all_buys += buy_fee
                total_quantity_bought += trans.quantity

                if trans.status == 'CLOSED':
                    if trans.sell_price is not None and trans.sell_date is not None:
                        sell_order_value_item = trans.quantity * trans.sell_price
                        sell_fee_item = sell_order_value_item * SELL_FEE_RATE 
                        cost_of_this_buy_item_incl_fee = buy_order_value + buy_fee
                        realized_pl_item = (sell_order_value_item - sell_fee_item) - cost_of_this_buy_item_incl_fee
                        realized_pl_from_closed_buys += realized_pl_item
                    else:
                        logging.warning(f"Lệnh BUY mã {symbol_key} ID {trans.id} trạng thái CLOSED nhưng thiếu thông tin bán.")
                
                elif trans.status == 'OPENED':
                    cost_basis_of_opened_buys_gross += buy_order_value
                    fees_of_opened_buys += buy_fee
                    current_quantity_held_opened += trans.quantity
                    # THÊM MỚI: Cộng dồn giá trị gốc của lệnh mua đang mở
                    original_value_of_opened_positions += buy_order_value 

        current_price_for_symbol = current_market_prices.get(symbol_key)
        unrealized_pl_from_opened_buys = Decimal('0')
        total_cost_basis_opened_buys_incl_fees = cost_basis_of_opened_buys_gross + fees_of_opened_buys
        current_market_value_opened_buys = Decimal('0')
        average_buy_price_opened_buys_excl_fees = None

        if current_quantity_held_opened > 0:
            if cost_basis_of_opened_buys_gross > 0:
                 average_buy_price_opened_buys_excl_fees = cost_basis_of_opened_buys_gross / current_quantity_held_opened
                 
            if current_price_for_symbol is not None:
                current_market_value_opened_buys = current_quantity_held_opened * current_price_for_symbol
                unrealized_pl_from_opened_buys = current_market_value_opened_buys - total_cost_basis_opened_buys_incl_fees
            else:
                unrealized_pl_from_opened_buys = Decimal('0')

        total_symbol_pl = realized_pl_from_closed_buys + unrealized_pl_from_opened_buys
        total_capital_invested_for_symbol_incl_fees = total_cost_basis_all_buys_gross + total_fees_all_buys
        
        percent_pl_symbol = Decimal('0')
        if total_capital_invested_for_symbol_incl_fees > 0:
            percent_pl_symbol = (total_symbol_pl / total_capital_invested_for_symbol_incl_fees) * 100

        performance_results[symbol_key] = {
            'symbol': symbol_key,
            'total_investment': total_capital_invested_for_symbol_incl_fees,
            'realized_pl': realized_pl_from_closed_buys,
            'unrealized_pl': unrealized_pl_from_opened_buys,
            'total_pl': total_symbol_pl,
            'percent_pl': percent_pl_symbol,
            'quantity_opened': current_quantity_held_opened, 
            'avg_buy_price_opened': average_buy_price_opened_buys_excl_fees,
            'cost_basis_opened': total_cost_basis_opened_buys_incl_fees, 
            'market_value_opened': current_market_value_opened_buys,
            'market_price': current_price_for_symbol,
            # THÊM MỚI: Gán giá trị đã tính
            'original_value_opened': original_value_of_opened_positions,
            'status_message': 'OK'
        }
        logging.debug(f"Hiệu suất cho mã {symbol_key}: {performance_results[symbol_key]}")

    logging.info(f"Đã tính toán hiệu suất cho {len(performance_results)} mã.")
    return performance_results
# === KẾT HÀM HELPER TÍNH HIỆU SUẤT ===

# === KẾT THÚC CÁC HÀM TRỢ GIÚP ===


# Ghi log kiểm toán hành động người dùng
def log_audit_action(action, target_table=None, target_id=None, details=None):
    if not request or (request.endpoint and (request.endpoint.startswith('static') or request.endpoint == 'uploaded_file')):
        return
    try:
        ip_addr = request.headers.get('X-Forwarded-For', request.remote_addr)
        if ip_addr and ',' in ip_addr:
            ip_addr = ip_addr.split(',')[0].strip()
        audit_entry = AuditLog(
            ip_address=ip_addr, action=action or request.endpoint,
            target_table=target_table, target_id=target_id, details=details
        )
        db.session.add(audit_entry)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logging.error(f"Lỗi khi ghi audit log (SQLAlchemy) cho action '{action}': {str(e)}", exc_info=True)

# Kiểm tra các thiết bị cần bảo trì dựa trên trường status
def check_maintenance_notifications():
    notifications = []
    today = date.today()
    pattern = re.compile(r"(?:ngày\s*bảo\s*trì|maintenance\s*date)\s*:\s*(\d{1,2}/\d{1,2}/\d{4})", re.IGNORECASE)
    try:
        records_with_status = Record.query.filter(Record.status != None, Record.status != '').all()
        for record in records_with_status:
            if record.status:
                 status_lines = record.status.splitlines()
                 for line in status_lines:
                     match = pattern.search(line)
                     if match:
                         date_str = match.group(1).strip()
                         try:
                             maintenance_date = datetime.strptime(date_str, '%d/%m/%Y').date()
                             if maintenance_date <= today:
                                 notifications.append(f"Thiết bị MAC: {record.mac_address} đã đến/quá hạn xử lý (Ngày dự kiến: {date_str}).")
                             break
                         except ValueError:
                             logging.warning(f"Lỗi phân tích ngày '{date_str}' cho MAC {record.mac_address} trong: '{line}'")
    except Exception as e:
        logging.error(f"Lỗi SQLAlchemy khi kiểm tra thông báo bảo trì: {e}", exc_info=True)
    return notifications

# Lấy thống kê sử dụng IP cho dải 192.168.222.x và 192.168.223.x
def get_ip_usage_stats():
    default_stats = {'used': [0, 0], 'free': [254, 254], 'total': 254,'total_used': 0, 'total_free': 508,'labels': ['192.168.223.x', '192.168.222.x']}
    try:
        used_223 = Record.query.filter(Record.ip_address.like('192.168.223.%')).count()
        used_222 = Record.query.filter(Record.ip_address.like('192.168.222.%')).count()
        total_per_range = 254
        free_223 = total_per_range - used_223
        free_222 = total_per_range - used_222
        total_used = used_223 + used_222
        total_free = free_223 + free_222
        return {
            'used': [used_223, used_222], 'free': [free_223, free_222],
            'total': total_per_range, 'total_used': total_used,
            'total_free': total_free, 'labels': ['192.168.223.x', '192.168.222.x']
        }
    except Exception as e:
        logging.error(f"Lỗi SQLAlchemy khi lấy thống kê IP: {e}", exc_info=True)
        return default_stats

# Lấy thống kê số lượng theo loại thiết bị
# Sửa đổi hàm get_device_type_stats để lọc theo dải IP 222.x và 223.x
def get_device_type_stats():
    stats = {'labels': [], 'data': [], 'total_count': 0}
    try:
        # Thêm điều kiện lọc IP tương tự như trong get_ip_usage_stats
        query_result = db.session.query(
            func.coalesce(Record.device_type, '(Chưa xác định)').label('type'),
            func.count(Record.id).label('count')
        ).filter(
            or_(
                Record.ip_address.like('192.168.223.%'),
                Record.ip_address.like('192.168.222.%')
            )
        ).group_by('type').order_by(desc('count')).all()
        if query_result:
            stats['labels'] = [r.type for r in query_result]
            stats['data'] = [r.count for r in query_result]
            stats['total_count'] = sum(stats['data'])
    except Exception as e:
        logging.error(f"Lỗi SQLAlchemy khi lấy thống kê loại thiết bị: {e}", exc_info=True)
    return stats

# Tìm các địa chỉ IP còn trống gần nhất trong dải 222 và 223
def find_available_ips(limit=5):
    available_ips = []
    ranges = ['192.168.223', '192.168.222']
    try:
        used_ips_query = Record.query.with_entities(Record.ip_address).filter(
            or_(Record.ip_address.like('192.168.223.%'), Record.ip_address.like('192.168.222.%'))
        ).all()
        used_ips = {ip[0].strip() for ip in used_ips_query if ip[0]}
        for ip_range in ranges:
            for i in range(1, 255):
                ip = f"{ip_range}.{i}"
                if ip not in used_ips:
                    available_ips.append(ip)
        def ip_to_tuple(ip):
            try: return tuple(int(octet) for octet in ip.split('.'))
            except ValueError: return (0, 0, 0, 0)
        available_ips.sort(key=ip_to_tuple, reverse=True)
        return available_ips[:limit]
    except Exception as e:
        logging.error(f"Lỗi SQLAlchemy khi tìm IP trống: {e}", exc_info=True)
        return []

# Xây dựng điều kiện lọc ORM cho trang danh sách thiết bị
def build_filter_conditions_orm(keyword, start_date_str, end_date_str):
    filters = []
    filter_start_date = format_date_for_storage(start_date_str)
    filter_end_date = format_date_for_storage(end_date_str)
    if filter_start_date: filters.append(Record.record_date >= filter_start_date)
    elif start_date_str: flash(f'Định dạng "Từ ngày" ({start_date_str}) không hợp lệ.', 'warning')
    if filter_end_date: filters.append(Record.record_date <= filter_end_date)
    elif end_date_str: flash(f'Định dạng "Đến ngày" ({end_date_str}) không hợp lệ.', 'warning')
    if keyword:
        keyword_like = f"%{keyword}%"
        filters.append(or_(
            Record.mac_address.ilike(keyword_like), Record.ip_address.ilike(keyword_like),
            Record.username.ilike(keyword_like), Record.device_type.ilike(keyword_like),
            Record.status.ilike(keyword_like), Record.details.ilike(keyword_like)
        ))
    return filters

# === HÀM TRỢ GIÚP: Xây dựng bộ lọc ORM cho WorkLog (ĐÃ CẬP NHẬT) ===
# Cập nhật tham số: bỏ các filter cũ, thêm keyword
def build_work_log_filters_orm(start_date_str, end_date_str, keyword):
    """
    Xây dựng danh sách các điều kiện lọc SQLAlchemy cho WorkLog.

    Args:
        start_date_str (str): Chuỗi ngày bắt đầu (từ request).
        end_date_str (str): Chuỗi ngày kết thúc (từ request).
        keyword (str): Từ khóa tìm kiếm chung.

    Returns:
        list: Danh sách các điều kiện SQLAlchemy filter.
    """
    filters = []
    log_start_date = format_date_for_storage(start_date_str)
    log_end_date = format_date_for_storage(end_date_str)

    # Lọc theo ngày (Giữ nguyên)
    if log_start_date:
        filters.append(WorkLog.log_date >= log_start_date)
    if log_end_date:
        filters.append(WorkLog.log_date <= log_end_date)

    # Lọc theo keyword MỚI (thay thế các filter cũ)
    if keyword:
        keyword_like = f"%{keyword}%"
        filters.append(or_(
            WorkLog.activity_type.ilike(keyword_like),
            WorkLog.device_identifier.ilike(keyword_like),
            WorkLog.description.ilike(keyword_like),
            WorkLog.technician.ilike(keyword_like)
            # Thêm các cột khác của WorkLog nếu muốn tìm kiếm ở đó, ví dụ:
            # WorkLog.cost == float(keyword) # Nếu muốn tìm chi phí chính xác (cần try-except)
        ))

    return filters



#  Hàm lấy giá cuối từ FireAnt ---
# === HÀM LẤY GIÁ FIREANT (Sửa lỗi - Parse JSON thay vì XML) ===
def get_fireant_last_prices(symbols: list) -> dict:
    """
    Lấy giá khớp lệnh cuối cùng (PriceLast) cho danh sách mã cổ phiếu từ API FireAnt.
    Đã sửa để parse JSON thay vì XML.
    """
    if not symbols:
        return {}

    # Import cần thiết
    import requests
    from decimal import Decimal, InvalidOperation # Cần Decimal để lưu giá chính xác
    import logging # Đã có

    prices = {}
    REQUEST_TIMEOUT = 7
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    valid_symbols = [s for s in symbols if s and isinstance(s, str)]
    if not valid_symbols:
        return {}

    logging.info(f"Bắt đầu lấy giá FireAnt (JSON) cho: {', '.join(valid_symbols)}")

    for symbol in valid_symbols:
        url = f"https://www.fireant.vn/api/Data/Markets/Quotes?symbols={symbol}"
        price_value = None
        response_text_snippet = "(No response content)"

        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
            response_text_snippet = response.text[:500] # Lấy text để log
            logging.debug(f"FireAnt response for {symbol}: Status={response.status_code}, Content snippet=\n{response_text_snippet}...")
            response.raise_for_status() # Check lỗi HTTP 4xx/5xx

            # --- Xử lý nội dung JSON ---
            try:
                # Parse JSON content
                data = response.json() # Tự động parse JSON thành list/dict Python

                # Kiểm tra cấu trúc JSON trả về (dựa vào log lỗi, có vẻ là list chứa 1 dict)
                if isinstance(data, list) and data:
                    quote_data = data[0] # Lấy dict đầu tiên trong list
                    if isinstance(quote_data, dict) and 'PriceLast' in quote_data:
                        price_raw = quote_data['PriceLast']
                        try:
                            # Chuyển đổi giá trị sang Decimal (có thể là float hoặc int từ JSON)
                            price_value = Decimal(str(price_raw)) # Chuyển sang string trước để đảm bảo Decimal hoạt động đúng
                            logging.debug(f"FireAnt: Parsed price for {symbol}: {price_value}")
                        except (InvalidOperation, TypeError):
                            logging.warning(f"FireAnt: Invalid number format or type '{price_raw}' (type: {type(price_raw)}) for PriceLast of {symbol}.")
                    else:
                        logging.warning(f"FireAnt: 'PriceLast' key not found or first element is not a dict for {symbol}.")
                else:
                     logging.warning(f"FireAnt: JSON response is not a non-empty list for {symbol}. Response: {response_text_snippet}...")

            except requests.exceptions.JSONDecodeError as e_json:
                logging.error(f"FireAnt: JSON Decode Error for {symbol}. Error: {e_json}. URL: {url}. Content causing error: {response_text_snippet}...", exc_info=False)
            except Exception as e_inner:
                logging.error(f"FireAnt: Unexpected error processing JSON content for {symbol}: {e_inner}", exc_info=True)
        # --- Kết thúc xử lý nội dung JSON ---

        except requests.exceptions.Timeout:
            logging.error(f"FireAnt: Request timeout for {symbol}. URL: {url}")
        except requests.exceptions.HTTPError as e_http:
             logging.error(f"FireAnt: HTTP Error {e_http.response.status_code} for {symbol}. URL: {url}. Response: {response_text_snippet}...")
        except requests.exceptions.RequestException as e_req:
            logging.error(f"FireAnt: Request Exception for {symbol}: {e_req}. URL: {url}", exc_info=True)
        except Exception as e_general:
             logging.error(f"FireAnt: General error calling API for {symbol}: {e_general}", exc_info=True)

        prices[symbol] = price_value

    logging.info(f"Hoàn tất lấy giá FireAnt. Kết quả (có thể có None): {prices}")
    return prices
# --- KẾT THÚC HÀM LẤY GIÁ FIREANT (Đã sửa Parse JSON) ---


#  Hàm lấy dữ liệu giao dịch nước ngoài từ FireAnt ---
def get_fireant_foreign_trade_data(symbols: list) -> dict:
    """
    Lấy dữ liệu giao dịch khối ngoại (BuyForeignValue, SellForeignValue) và giá cuối (PriceLast)
    cho danh sách mã cổ phiếu từ API FireAnt.
    Trả về dictionary với key là symbol, value là một dict chứa:
    {'buy_foreign_value': Decimal, 'sell_foreign_value': Decimal, 'price_last': Decimal, 'error': str_nếu_có}.
    """
    if not symbols:
        return {}

    import requests # Đảm bảo import ở đây nếu chưa có ở đầu file app.py
    from decimal import Decimal, InvalidOperation # Đảm bảo import ở đây
    import logging # Đảm bảo logging được cấu hình và sử dụng

    trade_data = {}
    REQUEST_TIMEOUT = 10 # Tăng timeout một chút cho API này
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    valid_symbols = [s for s in symbols if s and isinstance(s, str)]
    if not valid_symbols:
        return {}

    logging.info(f"Bắt đầu lấy dữ liệu GD Khối Ngoại FireAnt cho: {', '.join(valid_symbols)}")

    for symbol in valid_symbols:
        url = f"https://www.fireant.vn/api/Data/Markets/Quotes?symbols={symbol}"
        # Khởi tạo giá trị mặc định cho mỗi mã, thêm trường 'error'
        symbol_data = {'buy_foreign_value': None, 'sell_foreign_value': None, 'price_last': None, 'error': None}
        response_text_snippet = "(No response content)"

        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
            response_text_snippet = response.text[:500] # Lấy một phần để log nếu có lỗi parse
            logging.debug(f"FireAnt response (foreign trade) for {symbol}: Status={response.status_code}")
            response.raise_for_status() # Kiểm tra lỗi HTTP 4xx/5xx

            data_list = response.json() # Parse JSON
            if isinstance(data_list, list) and data_list:
                quote_data = data_list[0] # Lấy dict đầu tiên trong list
                if isinstance(quote_data, dict):
                    # Lấy PriceLast
                    if 'PriceLast' in quote_data and quote_data['PriceLast'] is not None:
                        try:
                            symbol_data['price_last'] = Decimal(str(quote_data['PriceLast']))
                        except (InvalidOperation, TypeError) as e_pl:
                            logging.warning(f"FireAnt: Invalid number format for PriceLast of {symbol}: {quote_data['PriceLast']}. Error: {e_pl}")
                            symbol_data['error'] = symbol_data.get('error', '') + "Lỗi định dạng PriceLast. "


                    # Lấy BuyForeignValue
                    # API FireAnt có thể trả về 0 thay vì null nếu không có giao dịch
                    if 'BuyForeignValue' in quote_data and quote_data['BuyForeignValue'] is not None:
                        try:
                            symbol_data['buy_foreign_value'] = Decimal(str(quote_data['BuyForeignValue']))
                        except (InvalidOperation, TypeError) as e_bfv:
                            logging.warning(f"FireAnt: Invalid number format for BuyForeignValue of {symbol}: {quote_data['BuyForeignValue']}. Error: {e_bfv}")
                            symbol_data['error'] = symbol_data.get('error', '') + "Lỗi định dạng BuyForeignValue. "


                    # Lấy SellForeignValue
                    # Cần xác nhận tên trường chính xác từ API. Giả định là 'SellForeignValue'.
                    if 'SellForeignValue' in quote_data and quote_data['SellForeignValue'] is not None:
                        try:
                            symbol_data['sell_foreign_value'] = Decimal(str(quote_data['SellForeignValue']))
                        except (InvalidOperation, TypeError) as e_sfv:
                            logging.warning(f"FireAnt: Invalid number format for SellForeignValue of {symbol}: {quote_data['SellForeignValue']}. Error: {e_sfv}")
                            symbol_data['error'] = symbol_data.get('error', '') + "Lỗi định dạng SellForeignValue. "

                    logging.debug(f"FireAnt: Parsed foreign trade data for {symbol}: Buy={symbol_data['buy_foreign_value']}, Sell={symbol_data['sell_foreign_value']}, Last={symbol_data['price_last']}")
                else:
                    logging.warning(f"FireAnt: Quote data is not a dict for {symbol}.")
                    symbol_data['error'] = "Dữ liệu API không đúng định dạng (không phải dict)."
            else:
                logging.warning(f"FireAnt: JSON response is not a non-empty list for {symbol}. Response: {response_text_snippet}...")
                symbol_data['error'] = "Phản hồi API không phải là danh sách hợp lệ."

        except requests.exceptions.JSONDecodeError as e_json:
            logging.error(f"FireAnt: JSON Decode Error (foreign trade) for {symbol}. Error: {e_json}. URL: {url}. Content: {response_text_snippet}", exc_info=False)
            symbol_data['error'] = "Lỗi giải mã JSON từ API."
        except requests.exceptions.Timeout:
            logging.error(f"FireAnt: Request timeout (foreign trade) for {symbol}. URL: {url}")
            symbol_data['error'] = "API request timeout."
        except requests.exceptions.HTTPError as e_http:
            logging.error(f"FireAnt: HTTP Error {e_http.response.status_code} (foreign trade) for {symbol}. URL: {url}. Response: {response_text_snippet}")
            symbol_data['error'] = f"Lỗi HTTP {e_http.response.status_code} từ API."
        except requests.exceptions.RequestException as e_req:
            logging.error(f"FireAnt: Request Exception (foreign trade) for {symbol}: {e_req}. URL: {url}", exc_info=True)
            symbol_data['error'] = "Lỗi request API chung."
        except Exception as e_general:
            logging.error(f"FireAnt: General error calling API (foreign trade) for {symbol}: {e_general}", exc_info=True)
            symbol_data['error'] = "Lỗi không xác định khi gọi API."

        trade_data[symbol] = symbol_data

    logging.info(f"Hoàn tất lấy dữ liệu GD Khối Ngoại FireAnt. Số mã xử lý: {len(trade_data)}/{len(valid_symbols)}.")
    return trade_data
#  Kết thúc Hàm lấy dữ liệu giao dịch nước ngoài từ FireAnt ---


    prices = {}
    # Namespace cần thiết để tìm tag trong XML của FireAnt
    ns = {'fa': 'http://schemas.datacontract.org/2004/07/FireAnt.Entities'}
    # Timeout cho request (giây)
    REQUEST_TIMEOUT = 5

    # Đảm bảo không có mã nào rỗng hoặc None trong danh sách
    valid_symbols = [s for s in symbols if s and isinstance(s, str)]
    if not valid_symbols:
        return {}

    logging.info(f"Bắt đầu lấy giá FireAnt cho: {', '.join(valid_symbols)}")

    for symbol in valid_symbols:
        url = f"https://www.fireant.vn/api/Data/Markets/Quotes?symbols={symbol}"
        price_value = None # Giá trị mặc định nếu lỗi
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status() # Ném lỗi nếu status code là 4xx hoặc 5xx

            try:
                # Parse XML content
                root = ET.fromstring(response.content)
                # Tìm phần tử Quote -> PriceLast sử dụng namespace
                price_element = root.find('.//fa:PriceLast', ns)

                if price_element is not None and price_element.text:
                    try:
                        # Chuyển đổi giá trị text sang Decimal
                        price_value = Decimal(price_element.text)
                        logging.debug(f"FireAnt: Lấy được giá cho {symbol}: {price_value}")
                    except InvalidOperation:
                        logging.warning(f"FireAnt: Không thể chuyển đổi giá trị '{price_element.text}' sang Decimal cho mã {symbol}.")
                else:
                    logging.warning(f"FireAnt: Không tìm thấy thẻ PriceLast hoặc giá trị rỗng cho mã {symbol} trong XML response.")

            except ET.ParseError:
                logging.error(f"FireAnt: Lỗi parse XML cho mã {symbol}. URL: {url}", exc_info=True)
            except Exception as e_parse:
                logging.error(f"FireAnt: Lỗi không xác định khi xử lý XML cho {symbol}: {e_parse}", exc_info=True)

        except requests.exceptions.Timeout:
            logging.error(f"FireAnt: Request timeout khi lấy giá cho mã {symbol}. URL: {url}")
        except requests.exceptions.RequestException as e_req:
            logging.error(f"FireAnt: Lỗi request khi lấy giá cho mã {symbol}: {e_req}. URL: {url}", exc_info=True)
        except Exception as e_general:
             logging.error(f"FireAnt: Lỗi không xác định khi gọi API cho {symbol}: {e_general}", exc_info=True)

        # Lưu kết quả (giá hoặc None nếu lỗi)
        prices[symbol] = price_value

    logging.info(f"Hoàn tất lấy giá FireAnt. Kết quả: {len(prices)} mã.")
    return prices
# --- KẾT THÚC HÀM LẤY GIÁ FIREANT ---

# === DECORATORS ===
def role_required(allowed_roles):
    """
    Decorator để kiểm tra xem current_user có vai trò được phép hay không.
    Nếu không, trả về lỗi 403 Forbidden.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Kiểm tra đăng nhập trước
            if not current_user.is_authenticated:
                # Nếu chưa đăng nhập, Flask-Login sẽ tự động redirect đến trang login
                # Hoặc có thể abort(401) nếu muốn
                return login_manager.unauthorized() # Sử dụng hàm của Flask-Login

            # Kiểm tra vai trò
            if current_user.role not in allowed_roles:
                logging.warning(f"Từ chối truy cập cho user '{current_user.username}' (role: {current_user.role}) đến endpoint '{request.endpoint}'. Yêu cầu roles: {allowed_roles}")
                flash(f"Bạn không có quyền truy cập chức năng này. Yêu cầu vai trò: {', '.join(allowed_roles)}.", "warning")
                # Trả về lỗi 403 Forbidden
                abort(403)

            # Nếu vượt qua kiểm tra, thực thi hàm gốc
            return f(*args, **kwargs)
        return decorated_function
    return decorator
# === KẾT THÚC DECORATORS ===



# === ROUTES THIẾT BỊ (Record) ===
# Route chính: Hiển thị danh sách thiết bị, thống kê, form lọc/thêm
@app.route('/')
@login_required # Đảm bảo người dùng đã đăng nhập
def index():
    # KIỂM TRA VAI TRÒ NGƯỜI DÙNG ĐỂ CHUYỂN HƯỚNG NẾU CẦN
    if current_user.role == 'card_user':
        # Nếu là card_user, chuyển hướng ngay đến trang quản lý thẻ
        flash("Bạn được chuyển hướng đến trang Quản lý Thẻ.", "info") # Thông báo tùy chọn
        return redirect(url_for('card_management_index'))
    
    # Nếu không phải card_user, tiếp tục xử lý logic của trang index (Dashboard TB) như bình thường
    keyword = request.args.get('keyword', default='', type=str).strip()
    start_date_str = request.args.get('start_date', default='', type=str).strip()
    end_date_str = request.args.get('end_date', default='', type=str).strip()
    
    # Xử lý page string an toàn hơn
    page_str = request.args.get('page', default='1')
    try:
        page = int(page_str)
        if page < 1:
            page = 1
    except ValueError:
        page = 1
        logging.warning(f"Giá trị 'page' không hợp lệ: '{page_str}'. Đặt lại thành 1.")


    # Lấy tóm tắt nhật ký tháng này
    work_log_summary = {'activity_data': [], 'total_cost': 0, 'device_data': []}
    try:
        today = date.today()
        start_of_month = today.replace(day=1)
        
        # Tóm tắt hoạt động
        activity_summary_query = db.session.query(
            WorkLog.activity_type, func.count(WorkLog.id).label('count')
        ).filter(WorkLog.log_date >= start_of_month, WorkLog.log_date <= today)\
         .group_by(WorkLog.activity_type).order_by(desc('count')).limit(5).all()
        if activity_summary_query: 
            work_log_summary['activity_data'] = [{'activity_type': r.activity_type, 'count': r.count} for r in activity_summary_query]
        
        # Tổng chi phí
        total_cost_result = db.session.query(func.sum(WorkLog.cost))\
            .filter(WorkLog.log_date >= start_of_month, WorkLog.log_date <= today).scalar()
        work_log_summary['total_cost'] = total_cost_result or Decimal('0.0') # Đảm bảo là Decimal
        
        # Tóm tắt thiết bị
        device_summary_query = db.session.query(
            WorkLog.device_identifier, func.count(WorkLog.id).label('count')
        ).filter(WorkLog.log_date >= start_of_month, WorkLog.log_date <= today, 
                 WorkLog.device_identifier.isnot(None), WorkLog.device_identifier != '')\
         .group_by(WorkLog.device_identifier).order_by(desc('count')).limit(5).all()
        if device_summary_query: 
            work_log_summary['device_data'] = [{'device_identifier': r.device_identifier, 'count': r.count} for r in device_summary_query]
    
    except Exception as e:
        logging.error(f"Lỗi SQLAlchemy khi lấy tóm tắt nhật ký (tháng này): {e}", exc_info=True)
        flash("Lỗi khi tải dữ liệu tóm tắt nhật ký.", "warning")

    # Lấy các thông tin khác cho dashboard
    maintenance_notifications = check_maintenance_notifications()
    ip_stats = get_ip_usage_stats()
    available_ips = find_available_ips(limit=5)
    device_type_stats = get_device_type_stats()

    # Query chính lấy danh sách thiết bị (Record)
    query = Record.query

    # === THÊM MỚI: Lọc theo chủ sở hữu nếu không phải admin ===
    if current_user.role != 'admin':
        query = query.filter(Record.user_id == current_user.id)
# === KẾT THÚC THÊM MỚI ===

    # Đảm bảo hàm build_filter_conditions_orm đã được định nghĩa và import
    filters_orm = build_filter_conditions_orm(keyword, start_date_str, end_date_str) 
    if filters_orm: 
        query = query.filter(and_(*filters_orm)) # Sử dụng and_ nếu filters_orm là list các điều kiện
    
    query = query.order_by(case((Record.record_date == None, 1), else_=0), desc(Record.record_date), desc(Record.id))
    
    RECORDS_PER_PAGE = current_app.config.get('RECORDS_PER_PAGE', 10)
    pagination = query.paginate(page=page, per_page=RECORDS_PER_PAGE, error_out=False)
    records_to_display = pagination.items

    # Chuẩn bị ngày hiển thị lại trên form lọc (giữ nguyên chuỗi gốc nếu định dạng sai để người dùng thấy)
    # display_start_date = format_date_for_storage(start_date_str) or '' # Nên là format_date_for_storage nếu muốn chuẩn hóa
    # display_end_date = format_date_for_storage(end_date_str) or ''   # Nên là format_date_for_storage

    return render_template('index.html',
                           records=records_to_display, 
                           pagination=pagination,
                           keyword=keyword, 
                           start_date=start_date_str, # Giữ nguyên chuỗi gốc cho form
                           end_date=end_date_str,     # Giữ nguyên chuỗi gốc cho form
                           page=page,
                           total_pages=pagination.pages, 
                           total_records=pagination.total,
                           notifications=maintenance_notifications, 
                           ip_stats=ip_stats,
                           available_ips=available_ips, 
                           work_log_summary=work_log_summary,
                           device_type_stats=device_type_stats)

# Route xử lý thêm thiết bị mới (chỉ chấp nhận POST)
@app.route('/add', methods=['POST'])
@login_required
@role_required(['admin', 'basic_user','device_log_user']) # Cân nhắc quyền nếu cần
def add_record():
    """
    Xử lý việc thêm một bản ghi thiết bị mới vào cơ sở dữ liệu.
    Hàm này được gọi khi người dùng submit form thêm thiết bị từ trang index.
    """
    # Lấy dữ liệu từ form
    mac_input = request.form.get('mac_address', '').strip()
    ip_address = request.form.get('ip_address', '').strip() or None
    username = request.form.get('username', '').strip() or None
    device_type = request.form.get('device_type', '').strip() or None
    status = request.form.get('status', '').strip() or None
    record_date_str = request.form.get('record_date', '').strip() # Form gửi ngày dạng YYYY-MM-DD
    details = request.form.get('details', '').strip() or None
    
    # Trong form của bạn, input file có name="images"
    # Nếu form của bạn có tên khác cho input file, hãy thay 'images' ở đây
    images_files = request.files.getlist('images') 

    # Lấy các tham số phân trang/lọc để redirect về đúng trang sau khi thêm
    # Các tham số này được truyền qua hidden input trong form thêm mới
    page_param = request.form.get('page', 1, type=int)
    keyword_param = request.form.get('keyword', '')
    start_date_param = request.form.get('start_date', '') # Form gửi ngày dạng YYYY-MM-DD
    end_date_param = request.form.get('end_date', '')     # Form gửi ngày dạng YYYY-MM-DD
    
    # Tạo URL redirect, các tham số ngày tháng sẽ được giữ nguyên định dạng từ form
    redirect_url = url_for('index', 
                           page=page_param, 
                           keyword=keyword_param, 
                           start_date=start_date_param, 
                           end_date=end_date_param)

    # --- Validate MAC address ---
    if not mac_input:
        flash('MAC Address là bắt buộc.', 'danger')
        return redirect(redirect_url)
    
    mac_address_normalized = normalize_mac(mac_input, separator='-')
    if not mac_address_normalized:
        flash('Định dạng MAC Address không hợp lệ. Hãy thử lại (VD: AA-BB-CC-DD-EE-FF).', 'danger')
        return redirect(redirect_url)

    # Kiểm tra MAC đã tồn tại chưa
    try:
        existing_record = Record.query.filter_by(mac_address=mac_address_normalized).first()
        if existing_record:
            flash(f'MAC Address "{mac_address_normalized}" đã tồn tại trong hệ thống.', 'warning')
            return redirect(redirect_url)
    except Exception as e_query_mac:
        logging.error(f"Lỗi khi kiểm tra MAC Address '{mac_address_normalized}': {e_query_mac}", exc_info=True)
        flash('Lỗi khi kiểm tra MAC Address. Vui lòng thử lại.', 'danger')
        return redirect(redirect_url)

    # --- Validate ngày ---
    record_date_db = None
    if record_date_str: # Nếu người dùng có nhập ngày
        # format_date_for_storage cần xử lý được định dạng YYYY-MM-DD từ input type="date"
        # Hoặc bạn có thể parse trực tiếp ở đây nếu format_date_for_storage không phù hợp
        try:
            record_date_db = datetime.strptime(record_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash(f'Định dạng ngày ghi nhận "{record_date_str}" không hợp lệ. Cần định dạng YYYY-MM-DD.', 'danger')
            return redirect(redirect_url)
    
    # --- Tạo bản ghi mới và lưu vào CSDL ---
    try:
        new_record = Record(
            mac_address=mac_address_normalized,
            ip_address=ip_address,
            username=username,
            device_type=device_type,
            status=status,
            record_date=record_date_db, # Sử dụng ngày đã parse
            details=details,
            user_id=current_user.id # <<< THÊM DÒNG NÀY
        )

        db.session.add(new_record)
        db.session.flush() # Quan trọng: flush để lấy new_record.id cho việc lưu ảnh

        added_image_paths = [] # Danh sách để lưu tên các file ảnh đã thêm thành công
        
        # Xử lý upload ảnh (nếu có)
        if images_files:
            upload_folder_abs = current_app.config.get('UPLOAD_FOLDER_ABSOLUTE')
            if not upload_folder_abs: # Kiểm tra xem UPLOAD_FOLDER_ABSOLUTE có được đặt không
                logging.error("UPLOAD_FOLDER_ABSOLUTE chưa được cấu hình trong app.config.")
                flash("Lỗi cấu hình: Thư mục upload chưa được thiết lập.", "danger")
                # Không nên rollback ở đây vì record có thể đã được flush
                # Cân nhắc việc không cho phép thêm nếu không thể lưu ảnh, hoặc cho phép thêm record mà không có ảnh
                return redirect(redirect_url)

            if not os.path.exists(upload_folder_abs):
                try:
                    os.makedirs(upload_folder_abs)
                    logging.info(f"Đã tạo thư mục uploads: {upload_folder_abs}")
                except OSError as e_mkdir:
                    logging.error(f"Không thể tạo thư mục uploads '{upload_folder_abs}': {e_mkdir}", exc_info=True)
                    flash("Lỗi máy chủ: Không thể tạo thư mục lưu trữ ảnh.", "danger")
                    return redirect(redirect_url)
            
            # Duyệt qua từng file ảnh được tải lên
            for image_file in images_files:
                # Kiểm tra xem file có tồn tại, có tên và có định dạng cho phép không
                if image_file and image_file.filename and allowed_file(image_file.filename):
                    try:
                        # Tạo tên file duy nhất để tránh ghi đè
                        # Sử dụng ID của record mới, timestamp và tên file gốc
                        filename = secure_filename(f"record_{new_record.id}_{int(datetime.now().timestamp())}_{image_file.filename}")
                        filepath = os.path.join(upload_folder_abs, filename)
                        image_file.save(filepath) # Lưu file vào thư mục uploads
                        
                        # Tạo bản ghi Image mới trong CSDL
                        new_image_db_entry = Image(record_id=new_record.id, image_path=filename)
                        db.session.add(new_image_db_entry)
                        added_image_paths.append(filename)
                        logging.info(f"Đã chuẩn bị thêm ảnh '{filename}' cho record ID {new_record.id} (MAC: {new_record.mac_address})")
                    except Exception as e_save_img:
                        logging.error(f"Lỗi khi lưu ảnh '{image_file.filename}' cho record mới (MAC: {mac_address_normalized}): {e_save_img}", exc_info=True)
                        flash(f"Lỗi khi lưu ảnh: {image_file.filename}. Thiết bị vẫn được thêm nhưng ảnh này bị lỗi.", "warning")
                elif image_file and image_file.filename: # File được chọn nhưng không hợp lệ
                    flash(f"Định dạng file ảnh '{image_file.filename}' không được phép. Ảnh này sẽ không được lưu.", "warning")
        
        db.session.commit() # Commit tất cả thay đổi (record mới và các image mới) vào CSDL
        
        flash_msg = f'Thêm thiết bị MAC {mac_address_normalized} thành công!'
        if added_image_paths: # Nếu có ảnh được thêm
            flash_msg += f" Đã đính kèm {len(added_image_paths)} ảnh."
        flash(flash_msg, 'success')
        
        # Ghi log kiểm toán
        log_audit_action(action='add_record', 
                         target_table='records', 
                         target_id=new_record.id, 
                         details=f"Added record MAC {mac_address_normalized}. Images added: {len(added_image_paths)} ({', '.join(added_image_paths) if added_image_paths else 'None'}).")
        logging.info(f"Thêm record ID {new_record.id} (MAC: {mac_address_normalized}). Images: {len(added_image_paths)}")

    except Exception as e_db:
        db.session.rollback() # Rollback nếu có lỗi xảy ra trong quá trình thêm vào CSDL
        logging.error(f"Lỗi SQLAlchemy khi thêm record mới (MAC: {mac_address_normalized}): {e_db}", exc_info=True)
        flash(f'Lỗi CSDL khi thêm thiết bị: {str(e_db)}', 'danger')

    return redirect(redirect_url) # Redirect về trang danh sách

# Route để xem chi tiết thiết bị (sử dụng view_images.html)
# Endpoint name sẽ là 'edit_record' theo mặc định, khớp với cách gọi trong index.html cho nút "Xem"
@app.route('/record/view/<int:record_id>', methods=['GET'])
@login_required
def edit_record(record_id):
    """
    Hiển thị trang chi tiết cho một bản ghi thiết bị, bao gồm ảnh và lịch sử công việc.
    Sử dụng template view_images.html.
    Endpoint này được gọi là 'edit_record' bởi url_for trong template index.html (cho nút xem chi tiết).
    """
    page_param = request.args.get('page', 1, type=int)
    keyword_param = request.args.get('keyword', '')
    start_date_param = request.args.get('start_date', '')
    end_date_param = request.args.get('end_date', '')
    try:
        record = db.session.get(Record, record_id)
        # === THÊM MỚI: Kiểm tra quyền sở hữu ===
        if record and record.user_id != current_user.id and current_user.role != 'admin':
            flash('Bạn không có quyền truy cập vào bản ghi thiết bị này.', 'danger')
            return redirect(url_for('index'))
        # === KẾT THÚC THÊM MỚI ===
        if not record:
            flash(f'Không tìm thấy bản ghi thiết bị có ID {record_id}.', 'warning')
            return redirect(url_for('index', page=page_param, keyword=keyword_param, start_date=start_date_param, end_date=end_date_param))

        images = Image.query.filter_by(record_id=record.id).order_by(Image.id).all()

        # Lấy lịch sử công việc cho thiết bị
        mac_hyphen = record.mac_address 
        mac_colon = mac_hyphen.replace('-', ':') # Chuyển đổi sang dạng dấu hai chấm
        mac_no_sep = mac_hyphen.replace('-', '')  # Chuyển đổi sang dạng không có dấu phân cách

        device_logs = WorkLog.query.filter(
            or_(
                WorkLog.device_identifier.ilike(mac_hyphen), # Tìm MAC dạng XX-XX-XX
                WorkLog.device_identifier.ilike(mac_colon),  # Tìm MAC dạng XX:XX:XX
                WorkLog.device_identifier.ilike(mac_no_sep)  # Tìm MAC dạng XXXXXXXXXXXX
            )
        ).order_by(desc(WorkLog.log_date), desc(WorkLog.id)).limit(10).all()

        return render_template('view_images.html',
                               record=record,
                               images=images,
                               device_logs=device_logs, 
                               page=page_param,
                               keyword=keyword_param,
                               start_date=start_date_param,
                               end_date=end_date_param)
    except Exception as e:
        current_app.logger.error(f"Lỗi SQLAlchemy khi tải trang chi tiết thiết bị ID {record_id}: {e}", exc_info=True)
        flash('Lỗi CSDL khi tải trang chi tiết thiết bị.', 'danger')
        return redirect(url_for('index', page=page_param, keyword=keyword_param, start_date=start_date_param, end_date=end_date_param))

# Route để hiển thị form chỉnh sửa thiết bị (sử dụng edit.html)
@app.route('/record/edit/<int:record_id>', methods=['GET'])
@login_required
@role_required(['admin', 'basic_user', 'device_log_user'])
def show_edit_record_form(record_id):
    """
    Hiển thị form để chỉnh sửa thông tin một bản ghi thiết bị.
    Sử dụng template edit.html.
    """
    record = db.session.get(Record, record_id)
    # === THÊM MỚI: Kiểm tra quyền sở hữu ===
    if record and record.user_id != current_user.id and current_user.role != 'admin':
        flash('Bạn không có quyền chỉnh sửa bản ghi thiết bị này.', 'danger')
        return redirect(url_for('index'))
    # === KẾT THÚC THÊM MỚI ===
    if not record:
        flash(f'Không tìm thấy bản ghi thiết bị có ID {record_id} để chỉnh sửa.', 'warning')
        return redirect(url_for('index')) # Hoặc một trang lỗi phù hợp

    images = Image.query.filter_by(record_id=record.id).order_by(Image.id).all()
    
    # Lấy các tham số query để truyền lại cho nút "Hủy bỏ" trong edit.html
    page_param = request.args.get('page', 1, type=int)
    keyword_param = request.args.get('keyword', '')
    start_date_param = request.args.get('start_date', '')
    end_date_param = request.args.get('end_date', '')
    
    # Lấy ALLOWED_EXTENSIONS từ config của app, nếu không có thì dùng giá trị mặc định
    # Điều này giả định ALLOWED_EXTENSIONS được set trong app.config
    # Nếu nó là biến global, bạn có thể truy cập trực tiếp.
    # Dựa theo cách edit.html dùng, nó mong đợi biến ALLOWED_EXTENSIONS trong context.
    allowed_extensions_config = current_app.config.get('ALLOWED_EXTENSIONS', {'png', 'jpg', 'jpeg', 'gif'})


    return render_template('edit.html', 
                           record=record, 
                           images=images,
                           page=page_param,
                           keyword=keyword_param,
                           start_date=start_date_param,
                           end_date=end_date_param,
                           ALLOWED_EXTENSIONS=allowed_extensions_config) # Truyền ALLOWED_EXTENSIONS

# Route xử lý cập nhật thông tin thiết bị (chấp nhận POST từ edit.html)
# Đảm bảo route này đã tồn tại và hoạt động đúng
@app.route('/update/<int:record_id>', methods=['POST'])
@login_required
def update_record(record_id):
    record = db.session.get(Record, record_id)
    # === THÊM MỚI: Kiểm tra quyền sở hữu trước khi thực hiện ===
    if record and record.user_id != current_user.id and current_user.role != 'admin':
        flash('Bạn không có quyền thực hiện hành động này trên bản ghi thiết bị này.', 'danger')
        return redirect(url_for('index'))
    # === KẾT THÚC THÊM MỚI ===
    if record is None:
        flash(f'Không tìm thấy bản ghi ID {record_id} để cập nhật.', 'danger')
        return redirect(url_for('index')) # Hoặc trang lỗi

    # Lấy dữ liệu từ form POST
    mac_input = request.form.get('mac_address', '').strip()
    # Kiểm tra xem MAC có bị thay đổi không, nếu có và khác MAC hiện tại thì validate
    mac_address_normalized_input = normalize_mac(mac_input, separator='-')

    if not mac_address_normalized_input:
        flash('MAC Address nhập vào không hợp lệ.', 'warning')
        return redirect(url_for('show_edit_record_form', record_id=record_id, 
                                page=request.form.get('page',1), keyword=request.form.get('keyword',''), 
                                start_date=request.form.get('start_date',''), end_date=request.form.get('end_date','')))

    if mac_address_normalized_input != record.mac_address:
        # Nếu MAC thay đổi, kiểm tra xem MAC mới có bị trùng không
        existing_mac = Record.query.filter(Record.mac_address == mac_address_normalized_input, Record.id != record_id).first()
        if existing_mac:
            flash(f'MAC Address "{mac_address_normalized_input}" đã tồn tại cho một thiết bị khác.', 'warning')
            return redirect(url_for('show_edit_record_form', record_id=record_id,
                                    page=request.form.get('page',1), keyword=request.form.get('keyword',''),
                                    start_date=request.form.get('start_date',''), end_date=request.form.get('end_date','')))
        record.mac_address = mac_address_normalized_input # Cập nhật MAC nếu hợp lệ và không trùng
    
    record.ip_address = request.form.get('ip_address', '').strip() or None
    record.username = request.form.get('username', '').strip() or None
    record.device_type = request.form.get('device_type', '').strip() or None
    record.status = request.form.get('status', '').strip() or None
    record_date_str = request.form.get('record_date', '').strip()
    record.details = request.form.get('details', '').strip() or None
    
    page = request.form.get('page', 1, type=int)
    keyword = request.form.get('keyword', '')
    start_date = request.form.get('start_date', '')
    end_date = request.form.get('end_date', '')
    
    # URL để redirect về form edit nếu có lỗi, hoặc về index nếu thành công
    error_redirect_url = url_for('show_edit_record_form', record_id=record_id, page=page, keyword=keyword, start_date=start_date, end_date=end_date)
    success_redirect_url = url_for('index', page=page, keyword=keyword, start_date=start_date, end_date=end_date)

    # Validate và chuyển đổi ngày
    if record_date_str:
        try:
            # edit.html gửi ngày dạng dd/mm/yyyy, cần parse cho đúng
            # Nếu edit.html gửi dạng yyyy-mm-dd (từ input type="date"), thì parse '%Y-%m-%d'
            # Dựa vào code gốc, record_date_display là dd/mm/yyyy
            # Tuy nhiên, input type="date" trong edit.html sẽ gửi yyyy-mm-dd
            # Nên format_date_for_storage cần xử lý được cả hai hoặc parse ở đây
            record_date_db = format_date_for_storage(record_date_str) # Giả sử hàm này xử lý được
            if not record_date_db and record_date_str: # Nếu có chuỗi ngày nhưng parse lỗi
                 flash(f'Định dạng ngày ghi nhận "{record_date_str}" không hợp lệ.', 'danger')
                 return redirect(error_redirect_url)
            record.record_date = record_date_db
        except ValueError: # Bắt lỗi nếu format_date_for_storage không xử lý được và ném ValueError
            flash(f'Định dạng ngày ghi nhận "{record_date_str}" không hợp lệ.', 'danger')
            return redirect(error_redirect_url)
    else:
        record.record_date = None # Nếu không nhập ngày thì set là None

    # Xử lý xóa ảnh
    delete_image_ids_str = request.form.getlist('delete_images') # list of strings
    deleted_image_paths = []
    if delete_image_ids_str:
        try:
            delete_image_ids = [int(img_id) for img_id in delete_image_ids_str] # Chuyển sang int
            images_to_delete = Image.query.filter(Image.id.in_(delete_image_ids), Image.record_id == record_id).all()
            upload_folder_abs = current_app.config['UPLOAD_FOLDER_ABSOLUTE']
            for img in images_to_delete:
                try:
                    image_path_to_delete = os.path.join(upload_folder_abs, img.image_path)
                    if os.path.exists(image_path_to_delete):
                        os.remove(image_path_to_delete)
                        current_app.logger.info(f"Đã xóa file ảnh vật lý: {img.image_path}")
                    else:
                        current_app.logger.warning(f"Không tìm thấy file ảnh vật lý để xóa: {img.image_path}")
                    deleted_image_paths.append(img.image_path)
                    db.session.delete(img)
                except Exception as e_del_file:
                    current_app.logger.error(f"Lỗi khi xóa file ảnh {img.image_path}: {e_del_file}")
                    flash(f"Lỗi khi xóa ảnh {img.image_path}", "warning")
        except ValueError:
            flash("ID ảnh không hợp lệ trong danh sách xóa.", "warning")
            return redirect(error_redirect_url)


    # Xử lý thêm ảnh mới
    new_images_files = request.files.getlist('new_images')
    added_image_paths = []
    if new_images_files:
         upload_folder_abs = current_app.config['UPLOAD_FOLDER_ABSOLUTE']
         if not upload_folder_abs or not os.path.exists(upload_folder_abs):
             flash("Lỗi cấu hình: Thư mục upload không tồn tại hoặc chưa được thiết lập.", "danger")
             # Không commit nếu không thể lưu ảnh mới, hoặc cho phép lưu record mà không có ảnh mới
             # return redirect(error_redirect_url) # Cân nhắc
         else:
            for image_file in new_images_files:
                if image_file and image_file.filename and allowed_file(image_file.filename):
                    try:
                        filename = secure_filename(f"record_{record_id}_{int(datetime.now().timestamp())}_{image_file.filename}")
                        filepath = os.path.join(upload_folder_abs, filename)
                        image_file.save(filepath)
                        new_image = Image(record_id=record_id, image_path=filename)
                        db.session.add(new_image)
                        added_image_paths.append(filename)
                        current_app.logger.info(f"Đã chuẩn bị thêm ảnh '{filename}' cho record ID {record_id}")
                    except Exception as e_save:
                        current_app.logger.error(f"Lỗi khi chuẩn bị lưu ảnh mới '{image_file.filename}' cho record {record_id}: {e_save}", exc_info=True)
                        flash(f"Lỗi khi lưu ảnh mới: {image_file.filename}", "warning")
                elif image_file and image_file.filename:
                    flash(f"Định dạng file ảnh mới '{image_file.filename}' không được phép.", "warning")

    # Commit các thay đổi vào CSDL
    try:
        db.session.commit()
        flash('Cập nhật thông tin thiết bị thành công!', 'success')
        details_log = f"Updated record ID {record_id} (MAC: {record.mac_address})."
        if deleted_image_paths: details_log += f" Deleted images: {len(deleted_image_paths)} ({', '.join(deleted_image_paths)})."
        if added_image_paths: details_log += f" Added images: {len(added_image_paths)} ({', '.join(added_image_paths)})."
        # log_audit_action('update_record', 'records', record_id, details_log) # Đảm bảo hàm này tồn tại
        current_app.logger.info(details_log)
        return redirect(success_redirect_url)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Lỗi SQLAlchemy khi cập nhật record ID {record_id}: {e}", exc_info=True)
        flash('Lỗi CSDL khi cập nhật thiết bị.', 'danger')
        return redirect(error_redirect_url)

# Route xử lý xóa một thiết bị (chấp nhận POST)
@app.route('/delete/<int:record_id>', methods=['POST'])
@login_required
def delete_record(record_id):
    record = db.session.get(Record, record_id)
    # === THÊM MỚI: Kiểm tra quyền sở hữu trước khi thực hiện ===
    if record and record.user_id != current_user.id and current_user.role != 'admin':
        flash('Bạn không có quyền thực hiện hành động này trên bản ghi thiết bị này.', 'danger')
        return redirect(url_for('index'))
    # === KẾT THÚC THÊM MỚI ===
    page = request.form.get('page', 1, type=int)
    keyword = request.form.get('keyword', '')
    start_date = request.form.get('start_date', '')
    end_date = request.form.get('end_date', '')
    redirect_url = url_for('index', page=page, keyword=keyword, start_date=start_date, end_date=end_date)
    delete_files_flag = request.form.get('delete_physical_files') == 'yes'
    if not record:
        flash(f"Không tìm thấy thiết bị ID {record_id} để xóa.", "warning")
        return redirect(redirect_url)

    mac_address_deleted = record.mac_address
    images_to_delete_in_db = list(record.images)
    try:
        db.session.delete(record)
        deleted_file_count, error_file_count = 0, 0
        deleted_filenames = []
        if delete_files_flag and images_to_delete_in_db:
            upload_folder_abs = current_app.config['UPLOAD_FOLDER_ABSOLUTE']
            image_paths_to_delete = [img.image_path for img in images_to_delete_in_db]
            deleted_file_count, error_file_count = delete_physical_files(image_paths_to_delete, upload_folder_abs)
            deleted_filenames = image_paths_to_delete
            if error_file_count > 0: flash(f"Lỗi khi xóa {error_file_count} file ảnh vật lý.", "warning")
        elif not delete_files_flag:
            logging.info(f"Bỏ qua xóa file vật lý cho record {record_id} (MAC: {mac_address_deleted}).")

        db.session.commit()
        flash_message = f"Đã xóa thông tin thiết bị MAC {mac_address_deleted} (ID: {record_id})."
        if delete_files_flag:
            if deleted_file_count > 0: flash_message += f" Đã xóa {deleted_file_count}/{len(deleted_filenames)} file ảnh vật lý."
            elif not images_to_delete_in_db: flash_message += " Không có file ảnh vật lý nào được liên kết để xóa."
        else: flash_message += " Các file ảnh vật lý (nếu có) được giữ lại."
        flash(flash_message, "success")

        log_details = f"Deleted record MAC {mac_address_deleted}. DB Images deleted via cascade/trigger."
        if delete_files_flag:
             if deleted_filenames: log_details += f" Physically deleted {deleted_file_count}/{len(deleted_filenames)} image file(s)."
             else: log_details += f" Physical file deletion requested, but no files found/associated."
        else: log_details += f" Physical file deletion skipped by user choice."
        log_audit_action('delete_record', 'records', record_id, log_details)
        logging.info(f"Đã xóa record ID {record_id} (MAC: {mac_address_deleted}). Physical file deletion: {delete_files_flag}, Deleted: {deleted_file_count}/{len(deleted_filenames)}")
    except Exception as e:
        db.session.rollback()
        logging.error(f"Lỗi SQLAlchemy khi xóa record ID {record_id}: {e}", exc_info=True)
        flash(f'Lỗi CSDL khi xóa thiết bị: {e}', 'danger')
    return redirect(redirect_url)

# Route xử lý import thiết bị từ file Excel (chấp nhận POST)
@app.route('/import', methods=['POST'])
@login_required
def import_records():
    if 'file' not in request.files:
        flash('Vui lòng chọn file Excel (.xlsx) để nhập', 'danger')
        return redirect(url_for('index'))
    file = request.files['file']
    if file.filename == '':
        flash('Không có file nào được chọn', 'warning')
        return redirect(url_for('index'))

    if file and allowed_import_file(file.filename):
        filename = secure_filename(file.filename)
        logging.info(f"Bắt đầu xử lý import file (SQLAlchemy upsert, MAC '-', xử lý Image Paths): {filename}")
        inserted_count, updated_count, skipped_record_count = 0, 0, 0
        image_added_count, image_deleted_count = 0, 0
        image_not_found_errors, error_rows_general = [], []
        try:
            df = pd.read_excel(file, dtype=str, keep_default_na=False)
            df.columns = df.columns.str.strip().str.lower()
            column_mapping = {
                'mac address': 'mac_address', 'loại thiết bị': 'device_type', 'ip address': 'ip_address',
                'trạng thái': 'status', 'chi tiết': 'details', 'ngày ghi nhận': 'record_date',
                'username': 'username', 'image paths': 'image_paths'
            }
            df.rename(columns=column_mapping, inplace=True)
            if 'mac_address' not in df.columns:
                flash('File Excel phải có cột "MAC Address".', 'danger')
                return redirect(url_for('index'))

            df['mac_address_original'] = df['mac_address'].astype(str).str.strip()
            df['mac_address'] = df['mac_address_original'].apply(lambda x: normalize_mac(x, separator='-'))
            df_valid_mac = df.dropna(subset=['mac_address']).copy()
            if df_valid_mac.empty:
                flash("Không tìm thấy MAC Address hợp lệ trong file Excel.", 'warning')
                return redirect(url_for('index'))
            if df_valid_mac['mac_address'].duplicated().any():
                duplicates = df_valid_mac[df_valid_mac['mac_address'].duplicated()]['mac_address_original'].tolist()
                flash(f"Lỗi: MAC Address trùng lặp trong file Excel: {', '.join(duplicates)}.", "danger")
                return redirect(url_for('index'))

            if 'record_date' in df_valid_mac.columns:
                df_valid_mac['record_date_original'] = df_valid_mac['record_date'].astype(str).str.strip()
                df_valid_mac['record_date'] = df_valid_mac['record_date_original'].apply(format_date_for_storage)
                invalid_date_rows = df_valid_mac[df_valid_mac['record_date_original'].ne('') & df_valid_mac['record_date'].isnull()]
                for index, row in invalid_date_rows.iterrows():
                    error_rows_general.append(f"Dòng {index + 2} (MAC: {row.get('mac_address_original', 'N/A')}): Ngày '{row['record_date_original']}' không hợp lệ.")
            else: df_valid_mac['record_date'] = None

            if 'image_paths' not in df_valid_mac.columns:
                logging.warning("Cột 'image paths' không tồn tại.")
                df_valid_mac['image_paths'] = ''
            else: df_valid_mac['image_paths'] = df_valid_mac['image_paths'].astype(str).fillna('').str.strip()

            ensure_cols = ['ip_address', 'username', 'device_type', 'status', 'details']
            valid_db_columns = ['mac_address', 'ip_address', 'username', 'device_type', 'status', 'record_date', 'details']
            for col in ensure_cols:
                if col not in df_valid_mac.columns: df_valid_mac[col] = None
                else:
                    df_valid_mac[col] = df_valid_mac[col].astype(str).fillna('').replace('nan', '').str.strip()
                    df_valid_mac[col] = df_valid_mac[col].where(df_valid_mac[col] != '', None)

            existing_records_dict = {rec.mac_address: rec for rec in Record.query.options(selectinload(Record.images)).all()}
            upload_folder_abs = current_app.config['UPLOAD_FOLDER_ABSOLUTE']
            if not os.path.isdir(upload_folder_abs):
                flash(f"Lỗi cấu hình: Thư mục uploads '{upload_folder_abs}' không hợp lệ.", "danger")
                logging.error(f"Import failed: Upload folder invalid: {upload_folder_abs}")
                return redirect(url_for('index'))

            try:
                for index, row in df_valid_mac.iterrows():
                    mac_normalized = row['mac_address']
                    record_data = {col: row[col] for col in valid_db_columns if col in row}
                    image_paths_str = row['image_paths']
                    row_identifier_log = f"Dòng {index + 2} (MAC: {row.get('mac_address_original', mac_normalized)})"
                    if any(row_identifier_log in error for error in error_rows_general):
                        skipped_record_count += 1
                        logging.warning(f"{row_identifier_log}: Bỏ qua do lỗi định dạng ngày.")
                        continue

                    image_filenames_excel = {img_name.strip() for img_name in image_paths_str.split(',') if img_name.strip()}
                    logging.debug(f"{row_identifier_log}: Ảnh Excel: {image_filenames_excel}")
                    record_to_process = None
                    is_update = False

                    if mac_normalized in existing_records_dict: # UPDATE
                        is_update = True
                        record_to_process = existing_records_dict[mac_normalized]
                        logging.debug(f"{row_identifier_log}: Bắt đầu UPDATE.")
                        update_details_record = []
                        for key, value in record_data.items():
                            if key != 'mac_address' and getattr(record_to_process, key) != value:
                                setattr(record_to_process, key, value)
                                update_details_record.append(f"{key}={value}")
                        if update_details_record: logging.info(f"{row_identifier_log}: Cập nhật fields: {', '.join(update_details_record)}")
                    else: # INSERT
                        logging.debug(f"{row_identifier_log}: Bắt đầu INSERT.")
                        record_to_process = Record(**record_data)
                        db.session.add(record_to_process)
                        try:
                            db.session.flush()
                            logging.info(f"{row_identifier_log}: Inserted, got ID: {record_to_process.id}")
                        except Exception as e_flush:
                            db.session.rollback()
                            error_msg = f"{row_identifier_log}: Lỗi flush CSDL - {e_flush}"
                            error_rows_general.append(error_msg); logging.error(error_msg, exc_info=True)
                            skipped_record_count += 1; continue

                    if record_to_process and record_to_process.id:
                        current_images_db_dict = {img.image_path: img for img in record_to_process.images}
                        current_filenames_db = set(current_images_db_dict.keys())
                        logging.debug(f"{row_identifier_log}: Ảnh DB: {current_filenames_db}")
                        images_to_delete_paths = current_filenames_db - image_filenames_excel
                        if images_to_delete_paths:
                            logging.info(f"{row_identifier_log}: Ảnh xóa khỏi DB: {images_to_delete_paths}")
                            for img_path in images_to_delete_paths: db.session.delete(current_images_db_dict[img_path])
                            image_deleted_count += len(images_to_delete_paths)
                        images_to_add_paths = image_filenames_excel - current_filenames_db
                        if images_to_add_paths:
                            logging.info(f"{row_identifier_log}: Ảnh thêm vào DB: {images_to_add_paths}")
                            for img_path in images_to_add_paths:
                                full_image_path_check = join(upload_folder_abs, img_path)
                                if os.path.exists(full_image_path_check):
                                    new_image = Image(record_id=record_to_process.id, image_path=img_path)
                                    db.session.add(new_image); image_added_count += 1
                                    logging.info(f"{row_identifier_log}: Thêm Image object '{img_path}'.")
                                else:
                                    error_msg = f"{row_identifier_log}: Ảnh '{img_path}' không tìm thấy tại '{full_image_path_check}'. Bỏ qua."
                                    image_not_found_errors.append(error_msg); logging.warning(error_msg)
                        if is_update: updated_count += 1 if update_details_record or images_to_delete_paths or images_to_add_paths else 0
                        else: inserted_count += 1
                    else: logging.error(f"{row_identifier_log}: Bỏ qua xử lý ảnh do thiếu record ID.")
                db.session.commit()
                flash(f'Import hoàn tất từ {filename}: Thêm {inserted_count}, Cập nhật {updated_count}, Bỏ qua {skipped_record_count}.', 'success')
                if image_added_count > 0: flash(f'Đã thêm {image_added_count} liên kết ảnh.', 'info')
                if image_deleted_count > 0: flash(f'Đã xóa {image_deleted_count} liên kết ảnh.', 'info')
                if error_rows_general: flash("Lỗi xử lý các dòng sau:", 'warning'); [flash(error, 'warning') for error in error_rows_general[:10]];
                if len(error_rows_general) > 10: flash("... và các lỗi khác.", 'warning')
                if image_not_found_errors: flash("Lỗi ảnh không tìm thấy file:", 'warning'); [flash(error, 'warning') for error in image_not_found_errors[:10]];
                if len(image_not_found_errors) > 10: flash("... và các lỗi khác.", 'warning')
                log_audit_action('import_records', 'records', None, f"Import {filename}: Ins={inserted_count}, Upd={updated_count}, Skip={skipped_record_count}. ImgAdd={image_added_count}, ImgDel={image_deleted_count}. Err(Gen={len(error_rows_general)}, ImgNF={len(image_not_found_errors)})")
            except Exception as e_sql:
                db.session.rollback(); logging.error(f"Lỗi SQL/Pandas: {e_sql}", exc_info=True)
                flash(f"Lỗi CSDL/xử lý dữ liệu: {e_sql}", "danger")
        except Exception as e:
            logging.error(f"Lỗi import Excel '{filename}': {str(e)}", exc_info=True)
            flash(f'Lỗi xử lý file Excel: {str(e)}.', 'danger')
    else:
        flash('Định dạng file không hợp lệ (chỉ .xlsx).', 'danger')
    return redirect(url_for('index'))

# Route xuất dữ liệu thiết bị ra file CSV hoặc Excel
@app.route('/export/<format>')
@login_required
def export_data(format):
    keyword = request.args.get('keyword', '')
    start_date_str = request.args.get('start_date', '')
    end_date_str = request.args.get('end_date', '')
    try:
        query = Record.query
        filters = build_filter_conditions_orm(keyword, start_date_str, end_date_str)
        if filters: query = query.filter(*filters)
        query = query.order_by(case((Record.record_date == None, 1), else_=0), desc(Record.record_date), desc(Record.id))
        records_to_export = query.options(joinedload(Record.images)).all()
        data_for_df = []
        for r in records_to_export:
            image_paths = ','.join([img.image_path for img in r.images]) if r.images else ''
            data_for_df.append({
                'MAC Address': r.mac_address, 'IP Address': r.ip_address or '', 'Username': r.username or '',
                'Loại Thiết bị': r.device_type or '', 'Trạng thái': r.status or '',
                'Ngày ghi nhận': r.record_date.strftime('%d/%m/%Y') if r.record_date else '',
                'Chi tiết': r.details or '', 'Image Paths': image_paths
            })
        df = pd.DataFrame(data_for_df)
        output = io.BytesIO()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if format == 'excel':
            filename = f'danh_sach_thiet_bi_{timestamp}.xlsx'
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                 df.to_excel(writer, index=False, sheet_name='DanhSachThietBi')
                 worksheet = writer.sheets['DanhSachThietBi']
                 for column_cells in worksheet.columns:
                     try:
                         length = max(len(str(cell.value)) for cell in column_cells if cell.value is not None)
                         col_letter = column_cells[0].column_letter
                         worksheet.column_dimensions[col_letter].width = min(length + 2, 60)
                     except Exception as e_width:
                         logging.warning(f"Lỗi chỉnh độ rộng cột {column_cells[0].column_letter}: {e_width}")
                         pass
        elif format == 'csv':
            filename = f'danh_sach_thiet_bi_{timestamp}.csv'
            csv_data = df.to_csv(index=False, encoding='utf-8-sig', sep=',')
            output.write(csv_data.encode('utf-8-sig'))
            mimetype='text/csv; charset=utf-8-sig'
        else:
            flash('Định dạng export không hỗ trợ.', 'warning')
            return redirect(url_for('index', keyword=keyword, start_date=start_date_str, end_date=end_date_str))
        output.seek(0)
        log_audit_action('export_data', 'records', None, f"Exported {len(records_to_export)} records (format: {format}).")
        return send_file(output, mimetype=mimetype, download_name=filename, as_attachment=True)
    except Exception as e:
        logging.error(f"Lỗi export data format {format}: {e}", exc_info=True)
        flash(f"Lỗi tạo file export: {e}", "danger")
        return redirect(url_for('index', keyword=keyword, start_date=start_date_str, end_date=end_date_str))

# Route thực hiện ping IP và mở cửa sổ dòng lệnh
@app.route('/ping_ip/<ip_address>')
@login_required
def ping_ip(ip_address):
    if not re.match(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$", ip_address):
        flash(f"Địa chỉ IP '{ip_address}' không hợp lệ.", "danger")
        return redirect(request.referrer or url_for('index'))
    try:
        system = platform.system().lower()
        ping_cmd_win = f"ping {ip_address} -t"
        ping_cmd_unix = f"ping {ip_address}"
        if system == "windows": subprocess.Popen(['start', 'cmd', '/k', ping_cmd_win], shell=True, creationflags=subprocess.CREATE_NEW_CONSOLE)
        elif system == "darwin":
            apple_script = f'tell application "Terminal"\n activate\n do script "{ping_cmd_unix}"\n end tell'
            subprocess.Popen(['osascript', '-e', apple_script])
        elif system == "linux":
            try: subprocess.Popen(['gnome-terminal', '--', 'bash', '-c', f'{ping_cmd_unix}; exec bash'])
            except FileNotFoundError:
                 try: subprocess.Popen(['xterm', '-hold', '-e', ping_cmd_unix])
                 except FileNotFoundError:
                     flash("Không tìm thấy gnome-terminal/xterm.", "warning")
                     return redirect(request.referrer or url_for('index'))
        else:
            flash(f"HĐH '{system}' không hỗ trợ mở cửa sổ ping.", "warning")
            return redirect(request.referrer or url_for('index'))
        flash(f"Đã yêu cầu mở cửa sổ ping tới {ip_address}.", "info")
    except Exception as e:
        flash(f"Lỗi mở cửa sổ ping: {e}", "danger")
        logging.error(f"Lỗi mở CMD ping {ip_address}: {e}", exc_info=True)
    return redirect(request.referrer or url_for('index'))

# Route phục vụ các file đã upload
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    if '..' in filename or filename.startswith('/'): abort(404)
    try:
        return send_from_directory(app.config['UPLOAD_FOLDER_ABSOLUTE'], filename)
    except FileNotFoundError:
        logging.warning(f"File không tồn tại trong uploads: {filename}")
        abort(404)
    except Exception as e:
        logging.error(f"Lỗi gửi file {filename}: {e}", exc_info=True)
        abort(500)

# === ROUTES NHẬT KÝ CÔNG VIỆC (WorkLog) - ĐÃ CẬP NHẬT LỌC ===

# === ROUTE: Hiển thị danh sách nhật ký (ĐÃ CẬP NHẬT) ===
@app.route('/work_log')
@login_required
@role_required(['admin', 'basic_user', 'device_log_user'])
def work_log():
    try:
        log_page = max(1, int(request.args.get('log_page', default=1))) if request.args.get('log_page', '1').isdigit() else 1
    except ValueError:
        log_page = 1

    # --- START: Lấy tham số lọc MỚI ---
    start_date_filter = request.args.get('start_date_filter', '').strip()
    end_date_filter = request.args.get('end_date_filter', '').strip()
    keyword = request.args.get('keyword', '').strip() # Đọc keyword mới
    # --- END: Lấy tham số lọc MỚI ---

    # Sử dụng hàm trợ giúp đã cập nhật để xây dựng filters
    filters_orm = build_work_log_filters_orm(start_date_filter, end_date_filter, keyword)

    # Xây dựng query và áp dụng filters
    query = WorkLog.query
    # === THÊM MỚI: Lọc theo chủ sở hữu nếu không phải admin ===
    if current_user.role != 'admin':
        query = query.filter(WorkLog.user_id == current_user.id)
    # === KẾT THÚC THÊM MỚI ===
    if filters_orm:
        query = query.filter(*filters_orm) # Áp dụng bộ lọc nếu có

    # Sắp xếp và Phân trang (Giữ nguyên)
    query = query.order_by(desc(WorkLog.log_date), desc(WorkLog.id))
    pagination = query.paginate(page=log_page, per_page=app.config['LOGS_PER_PAGE'], error_out=False)
    logs_to_display = pagination.items

    # Lấy danh sách loại hoạt động (Giữ nguyên, dùng cho form Add)
    activity_types = []
    try:
        types_query = db.session.query(WorkLog.activity_type).distinct().order_by(WorkLog.activity_type).all()
        activity_types = [t[0] for t in types_query if t[0]]
    except Exception as e:
        logging.error(f"Lỗi SQLAlchemy khi lấy loại hoạt động: {e}")
        flash("Lỗi khi tải danh sách loại hoạt động.", "warning")


    # --- START: Chuẩn bị dictionary filter MỚI cho template ---
    # Dictionary để truyền cho link phân trang và nút export
    filters_dict = {
        'start_date_filter': start_date_filter,
        'end_date_filter': end_date_filter,
        'keyword': keyword # Chỉ cần keyword
    }
    # Dictionary để hiển thị lại giá trị trên form lọc
    filters_form = filters_dict.copy()
    # Format lại ngày tháng cho input type="date"
    log_start_date_obj = format_date_for_storage(start_date_filter)
    log_end_date_obj = format_date_for_storage(end_date_filter)
    filters_form['start_date_filter'] = log_start_date_obj.strftime('%Y-%m-%d') if log_start_date_obj else ''
    filters_form['end_date_filter'] = log_end_date_obj.strftime('%Y-%m-%d') if log_end_date_obj else ''
    # Flash message nếu ngày nhập vào không hợp lệ
    if start_date_filter and not log_start_date_obj:
        flash(f'Định dạng "Từ ngày" ({start_date_filter}) không hợp lệ khi lọc nhật ký.', 'warning')
    if end_date_filter and not log_end_date_obj:
        flash(f'Định dạng "Đến ngày" ({end_date_filter}) không hợp lệ khi lọc nhật ký.', 'warning')
    # --- END: Chuẩn bị dictionary filter MỚI ---

    # Trả về template với dữ liệu đã cập nhật
    return render_template('work_log.html',
                           logs=logs_to_display,
                           activity_types=activity_types, # Vẫn cần cho form Thêm mới
                           pagination=pagination,
                           log_page=log_page,
                           total_log_pages=pagination.pages,
                           total_logs=pagination.total,
                           filters=filters_dict, # Đã cập nhật
                           filters_form=filters_form) # Đã cập nhật

# === THÊM ROUTE MỚI ĐỂ XEM CHI TIẾT NHẬT KÝ CÔNG VIỆC ===
@app.route('/work_log/view/<int:log_id>')
@login_required
@role_required(['admin', 'basic_user', 'device_log_user'])
def view_work_log_detail(log_id):
    """
    Hiển thị trang chi tiết cho một nhật ký công việc cụ thể.
    Bao gồm tất cả thông tin và ảnh đính kèm (dưới dạng slideshow nếu nhiều ảnh).
    """
    try:
        # Truy vấn WorkLog và tải sẵn các ảnh liên quan để tối ưu
        # Sử dụng get_or_404 để tự động trả về lỗi 404 nếu không tìm thấy log
        # Trong app.py, bên trong hàm view_work_log_detail(log_id)

        # Truy vấn bản ghi WorkLog cùng với các ảnh liên quan
        # Sử dụng .first() thay vì .get() vì .get() không hoạt động trực tiếp với .options() theo cách này
        log_entry = WorkLog.query.options(selectinload(WorkLog.images)).filter_by(id=log_id).first()
        # === THÊM MỚI: Kiểm tra quyền sở hữu ===
        if log_entry and log_entry.user_id != current_user.id and current_user.role != 'admin':
            flash('Bạn không có quyền truy cập vào nhật ký công việc này.', 'danger')
            return redirect(url_for('work_log'))
        # === KẾT THÚC THÊM MỚI ===
        if not log_entry:
            # Nếu không tìm thấy bản ghi, flash thông báo cụ thể
            flash(f"Không tìm thấy nhật ký công việc với ID {log_id}. Có thể ID không đúng hoặc nhật ký đã bị xóa.", 'warning')

            # Chuyển hướng về trang danh sách, giữ lại các tham số lọc và phân trang nếu có
            # để người dùng không bị mất ngữ cảnh tìm kiếm trước đó.
            return redirect(url_for('work_log', 
                                    log_page=request.args.get('log_page', 1, type=int), # Lấy page hiện tại
                                    start_date_filter=request.args.get('start_date_filter', ''),
                                    end_date_filter=request.args.get('end_date_filter', ''),
                                    keyword=request.args.get('keyword', '')))

# Nếu bản ghi tồn tại, log_entry đã chứa thông tin cần thiết (bao gồm cả images do selectinload)
# Không cần gán lại hay làm gì thêm với log_entry ở đây.

        # Lấy các tham số lọc và phân trang từ URL query string
        # để truyền cho template, giúp nút "Quay lại danh sách" hoạt động chính xác
        # Các tên tham số này phải khớp với tên được sử dụng trong route 'work_log'
        # và trong file 'work_log.html' cho các link phân trang và nút "Xem".
        # request.args.get('log_page', 1, type=int) # Đảm bảo log_page là số nguyên
        # request.args.get('start_date_filter', '')
        # request.args.get('end_date_filter', '')
        # request.args.get('keyword', '')
        # Các tham số này sẽ tự động có sẵn trong `request.args` ở template `view_work_log_detail.html`
        # nên không cần truyền tường minh vào render_template nếu template xử lý lấy từ request.args

        # Ghi log audit (tùy chọn)
        # log_audit_action('view_work_log_detail', 'work_logs', log_id, f"User {current_user.username} viewed work log ID {log_id}")

        return render_template('view_work_log_detail.html',
                               log=log_entry
                               # Các tham số lọc sẽ được truy cập qua request.args trong template
                               # Ví dụ: request.args.get('log_page', 1)
                               )

    except Exception as e:
        # Ghi log lỗi nếu có vấn đề xảy ra
        logging.error(f"Lỗi khi tải trang xem chi tiết nhật ký ID {log_id}: {e}", exc_info=True)
        # Hiển thị thông báo lỗi cho người dùng
        flash('Đã xảy ra lỗi khi tải chi tiết công việc. Vui lòng thử lại.', 'danger')
        # Chuyển hướng người dùng về trang danh sách nhật ký
        return redirect(url_for('work_log'))
# === KẾT THÚC ROUTE XEM CHI TIẾT NHẬT KÝ CÔNG VIỆC ===


# Route xử lý thêm nhật ký mới
@app.route('/work_log/add', methods=['POST'])
@login_required
@role_required(['admin', 'basic_user', 'device_log_user'])
def add_work_log():
    log_date_str = request.form.get('log_date', '').strip()
    activity_type = request.form.get('activity_type', '').strip()
    description = request.form.get('description', '').strip() or None
    device_identifier = request.form.get('device_identifier', '').strip() or None
    cost_str = request.form.get('cost', '0').strip()
    technician = request.form.get('technician', '').strip() or None
    images_files = request.files.getlist('images')

    if not log_date_str: flash("Ngày thực hiện là bắt buộc.", "danger"); return redirect(url_for('work_log'))
    if not activity_type: flash("Loại hoạt động là bắt buộc.", "danger"); return redirect(url_for('work_log'))
    log_date_db = format_date_for_storage(log_date_str)
    if not log_date_db: flash(f"Định dạng ngày '{log_date_str}' không hợp lệ.", "danger"); return redirect(url_for('work_log'))
    cost = 0.0
    if cost_str and cost_str != '0':
        try:
            cost_cleaned = cost_str.replace('.', '').replace(',', '.')
            cost = float(cost_cleaned)
            if cost < 0: flash("Chi phí không được là số âm.", "danger"); return redirect(url_for('work_log'))
        except ValueError: flash(f"Định dạng chi phí '{cost_str}' không hợp lệ.", "danger"); return redirect(url_for('work_log'))

    new_log = WorkLog(log_date=log_date_db, activity_type=activity_type, description=description, device_identifier=device_identifier, cost=cost, technician=technician, user_id=current_user.id)
    db.session.add(new_log)
    added_log_image_paths = []
    try:
        if images_files:
            upload_folder_abs = current_app.config['UPLOAD_FOLDER_ABSOLUTE']
            db.session.flush()
            log_id_for_filename = new_log.id
            if not log_id_for_filename: raise ValueError("Không thể lấy ID WorkLog mới sau khi flush.")
            for image_file in images_files:
                if image_file and image_file.filename and allowed_file(image_file.filename):
                    try:
                        filename = secure_filename(f"log_{log_id_for_filename}_{int(datetime.now().timestamp())}_{image_file.filename}")
                        filepath = join(upload_folder_abs, filename)
                        image_file.save(filepath)
                        new_log_image = WorkLogImage(work_log_id=log_id_for_filename, image_path=filename)
                        db.session.add(new_log_image)
                        added_log_image_paths.append(filename)
                        logging.info(f"Chuẩn bị lưu ảnh '{filename}' cho WorkLog ID {log_id_for_filename}")
                    except Exception as e_save:
                        logging.error(f"Lỗi lưu ảnh '{image_file.filename}' cho WorkLog {log_id_for_filename}: {e_save}", exc_info=True)
                        flash(f"Lỗi xử lý ảnh: {image_file.filename}", "warning")
                elif image_file and image_file.filename:
                    flash(f"Định dạng file ảnh '{image_file.filename}' không được phép.", "warning")
        db.session.commit()
        flash_msg = "Thêm nhật ký công việc thành công!"
        if added_log_image_paths: flash_msg += f" Đã đính kèm {len(added_log_image_paths)} ảnh."
        flash(flash_msg, "success")
        log_audit_action('add_work_log', 'work_logs', new_log.id, f"Added log: Type={activity_type}, Device={device_identifier or 'N/A'}. Added images: {len(added_log_image_paths)}.")
        logging.info(f"Thêm nhật ký ID: {new_log.id}, Date={log_date_db}, Type={activity_type}, Images: {len(added_log_image_paths)}")
    except Exception as e:
        db.session.rollback()
        logging.error(f"Lỗi SQLAlchemy khi thêm nhật ký: {e}", exc_info=True)
        flash(f"Lỗi CSDL khi thêm nhật ký: {e}", "danger")
    return redirect(url_for('work_log'))

# Route hiển thị form chỉnh sửa nhật ký
@app.route('/work_log/edit/<int:log_id>', methods=['GET'])
@login_required
@role_required(['admin', 'basic_user', 'device_log_user'])
def edit_work_log(log_id):
    try:
        log = db.session.query(WorkLog).options(selectinload(WorkLog.images)).get(log_id)
        # === THÊM MỚI: Kiểm tra quyền sở hữu ===
        # Thay 'log' bằng 'log_to_update' hoặc 'log_to_delete' tùy theo tên biến trong hàm
        if log and log.user_id != current_user.id and current_user.role != 'admin':
            flash('Bạn không có quyền thực hiện hành động này trên nhật ký công việc này.', 'danger')
            return redirect(url_for('work_log'))
        # === KẾT THÚC THÊM MỚI ===
        if not log:
            flash(f"Không tìm thấy nhật ký ID {log_id}.", "warning")
            return redirect(url_for('work_log'))
        activity_types = []
        try:
            types_query = db.session.query(WorkLog.activity_type).distinct().order_by(WorkLog.activity_type).all()
            activity_types = [t[0] for t in types_query if t[0]]
        except Exception as e_types: logging.error(f"Lỗi lấy loại HĐ (edit): {e_types}")
        return render_template('edit_work_log.html', log=log, activity_types=activity_types)
    except Exception as e:
        logging.error(f"Lỗi tải trang sửa nhật ký ID {log_id}: {e}", exc_info=True)
        flash('Lỗi CSDL khi tải trang sửa.', 'danger')
        return redirect(url_for('work_log'))

# Route xử lý cập nhật nhật ký
@app.route('/work_log/update/<int:log_id>', methods=['POST'])
@login_required
@role_required(['admin', 'basic_user', 'device_log_user'])
def update_work_log(log_id):
    log_to_update = db.session.query(WorkLog).options(selectinload(WorkLog.images)).get(log_id)
    # === THÊM MỚI: Kiểm tra quyền sở hữu ===
    # Thay 'log' bằng 'log_to_update' hoặc 'log_to_delete' tùy theo tên biến trong hàm
    if log_to_update and log_to_update.user_id != current_user.id and current_user.role != 'admin':
        flash('Bạn không có quyền thực hiện hành động này trên nhật ký công việc này.', 'danger')
        return redirect(url_for('work_log'))
    # === KẾT THÚC THÊM MỚI ===
    if log_to_update is None: abort(404)
    log_date_str = request.form.get('log_date', '').strip()
    activity_type = request.form.get('activity_type', '').strip()
    description = request.form.get('description', '').strip() or None
    device_identifier = request.form.get('device_identifier', '').strip() or None
    cost_str = request.form.get('cost', '0').strip()
    technician = request.form.get('technician', '').strip() or None
    delete_image_ids = request.form.getlist('delete_images')
    new_images_files = request.files.getlist('new_images')
    edit_redirect_url = url_for('edit_work_log', log_id=log_id)

    if not log_date_str: flash("Ngày thực hiện là bắt buộc.", "danger"); return redirect(edit_redirect_url)
    if not activity_type: flash("Loại hoạt động là bắt buộc.", "danger"); return redirect(edit_redirect_url)
    log_date_db = format_date_for_storage(log_date_str)
    if not log_date_db: flash(f"Định dạng ngày '{log_date_str}' không hợp lệ.", "danger"); return redirect(edit_redirect_url)
    cost = 0.0
    if cost_str and cost_str != '0':
        try:
            cost_cleaned = cost_str.replace('.', '').replace(',', '.')
            cost = float(cost_cleaned)
            if cost < 0: flash("Chi phí không được là số âm.", "danger"); return redirect(edit_redirect_url)
        except ValueError: flash(f"Định dạng chi phí '{cost_str}' không hợp lệ.", "danger"); return redirect(edit_redirect_url)

    log_to_update.log_date = log_date_db
    log_to_update.activity_type = activity_type
    log_to_update.description = description
    log_to_update.device_identifier = device_identifier
    log_to_update.cost = cost
    log_to_update.technician = technician

    # Xử lý xóa ảnh cũ
    deleted_log_image_paths = []
    if delete_image_ids:
        try:
            delete_ids_int = [int(img_id) for img_id in delete_image_ids]
            images_to_delete = db.session.query(WorkLogImage).filter(WorkLogImage.id.in_(delete_ids_int), WorkLogImage.work_log_id == log_id).all()
            upload_folder_abs = current_app.config['UPLOAD_FOLDER_ABSOLUTE']
            for img in images_to_delete:
                try:
                    image_path_to_delete = join(upload_folder_abs, img.image_path)
                    if os.path.exists(image_path_to_delete): os.remove(image_path_to_delete); logging.info(f"Xóa file ảnh WorkLog: {img.image_path}")
                    else: logging.warning(f"Không tìm thấy file ảnh WorkLog để xóa: {img.image_path}")
                    deleted_log_image_paths.append(img.image_path)
                    db.session.delete(img)
                except Exception as e_del_file: logging.error(f"Lỗi xóa file WorkLog {img.image_path}: {e_del_file}"); flash(f"Lỗi xóa ảnh {img.image_path}", "warning")
        except ValueError: flash("ID ảnh cần xóa không hợp lệ.", "warning"); logging.warning(f"Invalid image ID in delete_images list for WorkLog {log_id}: {delete_image_ids}")

    # Xử lý thêm ảnh mới
    added_log_image_paths = []
    if new_images_files:
         upload_folder_abs = current_app.config['UPLOAD_FOLDER_ABSOLUTE']
         for image_file in new_images_files:
            if image_file and image_file.filename and allowed_file(image_file.filename):
                try:
                    filename = secure_filename(f"log_{log_id}_{int(datetime.now().timestamp())}_{image_file.filename}")
                    filepath = join(upload_folder_abs, filename)
                    image_file.save(filepath)
                    new_log_image = WorkLogImage(work_log_id=log_id, image_path=filename)
                    db.session.add(new_log_image)
                    added_log_image_paths.append(filename)
                    logging.info(f"Chuẩn bị thêm ảnh '{filename}' cho WorkLog ID {log_id}")
                except Exception as e_save: logging.error(f"Lỗi lưu ảnh mới '{image_file.filename}' cho WorkLog {log_id}: {e_save}", exc_info=True); flash(f"Lỗi lưu ảnh mới: {image_file.filename}", "warning")
            elif image_file and image_file.filename: flash(f"Định dạng ảnh mới '{image_file.filename}' không phép.", "warning")

    # Commit
    try:
        db.session.commit()
        flash_msg = "Cập nhật nhật ký thành công!"
        if added_log_image_paths: flash_msg += f" Đã thêm {len(added_log_image_paths)} ảnh."
        if deleted_log_image_paths: flash_msg += f" Đã xóa {len(deleted_log_image_paths)} ảnh."
        flash(flash_msg, "success")
        log_details = f"Updated WorkLog ID {log_id}."
        if deleted_log_image_paths: log_details += f" Deleted images: {len(deleted_log_image_paths)}."
        if added_log_image_paths: log_details += f" Added images: {len(added_log_image_paths)}."
        log_audit_action('update_work_log', 'work_logs', log_id, log_details)
        logging.info(f"Cập nhật nhật ký ID {log_id}. Added: {len(added_log_image_paths)}, Deleted: {len(deleted_log_image_paths)}")
    except Exception as e:
        db.session.rollback(); logging.error(f"Lỗi SQLAlchemy cập nhật nhật ký ID {log_id}: {e}", exc_info=True)
        flash(f'Lỗi CSDL khi cập nhật: {e}', 'danger'); return redirect(edit_redirect_url)
    return redirect(url_for('work_log'))

# Route xử lý xóa một nhật ký
@app.route('/work_log/delete/<int:log_id>', methods=['POST'])
@login_required
@role_required(['admin', 'basic_user', 'device_log_user'])
def delete_work_log(log_id):
    log_to_delete = db.session.get(WorkLog, log_id)
    # === THÊM MỚI: Kiểm tra quyền sở hữu ===
    # Thay 'log' bằng 'log_to_update' hoặc 'log_to_delete' tùy theo tên biến trong hàm
    if log_to_delete and log_to_delete.user_id != current_user.id and current_user.role != 'admin':
        flash('Bạn không có quyền thực hiện hành động này trên nhật ký công việc này.', 'danger')
        return redirect(url_for('work_log'))
    # === KẾT THÚC THÊM MỚI ===
    delete_files_flag = request.form.get('delete_physical_files') == 'yes'
    if not log_to_delete: flash(f"Không tìm thấy nhật ký ID {log_id}.", "warning"); return redirect(url_for('work_log'))

    images_to_delete_in_db = list(log_to_delete.images)
    log_info_str = f"Log ID {log_id} (Type: {log_to_delete.activity_type}, Date: {log_to_delete.log_date})"
    try:
        db.session.delete(log_to_delete)
        deleted_file_count, error_file_count = 0, 0
        deleted_filenames = []
        if delete_files_flag and images_to_delete_in_db:
            upload_folder_abs = current_app.config['UPLOAD_FOLDER_ABSOLUTE']
            image_paths_to_delete = [img.image_path for img in images_to_delete_in_db]
            deleted_file_count, error_file_count = delete_physical_files(image_paths_to_delete, upload_folder_abs)
            deleted_filenames = image_paths_to_delete
            if error_file_count > 0: flash(f"Lỗi xóa {error_file_count} file ảnh của nhật ký.", "warning")
        elif not delete_files_flag: logging.info(f"Bỏ qua xóa file vật lý cho {log_info_str}.")

        db.session.commit()
        flash_message = f"Đã xóa nhật ký {log_info_str}."
        if delete_files_flag:
            if deleted_file_count > 0: flash_message += f" Đã xóa {deleted_file_count}/{len(deleted_filenames)} file ảnh vật lý."
            elif not images_to_delete_in_db: flash_message += " Không có file ảnh liên kết để xóa."
        else: flash_message += " Các file ảnh vật lý (nếu có) được giữ lại."
        flash(flash_message, "success")

        log_details = f"Deleted {log_info_str}. DB Images deleted via cascade."
        if delete_files_flag:
             if deleted_filenames: log_details += f" Physically deleted {deleted_file_count}/{len(deleted_filenames)} file(s)."
             else: log_details += f" Physical deletion requested, but no files associated."
        else: log_details += f" Physical file deletion skipped."
        log_audit_action('delete_work_log', 'work_logs', log_id, log_details)
        logging.info(f"Đã xóa {log_info_str}. Physical delete: {delete_files_flag}, Deleted: {deleted_file_count}/{len(deleted_filenames)}")
    except Exception as e:
        db.session.rollback(); logging.error(f"Lỗi SQLAlchemy xóa nhật ký ID {log_id}: {e}", exc_info=True)
        flash(f'Lỗi CSDL khi xóa: {e}', 'danger')
    return redirect(url_for('work_log'))


# === ROUTES XUẤT FILE NHẬT KÝ (ĐÃ CẬP NHẬT LỌC) ===

# Route xuất lịch sử công việc của một thiết bị cụ thể
@app.route('/export/work_logs/device/<mac_address>')
@login_required
def export_device_work_logs(mac_address):
    mac_hyphen = normalize_mac(mac_address, separator='-')
    if not mac_hyphen: flash(f"MAC '{mac_address}' không hợp lệ.", 'danger'); return redirect(request.referrer or url_for('index'))
    try:
        mac_colon = mac_hyphen.replace('-', ':')
        mac_no_sep = mac_hyphen.replace('-', '')
        logs_to_export = WorkLog.query.filter(
            or_(WorkLog.device_identifier == mac_hyphen, WorkLog.device_identifier == mac_colon, WorkLog.device_identifier == mac_no_sep)
        ).order_by(desc(WorkLog.log_date), desc(WorkLog.id)).all()
        if not logs_to_export:
            flash(f"Không tìm thấy lịch sử công việc cho MAC {mac_hyphen}.", 'info')
            record = db.session.get(Record, mac_hyphen)
            return redirect(url_for('view_images', record_id=record.id) if record else url_for('index'))
        data_for_df = [{
            'ID': log.id, 'Ngày': log.log_date.strftime('%d/%m/%Y') if log.log_date else '',
            'Loại Hoạt Động': log.activity_type, 'Định Danh TB': log.device_identifier or '',
            'Mô Tả': log.description or '', 'Chi Phí': log.cost, 'Người Thực Hiện': log.technician or '',
            'Thời Gian Tạo': log.created_at.strftime('%Y-%m-%d %H:%M:%S') if log.created_at else ''
        } for log in logs_to_export]
        df = pd.DataFrame(data_for_df)
        output = io.BytesIO()
        safe_mac_filename = mac_hyphen.replace('-', '')
        filename = f"lich_su_cong_viec_{safe_mac_filename}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name=f'Logs_{safe_mac_filename}')
            worksheet = writer.sheets[f'Logs_{safe_mac_filename}']
            for column_cells in worksheet.columns:
                try:
                    length = max(len(str(cell.value)) for cell in column_cells if cell.value is not None)
                    worksheet.column_dimensions[column_cells[0].column_letter].width = min(length + 2, 50)
                except Exception as e_width: logging.warning(f"Lỗi chỉnh độ rộng cột {column_cells[0].column_letter}: {e_width}"); pass
        output.seek(0)
        log_audit_action('export_device_work_logs', 'work_logs', None, f"Exported logs for MAC {mac_hyphen}")
        return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', download_name=filename, as_attachment=True)
    except Exception as e:
        logging.error(f"Lỗi export LS công việc MAC {mac_hyphen}: {e}", exc_info=True)
        flash(f"Lỗi tạo file export lịch sử: {e}", "danger")
        record = db.session.get(Record, mac_hyphen)
        return redirect(url_for('view_images', record_id=record.id) if record else url_for('index'))

# === ROUTE: Xuất file nhật ký đã lọc (ĐÃ CẬP NHẬT) ===
@app.route('/export/work_logs/filtered')
@login_required
def export_filtered_work_logs():
    """Xuất danh sách work log hiện tại (đã lọc theo logic MỚI) ra file Excel."""
    try:
        # --- START: Lấy các tham số lọc MỚI ---
        start_date_filter = request.args.get('start_date_filter', '').strip()
        end_date_filter = request.args.get('end_date_filter', '').strip()
        keyword = request.args.get('keyword', '').strip() # Lấy keyword mới
        # --- END: Lấy các tham số lọc MỚI ---

        # Sử dụng hàm trợ giúp đã cập nhật để xây dựng query
        filters_orm = build_work_log_filters_orm(start_date_filter, end_date_filter, keyword)
        query = WorkLog.query
        if filters_orm:
            query = query.filter(*filters_orm)
        query = query.order_by(desc(WorkLog.log_date), desc(WorkLog.id))

        # Tải sẵn ảnh liên quan (Giữ nguyên)
        logs_to_export = query.options(selectinload(WorkLog.images)).all()

        # Nếu không có dữ liệu phù hợp (Giữ nguyên)
        if not logs_to_export:
            flash("Không có dữ liệu nhật ký công việc nào phù hợp với bộ lọc để xuất.", 'info')
            # Redirect về trang log với các filter MỚI
            return redirect(url_for('work_log',
                                    start_date_filter=start_date_filter,
                                    end_date_filter=end_date_filter,
                                    keyword=keyword))

        # Chuẩn bị dữ liệu cho DataFrame (Đổi tên cột)
        data_for_df = []
        for log in logs_to_export:
            image_paths = ','.join([img.image_path for img in log.images]) if log.images else ''
            data_for_df.append({
                'ID Log': log.id,
                'Ngày Thực Hiện': log.log_date.strftime('%d/%m/%Y') if log.log_date else '',
                'Loại Hoạt Động': log.activity_type,
                'Định Danh Thiết Bị': log.device_identifier or '',
                'Mô Tả Chi Tiết': log.description or '',
                'Chi Phí': log.cost,
                'Nhà Cung Cấp': log.technician or '', # Đổi tên cột
                'Đường Dẫn Ảnh': image_paths # Đổi tên cột
            })

        # Tạo DataFrame và file Excel (Giữ nguyên)
        df = pd.DataFrame(data_for_df)
        output = io.BytesIO()
        filename = f"danh_sach_cong_viec_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
             df.to_excel(writer, index=False, sheet_name='DanhSachCongViec')
             worksheet = writer.sheets['DanhSachCongViec']
             # Tự động điều chỉnh độ rộng cột
             for column_cells in worksheet.columns:
                 try:
                     length = max(len(str(cell.value)) for cell in column_cells if cell.value is not None)
                     worksheet.column_dimensions[column_cells[0].column_letter].width = min(length + 2, 60)
                 except ValueError: pass # Bỏ qua lỗi nếu cột rỗng
                 except Exception as e_width:
                    logging.warning(f"Lỗi chỉnh độ rộng cột {column_cells[0].column_letter} khi export: {e_width}")
                    pass # Bỏ qua nếu có lỗi khác
        output.seek(0)

        # Ghi log audit (Giữ nguyên)
        log_audit_action('export_filtered_work_logs', 'work_logs', None, f"Exported filtered work logs ({len(logs_to_export)} logs).")
        # Gửi file về client (Giữ nguyên)
        return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', download_name=filename, as_attachment=True)

    except Exception as e:
        logging.error(f"Lỗi khi export danh sách công việc đã lọc: {e}", exc_info=True)
        flash(f"Lỗi khi tạo file export danh sách công việc: {e}", "danger")
        # Redirect về trang log với filter MỚI
        return redirect(url_for('work_log',
                                start_date_filter=request.args.get('start_date_filter', ''),
                                end_date_filter=request.args.get('end_date_filter', ''),
                                keyword=request.args.get('keyword', '')))


# Route xử lý import nhật ký công việc từ Excel
@app.route('/work_log/import', methods=['POST'])
@login_required
def import_work_logs():
    if 'file' not in request.files: flash('Vui lòng chọn file Excel (.xlsx).', 'danger'); return redirect(url_for('work_log'))
    file = request.files['file']
    if file.filename == '': flash('Không có file nào được chọn.', 'warning'); return redirect(url_for('work_log'))
    if file and allowed_import_file(file.filename):
        filename = secure_filename(file.filename)
        logging.info(f"Bắt đầu import Work Log từ file: {filename} (có kiểm tra trùng lặp)")
        inserted_count, skipped_count, duplicate_count = 0, 0, 0
        image_added_count, image_not_found_errors, error_rows_general = 0, [], []
        required_columns = ['log date', 'activity type']
        try:
            df = pd.read_excel(file, dtype=str, keep_default_na=False)
            df.columns = df.columns.str.strip().str.lower()
            missing_cols = [col for col in required_columns if col not in df.columns]
            if missing_cols: flash(f"File thiếu cột bắt buộc: {', '.join(missing_cols)}", 'danger'); return redirect(url_for('work_log'))
            column_mapping = {
                'log date': 'log_date', 'activity type': 'activity_type', 'mô tả': 'description',
                'định danh tb': 'device_identifier', 'chi phí': 'cost',
                'người thực hiện': 'technician', 'nhà cung cấp': 'technician', 'image paths': 'image_paths'
            }
            df.rename(columns=column_mapping, inplace=True)
            upload_folder_abs = current_app.config['UPLOAD_FOLDER_ABSOLUTE']
            if not os.path.isdir(upload_folder_abs): flash(f"Lỗi: Thư mục uploads '{upload_folder_abs}' không hợp lệ.", "danger"); logging.error(f"Import WorkLog failed: Upload folder invalid."); return redirect(url_for('work_log'))

            for index, row in df.iterrows():
                log_date_str = row.get('log_date', '').strip()
                activity_type = row.get('activity_type', '').strip()
                description = row.get('description', '').strip() or None
                device_identifier = row.get('device_identifier', '').strip() or None
                cost_str = row.get('cost', '0').strip()
                technician = row.get('technician', '').strip() or None
                image_paths_str = row.get('image_paths', '').strip()
                row_identifier_log = f"Dòng {index + 2}"

                log_date_db = format_date_for_storage(log_date_str)
                if not log_date_db or not activity_type:
                    error_msg = f"{row_identifier_log}: Thiếu/sai 'Log Date' hoặc 'Activity Type'. Bỏ qua."
                    error_rows_general.append(error_msg); logging.warning(error_msg); skipped_count += 1; continue
                cost = 0.0
                if cost_str and cost_str != '0':
                    try: cost = float(cost_str.replace('.', '').replace(',', '.'))
                    except ValueError: error_msg = f"{row_identifier_log}: Sai định dạng 'Cost' ({cost_str}). Dùng 0."; error_rows_general.append(error_msg); logging.warning(error_msg)
                if cost < 0: cost = 0
                try:
                    filter_conditions = [
                        WorkLog.log_date == log_date_db, WorkLog.activity_type == activity_type,
                        WorkLog.description.is_(description), WorkLog.device_identifier.is_(device_identifier),
                        WorkLog.cost == cost, WorkLog.technician.is_(technician)
                    ]
                    existing_log = db.session.query(WorkLog).filter(and_(*filter_conditions)).first()
                    if existing_log: duplicate_count += 1; logging.info(f"{row_identifier_log}: Trùng lặp (ID: {existing_log.id}). Bỏ qua."); continue
                except Exception as e_check: error_msg = f"{row_identifier_log}: Lỗi kiểm tra trùng lặp - {e_check}."; error_rows_general.append(error_msg); logging.error(error_msg, exc_info=True); skipped_count += 1; continue

                new_log = WorkLog(log_date=log_date_db, activity_type=activity_type, description=description, device_identifier=device_identifier, cost=cost, technician=technician)
                db.session.add(new_log)
                try:
                    db.session.flush()
                    log_id_new = new_log.id
                    if not log_id_new: raise ValueError("Không lấy được ID WorkLog mới.")
                    image_filenames_excel = {img_name.strip() for img_name in image_paths_str.split(',') if img_name.strip()}
                    images_actually_added = 0
                    if image_filenames_excel:
                        logging.info(f"{row_identifier_log} (LogID:{log_id_new}): Ảnh Excel: {image_filenames_excel}")
                        for img_path in image_filenames_excel:
                            full_image_path_check = join(upload_folder_abs, img_path)
                            if os.path.exists(full_image_path_check):
                                new_image = WorkLogImage(work_log_id=log_id_new, image_path=img_path)
                                db.session.add(new_image); images_actually_added += 1
                            else:
                                error_msg = f"{row_identifier_log} (LogID:{log_id_new}): Ảnh '{img_path}' không tìm thấy. Bỏ qua."
                                image_not_found_errors.append(error_msg); logging.warning(error_msg)
                        image_added_count += images_actually_added
                    inserted_count += 1
                except Exception as e_inner:
                    db.session.rollback(); error_msg = f"{row_identifier_log}: Lỗi lưu log/ảnh - {e_inner}"
                    error_rows_general.append(error_msg); logging.error(error_msg, exc_info=True); skipped_count += 1; continue
            db.session.commit()
            flash(f'Import Work Log: Thêm {inserted_count}, Lỗi {skipped_count}, Trùng lặp {duplicate_count}.', 'success')
            if image_added_count > 0: flash(f'Đã thêm {image_added_count} liên kết ảnh.', 'info')
            if error_rows_general: flash("Lỗi dòng:", 'warning'); [flash(error, 'warning') for error in error_rows_general[:10]];
            if len(error_rows_general) > 10: flash("...", 'warning')
            if image_not_found_errors: flash("Lỗi ảnh không tìm thấy:", 'warning'); [flash(error, 'warning') for error in image_not_found_errors[:10]];
            if len(image_not_found_errors) > 10: flash("...", 'warning')
            log_audit_action('import_work_logs', 'work_logs', None, f"Import {filename}: Ins={inserted_count}, Skip(Err)={skipped_count}, Skip(Dup)={duplicate_count}. ImgAdd={image_added_count}. Err(Gen={len(error_rows_general)}, ImgNF={len(image_not_found_errors)})")
        except Exception as e:
            db.session.rollback(); logging.error(f"Lỗi import Work Log Excel '{filename}': {str(e)}", exc_info=True)
            flash(f'Lỗi xử lý file Excel: {str(e)}.', 'danger')
    else: flash('Định dạng file không hợp lệ (chỉ .xlsx).', 'danger')
    return redirect(url_for('work_log'))


# === ROUTES XÓA TOÀN BỘ DỮ LIỆU ===

@app.route('/delete_all_records', methods=['POST'])
@login_required
def delete_all_records():
    """Xóa toàn bộ dữ liệu trong bảng records và các ảnh liên quan (nếu chọn)."""
    password = request.form.get('password')
    delete_files_flag = request.form.get('delete_physical_files') == 'yes'
    correct_password = current_app.config.get('DELETE_PASSWORD')
    if not password or password != correct_password:
        flash('Mật khẩu xác nhận không đúng.', 'danger')
        logging.warning(f"Thất bại xóa toàn bộ thiết bị: Sai MK từ IP {request.remote_addr}")
        return redirect(url_for('index'))

    image_paths_to_delete, records_deleted_count, files_deleted_count, files_error_count = [], 0, 0, 0
    try:
        if delete_files_flag:
            all_image_records = Image.query.with_entities(Image.image_path).all()
            image_paths_to_delete = [img.image_path for img in all_image_records if img.image_path]
            logging.info(f"Chuẩn bị xóa {len(image_paths_to_delete)} file ảnh thiết bị.")
        records_deleted_count = Record.query.delete(synchronize_session=False)
        logging.info(f"Gửi lệnh xóa {records_deleted_count} bản ghi Record (cascade/trigger xử lý Images DB).")
        if delete_files_flag and image_paths_to_delete:
            upload_folder_abs = current_app.config['UPLOAD_FOLDER_ABSOLUTE']
            files_deleted_count, files_error_count = delete_physical_files(image_paths_to_delete, upload_folder_abs)
            if files_error_count > 0: flash(f"Lỗi xóa {files_error_count} file ảnh thiết bị.", "warning")
        db.session.commit()
        flash_message = f"Đã xóa {records_deleted_count} bản ghi thiết bị."
        if delete_files_flag:
            flash_message += f" Đã xóa {files_deleted_count}/{len(image_paths_to_delete)} file ảnh liên quan."
            if files_error_count > 0: flash_message += f" ({files_error_count} lỗi)"
        else: flash_message += " Các file ảnh vật lý được giữ lại."
        flash(flash_message, 'success')
        log_details = f"DELETED ALL RECORDS ({records_deleted_count}). Physical files delete: {delete_files_flag}."
        if delete_files_flag: log_details += f" Files deleted: {files_deleted_count}/{len(image_paths_to_delete)}."
        log_audit_action('delete_all_records', 'records', None, log_details)
        logging.info(f"Xóa toàn bộ thiết bị thành công bởi IP {request.remote_addr}. Records: {records_deleted_count}. Delete files: {delete_files_flag}. Files deleted: {files_deleted_count}/{len(image_paths_to_delete)}")
    except Exception as e:
        db.session.rollback(); logging.error(f"Lỗi xóa toàn bộ thiết bị: {e}", exc_info=True)
        flash(f'Lỗi CSDL khi xóa toàn bộ thiết bị: {e}', 'danger')
    return redirect(url_for('index'))

@app.route('/delete_all_work_logs', methods=['POST'])
@login_required
def delete_all_work_logs():
    """Xóa toàn bộ dữ liệu trong bảng work_logs và các ảnh liên quan (nếu chọn)."""
    password = request.form.get('password')
    delete_files_flag = request.form.get('delete_physical_files') == 'yes'
    correct_password = current_app.config.get('DELETE_PASSWORD')
    if not password or password != correct_password:
        flash('Mật khẩu xác nhận không đúng.', 'danger')
        logging.warning(f"Thất bại xóa toàn bộ nhật ký: Sai MK từ IP {request.remote_addr}")
        return redirect(url_for('work_log'))

    image_paths_to_delete, logs_deleted_count, files_deleted_count, files_error_count = [], 0, 0, 0
    try:
        if delete_files_flag:
            all_log_image_records = WorkLogImage.query.with_entities(WorkLogImage.image_path).all()
            image_paths_to_delete = [img.image_path for img in all_log_image_records if img.image_path]
            logging.info(f"Chuẩn bị xóa {len(image_paths_to_delete)} file ảnh nhật ký.")
        logs_deleted_count = WorkLog.query.delete(synchronize_session=False)
        logging.info(f"Gửi lệnh xóa {logs_deleted_count} bản ghi WorkLog (cascade xử lý WorkLogImages DB).")
        if delete_files_flag and image_paths_to_delete:
            upload_folder_abs = current_app.config['UPLOAD_FOLDER_ABSOLUTE']
            files_deleted_count, files_error_count = delete_physical_files(image_paths_to_delete, upload_folder_abs)
            if files_error_count > 0: flash(f"Lỗi xóa {files_error_count} file ảnh nhật ký.", "warning")
        db.session.commit()
        flash_message = f"Đã xóa {logs_deleted_count} bản ghi nhật ký công việc."
        if delete_files_flag:
            flash_message += f" Đã xóa {files_deleted_count}/{len(image_paths_to_delete)} file ảnh liên quan."
            if files_error_count > 0: flash_message += f" ({files_error_count} lỗi)"
        else: flash_message += " Các file ảnh vật lý được giữ lại."
        flash(flash_message, 'success')
        log_details = f"DELETED ALL WORK LOGS ({logs_deleted_count}). Physical files delete: {delete_files_flag}."
        if delete_files_flag: log_details += f" Files deleted: {files_deleted_count}/{len(image_paths_to_delete)}."
        log_audit_action('delete_all_work_logs', 'work_logs', None, log_details)
        logging.info(f"Xóa toàn bộ nhật ký thành công bởi IP {request.remote_addr}. Logs: {logs_deleted_count}. Delete files: {delete_files_flag}. Files deleted: {files_deleted_count}/{len(image_paths_to_delete)}")
    except Exception as e:
        db.session.rollback(); logging.error(f"Lỗi xóa toàn bộ nhật ký: {e}", exc_info=True)
        flash(f'Lỗi CSDL khi xóa toàn bộ nhật ký: {e}', 'danger')
    return redirect(url_for('work_log'))



# === LỆNH COMMAND LINE INTERFACE (CLI) ===
@app.cli.command("create-user")
@click.argument("username")
@click.password_option() # Tự động yêu cầu nhập password ẩn
@click.option('--role', default='basic_user', help="Vai trò của người dùng (ví dụ: admin, stock_user, basic_user). Mặc định: basic_user") # <<< THÊM OPTION ROLE
def create_user(username, password, role): # <<< THÊM THAM SỐ role
    """Tạo một người dùng mới trong database với vai trò được chỉ định."""
    if User.query.filter_by(username=username).first():
        click.echo(f"Lỗi: Username '{username}' đã tồn tại.")
        return

    # <<< KIỂM TRA ROLE HỢP LỆ (Tùy chọn) >>>
    # Thêm các role hợp lệ vào đây nếu muốn giới hạn
    allowed_roles = ['admin', 'stock_user', 'basic_user', 'card_user', 'device_log_user']
    if role not in allowed_roles:
         click.echo(f"Lỗi: Vai trò '{role}' không hợp lệ. Các vai trò được phép: {', '.join(allowed_roles)}")
         return

    # <<< CẬP NHẬT: Thêm role khi tạo User >>>
    new_user = User(username=username, role=role)
    new_user.set_password(password)
    try:
        db.session.add(new_user)
        db.session.commit()
        # <<< CẬP NHẬT: Thông báo có kèm role >>>
        click.echo(f"Đã tạo người dùng '{username}' với vai trò '{role}' thành công.")
    except Exception as e:
        db.session.rollback()
        click.echo(f"Lỗi khi tạo người dùng: {e}")
        logging.error(f"Lỗi CLI create-user: {e}", exc_info=True)
# === THÊM LỆNH CLI MỚI ĐỂ KIỂM TRA ===
@app.cli.command("list-users")
def list_users():
    """Liệt kê tất cả người dùng trong database."""
    import click
    from models import User
    try:
        users = User.query.all()
        if not users:
            click.echo("Không có người dùng nào trong database.")
            return
        
        click.echo(f"{'ID':<5} {'Username':<25} {'Role':<25}")
        click.echo("-" * 60)
        for user in users:
            click.echo(f"{user.id:<5} {user.username:<25} {user.role:<25}")
            
    except Exception as e:
        click.echo(f"Lỗi khi lấy danh sách người dùng: {e}")
# === KẾT THÚC LỆNH CLI MỚI ===

# === KẾT THÚC LỆNH CLI ===


# === THÊM LỆNH MỚI ĐỂ ĐẶT LẠI MẬT KHẨU ===
@app.cli.command("set-password")
@click.argument("username")
@click.password_option()
def set_password(username, password):
    """Cập nhật mật khẩu cho một người dùng đã tồn tại."""
    user = User.query.filter_by(username=username).first()
    if not user:
        click.echo(f"Lỗi: Không tìm thấy người dùng '{username}'.")
        return

    # Cập nhật mật khẩu cho người dùng tìm thấy
    user.set_password(password)
    try:
        db.session.add(user) # Cần add lại để SQLAlchemy theo dõi thay đổi
        db.session.commit()
        click.echo(f"Đã cập nhật mật khẩu cho người dùng '{username}' thành công.")
    except Exception as e:
        db.session.rollback()
        click.echo(f"Lỗi khi cập nhật mật khẩu: {e}")
        logging.error(f"Lỗi CLI set-password cho user '{username}': {e}", exc_info=True)
# --- THÊM MỚI: Lệnh đặt vai trò cho người dùng ---
@app.cli.command("set-role")
@click.argument("username")
@click.argument("role")
def set_role(username, role):
    """Cập nhật vai trò cho một người dùng đã tồn tại."""
    user = User.query.filter_by(username=username).first()
    if not user:
        click.echo(f"Lỗi: Không tìm thấy người dùng '{username}'.")
        return

    # Kiểm tra role hợp lệ (tương tự create-user)
    allowed_roles = ['admin', 'stock_user', 'basic_user','card_user','device_log_user']
    if role not in allowed_roles:
         click.echo(f"Lỗi: Vai trò '{role}' không hợp lệ. Các vai trò được phép: {', '.join(allowed_roles)}")
         return

    # Cập nhật role
    user.role = role
    try:
        db.session.add(user) # Cần add lại để SQLAlchemy theo dõi thay đổi
        db.session.commit()
        click.echo(f"Đã cập nhật vai trò cho người dùng '{username}' thành '{role}'.")
    except Exception as e:
        db.session.rollback()
        click.echo(f"Lỗi khi cập nhật vai trò: {e}")
        logging.error(f"Lỗi CLI set-role cho user '{username}': {e}", exc_info=True)
# === KẾT THÚC LỆNH MỚI ===



# --- Trình xử lý lỗi chung ---
@app.errorhandler(Exception)
def handle_exception(e):
    logging.error(f"Unhandled Exception: {str(e)}", exc_info=True)
    try: db.session.rollback(); logging.info("Rolled back DB session.")
    except Exception as db_err: logging.error(f"Error during rollback: {db_err}")
    from werkzeug.exceptions import HTTPException
    error_message, status_code = "Lỗi không mong muốn phía máy chủ.", 500
    if isinstance(e, HTTPException):
        error_message = f"Lỗi {e.code}: {e.name}. {getattr(e, 'description', '')}"
        status_code = e.code
    if status_code == 404: error_message = f"Lỗi 404: Không tìm thấy trang ({request.path})."
    elif status_code == 405: error_message = f"Lỗi 405: Phương thức {request.method} không được phép."
    elif status_code == 500: error_message = "Lỗi 500: Lỗi xử lý máy chủ. Thử lại sau."
    return f"<h1>Lỗi {status_code}</h1><p>{error_message}</p><p><a href='{url_for('index')}'>Quay lại trang chủ</a></p>", status_code

# === HÀM HELPER TÍNH XIRR (MDRR) - REFINED ===
def calculate_xirr_performance(nav_start_value, nav_end_value, cash_flows_list, nav_start_date, nav_end_date):
    """
    Tính toán hiệu suất danh mục, ưu tiên XIRR, sau đó là Modified Dietz, cuối cùng là CAGR.
    Trả về một tuple: (period_rate, annualized_rate) dưới dạng Decimal.
    """
    # Helper function for logging percentages
    def format_rate_for_log(rate_value, default_str='N/A'):
        if isinstance(rate_value, Decimal):
            try:
                return f"{float(rate_value):.4%}"
            except (TypeError, ValueError):
                return str(rate_value)
        elif rate_value is None:
            return default_str
        return str(rate_value)

    logging.info(f"--- calculate_xirr_performance CALLED ---")
    logging.info(f"Inputs: NAV_start={nav_start_value}, NAV_end={nav_end_value}, StartDate={nav_start_date}, EndDate={nav_end_date}")
    logging.debug(f"CashFlows List (raw): {cash_flows_list}")

    if nav_start_value is None or nav_end_value is None or nav_start_date is None or nav_end_date is None:
        logging.warning("calculate_xirr_performance: Thiếu NAV hoặc ngày đầu vào.")
        return None, None
    if not isinstance(nav_start_date, date) or not isinstance(nav_end_date, date):
        logging.warning(f"calculate_xirr_performance: Ngày bắt đầu ({type(nav_start_date)}) hoặc kết thúc ({type(nav_end_date)}) không phải là đối tượng date hợp lệ.")
        return None, None
    if nav_start_date > nav_end_date:
        logging.warning("calculate_xirr_performance: Ngày bắt đầu không thể sau ngày kết thúc.")
        return None, None

    try:
        nav_start_value_dec = Decimal(str(nav_start_value))
        nav_end_value_dec = Decimal(str(nav_end_value))
        logging.info(f"Converted NAVs: NAV_start_dec={nav_start_value_dec}, NAV_end_dec={nav_end_value_dec}")
    except InvalidOperation:
        logging.warning("calculate_xirr_performance: Giá trị NAV không hợp lệ khi chuyển sang Decimal.")
        return None, None

    processed_cash_flows = []
    for cf_idx, cf in enumerate(cash_flows_list):
        try:
            cf_date_original = cf.get('date')
            cf_amount_original = cf.get('amount')
            cf_date = cf_date_original
            if isinstance(cf_date, datetime):
                cf_date = cf_date.date()
            elif not isinstance(cf_date, date):
                cf_date = datetime.strptime(str(cf_date), '%Y-%m-%d').date()
            
            processed_cash_flows.append({
                'date': cf_date,
                'amount': Decimal(str(cf_amount_original))
            })
            logging.debug(f"Processed CF {cf_idx}: Date={cf_date}, Amount={processed_cash_flows[-1]['amount']}")
        except (TypeError, ValueError, InvalidOperation, AttributeError) as e_cf:
            logging.warning(f"calculate_xirr_performance: Dòng tiền không hợp lệ {cf}. Lỗi: {e_cf}. Bỏ qua dòng tiền này.")
            continue
    logging.info(f"Total Processed Cash Flows: {len(processed_cash_flows)}")


    # === 1. Thử tính XIRR ===
    if xirr_function_to_use is not None:
        logging.info("Attempting XIRR calculation...")
        xirr_values = [-nav_start_value_dec]
        xirr_dates = [nav_start_date]
        for cf in processed_cash_flows:
            if nav_start_date < cf['date'] <= nav_end_date:
                xirr_values.append(-cf['amount']) # Nộp tiền (dương trong CF list) -> âm cho XIRR
                xirr_dates.append(cf['date'])
        xirr_values.append(nav_end_value_dec)
        xirr_dates.append(nav_end_date)
        logging.debug(f"XIRR Inputs: Values={xirr_values}, Dates={xirr_dates}")

        if len(xirr_values) >= 2:
            has_positive = any(v > Decimal('1e-9') for v in xirr_values)
            has_negative = any(v < Decimal('-1e-9') for v in xirr_values)
            if has_positive and has_negative:
                try:
                    xirr_values_float = [float(v) for v in xirr_values]
                    rate_xirr = xirr_function_to_use(xirr_values_float, xirr_dates)
                    if rate_xirr is not None and isinstance(rate_xirr, (float, int)) and not (math.isnan(rate_xirr) or math.isinf(rate_xirr)):
                        xirr_decimal_rate = Decimal(str(rate_xirr))
                        logging.info(f"XIRR calculation successful (using {'numpy_financial' if numpy_financial_xirr_imported else ('pyxirr' if pyxirr_imported else 'unknown_lib')}): {format_rate_for_log(xirr_decimal_rate)}")
                        return xirr_decimal_rate, xirr_decimal_rate
                    else:
                        logging.warning(f"XIRR function returned invalid value: {rate_xirr}.")
                except Exception as e_xirr:
                    logging.error(f"Error during XIRR calculation (using {'numpy_financial' if numpy_financial_xirr_imported else ('pyxirr' if pyxirr_imported else 'unknown_lib')}): {e_xirr}", exc_info=True)
            else:
                logging.warning("XIRR calculation skipped: Values do not have both positive and negative numbers, or not enough cash flows in the period.")
        else:
            logging.warning("XIRR calculation skipped: Not enough data points.")
    else:
        logging.info("XIRR function (xirr_function_to_use) is not available. Proceeding to Modified Dietz.")

    # === 2. Thử tính Modified Dietz (Nếu XIRR thất bại) ===
    logging.info("Attempting Modified Dietz calculation...")
    period_return_md_final = None
    annualized_return_md_final = None
    try:
        if nav_end_date == nav_start_date:
            logging.info("Modified Dietz: 0-day period.")
            if nav_start_value_dec != Decimal('0.0'):
                # For a 0-day period, return is (End - Start - NCF_on_day) / Start
                # NCF_on_day are cash flows that happened ON the start_date
                ncf_on_start_date = sum(cf['amount'] for cf in processed_cash_flows if cf['date'] == nav_start_date)
                logging.info(f"Modified Dietz (0-day): NCF on start date = {ncf_on_start_date}")
                numerator_0day = nav_end_value_dec - nav_start_value_dec - ncf_on_start_date
                if nav_start_value_dec != Decimal('0.0'): # Denominator is just nav_start
                    period_return_md_final = numerator_0day / nav_start_value_dec
                else: # nav_start_value_dec is zero
                    period_return_md_final = Decimal('0.0') if numerator_0day == Decimal('0.0') else None # Avoid 0/0 or X/0

                logging.info(f"Modified Dietz (0-day period): Period Rate={format_rate_for_log(period_return_md_final)}")
                if period_return_md_final is not None:
                    return period_return_md_final, None # No annualization for 0-day
                # else fall through
            else:
                 logging.warning("Modified Dietz (0-day period): NAV start is zero, cannot calculate rate.")
        else: # Period > 0 days
            total_days_in_period = (nav_end_date - nav_start_date).days
            logging.info(f"Modified Dietz: Total days in period = {total_days_in_period}")
            if total_days_in_period <= 0:
                 raise ValueError("Số ngày trong kỳ phải lớn hơn 0 cho Modified Dietz.")

            # NetCashFlow (NCF): Sum of all cash flows CF_i during the period.
            # Cash flows are positive for inflows (deposits), negative for outflows (withdrawals).
            net_cash_flow = sum(cf['amount'] for cf in processed_cash_flows if nav_start_date < cf['date'] <= nav_end_date)
            logging.info(f"Modified Dietz: Net Cash Flow (NCF) in period = {net_cash_flow}")

            # Sum of Weighted Cash Flows: SUM (CF_i * W_i)
            # W_i = (CD - D_i) / CD
            # CD = Calendar days in period (total_days_in_period)
            # D_i = Calendar days from beginning of period to cash flow CF_i
            sum_weighted_cash_flows = Decimal('0.0')
            for cf in processed_cash_flows:
                if nav_start_date < cf['date'] <= nav_end_date: # CF must be within the period
                    days_from_start_to_cf = (cf['date'] - nav_start_date).days
                    # Weight: (Total Days - Days from start to CF) / Total Days
                    # This weight represents the proportion of the period the cash flow was NOT present
                    # For the Modified Dietz denominator, we need the proportion of time it WAS present.
                    # Or, simpler: W_i = (CD - D_i) / CD is correct for the formula: Denominator = BMV + SUM(CF_i * W_i)
                    # where W_i is the weight for the average capital contribution.
                    # Let's use the standard formula for denominator: NAV_start + SUM( CF_i * ( (CD - D_i_cf) / CD ) )
                    # CD = total_days_in_period
                    # D_i_cf = number of days from start of period until CF_i occurs.
                    if total_days_in_period > 0: # Ensure not dividing by zero
                         weight_cf = Decimal(str(total_days_in_period - days_from_start_to_cf)) / Decimal(str(total_days_in_period))
                         sum_weighted_cash_flows += cf['amount'] * weight_cf
                         logging.debug(f"Modified Dietz CF: Date={cf['date']}, Amount={cf['amount']}, DaysFromStart={days_from_start_to_cf}, Weight={weight_cf:.4f}, WeightedAmt={cf['amount'] * weight_cf}")
            
            logging.info(f"Modified Dietz: Sum of Weighted Cash Flows = {sum_weighted_cash_flows}")
            
            # Denominator = Beginning Market Value (BMV) + Sum of Weighted Cash Flows
            denominator_md = nav_start_value_dec + sum_weighted_cash_flows
            logging.info(f"Modified Dietz: Denominator (NAV_start + SumWeightedCF) = {denominator_md}")

            if denominator_md == Decimal('0.0'):
                logging.warning("Modified Dietz calculation: Denominator is zero. Cannot calculate rate.")
            else:
                # Numerator = Ending Market Value (EMV) - Beginning Market Value (BMV) - Net Cash Flow (NCF)
                numerator_md = nav_end_value_dec - nav_start_value_dec - net_cash_flow
                logging.info(f"Modified Dietz: Numerator (NAV_end - NAV_start - NCF) = {numerator_md}")
                period_return_md_final = numerator_md / denominator_md

                if total_days_in_period > 0:
                    annualization_factor = Decimal('365.0') / Decimal(str(total_days_in_period))
                    base_for_annualization = Decimal('1.0') + period_return_md_final
                    if base_for_annualization < Decimal('0.0') and annualization_factor % Decimal('1.0') != Decimal('0.0'):
                         logging.warning(f"Modified Dietz: Cannot annualize with negative base ({base_for_annualization}) and non-integer exponent ({annualization_factor}).")
                         annualized_return_md_final = None
                    else:
                        try:
                            annualized_return_md_final = (base_for_annualization ** annualization_factor) - Decimal('1.0')
                        except InvalidOperation as e_annual_md:
                            logging.error(f"Modified Dietz: Error during annualization {e_annual_md}. Base: {base_for_annualization}, Factor: {annualization_factor}")
                            annualized_return_md_final = None
                else: # Should not happen due to earlier check, but for safety
                    annualized_return_md_final = None
                
                logging.info(f"Modified Dietz calculation successful: Period Rate={format_rate_for_log(period_return_md_final)}, Annualized Rate={format_rate_for_log(annualized_return_md_final)}")
                return period_return_md_final, annualized_return_md_final

    except ValueError as e_val:
        logging.error(f"Modified Dietz calculation error: {e_val}", exc_info=True)
    except InvalidOperation as e_decimal:
        logging.error(f"Modified Dietz calculation error (Decimal InvalidOperation): {e_decimal}", exc_info=True)
    except ZeroDivisionError:
        logging.error("Modified Dietz calculation error: Division by zero.", exc_info=True)
    except Exception as e_md:
        logging.error(f"Unexpected error during Modified Dietz calculation: {e_md}", exc_info=True)

    # === 3. Fallback: CAGR ===
    logging.info("Falling back to CAGR calculation.")
    cagr_period_return_final = None
    annualized_cagr_result_final = None
    try:
        num_days_cagr = (nav_end_date - nav_start_date).days
        if num_days_cagr == 0:
            if nav_start_value_dec != Decimal('0.0'):
                if not any(cf['date'] == nav_start_date for cf in processed_cash_flows): # Only if no CF on the same day
                    cagr_period_return_final = (nav_end_value_dec / nav_start_value_dec) - Decimal('1.0')
            # annualized_cagr_result_final remains None
        elif num_days_cagr > 0:
            if nav_start_value_dec > Decimal('0.0'):
                years_cagr = Decimal(str(num_days_cagr)) / Decimal('365.0')
                # For CAGR, we should ideally adjust NAV_end for cash flows if we want a "truer" asset return
                # However, a simple CAGR doesn't typically do this. It just looks at start and end NAV.
                # If NAV_end already includes the cash flow (e.g. user updated NAV after deposit), then simple CAGR is fine.
                # If NAV_end does NOT include the cash flow, simple CAGR will be skewed.
                # The problem description implies NAV_end might NOT have the 100M deposit yet.
                # Let's calculate simple CAGR based on provided NAVs first.
                nav_end_for_cagr = nav_end_value_dec # Use the NAV_end as provided
                # If you wanted to "remove" cash flow impact for a simple CAGR:
                # ncf_for_cagr_period = sum(cf['amount'] for cf in processed_cash_flows if nav_start_date < cf['date'] <= nav_end_date)
                # nav_end_adjusted_for_cagr = nav_end_value_dec - ncf_for_cagr_period
                # ratio_cagr = nav_end_adjusted_for_cagr / nav_start_value_dec
                # This is a simplification and not a standard TWRR.

                ratio_cagr = nav_end_for_cagr / nav_start_value_dec
                logging.info(f"CAGR: Ratio (NAV_end / NAV_start) = {ratio_cagr}")

                if ratio_cagr >= Decimal('0.0'):
                    try:
                        if ratio_cagr < Decimal('0.0') and (Decimal('1.0') / years_cagr % Decimal('1.0') != Decimal('0.0')):
                             annualized_cagr_result_final = None
                        else:
                            annualized_cagr_result_final = (ratio_cagr ** (Decimal('1.0') / years_cagr)) - Decimal('1.0')

                        if annualized_cagr_result_final is not None:
                            base_for_period_cagr = Decimal('1.0') + annualized_cagr_result_final
                            if base_for_period_cagr < Decimal('0.0') and years_cagr % Decimal('1.0') != Decimal('0.0'):
                                 cagr_period_return_final = None
                            else:
                                cagr_period_return_final = (base_for_period_cagr ** years_cagr) - Decimal('1.0')
                    except (OverflowError, InvalidOperation) as e_cagr_math:
                        logging.error(f"Lỗi tính toán CAGR (Overflow/InvalidOp): {e_cagr_math}. Ratio: {ratio_cagr}, Years: {years_cagr}")
                else: # ratio_cagr < 0
                    logging.warning("Cannot calculate CAGR: NAV start/end ratio is negative.")
    except Exception as e_cagr:
        logging.error(f"Error during CAGR calculation: {e_cagr}", exc_info=True)

    if cagr_period_return_final is not None:
        logging.info(f"CAGR calculation result: Period Rate={format_rate_for_log(cagr_period_return_final)}, Annualized Rate={format_rate_for_log(annualized_cagr_result_final)}")
        return cagr_period_return_final, annualized_cagr_result_final
    else:
        logging.warning("All calculation methods (XIRR, Modified Dietz, CAGR) failed or returned no result.")
        return None, None
# === KẾT THÚC HÀM HELPER XIRR (REFINED) ===


# === ROUTE HIỂN THỊ DANH SÁCH GIAO DỊCH CHỨNG KHOÁN (CẬP NHẬT BIỂU ĐỒ P&L) ===
@app.route('/stock', methods=['GET'])
@login_required
@role_required(['admin', 'stock_user'])
def stock_journal():
    """
    Hiển thị trang nhật ký giao dịch chứng khoán với các tính năng:
    - Lọc giao dịch theo mã, trạng thái, ngày.
    - Phân trang kết quả.
    - Hiển thị Lãi/Lỗ (tạm tính/đã thực hiện) cho từng giao dịch mua.
    - Tính toán và hiển thị hiệu suất chi tiết cho các mã đang MỞ (phần "Chi tiết Hiệu suất Từng Mã").
    - Hiển thị biểu đồ:
        - Phân bổ danh mục (theo giá trị thị trường các mã đang mở).
        - Tương quan NAV - VNI (% thay đổi so với ngày đầu của KỲ ĐƯỢC CHỌN).
        - So sánh Tổng Lãi/Lỗ của các mã ĐANG MỞ. <-- ĐÃ CẬP NHẬT
    - Tính toán MDRR (XIRR).
    - Lọc biểu đồ NAV/VNI theo khoảng thời gian.
    """
    try:
        # === 1. Xử lý Phân trang và Lọc Giao Dịch ===
        page = request.args.get('page', 1, type=int)
        filter_symbol_input = request.args.get('filter_symbol', '').strip().upper()
        filter_status_input = request.args.get('filter_status', '').strip().upper()
        filter_trans_start_date_str = request.args.get('filter_trans_start_date', '').strip()
        filter_trans_end_date_str = request.args.get('filter_trans_end_date', '').strip()

        filter_trans_start_date_db = format_date_for_storage(filter_trans_start_date_str)
        filter_trans_end_date_db = format_date_for_storage(filter_trans_end_date_str)

        if filter_trans_start_date_db and filter_trans_end_date_db and filter_trans_start_date_db > filter_trans_end_date_db:
            flash("Ngày bắt đầu lọc giao dịch không thể sau ngày kết thúc.", "warning")
            filter_trans_start_date_db, filter_trans_end_date_db = None, None
            filter_trans_start_date_str, filter_trans_end_date_str = '', ''

        transactions_query = StockTransaction.query.filter_by(user_id=current_user.id)
        if filter_symbol_input:
            symbols_to_filter = [s.strip() for s in filter_symbol_input.split(',') if s.strip()]
            if symbols_to_filter:
                transactions_query = transactions_query.filter(StockTransaction.symbol.in_(symbols_to_filter))
        if filter_status_input:
            transactions_query = transactions_query.filter(StockTransaction.status == filter_status_input)
        if filter_trans_start_date_db:
            transactions_query = transactions_query.filter(StockTransaction.transaction_date >= filter_trans_start_date_db)
        if filter_trans_end_date_db:
            transactions_query = transactions_query.filter(StockTransaction.transaction_date <= filter_trans_end_date_db)

        transactions_query = transactions_query.order_by(desc(StockTransaction.transaction_date), desc(StockTransaction.id))
        pagination = transactions_query.paginate(
            page=page,
            per_page=app.config.get('STOCK_TRANSACTIONS_PER_PAGE', 10),
            error_out=False
        )
        transactions_to_display = pagination.items

        all_user_transactions = StockTransaction.query.filter_by(user_id=current_user.id).all()

        # === 2. Xử lý Ngày cho Tính Toán MDRR ===
        mdrr_start_date_str_input = request.args.get('mdrr_start_select', '').strip()
        mdrr_end_date_str_input = request.args.get('mdrr_end_select', '').strip()
        mdrr_start_date_for_calc = format_date_for_storage(mdrr_start_date_str_input)
        mdrr_end_date_for_calc = format_date_for_storage(mdrr_end_date_str_input)
        mdrr_start_date_for_form = mdrr_start_date_str_input
        mdrr_end_date_for_form = mdrr_end_date_str_input

        if not mdrr_start_date_for_calc and not mdrr_end_date_for_calc:
            min_nav_date_result = db.session.query(func.min(PerformanceData.date)).filter(PerformanceData.user_id == current_user.id, PerformanceData.nav_value.isnot(None)).scalar()
            max_nav_date_result = db.session.query(func.max(PerformanceData.date)).filter(PerformanceData.user_id == current_user.id, PerformanceData.nav_value.isnot(None)).scalar()
            if min_nav_date_result and max_nav_date_result:
                mdrr_start_date_for_calc = min_nav_date_result
                mdrr_end_date_for_calc = max_nav_date_result
                mdrr_start_date_for_form = mdrr_start_date_for_calc.strftime('%Y-%m-%d')
                mdrr_end_date_for_form = mdrr_end_date_for_calc.strftime('%Y-%m-%d')
        if mdrr_start_date_for_calc and mdrr_end_date_for_calc and mdrr_start_date_for_calc > mdrr_end_date_for_calc:
            flash("Ngày bắt đầu tính MDRR không thể sau ngày kết thúc.", "warning")
            mdrr_start_date_for_calc, mdrr_end_date_for_calc = None, None
            mdrr_start_date_for_form, mdrr_end_date_for_form = '', ''

        # === 3. Lấy Giá Thị trường ===
        market_prices = {}
        try:
            all_user_symbols_ever = [item[0] for item in db.session.query(StockTransaction.symbol).filter_by(user_id=current_user.id).distinct().all() if item[0]]
            if all_user_symbols_ever:
                market_prices = get_fireant_last_prices(all_user_symbols_ever)
        except Exception as e_api:
            logging.error(f"Lỗi gọi API FireAnt trong stock_journal: {e_api}", exc_info=True)
            flash("Không thể tải dữ liệu giá thị trường hiện tại.", "warning")

        # === 4. Tính toán Lãi/Lỗ cho Từng Giao dịch Hiển thị trên Bảng ===
        for trans in transactions_to_display:
            trans.calculated_pl = None
            trans.calculated_pl_percent = None
            if trans.transaction_type == 'BUY':
                try:
                    if trans.quantity is not None and trans.price is not None:
                        buy_order_value = trans.quantity * trans.price
                        buy_fee = buy_order_value * BUY_FEE_RATE
                        total_buy_cost = buy_order_value + buy_fee
                        if trans.status == 'OPENED':
                            market_price = market_prices.get(trans.symbol)
                            if market_price is not None:
                                current_market_value = trans.quantity * market_price
                                unrealized_pl = current_market_value - total_buy_cost
                                trans.calculated_pl = unrealized_pl
                                if total_buy_cost != 0:
                                    trans.calculated_pl_percent = (unrealized_pl / total_buy_cost) * 100
                            else:
                                trans.calculated_pl = "Chưa có giá TT"
                        elif trans.status == 'CLOSED':
                            if trans.sell_price is not None and trans.sell_date is not None:
                                sell_order_value = trans.quantity * trans.sell_price
                                sell_fee = sell_order_value * SELL_FEE_RATE
                                realized_pl = sell_order_value - sell_fee - total_buy_cost
                                trans.calculated_pl = realized_pl
                                if total_buy_cost != 0:
                                    trans.calculated_pl_percent = (realized_pl / total_buy_cost) * 100
                            else:
                                trans.calculated_pl = "Thiếu TT bán"
                    else:
                        trans.calculated_pl = "Thiếu SL/Giá"
                except Exception as e_pl:
                    logging.error(f"Lỗi tính P&L cho giao dịch ID {trans.id}: {e_pl}", exc_info=True)
                    trans.calculated_pl = "Lỗi tính toán"

        # === 5. Tính toán Hiệu suất theo Mã ===
        # --- 5.a (Không thay đổi) Cho BIỂU ĐỒ SO SÁNH P&L (Mã đã lọc) - SẼ ĐƯỢC THAY THẾ BỞI DỮ LIỆU MÃ ĐANG MỞ ---
        # performance_data_for_filtered_symbols = {} # Sẽ không dùng biến này cho biểu đồ P&L nữa
        # all_transactions_in_current_filter = transactions_query.all()
        # symbols_from_filtered_transactions = sorted(list(set(t.symbol for t in all_transactions_in_current_filter if t.symbol)))
        # if symbols_from_filtered_transactions:
        #     try:
        #         performance_data_for_filtered_symbols = calculate_performance_for_listed_symbols(
        #             symbols_to_analyze=symbols_from_filtered_transactions,
        #             all_user_stock_transactions=all_user_transactions,
        #             current_market_prices=market_prices
        #         )
        #     except Exception as e_perf_calc_filtered:
        #         logging.error(f"Lỗi khi gọi calculate_performance_for_listed_symbols (cho mã đã lọc): {e_perf_calc_filtered}", exc_info=True)
        #         flash("Lỗi khi tính toán hiệu suất cho các mã đã lọc (biểu đồ).", "danger")

        # --- 5.b Cho PHẦN "CHI TIẾT HIỆU SUẤT TỪNG MÃ" VÀ BIỂU ĐỒ "SO SÁNH P&L MÃ ĐANG MỞ" ---
        performance_data_for_opened_positions_section = {}
        symbols_with_opened_buy_positions_query = db.session.query(StockTransaction.symbol).filter(
            StockTransaction.user_id == current_user.id,
            StockTransaction.transaction_type == 'BUY',
            StockTransaction.status == 'OPENED',
            StockTransaction.symbol.isnot(None)
        ).distinct()
        symbols_for_opened_positions_analysis = sorted([item[0] for item in symbols_with_opened_buy_positions_query.all()])

        if symbols_for_opened_positions_analysis:
            try:
                performance_data_for_opened_positions_section = calculate_performance_for_listed_symbols(
                    symbols_to_analyze=symbols_for_opened_positions_analysis, # Chỉ các mã đang mở
                    all_user_stock_transactions=all_user_transactions,
                    current_market_prices=market_prices
                )
            except Exception as e_perf_calc_opened:
                logging.error(f"Lỗi khi tính toán hiệu suất cho các mã đang mở: {e_perf_calc_opened}", exc_info=True)
                flash("Lỗi khi tính toán hiệu suất chi tiết cho các mã đang mở.", "danger")

        # === 6. Chuẩn bị dữ liệu cho Biểu đồ ===
        charts_data = {
            'nav_vni_labels': [], 'nav_values': [], 'vnindex_values': [],
            'comparison_pl_labels': [], 'comparison_pl_data': [], # Sẽ được điền từ mã đang mở
            'allocation_labels': [], 'allocation_values': []
        }

        # --- 6.1 Lấy và LỌC dữ liệu NAV/VNI lịch sử THEO KHOẢNG THỜI GIAN ĐƯỢC CHỌN ---
        selected_nav_vni_period = request.args.get('nav_vni_period', 'all').strip().lower()
        nav_vni_start_date_filter = None
        all_performance_history_db = PerformanceData.query.filter(
            PerformanceData.user_id == current_user.id
        ).order_by(PerformanceData.date.asc()).all()

        performance_history_filtered = []
        if all_performance_history_db:
            latest_date_in_history = all_performance_history_db[-1].date
            if selected_nav_vni_period == '1w': nav_vni_start_date_filter = latest_date_in_history - timedelta(weeks=1)
            elif selected_nav_vni_period == '1m': nav_vni_start_date_filter = latest_date_in_history - relativedelta(months=1)
            elif selected_nav_vni_period == '3m': nav_vni_start_date_filter = latest_date_in_history - relativedelta(months=3)
            elif selected_nav_vni_period == '6m': nav_vni_start_date_filter = latest_date_in_history - relativedelta(months=6)
            elif selected_nav_vni_period == '1y': nav_vni_start_date_filter = latest_date_in_history - relativedelta(years=1)

            if nav_vni_start_date_filter:
                first_entry_after_start = next((entry for entry in all_performance_history_db if entry.date >= nav_vni_start_date_filter), None)
                if first_entry_after_start:
                     performance_history_filtered = [entry for entry in all_performance_history_db if entry.date >= first_entry_after_start.date]
                else: performance_history_filtered = []
            else: performance_history_filtered = all_performance_history_db
        else: performance_history_filtered = []

        # --- 6.2 Tính toán % thay đổi cho NAV và VNI (DỰA TRÊN DỮ LIỆU ĐÃ LỌC) ---
        baseline_nav_value, baseline_vnindex_value = None, None
        first_valid_entry_index_filtered = -1
        for i, entry in enumerate(performance_history_filtered):
            if entry.nav_value is not None or entry.vnindex_value is not None:
                first_valid_entry_index_filtered = i
                baseline_nav_value = entry.nav_value if entry.nav_value is not None else None
                baseline_vnindex_value = entry.vnindex_value if entry.vnindex_value is not None else None
                break
        if first_valid_entry_index_filtered != -1:
            for i in range(first_valid_entry_index_filtered, len(performance_history_filtered)):
                current_entry = performance_history_filtered[i]
                charts_data['nav_vni_labels'].append(current_entry.date.strftime('%d/%m/%Y'))
                nav_change_pct, vni_change_pct = None, None
                if current_entry.nav_value is not None and baseline_nav_value is not None and baseline_nav_value != 0:
                    try: nav_change_pct = float(((Decimal(str(current_entry.nav_value)) / Decimal(str(baseline_nav_value))) - 1) * 100) # Ensure Decimal conversion
                    except: nav_change_pct = None
                elif i == first_valid_entry_index_filtered and current_entry.nav_value is not None: nav_change_pct = 0.0
                charts_data['nav_values'].append(nav_change_pct)

                if current_entry.vnindex_value is not None and baseline_vnindex_value is not None and baseline_vnindex_value != 0:
                    try: vni_change_pct = float(((Decimal(str(current_entry.vnindex_value)) / Decimal(str(baseline_vnindex_value))) - 1) * 100) # Ensure Decimal conversion
                    except: vni_change_pct = None
                elif i == first_valid_entry_index_filtered and current_entry.vnindex_value is not None: vni_change_pct = 0.0
                charts_data['vnindex_values'].append(vni_change_pct)

                if baseline_nav_value is None and current_entry.nav_value is not None: baseline_nav_value = current_entry.nav_value; charts_data['nav_values'][-1] = 0.0
                if baseline_vnindex_value is None and current_entry.vnindex_value is not None: baseline_vnindex_value = current_entry.vnindex_value; charts_data['vnindex_values'][-1] = 0.0

        # --- 6.3 Chuẩn bị dữ liệu So sánh P&L Mã (SỬ DỤNG DỮ LIỆU CÁC MÃ ĐANG MỞ) ---
        if performance_data_for_opened_positions_section: # Sử dụng dữ liệu từ các mã đang MỞ
            sorted_perf_items_opened = sorted(
                performance_data_for_opened_positions_section.items(),
                key=lambda item: item[1].get('total_pl', Decimal('-Infinity')),
                reverse=True
            )
            for symbol, data in sorted_perf_items_opened:
                if data.get('status_message') == 'OK':
                    charts_data['comparison_pl_labels'].append(symbol)
                    charts_data['comparison_pl_data'].append(float(data.get('total_pl', 0)))

        # --- 6.4 Chuẩn bị dữ liệu Phân bổ Danh mục (Chỉ các mã đang MỞ) ---
        opened_buy_transactions_for_alloc = [t for t in all_user_transactions if t.user_id == current_user.id and t.transaction_type == 'BUY' and t.status == 'OPENED']
        allocation_data_map = {}
        for trans_alloc in opened_buy_transactions_for_alloc:
            if trans_alloc.quantity is not None and trans_alloc.symbol:
                asset_price = market_prices.get(trans_alloc.symbol)
                if asset_price is not None:
                    try:
                        market_value_holding = trans_alloc.quantity * asset_price
                        allocation_data_map[trans_alloc.symbol] = allocation_data_map.get(trans_alloc.symbol, Decimal('0.0')) + market_value_holding
                    except (InvalidOperation, TypeError) as e_alloc:
                         logging.warning(f"Lỗi tính giá trị phân bổ cho {trans_alloc.symbol}: {e_alloc}")
        charts_data['allocation_labels'] = list(allocation_data_map.keys())
        charts_data['allocation_values'] = [float(val) for val in allocation_data_map.values()]


        # === 7. Tính toán các chỉ số tổng hợp (Tóm tắt Danh mục và MDRR/XIRR) ===
        portfolio_summary = {
            'total_market_value': Decimal('0.0'), 'total_cost_basis': Decimal('0.0'),
            'unrealized_pl': Decimal('0.0'), 'unrealized_pl_percent': Decimal('0.0'),
            'total_deposit_period': Decimal('0.0'), 'total_withdrawal_period': Decimal('0.0'),
            'mdrr': None, 'annualized_mdrr': None,
            'mdrr_start_date': mdrr_start_date_for_calc, 'mdrr_end_date': mdrr_end_date_for_calc,
            'actual_nav_start_date': None, 'actual_nav_end_date': None,
            'latest_nav_value': None, 'current_cash': None
        }
        current_total_market_value_opened = sum(
            (trans.quantity * market_prices.get(trans.symbol, Decimal('0.0')))
            for trans in opened_buy_transactions_for_alloc
            if trans.quantity is not None and trans.symbol and market_prices.get(trans.symbol) is not None
        )
        current_total_cost_basis_opened = sum(
            ((trans.quantity * trans.price) + (trans.quantity * trans.price * BUY_FEE_RATE))
            for trans in opened_buy_transactions_for_alloc
            if trans.quantity is not None and trans.price is not None
        )
        current_unrealized_pl = current_total_market_value_opened - current_total_cost_basis_opened
        current_unrealized_pl_percent = (current_unrealized_pl / current_total_cost_basis_opened * 100) if current_total_cost_basis_opened > 0 else Decimal('0.0')
        portfolio_summary.update({
            'total_market_value': current_total_market_value_opened,
            'total_cost_basis': current_total_cost_basis_opened,
            'unrealized_pl': current_unrealized_pl,
            'unrealized_pl_percent': current_unrealized_pl_percent
        })
        latest_nav_entry = PerformanceData.query.filter(PerformanceData.user_id == current_user.id, PerformanceData.nav_value.isnot(None)).order_by(PerformanceData.date.desc()).first()
        if latest_nav_entry and latest_nav_entry.nav_value is not None:
            portfolio_summary['latest_nav_value'] = latest_nav_entry.nav_value
            portfolio_summary['current_cash'] = latest_nav_entry.nav_value - current_total_cost_basis_opened

        deposits_in_filtered_period_q = StockTransaction.query.filter_by(user_id=current_user.id, transaction_type='DEPOSIT')
        withdrawals_in_filtered_period_q = StockTransaction.query.filter_by(user_id=current_user.id, transaction_type='WITHDRAWAL')
        if filter_trans_start_date_db:
            deposits_in_filtered_period_q = deposits_in_filtered_period_q.filter(StockTransaction.transaction_date >= filter_trans_start_date_db)
            withdrawals_in_filtered_period_q = withdrawals_in_filtered_period_q.filter(StockTransaction.transaction_date >= filter_trans_start_date_db)
        if filter_trans_end_date_db:
            deposits_in_filtered_period_q = deposits_in_filtered_period_q.filter(StockTransaction.transaction_date <= filter_trans_end_date_db)
            withdrawals_in_filtered_period_q = withdrawals_in_filtered_period_q.filter(StockTransaction.transaction_date <= filter_trans_end_date_db)
        portfolio_summary['total_deposit_period'] = deposits_in_filtered_period_q.with_entities(func.sum(StockTransaction.price)).scalar() or Decimal('0.0')
        portfolio_summary['total_withdrawal_period'] = withdrawals_in_filtered_period_q.with_entities(func.sum(StockTransaction.price)).scalar() or Decimal('0.0')

        if mdrr_start_date_for_calc and mdrr_end_date_for_calc:
            nav_start_entry_mdrr = PerformanceData.query.filter(PerformanceData.user_id == current_user.id, PerformanceData.date <= mdrr_start_date_for_calc, PerformanceData.nav_value.isnot(None)).order_by(PerformanceData.date.desc()).first()
            if nav_start_entry_mdrr:
                actual_nav_start_date = nav_start_entry_mdrr.date
                nav_start_val = nav_start_entry_mdrr.nav_value
                portfolio_summary['actual_nav_start_date'] = actual_nav_start_date
                nav_end_entry_mdrr = PerformanceData.query.filter(PerformanceData.user_id == current_user.id, PerformanceData.date >= actual_nav_start_date, PerformanceData.date <= mdrr_end_date_for_calc, PerformanceData.nav_value.isnot(None)).order_by(PerformanceData.date.desc()).first()
                if nav_end_entry_mdrr:
                    actual_nav_end_date = nav_end_entry_mdrr.date
                    nav_end_val = nav_end_entry_mdrr.nav_value
                    portfolio_summary['actual_nav_end_date'] = actual_nav_end_date
                    cash_flows_for_xirr_db = StockTransaction.query.filter(StockTransaction.user_id == current_user.id, StockTransaction.transaction_date > actual_nav_start_date, StockTransaction.transaction_date <= actual_nav_end_date, StockTransaction.transaction_type.in_(['DEPOSIT', 'WITHDRAWAL'])).order_by(StockTransaction.transaction_date).all()
                    cash_flows_xirr_list = [{'date': cf.transaction_date, 'amount': (cf.price if cf.transaction_type == 'DEPOSIT' else -cf.price)} for cf in cash_flows_for_xirr_db if cf.price is not None]
                    xirr_rate, annualized_xirr_rate = calculate_xirr_performance(nav_start_val, nav_end_val, cash_flows_xirr_list, actual_nav_start_date, actual_nav_end_date)
                    if xirr_rate is not None:
                        portfolio_summary['mdrr'] = xirr_rate
                        portfolio_summary['annualized_mdrr'] = annualized_xirr_rate
                    else: flash(f"Không thể tính XIRR cho kỳ từ {actual_nav_start_date.strftime('%d/%m/%Y')} đến {actual_nav_end_date.strftime('%d/%m/%Y')}.", "warning")
                else: flash(f"Không tìm thấy dữ liệu NAV cuối kỳ hợp lệ (từ {actual_nav_start_date.strftime('%d/%m/%Y')} đến {mdrr_end_date_for_calc.strftime('%d/%m/%Y')}).", "warning")
            else: flash(f"Không tìm thấy dữ liệu NAV cho ngày bắt đầu kỳ ({mdrr_start_date_for_calc.strftime('%d/%m/%Y')}).", "warning")
        elif mdrr_start_date_str_input or mdrr_end_date_str_input:
            flash("Vui lòng chọn cả ngày bắt đầu và ngày kết thúc hợp lệ để tính toán hiệu suất (MDRR/XIRR).", "info")

        # === 8. Truyền dữ liệu tới Template ===
        return render_template(
            'stock_journal.html',
            transactions=transactions_to_display,
            pagination=pagination,
            market_prices=market_prices,
            portfolio_summary=portfolio_summary,
            performance_by_symbol_data=performance_data_for_opened_positions_section, # Dữ liệu cho phần "Chi tiết Hiệu suất"
            charts_data=charts_data, # Dữ liệu cho tất cả biểu đồ
            filter_symbol=filter_symbol_input,
            filter_status=filter_status_input,
            filter_trans_start_date=filter_trans_start_date_str,
            filter_trans_end_date=filter_trans_end_date_str,
            mdrr_start_select=mdrr_start_date_for_form,
            mdrr_end_select=mdrr_end_date_for_form,
            selected_nav_vni_period=selected_nav_vni_period
        )

    except Exception as e:
        logging.error(f"Lỗi nghiêm trọng trong route stock_journal: {e}", exc_info=True)
        try:
            db.session.rollback()
            logging.info("Đã rollback session DB do lỗi trong stock_journal.")
        except Exception as e_rollback:
            logging.error(f"Lỗi khi rollback session DB: {e_rollback}", exc_info=True)

        flash("Đã xảy ra lỗi nghiêm trọng khi tải trang nhật ký chứng khoán. Vui lòng thử lại.", "danger")
        empty_pagination = type('Pagination', (), {'items': [], 'page': 1, 'pages': 0, 'total': 0, 'has_prev': False, 'has_next': False, 'prev_num':0, 'next_num':0, 'iter_pages': lambda **k: []})()
        error_portfolio_summary = {
            'total_market_value': Decimal('0.0'), 'total_cost_basis': Decimal('0.0'),
            'unrealized_pl': Decimal('0.0'), 'unrealized_pl_percent': Decimal('0.0'),
            'total_deposit_period': Decimal('0.0'), 'total_withdrawal_period': Decimal('0.0'),
            'mdrr': None, 'annualized_mdrr': None,
            'mdrr_start_date': None, 'mdrr_end_date': None,
            'actual_nav_start_date': None, 'actual_nav_end_date': None,
            'latest_nav_value': None, 'current_cash': None
        }
        error_charts_data = {
            'nav_vni_labels': [], 'nav_values': [], 'vnindex_values': [],
            'comparison_pl_labels': [], 'comparison_pl_data': [],
            'allocation_labels': [], 'allocation_values': []
        }
        return render_template('stock_journal.html',
                               transactions=[], pagination=empty_pagination, market_prices={},
                               portfolio_summary=error_portfolio_summary,
                               performance_by_symbol_data={},
                               charts_data=error_charts_data,
                               filter_symbol=request.args.get('filter_symbol', ''),
                               filter_status=request.args.get('filter_status', ''),
                               filter_trans_start_date=request.args.get('filter_trans_start_date', ''),
                               filter_trans_end_date=request.args.get('filter_trans_end_date', ''),
                               mdrr_start_select=request.args.get('mdrr_start_select', ''),
                               mdrr_end_select=request.args.get('mdrr_end_select', ''),
                               selected_nav_vni_period=request.args.get('nav_vni_period', 'all'),
                               error_message="Đã xảy ra lỗi nghiêm trọng. Vui lòng thử lại sau."
                              )
# === KẾT THÚC ROUTE stock_journal ===




# --- Route thêm giao dịch mới (Đã cập nhật: Bỏ Phí, Thêm Nộp/Rút) ---
# --- Route thêm giao dịch mới (ĐÃ CẬP NHẬT: Mặc định status cho BUY là OPENED) ---
@app.route('/stock/add', methods=['GET', 'POST'])
@login_required
@role_required(['admin', 'stock_user'])
def add_stock_transaction():
    """Hiển thị form thêm và xử lý thêm giao dịch chứng khoán mới (bao gồm Nộp/Rút)."""
    if request.method == 'POST':
        # --- Lấy dữ liệu từ form ---
        symbol_raw = request.form.get('symbol', '').strip().upper()
        transaction_date_str = request.form.get('transaction_date', '').strip()
        transaction_type = request.form.get('transaction_type', '').strip().upper() # Đã lấy transaction_type
        quantity_str = request.form.get('quantity', '').strip()
        price_str = request.form.get('price', '').strip()

        # --- Validate dữ liệu cơ bản (giữ nguyên phần validate) ---
        errors = []
        symbol = symbol_raw

        valid_types = ['BUY', 'SELL', 'DIVIDEND_CASH', 'DEPOSIT', 'WITHDRAWAL']
        if not transaction_type:
            errors.append("Loại giao dịch là bắt buộc.")
        elif transaction_type not in valid_types:
            errors.append(f"Loại giao dịch '{transaction_type}' không hợp lệ.")

        is_cash_flow = transaction_type in ['DEPOSIT', 'WITHDRAWAL']
        if is_cash_flow:
            symbol = None
            if symbol_raw:
                 flash("Không cần nhập Mã Chứng khoán cho giao dịch Nộp/Rút tiền.", "info")
            if not quantity_str:
                quantity_str = '1'
            if not price_str: errors.append("Số tiền Nộp/Rút là bắt buộc.")
        else:
            if not symbol: errors.append("Mã chứng khoán là bắt buộc.")
            if not quantity_str: errors.append("Số lượng là bắt buộc.")
            if not price_str: errors.append("Giá là bắt buộc.")

        if not transaction_date_str: errors.append("Ngày giao dịch là bắt buộc.")

        transaction_date_db = None
        if transaction_date_str:
            transaction_date_db = format_date_for_storage(transaction_date_str)
            if not transaction_date_db:
                errors.append(f"Định dạng ngày '{transaction_date_str}' không hợp lệ.")

        quantity, price = None, None
        try:
            if quantity_str:
                quantity = Decimal(quantity_str)
                if not is_cash_flow and quantity <= 0:
                    errors.append("Số lượng (Mua/Bán...) phải lớn hơn 0.")
                elif quantity < 0:
                     errors.append("Số lượng không được âm.")
        except InvalidOperation: errors.append("Định dạng số lượng không hợp lệ.")

        try:
            if price_str:
                price = Decimal(price_str.replace(',', ''))
                if price < 0: errors.append("Giá / Số tiền không được âm.")
        except InvalidOperation: errors.append("Định dạng Giá / Số tiền không hợp lệ.")

        if errors:
            for error in errors:
                flash(error, 'danger')
            return redirect(url_for('add_stock_transaction'))

        # --- Tạo và Lưu đối tượng StockTransaction ---
        try:
            # === CẢI TIẾN: Gán status mặc định cho giao dịch MUA ===
            status_to_set = None
            if transaction_type == 'BUY':
                status_to_set = 'OPENED'
            # ======================================================

            new_transaction = StockTransaction(
                user_id=current_user.id,
                symbol=symbol,
                transaction_date=transaction_date_db,
                transaction_type=transaction_type,
                quantity=quantity,
                price=price,
                fees=Decimal('0.0'),
                status=status_to_set  # <<< THÊM status VÀO ĐÂY
            )
            db.session.add(new_transaction)
            db.session.commit()

            log_detail = f"User {current_user.username} added {transaction_type}"
            if symbol:
                flash(f"Đã thêm giao dịch {transaction_type} {symbol} thành công!", 'success')
                log_detail += f" {symbol}"
            else:
                flash(f"Đã thêm giao dịch {transaction_type} thành công!", 'success')
            
            # Bổ sung status vào log nếu là BUY
            if transaction_type == 'BUY':
                log_detail += f" (Status: {status_to_set})"
            log_audit_action('add_stock_transaction', 'stock_transactions', new_transaction.id, log_detail)
            
            return redirect(url_for('stock_journal'))
        except Exception as e:
            db.session.rollback()
            logging.error(f"Lỗi khi thêm giao dịch chứng khoán cho user {current_user.id}: {e}", exc_info=True)
            flash("Đã xảy ra lỗi khi lưu giao dịch.", "danger")
            return redirect(url_for('add_stock_transaction'))
    else:
        return render_template('stock_form.html', form_title="Thêm Giao dịch Mới", transaction=None)

# --- Route sửa giao dịch (Đã cập nhật: Bỏ Phí, Thêm Nộp/Rút) ---
@app.route('/stock/edit/<int:trans_id>', methods=['GET', 'POST'])
@login_required
@role_required(['admin', 'stock_user'])
def edit_stock_transaction(trans_id):
    """Hiển thị form sửa và xử lý cập nhật giao dịch chứng khoán (bao gồm Nộp/Rút)."""

    # --- Lấy giao dịch từ DB và kiểm tra quyền ---
    try:
        transaction = StockTransaction.query.filter_by(id=trans_id, user_id=current_user.id).first()
        if not transaction:
            flash("Không tìm thấy giao dịch hoặc bạn không có quyền sửa giao dịch này.", "warning")
            return redirect(url_for('stock_journal'))
    except Exception as e:
        logging.error(f"Lỗi khi lấy giao dịch ID {trans_id} để sửa: {e}", exc_info=True)
        flash("Lỗi khi tải dữ liệu giao dịch để sửa.", "danger")
        return redirect(url_for('stock_journal'))

    if request.method == 'POST':
        # --- Lấy dữ liệu từ form ---
        symbol_raw = request.form.get('symbol', '').strip().upper()
        transaction_date_str = request.form.get('transaction_date', '').strip()
        transaction_type = request.form.get('transaction_type', '').strip().upper()
        quantity_str = request.form.get('quantity', '').strip()
        price_str = request.form.get('price', '').strip() # Giá hoặc Số tiền
        # fees_str = request.form.get('fees', '0').strip() # <<< BỎ LẤY PHÍ
        
        # --- Validate dữ liệu (tương tự như hàm add) ---
        errors = []
        symbol = symbol_raw

        valid_types = ['BUY', 'SELL', 'DIVIDEND_CASH', 'DEPOSIT', 'WITHDRAWAL'] # Cập nhật list
        if not transaction_type:
            errors.append("Loại giao dịch là bắt buộc.")
        elif transaction_type not in valid_types:
            errors.append(f"Loại giao dịch '{transaction_type}' không hợp lệ.")

        is_cash_flow = transaction_type in ['DEPOSIT', 'WITHDRAWAL']
        if is_cash_flow:
            symbol = None
            if symbol_raw:
                 flash("Không cần nhập Mã Chứng khoán cho giao dịch Nộp/Rút tiền.", "info")
            if not quantity_str:
                quantity_str = '1'
            if not price_str: errors.append("Số tiền Nộp/Rút là bắt buộc.")
        else: # Giao dịch CK
            if not symbol: errors.append("Mã chứng khoán là bắt buộc.")
            if not quantity_str: errors.append("Số lượng là bắt buộc.")
            if not price_str: errors.append("Giá là bắt buộc.")

        if not transaction_date_str: errors.append("Ngày giao dịch là bắt buộc.")

        transaction_date_db = None
        if transaction_date_str:
            transaction_date_db = format_date_for_storage(transaction_date_str)
            if not transaction_date_db: errors.append(f"Định dạng ngày '{transaction_date_str}' không hợp lệ.")

        quantity, price = None, None
        # fees = Decimal('0.0') # <<< LUÔN ĐẶT PHÍ BẰNG 0

        try:
            if quantity_str:
                quantity = Decimal(quantity_str)
                if not is_cash_flow and quantity <= 0:
                    errors.append("Số lượng (Mua/Bán...) phải lớn hơn 0.")
                elif quantity < 0:
                    errors.append("Số lượng không được âm.")
        except InvalidOperation: errors.append("Định dạng số lượng không hợp lệ.")

        try:
            if price_str:
                price = Decimal(price_str.replace(',', ''))
                if price < 0: errors.append("Giá / Số tiền không được âm.")
            # Không cần kiểm tra price rỗng nữa vì đã kiểm tra theo is_cash_flow ở trên
        except InvalidOperation: errors.append("Định dạng Giá / Số tiền không hợp lệ.")

        # --- Xử lý nếu có lỗi ---
        if errors:
            for error in errors: flash(error, 'danger')
            # Khi lỗi, cần chuẩn bị lại transaction_date_form để hiển thị đúng trên form GET
            if transaction.transaction_date:
                 transaction.transaction_date_form = transaction.transaction_date.strftime('%Y-%m-%d')
            else:
                 transaction.transaction_date_form = ''
            # Render lại form với dữ liệu cũ của transaction và báo lỗi
            # Không dùng redirect vì sẽ mất thông báo lỗi flash và dữ liệu người dùng vừa nhập
            return render_template('stock_form.html',
                                   form_title="Chỉnh sửa Giao dịch",
                                   transaction=transaction, # Dữ liệu gốc để hiển thị
                                   form_data=request.form # Dữ liệu người dùng vừa nhập (để fill lại nếu cần)
                                  )

        # --- Cập nhật đối tượng StockTransaction ---
        try:
            # Đảm bảo quantity có giá trị (e.g., 1) nếu là Nộp/Rút và người dùng không nhập
            if is_cash_flow and not quantity:
                 quantity = Decimal('1')

            transaction.symbol = symbol # Sẽ là None nếu là Nộp/Rút
            transaction.transaction_date = transaction_date_db
            transaction.transaction_type = transaction_type
            transaction.quantity = quantity
            transaction.price = price # Là giá hoặc số tiền
            transaction.fees = Decimal('0.0') # <<< Luôn là 0
            

            db.session.commit()
            flash(f"Đã cập nhật giao dịch {transaction.id} thành công!", 'success')
            log_audit_action('edit_stock_transaction', 'stock_transactions', trans_id, f"User {current_user.username} updated transaction ID {trans_id}")
            return redirect(url_for('stock_journal'))
        except Exception as e:
            db.session.rollback()
            logging.error(f"Lỗi khi cập nhật giao dịch {trans_id} cho user {current_user.id}: {e}", exc_info=True)
            flash("Đã xảy ra lỗi khi lưu thay đổi.", "danger")
            # Render lại form khi có lỗi CSDL
            if transaction.transaction_date:
                 transaction.transaction_date_form = transaction.transaction_date.strftime('%Y-%m-%d')
            else:
                 transaction.transaction_date_form = ''
            return render_template('stock_form.html',
                                   form_title="Chỉnh sửa Giao dịch",
                                   transaction=transaction,
                                   form_data=request.form) # Giữ lại dữ liệu nhập

    # --- Xử lý GET request (Không đổi nhiều) ---
    else:
        # Chuẩn bị date_form cho input type="date"
        if transaction.transaction_date:
            transaction.transaction_date_form = transaction.transaction_date.strftime('%Y-%m-%d')
        else:
             transaction.transaction_date_form = ''
        return render_template('stock_form.html', form_title="Chỉnh sửa Giao dịch", transaction=transaction)



# --- Route xóa giao dịch ---
@app.route('/stock/delete/<int:trans_id>', methods=['POST']) # Chỉ chấp nhận POST để xóa
@login_required
@role_required(['admin', 'stock_user'])
def delete_stock_transaction(trans_id):
    try:
        # Lấy transaction VÀ kiểm tra quyền sở hữu
        transaction = StockTransaction.query.filter_by(id=trans_id, user_id=current_user.id).first()

        if transaction:
            # Lưu lại thông tin để log trước khi xóa
            trans_info_for_log = f"ID {transaction.id} ({transaction.transaction_type} {transaction.symbol or 'N/A'} on {transaction.transaction_date.strftime('%Y-%m-%d') if transaction.transaction_date else 'N/A'})"
            
            db.session.delete(transaction)
            db.session.commit()
            flash(f"Đã xóa giao dịch {trans_info_for_log} thành công!", 'success')
            log_audit_action('delete_stock_transaction', 
                             target_table='stock_transactions', 
                             target_id=trans_id, 
                             details=f"User {current_user.username} deleted transaction: {trans_info_for_log}")
        else:
            flash("Không tìm thấy giao dịch hoặc bạn không có quyền xóa giao dịch này.", "warning")
            log_audit_action('delete_stock_transaction_failed', 
                             target_table='stock_transactions', 
                             target_id=trans_id, 
                             details=f"User {current_user.username} failed to delete transaction ID {trans_id} (not found or no permission).")

    except Exception as e:
        db.session.rollback()
        logging.error(f"Lỗi khi xóa giao dịch {trans_id} của user {current_user.id}: {e}", exc_info=True)
        flash("Đã xảy ra lỗi trong quá trình xóa giao dịch.", "danger")

    return redirect(url_for('stock_journal'))



# --- Route Xuất Excel Giao dịch Chứng khoán ---
@app.route('/stock/export/excel')
@login_required
@role_required(['admin', 'stock_user']) # Hoặc chỉ user có quyền xem stock
def export_stock_transactions():
    try:
        transactions = StockTransaction.query.filter_by(user_id=current_user.id)\
                                             .order_by(StockTransaction.transaction_date, StockTransaction.id)\
                                             .all()
        if not transactions:
            flash("Không có dữ liệu giao dịch nào để xuất.", 'info')
            return redirect(url_for('stock_journal'))

        data_for_df = []
        for trans in transactions:
            # Xử lý tiền nộp/rút như trong Tác vụ 3 (hàm stock_journal khi hiển thị)
            # Nhưng ở đây chúng ta xuất file, nên có thể không cần các cột tiền nộp/rút riêng nếu không muốn
            # Giả định giữ nguyên các cột cũ và thêm các cột mới từ Yêu cầu 2 & 4
            
            data_for_df.append({
                'ID': trans.id,
                'Ngày GD': trans.transaction_date.strftime('%d/%m/%Y') if trans.transaction_date else '',
                'Mã CK': trans.symbol if trans.symbol else '',
                'Loại GD': trans.transaction_type,
                'Số lượng': float(trans.quantity) if trans.quantity is not None else None,
                'Giá Gốc/CP': float(trans.price) if trans.price is not None else None, # Giá mua/bán hoặc giá trị cổ tức TM, tiền nộp/rút
                'Phí': float(trans.fees) if trans.fees is not None else 0.0,
                # <<< THÊM CỘT MỚI CHO YÊU CẦU 4 (NHẤT QUÁN) >>>
                'Giá Bán/CP': float(trans.sell_price) if trans.sell_price is not None else None,
                'Ngày Bán': trans.sell_date.strftime('%d/%m/%Y') if trans.sell_date else None,
                'Trạng Thái': trans.status, # OPENED hoặc CLOSED
                # <<< KẾT THÚC THÊM CỘT MỚI >>>
                
            })

        # Định nghĩa thứ tự cột mong muốn cho file export
        column_order = [
            'ID', 'Ngày GD', 'Mã CK', 'Loại GD', 'Số lượng', 'Giá Gốc/CP', 
            'Giá Bán/CP', 'Ngày Bán', 'Trạng Thái', # Các cột mới
            'Phí', 
        ]
        df = pd.DataFrame(data_for_df, columns=column_order)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='GiaoDichChungKhoan')
            worksheet = writer.sheets['GiaoDichChungKhoan']
            for column_cells in worksheet.columns:
                try:
                    length = max(len(str(cell.value)) for cell in column_cells if cell.value is not None) + 1
                    adjusted_width = min(max(10, length), 40)
                    worksheet.column_dimensions[column_cells[0].column_letter].width = adjusted_width
                except ValueError: pass
                except Exception as e_width:
                    logging.warning(f"Lỗi chỉnh độ rộng cột khi export stock: {e_width}")
                    pass
        output.seek(0)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"nhat_ky_giao_dich_{current_user.username}_{timestamp}.xlsx"
        log_audit_action('export_stock_transactions', 'stock_transactions', None, f"User {current_user.username} exported {len(transactions)} transactions (with new columns).")
        return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', download_name=filename, as_attachment=True)
    except Exception as e:
        logging.error(f"Lỗi khi export giao dịch chứng khoán cho user {current_user.id}: {e}", exc_info=True)
        flash(f"Đã xảy ra lỗi khi tạo file export: {e}", "danger")
        return redirect(url_for('stock_journal'))




# --- Route Nhập Excel Giao dịch Chứng khoán ---
@app.route('/stock/import/excel', methods=['POST'])
@login_required
@role_required(['admin', 'stock_user'])
def import_stock_transactions():
    if 'file' not in request.files:
        flash('Không tìm thấy phần tải file trong yêu cầu.', 'danger')
        return redirect(url_for('stock_journal'))
    file = request.files['file']
    if file.filename == '':
        flash('Chưa chọn file nào để tải lên.', 'warning')
        return redirect(url_for('stock_journal'))
    if not file or not allowed_import_file(file.filename):
        flash('Loại file không hợp lệ. Chỉ chấp nhận file .xlsx', 'danger')
        return redirect(url_for('stock_journal'))

    filename = secure_filename(file.filename)
    logging.info(f"User {current_user.username} bắt đầu import giao dịch chứng khoán từ file: {filename} (with new columns logic, no UPSERT)")

    inserted_count, skipped_error_count, skipped_duplicate_count = 0, 0, 0
    error_details, duplicate_details = [], []

    # Cập nhật các loại giao dịch hợp lệ và các cột
    VALID_TRANSACTION_TYPES_IMPORT = ['BUY', 'SELL', 'DIVIDEND_CASH', 'DEPOSIT', 'WITHDRAWAL']
    VALID_STATUS_IMPORT = ['OPENED', 'CLOSED']

    try:
        df = pd.read_excel(file, dtype=str, keep_default_na=False)
        df.columns = df.columns.str.strip().str.lower()

        # Cập nhật các cột bắt buộc và mapping
        # Các cột chính vẫn như cũ, các cột mới là tùy chọn khi import nhưng nếu có sẽ được xử lý
        required_cols_lower = ['ngày gd', 'loại gd'] # Mã CK, Số lượng, Giá sẽ tùy thuộc Loại GD

        # Mapping cho các cột, bao gồm cả cột mới và id (chỉ để đọc, không dùng UPSERT)
        column_mapping = {
            'id': 'id_excel', # Đọc cột ID từ file export nếu có, nhưng không dùng cho UPSERT
            'mã ck': 'symbol',
            'ngày gd': 'transaction_date',
            'loại gd': 'transaction_type',
            'số lượng': 'quantity',
            'giá gốc/cp': 'price', # Hoặc 'giá'
            'giá bán/cp': 'sell_price', # Mới
            'ngày bán': 'sell_date',   # Mới
            'trạng thái': 'status',     # Mới
            'phí': 'fees',
            'ghi chú': 'notes'
        }
        # Kiểm tra các cột cơ bản cho mọi loại giao dịch
        missing_basic_cols = [col_key for col_key, col_val in column_mapping.items() if col_key in required_cols_lower and col_key not in df.columns]
        if missing_basic_cols:
            flash(f"File Excel thiếu các cột cơ bản: {', '.join(missing_basic_cols)}", 'danger')
            logging.error(f"Import failed: Missing required columns: {', '.join(missing_basic_cols)}")
            return redirect(url_for('stock_journal'))

        # Đổi tên các cột có trong DataFrame dựa trên mapping
        df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns}, inplace=True)

        # Duyệt qua từng dòng trong DataFrame đã đọc
        for index, row in df.iterrows():
            row_num = index + 2 # Số dòng trong file Excel (bỏ qua header)
            error_in_row = []

            # Lấy dữ liệu từ row, dùng .get() để tránh lỗi nếu cột không tồn tại sau rename
            symbol_raw = str(row.get('symbol', '')).strip().upper()
            date_str = str(row.get('transaction_date', '')).strip()
            trans_type_raw = str(row.get('transaction_type', '')).strip().upper()

            qty_str = str(row.get('quantity', '')).strip()
            price_str = str(row.get('price', '')).strip().replace(',', '')

            sell_price_str = str(row.get('sell_price', '')).strip().replace(',', '') # Mới
            sell_date_str = str(row.get('sell_date', '')).strip()                   # Mới
            status_raw = str(row.get('status', '')).strip().upper()                 # Mới

            fees_str = str(row.get('fees', '0')).strip().replace(',', '')
            notes = str(row.get('notes', '')).strip() or None

            # id_from_excel = str(row.get('id_excel', '')).strip() # Không dùng cho UPSERT

            # ---- VALIDATE DỮ LIỆU ----
            symbol, trans_type = symbol_raw, trans_type_raw # symbol có thể bị ghi đè sau

            # Validate Loại Giao dịch
            if not trans_type:
                error_in_row.append("Thiếu 'Loại GD'")
            elif trans_type not in VALID_TRANSACTION_TYPES_IMPORT:
                error_in_row.append(f"Loại GD '{trans_type}' không hợp lệ. Chỉ chấp nhận: {', '.join(VALID_TRANSACTION_TYPES_IMPORT)}")

            # Logic riêng cho Nộp/Rút tiền (DEPOSIT, WITHDRAWAL)
            is_cash_flow_import = trans_type in ['DEPOSIT', 'WITHDRAWAL']
            if is_cash_flow_import:
                symbol = None # Ghi đè symbol cho giao dịch tiền
                if not price_str: error_in_row.append("Thiếu 'Giá Gốc/CP' (là Số tiền cho Nộp/Rút)")
                if not qty_str: qty_str = "1" # Mặc định số lượng là 1 cho giao dịch tiền
                # Giao dịch tiền không có sell_price, sell_date, status liên quan đến trạng thái lệnh
                sell_price_str = ''
                sell_date_str = ''
                status_raw = '' # Xóa status nếu có từ file cho giao dịch tiền
            else: # Logic cho các loại giao dịch CK (BUY, SELL, DIVIDEND_CASH...)
                 if not symbol: error_in_row.append("Thiếu 'Mã CK'")
                 if not qty_str: error_in_row.append("Thiếu 'Số lượng'")
                 if not price_str: error_in_row.append("Thiếu 'Giá Gốc/CP'")


            # Validate Ngày Giao dịch
            trans_date_db = None
            if date_str:
                trans_date_db = format_date_for_storage(date_str)
                if not trans_date_db: error_in_row.append(f"Sai định dạng 'Ngày GD' ({date_str}) (cần DD/MM/YYYY)")

            # Validate Số lượng, Giá Gốc/CP, Phí
            quantity, price, fees = None, None, Decimal('0.0')
            try:
                if qty_str: quantity = Decimal(qty_str)
                # Kiểm tra số lượng cho giao dịch CK
                if not is_cash_flow_import and quantity is not None and quantity <= 0:
                     error_in_row.append(f"Số lượng ({qty_str}) phải > 0 cho giao dịch CK")
                elif quantity is not None and quantity < 0 : # Số lượng không bao giờ được âm
                     error_in_row.append(f"Số lượng ({qty_str}) không được âm")
            except (InvalidOperation, ValueError, AssertionError): error_in_row.append(f"Sai 'Số lượng' ({qty_str})")

            try:
                if price_str: price = Decimal(price_str)
                # Kiểm tra giá/số tiền không âm
                if price is not None and price < 0: error_in_row.append(f"Giá Gốc/CP ({price_str}) không được âm")
            except (InvalidOperation, ValueError, AssertionError): error_in_row.append(f"Sai 'Giá Gốc/CP' ({price_str})")

            if fees_str:
                try:
                    fees = Decimal(fees_str)
                    if fees < 0: error_in_row.append(f"Phí ({fees_str}) không được âm")
                except (InvalidOperation, ValueError, AssertionError): error_in_row.append(f"Sai 'Phí' ({fees_str})")
            else:
                 fees = Decimal('0.0') # Đảm bảo fees là Decimal ngay cả khi trống

            # --- Validate và Xử lý các trường mới (sell_price, sell_date, status) ---
            sell_price, sell_date_db = None, None
            status_db = None # Khởi tạo status_db

            if sell_price_str:
                try:
                    sell_price = Decimal(sell_price_str)
                    if sell_price < 0: error_in_row.append(f"Giá Bán/CP ({sell_price_str}) không được âm")
                except (InvalidOperation, ValueError, AssertionError): error_in_row.append(f"Sai 'Giá Bán/CP' ({sell_price_str})")

            if sell_date_str:
                sell_date_db = format_date_for_storage(sell_date_str)
                if not sell_date_db:
                    error_in_row.append(f"Sai định dạng 'Ngày Bán' ({sell_date_str}) (cần DD/MM/YYYY)")
                # Kiểm tra ngày bán không trước ngày GD chỉ khi cả hai ngày đều hợp lệ
                elif trans_date_db is not None and sell_date_db is not None and sell_date_db < trans_date_db:
                    error_in_row.append(f"Ngày Bán ({sell_date_str}) không thể trước Ngày GD ({date_str})")

            # Logic xử lý Status: Ưu tiên từ file, sau đó suy luận cho lệnh BUY
            if status_raw:
                if status_raw in VALID_STATUS_IMPORT:
                    status_db = status_raw
                else:
                    error_in_row.append(f"Trạng Thái '{status_raw}' không hợp lệ. Chỉ chấp nhận: {', '.join(VALID_STATUS_IMPORT)}")
            # Suy luận status chỉ khi trans_type là BUY VÀ status từ file trống/không hợp lệ
            elif trans_type == 'BUY':
                 # Nếu có thông tin bán hợp lệ từ file (dù status trống) -> coi là CLOSED
                 if (sell_price is not None) and (sell_date_db is not None): # Cần cả giá và ngày để là CLOSED
                     status_db = 'CLOSED'
                 else: # Không có đủ thông tin bán -> coi là OPENED
                     status_db = 'OPENED'
            # Các loại GD khác (SELL, DEPOSIT, WITHDRAWAL, DIVIDEND_CASH) không có status OPENED/CLOSED theo nghĩa này
            # status_db sẽ giữ giá trị None nếu không phải BUY và không có status hợp lệ từ file

            # Kiểm tra tính nhất quán giữa status và sell_price/sell_date cho giao dịch BUY
            if trans_type == 'BUY':
                 if status_db == 'OPENED':
                     # Nếu status là OPENED, sell_price và sell_date PHẢI là None
                     if sell_price is not None or sell_date_db is not None:
                         error_in_row.append("Lệnh BUY trạng thái OPENED không được có thông tin Giá Bán hoặc Ngày Bán.")
                         # Tùy chọn: Có thể sửa dữ liệu ở đây thay vì báo lỗi
                         sell_price = None
                         sell_date_db = None
                 elif status_db == 'CLOSED':
                      # Nếu status là CLOSED, sell_price và sell_date PHẢI được cung cấp
                     if sell_price is None or sell_date_db is None:
                         error_in_row.append("Lệnh BUY trạng thái CLOSED cần có cả Giá Bán và Ngày Bán.")
                         # Tùy chọn: Có thể sửa dữ liệu ở đây thay vì báo lỗi
                         # status_db = 'OPENED' # Chuyển về OPENED nếu thiếu thông tin bán
                         # sell_price = None
                         # sell_date_db = None


            # Nếu có lỗi trong dòng, bỏ qua dòng này
            if error_in_row:
                skipped_error_count += 1
                error_details.append(f"Dòng {row_num} (Mã: {symbol_raw or 'N/A'}, Loại: {trans_type_raw or 'N/A'}): {'; '.join(error_in_row)}")
                logging.warning(f"Import skipped row {row_num} due to errors: {error_in_row}")
                continue # Bỏ qua dòng này và chuyển sang dòng kế tiếp

            # ---- KIỂM TRA TRÙNG LẶP (Giữ nguyên logic hiện tại - không dùng UPSERT) ----
            # Kiểm tra xem có bản ghi nào giống hệt (các trường chính) đã tồn tại chưa
            try:
                # Xây dựng điều kiện lọc cho việc kiểm tra trùng lặp
                filter_conditions = [
                    StockTransaction.user_id == current_user.id,
                    StockTransaction.symbol == symbol, # symbol có thể là None cho GD tiền
                    StockTransaction.transaction_date == trans_date_db,
                    StockTransaction.transaction_type == trans_type,
                    StockTransaction.quantity == quantity,
                    StockTransaction.price == price,
                    StockTransaction.fees == fees, # Bao gồm phí trong kiểm tra trùng lặp
                    
                ]
                
                # Thêm các trường mới vào điều kiện kiểm tra trùng lặp nếu phù hợp với loại GD
                if trans_type == 'BUY': # Chỉ lệnh BUY mới có trạng thái, giá bán, ngày bán
                    filter_conditions.extend([
                        StockTransaction.status.is_(status_db) if status_db is None else StockTransaction.status == status_db,
                        StockTransaction.sell_price.is_(sell_price) if sell_price is None else StockTransaction.sell_price == sell_price,
                        StockTransaction.sell_date.is_(sell_date_db) if sell_date_db is None else StockTransaction.sell_date == sell_date_db
                    ])
                # Các loại GD khác không cần kiểm tra trùng lặp các trường sell_price, sell_date, status


                existing_transaction = db.session.query(StockTransaction).filter(and_(*filter_conditions)).first()

                if existing_transaction:
                    skipped_duplicate_count += 1
                    duplicate_details.append(f"Dòng {row_num}: {trans_type} {symbol_raw or 'N/A'} đã tồn tại một bản ghi tương tự (ID DB: {existing_transaction.id}).")
                    logging.info(f"Import skipped row {row_num} due to duplicate.")
                    continue # Bỏ qua dòng này nếu trùng lặp

            except Exception as e_check_dup:
                # Nếu có lỗi xảy ra trong quá trình kiểm tra trùng lặp
                skipped_error_count += 1
                error_details.append(f"Dòng {row_num}: Lỗi kiểm tra trùng lặp - {str(e_check_dup)}")
                logging.error(f"Lỗi kiểm tra trùng lặp GD CK dòng {row_num}: {e_check_dup}", exc_info=True)
                continue # Bỏ qua dòng này do lỗi kiểm tra trùng lặp

            # ---- THÊM GIAO DỊCH MỚI (Chỉ khi không có lỗi và không trùng lặp) ----
            new_transaction = StockTransaction(
                user_id=current_user.id,
                symbol=symbol, # Sẽ là None nếu là Nộp/Rút
                transaction_date=trans_date_db,
                transaction_type=trans_type,
                quantity=quantity,
                price=price,
                fees=fees, # Sử dụng giá trị đã parse, mặc định là 0.0                
                sell_price=sell_price, # Sử dụng giá trị đã validate/xử lý
                sell_date=sell_date_db, # Sử dụng giá trị đã validate/xử lý
                status=status_db        # Sử dụng giá trị đã xử lý (ưu tiên từ file hoặc suy luận cho BUY)
            )
            db.session.add(new_transaction)
            inserted_count += 1

        # Commit các bản ghi đã được thêm vào session (nếu có bản ghi nào đó được thêm)
        if inserted_count > 0 :
            try:
                db.session.commit()
            except Exception as e_commit:
                 db.session.rollback()
                 logging.error(f"Lỗi CSDL khi commit import GD CK: {e_commit}", exc_info=True)
                 flash(f"Lỗi CSDL khi lưu các giao dịch đã nhập: {str(e_commit)}", "danger")
                 # Có thể thêm error_details cho lỗi commit toàn bộ nếu muốn
                 # error_details.append(f"Lỗi CSDL khi commit toàn bộ giao dịch đã nhập: {str(e_commit)}")
                 # skipped_error_count += inserted_count # Có thể coi tất cả là lỗi nếu commit fail

        # ---- THÔNG BÁO KẾT QUẢ ----
        log_msg_parts = [f"User {current_user.username} imported from {filename}:"]
        if inserted_count > 0:
            flash(f"Đã nhập thành công {inserted_count} giao dịch mới.", 'success')
            log_msg_parts.append(f"Added={inserted_count}")

        if skipped_error_count > 0:
            flash(f"Đã bỏ qua {skipped_error_count} dòng do lỗi dữ liệu.", 'warning')
            log_msg_parts.append(f"ErrorSkip={skipped_error_count}")
            # Hiển thị chi tiết lỗi, giới hạn số lượng để tránh tràn flash message
            for i, detail in enumerate(error_details[:10]): # Hiển thị tối đa 10 lỗi chi tiết
                 flash(f"- {detail}", 'warning')
            if skipped_error_count > 10: flash("- ... và nhiều lỗi khác. Vui lòng kiểm tra log.", 'warning')


        if skipped_duplicate_count > 0:
            flash(f"Đã bỏ qua {skipped_duplicate_count} giao dịch do đã tồn tại (trùng lặp).", 'info')
            log_msg_parts.append(f"DupSkip={skipped_duplicate_count}")
            # Hiển thị chi tiết các dòng bị bỏ qua do trùng lặp, giới hạn số lượng
            for i, detail in enumerate(duplicate_details[:10]): # Hiển thị tối đa 10 dòng trùng lặp
                 flash(f"- {detail}", 'info')
            if skipped_duplicate_count > 10: flash("- ... và nhiều trùng lặp khác.", 'info')

        # Thông báo nếu không có dòng nào được xử lý thành công
        if inserted_count == 0 and skipped_error_count == 0 and skipped_duplicate_count == 0:
             flash("File hợp lệ nhưng không có dữ liệu mới hoặc tất cả đều trùng lặp.", 'info')

        # Ghi log audit cho toàn bộ quá trình import
        log_audit_action('import_stock_transactions', 'stock_transactions', None, " ".join(log_msg_parts))
        logging.info("Import Work Log Summary: " + " ".join(log_msg_parts))


    except pd.errors.EmptyDataError:
        flash("Lỗi: File Excel rỗng hoặc không có dữ liệu.", 'danger')
        logging.error(f"Import failed: Empty Excel file '{filename}'.")
    except Exception as e:
        # Catch các lỗi khác có thể xảy ra trong quá trình đọc/xử lý file
        db.session.rollback() # Đảm bảo rollback nếu có lỗi trước commit
        logging.error(f"Lỗi nghiêm trọng khi import GD CK từ file {filename} cho user {current_user.id}: {e}", exc_info=True)
        flash(f"Đã xảy ra lỗi không mong muốn trong quá trình nhập file: {str(e)}", "danger")
        log_audit_action('import_stock_transactions_failed', 'stock_transactions', None, f"User {current_user.username} failed import from {filename}: {str(e)}")


    return redirect(url_for('stock_journal'))


# --- API Endpoint để lấy giá CK (cho Refresh) ---
@app.route('/stock/api/get_prices')
@login_required
@role_required(['admin', 'stock_user'])
def get_stock_prices_api():
    """API endpoint trả về giá cuối cùng dạng JSON cho các mã CK được yêu cầu."""
    symbols_str = request.args.get('symbols', '') # Lấy danh sách mã từ query param ?symbols=HPG,FPT,...
    if not symbols_str:
        return jsonify({"error": "No symbols provided"}), 400

    symbols_list = [symbol.strip().upper() for symbol in symbols_str.split(',') if symbol.strip()]
    if not symbols_list:
         return jsonify({"error": "No valid symbols provided"}), 400

    try:
        # Gọi lại hàm helper đã có
        prices_decimal = get_fireant_last_prices(symbols_list)

        # Chuyển Decimal thành string hoặc float để jsonify hoạt động
        # (JSON không hỗ trợ Decimal trực tiếp)
        prices_serializable = {
            symbol: str(price) if price is not None else None
            for symbol, price in prices_decimal.items()
        }
        return jsonify(prices_serializable)

    except Exception as e:
        logging.error(f"Lỗi API get_stock_prices_api: {e}", exc_info=True)
        return jsonify({"error": "Server error fetching prices"}), 500


# ========== BẮT ĐẦU: ROUTES QUẢN LÝ DỮ LIỆU NAV/VNINDEX ==========
@app.route('/stock/performance', methods=['GET', 'POST'])
@login_required
@role_required(['admin', 'stock_user']) # Chỉ admin hoặc stock_user mới được truy cập
def manage_performance_data():
    """Hiển thị form nhập và xử lý lưu/cập nhật dữ liệu NAV/VNIndex."""
    # Biến ngữ cảnh để template biết đang ở mode nào
    is_performance_mode = True
    recent_data = []
    today_str = date.today().strftime('%Y-%m-%d')

    if request.method == 'POST':
        date_str = request.form.get('date')
        nav_value_str = request.form.get('nav_value', '').strip()
        vnindex_value_str = request.form.get('vnindex_value', '').strip()

        # --- Validate dữ liệu ---
        errors = []
        perf_date = None
        nav_value = None
        vnindex_value = None

        if not date_str:
            errors.append("Ngày là bắt buộc.")
        else:
            try:
                perf_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                # Optional: Add check if date is in the future?
                # if perf_date > date.today():
                #     errors.append("Không thể nhập dữ liệu cho ngày trong tương lai.")
            except ValueError:
                errors.append("Định dạng ngày không hợp lệ (cần YYYY-MM-DD).")

        if not nav_value_str and not vnindex_value_str:
             errors.append("Cần nhập ít nhất giá trị NAV hoặc điểm VNIndex.")

        if nav_value_str:
            try:
                nav_value = Decimal(nav_value_str.replace(',', ''))
                if nav_value < 0:
                    errors.append("Giá trị NAV không được âm.")
            except InvalidOperation:
                errors.append("Định dạng giá trị NAV không hợp lệ.")

        if vnindex_value_str:
            try:
                vnindex_value = Decimal(vnindex_value_str.replace(',', ''))
                if vnindex_value < 0:
                    errors.append("Điểm VNIndex không được âm.")
            except InvalidOperation:
                errors.append("Định dạng điểm VNIndex không hợp lệ.")

        if errors:
            for error in errors:
                flash(error, 'danger')
            # Fall through to GET logic to re-render the form with errors
        else:
            try:
                # Tìm bản ghi hiện có cho user và ngày này (Find or Create/Update)
                existing_entry = PerformanceData.query.filter_by(
                    user_id=current_user.id,
                    date=perf_date
                ).first()

                action_log = "" # For logging details
                if existing_entry:
                    # Cập nhật bản ghi cũ
                    action_log = f"Updated entry ID {existing_entry.id}. Old NAV: {existing_entry.nav_value}, Old VNI: {existing_entry.vnindex_value}."
                    existing_entry.nav_value = nav_value
                    existing_entry.vnindex_value = vnindex_value
                    db.session.add(existing_entry)
                    action = 'cập nhật'
                    entry_id = existing_entry.id
                else:
                    # Tạo bản ghi mới
                    new_entry = PerformanceData(
                        user_id=current_user.id,
                        date=perf_date,
                        nav_value=nav_value,
                        vnindex_value=vnindex_value
                    )
                    db.session.add(new_entry)
                    action = 'thêm mới'
                    # Flush để lấy ID nếu cần log ngay, commit sẽ làm điều này nhưng flush an toàn hơn nếu cần ID trước commit
                    db.session.flush()
                    entry_id = new_entry.id
                    action_log = f"Created new entry ID {entry_id}."

                action_log += f" New NAV: {nav_value}, New VNI: {vnindex_value}."

                db.session.commit()
                flash(f"Đã {action} dữ liệu cho ngày {perf_date.strftime('%d/%m/%Y')} thành công!", 'success')
                log_audit_action(f'{action}_performance_data', 'performance_data', entry_id, f"User {current_user.username} {action_log}")

                # Redirect để tránh double submit và làm mới bảng
                return redirect(url_for('manage_performance_data'))

            except Exception as e:
                db.session.rollback()
                logging.error(f"Lỗi khi lưu dữ liệu NAV/VNIndex cho ngày {perf_date}: {e}", exc_info=True)
                flash(f"Đã xảy ra lỗi khi lưu dữ liệu: {e}", "danger")
                # Fall through to GET logic to re-render form

    # --- Xử lý GET request (hoặc POST bị lỗi thì cũng chạy đến đây) ---
    try:
        # Lấy dữ liệu 30 ngày gần nhất để hiển thị
        cutoff_date = date.today() - timedelta(days=30)
        recent_data = PerformanceData.query.filter(
            PerformanceData.user_id == current_user.id,
            PerformanceData.date >= cutoff_date
        ).order_by(PerformanceData.date.desc()).all()
    except Exception as e:
        logging.error(f"Lỗi khi lấy dữ liệu NAV/VNIndex gần đây: {e}", exc_info=True)
        flash("Lỗi khi tải dữ liệu đã nhập gần đây.", "warning")
        recent_data = [] # Đảm bảo recent_data là list trống nếu lỗi

    # Truyền ngày hôm nay cho giá trị mặc định của input date
    # và dữ liệu gần đây cho bảng, và biến is_performance_mode
    # Sử dụng lại stock_form.html nhưng truyền is_performance_mode=True
    return render_template('stock_form.html',
                           is_performance_mode=True, # QUAN TRỌNG: Để template biết mode
                           recent_data=recent_data,
                           today_str=today_str,
                           form_title="Quản lý Dữ liệu NAV & VNIndex",
                           transaction=None # Không có transaction ở mode này
                           )

# Route để xử lý xóa một mục PerformanceData
@app.route('/stock/performance/delete/<int:entry_id>', methods=['POST'])
@login_required
@role_required(['admin', 'stock_user'])
def delete_performance_data(entry_id):
    """Xóa một bản ghi PerformanceData cụ thể."""
    try:
        # Chỉ cho phép xóa dữ liệu của chính mình
        entry_to_delete = PerformanceData.query.filter_by(id=entry_id, user_id=current_user.id).first()
        if entry_to_delete:
            entry_date_str = entry_to_delete.date.strftime('%d/%m/%Y') # Lưu lại ngày để flash msg
            nav_val = entry_to_delete.nav_value
            vni_val = entry_to_delete.vnindex_value
            db.session.delete(entry_to_delete)
            db.session.commit()
            flash(f"Đã xóa dữ liệu NAV/VNIndex cho ngày {entry_date_str}.", 'success')
            log_audit_action('delete_performance_data', 'performance_data', entry_id, f"User {current_user.username} deleted data for {entry_date_str} (NAV:{nav_val}, VNI:{vni_val})")
        else:
            flash("Không tìm thấy dữ liệu hoặc bạn không có quyền xóa mục này.", 'warning')
    except Exception as e:
        db.session.rollback()
        logging.error(f"Lỗi khi xóa PerformanceData ID {entry_id}: {e}", exc_info=True)
        flash(f"Đã xảy ra lỗi khi xóa dữ liệu: {e}", "danger")

    # Luôn redirect về trang quản lý performance data
    return redirect(url_for('manage_performance_data'))


# === ROUTE ĐỂ XỬ LÝ BÁN CỔ PHIẾU ===
@app.route('/stock/execute_sell/<int:buy_transaction_id>', methods=['POST'])
@login_required
@role_required(['admin', 'stock_user'])
def execute_sell_stock(buy_transaction_id):
    buy_transaction = StockTransaction.query.filter_by(
        id=buy_transaction_id,
        user_id=current_user.id,
        transaction_type='BUY',
        status='OPENED'  # Chỉ bán được lệnh đang mở
    ).first()

    if not buy_transaction:
        flash("Không tìm thấy lệnh mua hợp lệ để bán hoặc lệnh đã được xử lý.", "danger")
        return redirect(url_for('stock_journal'))

    sell_quantity_str = request.form.get('sell_quantity_modal', '').strip()
    sell_price_str = request.form.get('sell_price_modal', '').strip()
    sell_date_str = request.form.get('sell_date_modal', '').strip()

    errors = []
    sell_quantity = None
    sell_price = None
    sell_date_db = None

    # Validate Số lượng bán
    try:
        sell_quantity = Decimal(sell_quantity_str)
        if not (0 < sell_quantity <= buy_transaction.quantity):
            errors.append(f"Số lượng bán phải lớn hơn 0 và không vượt quá số lượng mua gốc ({buy_transaction.quantity:,.0f}).")
    except InvalidOperation:
        errors.append("Định dạng số lượng bán không hợp lệ.")

    # Validate Giá bán
    try:
        sell_price = Decimal(sell_price_str.replace(',', ''))
        if sell_price < 0: # Có thể cho phép giá bán = 0 nếu có trường hợp đặc biệt (VD: hủy niêm yết)
            errors.append("Giá bán không được âm.")
    except InvalidOperation:
        errors.append("Định dạng giá bán không hợp lệ.")

    # Validate Ngày bán
    if not sell_date_str:
        errors.append("Ngày bán là bắt buộc.")
    else:
        sell_date_db = format_date_for_storage(sell_date_str) # Sử dụng hàm format_date_for_storage đã có
        if not sell_date_db:
            errors.append(f"Định dạng ngày bán '{sell_date_str}' không hợp lệ.")
        elif buy_transaction.transaction_date and sell_date_db < buy_transaction.transaction_date:
            errors.append(f"Ngày bán ({sell_date_db.strftime('%d/%m/%Y')}) không thể trước ngày mua ({buy_transaction.transaction_date.strftime('%d/%m/%Y')}).")

    if errors:
        for error in errors:
            flash(error, 'danger')
        return redirect(url_for('stock_journal')) # Redirect về trang nhật ký, modal sẽ không còn hiển thị lỗi cụ thể trong form.

    try:
        # Cập nhật lệnh mua gốc
        # Hiện tại, kế hoạch là đóng toàn bộ lệnh mua khi bán.
        # Nếu bán một phần, logic sẽ phức tạp hơn (tạo giao dịch bán mới, giảm số lượng lệnh mua gốc hoặc tách lệnh).
        # Giả định bán toàn bộ số lượng của lệnh mua gốc tại đây.
        if sell_quantity != buy_transaction.quantity:
             # Nếu bạn muốn hỗ trợ bán một phần, đây là nơi cần thay đổi logic phức tạp hơn.
             # Hiện tại, nếu số lượng bán không khớp SL mua gốc (sau khi validate ở trên), có thể coi là lỗi logic.
             # Tuy nhiên, modal đã giới hạn max là số lượng mua.
             pass # Giữ nguyên số lượng bán từ form nếu đã validate

        buy_transaction.sell_price = sell_price
        buy_transaction.sell_date = sell_date_db
        buy_transaction.status = 'CLOSED'
        # Nếu bán một phần, bạn sẽ không set status = 'CLOSED' ngay mà có thể giảm quantity của lệnh mua.

        db.session.add(buy_transaction)
        db.session.commit()

        flash(f"Đã ghi nhận bán {sell_quantity:,.0f} cổ phiếu {buy_transaction.symbol} với giá {sell_price:,.0f}/CP vào ngày {sell_date_db.strftime('%d/%m/%Y')}. Lệnh mua gốc đã đóng.", "success")
        log_audit_action('execute_sell_stock',
                         target_table='stock_transactions',
                         target_id=buy_transaction.id,
                         details=f"User {current_user.username} sold {sell_quantity} of {buy_transaction.symbol} at {sell_price} on {sell_date_db}. Original buy ID {buy_transaction.id} closed.")
    except Exception as e:
        db.session.rollback()
        logging.error(f"Lỗi khi thực hiện bán cho lệnh mua ID {buy_transaction_id}: {e}", exc_info=True)
        flash("Đã xảy ra lỗi khi lưu thông tin bán cổ phiếu.", "danger")

    return redirect(url_for('stock_journal'))
# === KẾT THÚC ROUTE ĐỂ XỬ LÝ BÁN CỔ PHIẾU ===

# === ROUTE XOÁ TOÀN BỘ DỮ LIỆU GIAO DỊCH ===
@app.route('/stock/delete_all', methods=['POST'])
@login_required
@role_required(['admin', 'stock_user']) # Hoặc chỉ 'admin' nếu cần
def delete_all_stock_transactions():
    """Xóa toàn bộ dữ liệu giao dịch chứng khoán của người dùng hiện tại."""
    password = request.form.get('password')
    # Lấy mật khẩu xóa từ config (nên đặt trong config.py)
    correct_password = current_app.config.get('DELETE_PASSWORD')

    if not correct_password:
         flash('Chức năng xóa toàn bộ chưa được cấu hình mật khẩu bảo vệ.', 'danger')
         logging.error("Attempted delete_all_stock_transactions but DELETE_PASSWORD is not set.")
         return redirect(url_for('stock_journal'))

    if not password or password != correct_password:
        flash('Mật khẩu xác nhận không đúng.', 'danger')
        logging.warning(f"Thất bại xóa toàn bộ giao dịch CK cho user '{current_user.username}': Sai MK từ IP {request.remote_addr}")
        log_audit_action('delete_all_stock_transactions_failed', target_table='stock_transactions', target_id=None, details=f"User {current_user.username} failed: Incorrect password.")
        return redirect(url_for('stock_journal'))

    deleted_count = 0
    try:
        # Xóa tất cả giao dịch của người dùng hiện tại
        # Lưu ý: synchronize_session=False thường được dùng với delete hàng loạt
        # nhưng hãy kiểm tra tài liệu SQLAlchemy/Flask-SQLAlchemy để biết các hàm ý
        num_deleted = StockTransaction.query.filter_by(user_id=current_user.id).delete(synchronize_session=False)
        db.session.commit()
        deleted_count = num_deleted if num_deleted is not None else 0 # Đếm số lượng đã xóa
        flash(f"Đã xóa thành công {deleted_count} giao dịch chứng khoán của bạn.", 'success')
        log_audit_action('delete_all_stock_transactions', target_table='stock_transactions', target_id=None, details=f"User {current_user.username} deleted {deleted_count} stock transactions.")
        logging.info(f"User '{current_user.username}' (ID: {current_user.id}) deleted {deleted_count} stock transactions.")

    except Exception as e:
        db.session.rollback()
        logging.error(f"Lỗi khi xóa toàn bộ giao dịch CK của user {current_user.id}: {e}", exc_info=True)
        flash(f'Lỗi CSDL khi xóa toàn bộ giao dịch: {e}', 'danger')

    return redirect(url_for('stock_journal'))
# === KẾT THÚC ROUTE XOÁ TOÀN BỘ DỮ LIỆU GIAO DỊCH ===


# Route Cập nhật Dữ liệu Giao dịch Nước Ngoài Thủ công
@app.route('/stock/update_foreign_data', methods=['POST'])
@login_required
@role_required(['admin', 'stock_user']) # Đảm bảo decorator này đã được định nghĩa
def update_foreign_data():
    try:
        today = date.today()
        
        # 1. Lấy danh sách các mã cổ phiếu người dùng đang nắm giữ (BUY còn OPENED)
        symbols_held_query = db.session.query(StockTransaction.symbol).filter(
            StockTransaction.user_id == current_user.id,
            StockTransaction.transaction_type == 'BUY',
            StockTransaction.status == 'OPENED',
            StockTransaction.symbol.isnot(None)
        ).distinct()
        symbols_held_list = [item[0] for item in symbols_held_query.all() if item[0]]
        logging.info(f"User {current_user.id} - Mã đang nắm giữ: {symbols_held_list}")

        # 2. Lấy danh sách mã VN100
        vn100_list = load_vn100_symbols() # Sử dụng hàm helper đã tạo
        logging.info(f"User {current_user.id} - Danh sách VN100 tải được: {len(vn100_list)} mã")

        # 3. Kết hợp và loại bỏ trùng lặp
        # Sử dụng set để tự động loại bỏ trùng lặp và sau đó chuyển lại thành list
        combined_symbols_set = set(symbols_held_list) | set(vn100_list)
        symbols_to_update = sorted(list(combined_symbols_set)) # Sắp xếp để log dễ nhìn hơn

        if not symbols_to_update:
            flash("Không có mã cổ phiếu nào (đang nắm giữ hoặc VN100) để cập nhật dữ liệu khối ngoại.", "info")
            # Xác định trang để redirect về, ưu tiên trang gọi đến nếu có, nếu không thì về stock_journal
            # request.referrer có thể không đáng tin cậy, nên có thể cần một tham số redirect
            # Hoặc đơn giản là luôn redirect về stock_journal
            return redirect(request.referrer or url_for('stock_journal'))

        logging.info(f"User {current_user.id} - Tổng số mã sẽ cập nhật GDNN (kết hợp nắm giữ và VN100): {len(symbols_to_update)} mã. Danh sách: {symbols_to_update}")
        
        # 4. Lấy dữ liệu từ FireAnt cho tất cả các mã này
        fireant_data_full = get_fireant_foreign_trade_data(symbols_to_update)

        updated_count = 0
        created_count = 0
        error_symbols_details = [] 

        for symbol in symbols_to_update: 
            data_values = fireant_data_full.get(symbol)

            if not data_values or data_values.get('error'):
                error_msg = data_values.get('error', 'Không nhận được dữ liệu từ API') if data_values else 'Không nhận được dữ liệu từ API'
                logging.warning(f"Không thể lấy dữ liệu khối ngoại cho mã {symbol} từ FireAnt. Lý do: {error_msg}")
                error_symbols_details.append(f"{symbol} ({error_msg})")
                continue 

            buy_val_api = data_values.get('buy_foreign_value')
            sell_val_api = data_values.get('sell_foreign_value')
            
            buy_val_for_calc = buy_val_api if buy_val_api is not None else Decimal('0')
            sell_val_for_calc = sell_val_api if sell_val_api is not None else Decimal('0')
            net_val_calculated = buy_val_for_calc - sell_val_for_calc

            try:
                # Quan trọng: Dữ liệu GDNN được lưu với user_id của người dùng hiện tại,
                # ngay cả khi đó là dữ liệu của một mã VN100 mà họ không nắm giữ.
                # Điều này có nghĩa là mỗi người dùng có "bản sao" dữ liệu GDNN của riêng mình.
                existing_entry = StockForeignDailyData.query.filter_by(
                    user_id=current_user.id, # Luôn là user hiện tại
                    symbol=symbol,
                    date=today
                ).first()

                action_taken = ""
                if existing_entry:
                    action_taken = "cập nhật"
                    existing_entry.buy_foreign_value = buy_val_api 
                    existing_entry.sell_foreign_value = sell_val_api 
                    existing_entry.net_foreign_value = net_val_calculated 
                    updated_count += 1
                else:
                    action_taken = "thêm mới"
                    new_entry = StockForeignDailyData(
                        user_id=current_user.id, # Luôn là user hiện tại
                        symbol=symbol,
                        date=today,
                        buy_foreign_value=buy_val_api,
                        sell_foreign_value=sell_val_api,
                        net_foreign_value=net_val_calculated
                    )
                    db.session.add(new_entry)
                    created_count += 1
                logging.info(f"User {current_user.id} - Đã {action_taken} dữ liệu khối ngoại cho {symbol} ngày {today}: Buy={buy_val_api}, Sell={sell_val_api}, Net={net_val_calculated}")

            except Exception as e_db:
                logging.error(f"User {current_user.id} - Lỗi CSDL khi {action_taken} dữ liệu khối ngoại cho mã {symbol}: {e_db}", exc_info=True)
                error_symbols_details.append(f"{symbol} (lỗi CSDL: {str(e_db)[:50]}...)")

        try:
            db.session.commit()
        except Exception as e_commit_all:
            db.session.rollback()
            logging.error(f"User {current_user.id} - Lỗi CSDL khi commit tất cả dữ liệu khối ngoại: {e_commit_all}", exc_info=True)
            flash(f"Lỗi CSDL nghiêm trọng khi lưu dữ liệu khối ngoại: {e_commit_all}", "danger")
            return redirect(request.referrer or url_for('stock_journal'))

        if error_symbols_details:
            flash(f"Cập nhật GDNN hoàn tất với một số lỗi cho các mã: {', '.join(error_symbols_details)}.", "warning")
        
        flash_msg_parts = []
        if created_count > 0:
            flash_msg_parts.append(f"{created_count} mã được thêm mới")
        if updated_count > 0:
            flash_msg_parts.append(f"{updated_count} mã được cập nhật")
        
        if flash_msg_parts:
            flash(f"Dữ liệu giao dịch nước ngoài cho ngày {today.strftime('%d/%m/%Y')} ({', '.join(flash_msg_parts)}) đã được xử lý cho các mã đang theo dõi và VN100.", "success")
        elif not error_symbols_details: 
             flash("Không có dữ liệu mới hoặc thay đổi nào từ API để cập nhật cho các mã đang theo dõi và VN100.", "info")

        log_audit_action('update_foreign_stock_data_all', target_table='stock_foreign_daily_data',
                         details=f"User {current_user.username} updated foreign data for held & VN100. Added: {created_count}, Updated: {updated_count}, Errors: {len(error_symbols_details)} ({'; '.join(error_symbols_details)})")

    except Exception as e:
        db.session.rollback() 
        logging.error(f"User {current_user.id} - Lỗi nghiêm trọng trong quá trình cập nhật dữ liệu khối ngoại: {e}", exc_info=True)
        flash(f"Đã xảy ra lỗi không mong muốn trong quá trình cập nhật GDNN: {e}", "danger")

    return redirect(request.referrer or url_for('stock_journal'))


# --- Đặt hàm này ở khu vực các hàm helper trong app.py ---
def load_vn100_symbols(file_path='VN100.md'):
    """
    Tải danh sách mã VN100 từ file .md.
    Mỗi mã trên một dòng, có thể có đánh số.
    """
    vn100_symbols_list = []
    try:
        # Đường dẫn đến file VN100.md, giả sử nó nằm cùng cấp với thư mục chạy app.py
        # hoặc bạn có thể cung cấp đường dẫn tuyệt đối.
        # Trong môi trường Flask, current_app.root_path là thư mục gốc của ứng dụng.
        actual_file_path = os.path.join(current_app.root_path, file_path)

        if not os.path.exists(actual_file_path):
            # Thử tìm ở thư mục cha nếu app.py nằm trong thư mục con (ví dụ: src)
            # Điều này có thể không cần thiết nếu cấu trúc file của bạn khác.
            # actual_file_path = os.path.join(os.path.dirname(current_app.root_path), file_path)
            # Bỏ qua logic tìm ở thư mục cha phức tạp, giả định file nằm ở root_path
             logging.error(f"File VN100.md không tìm thấy tại: {actual_file_path}")
             # flash(f"Lỗi: Không tìm thấy file danh sách VN100 ({file_path}). Vui lòng đặt file VN100.md vào thư mục gốc của ứng dụng.", "danger")
             # Trả về list rỗng để không làm crash app, lỗi sẽ được báo ở nơi gọi
             return []


        with open(actual_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line_content = line.strip()
                if line_content:
                    # Loại bỏ phần số thứ tự và dấu chấm (ví dụ: "1. AAA" -> "AAA")
                    match = re.match(r"^\d+\.\s*(.*)", line_content)
                    if match:
                        symbol = match.group(1).strip().upper()
                    else:
                        symbol = line_content.strip().upper() # Nếu dòng chỉ chứa mã
                    
                    if symbol: # Đảm bảo mã không rỗng sau khi xử lý
                        vn100_symbols_list.append(symbol)
        logging.info(f"Đã tải thành công {len(vn100_symbols_list)} mã từ {actual_file_path}")
    except FileNotFoundError:
        logging.error(f"File VN100.md không tìm thấy tại: {actual_file_path}")
        flash(f"Lỗi: Không tìm thấy file danh sách VN100 ({file_path}). Chức năng xem VN100 sẽ không hoạt động.", "danger")
    except Exception as e:
        logging.error(f"Lỗi khi tải danh sách mã VN100 từ {file_path}: {e}", exc_info=True)
        flash(f"Lỗi khi đọc file danh sách VN100: {e}", "warning")
    return vn100_symbols_list

# Route hiển thị trang Biểu đồ Giao dịch Nước Ngoài:
@app.route('/stock/foreign_investment_charts')
@login_required
@role_required(['admin', 'stock_user'])
def foreign_investment_charts():
    try:
        days_to_show_str = request.args.get('days', '30')
        view_mode = request.args.get('view_mode', 'user_held') # 'user_held' hoặc 'vn100'
        custom_symbols_input_str = request.args.get('custom_symbols', '').strip().upper()
        
        days_to_show = int(days_to_show_str) if days_to_show_str.isdigit() and int(days_to_show_str) > 0 else 30

        today = date.today()
        end_date_chart = today
        start_date_chart = end_date_chart - timedelta(days=days_to_show - 1)
        
        symbols_for_line_chart = []
        processed_custom_symbols = []

        if custom_symbols_input_str:
            processed_custom_symbols = [s.strip() for s in custom_symbols_input_str.split(',') if s.strip()]

        if view_mode == 'vn100':
            symbols_for_line_chart = load_vn100_symbols()
            if processed_custom_symbols: # Nếu người dùng nhập mã tùy chỉnh khi đang ở chế độ VN100
                symbols_for_line_chart = [s for s in symbols_for_line_chart if s in processed_custom_symbols]
                if not symbols_for_line_chart and processed_custom_symbols:
                     flash(f"Các mã bạn nhập ({custom_symbols_input_str}) không thuộc VN100 hoặc danh sách VN100 rỗng. Hiển thị toàn bộ VN100 (nếu có).", "warning")
                     symbols_for_line_chart = load_vn100_symbols() # Tải lại nếu lọc không ra kết quả
        elif view_mode == 'user_held':
            # LẤY DANH SÁCH MÃ ĐANG THỰC SỰ NẮM GIỮ (BUY & OPENED)
            user_currently_holding_symbols_query = db.session.query(StockTransaction.symbol).filter(
                StockTransaction.user_id == current_user.id,
                StockTransaction.transaction_type == 'BUY',
                StockTransaction.status == 'OPENED',
                StockTransaction.symbol.isnot(None)
            ).distinct()
            user_currently_holding_symbols = [s[0] for s in user_currently_holding_symbols_query.all() if s[0]]

            if processed_custom_symbols:
                # Lọc các mã tùy chỉnh dựa trên danh sách đang nắm giữ
                symbols_for_line_chart = [s for s in processed_custom_symbols if s in user_currently_holding_symbols]
                if not symbols_for_line_chart and processed_custom_symbols:
                    flash(f"Không tìm thấy dữ liệu cho các mã tùy chỉnh ({custom_symbols_input_str}) trong danh sách bạn đang nắm giữ.", "warning")
                    # Có thể quyết định hiển thị tất cả mã đang nắm giữ nếu custom input không hợp lệ
                    # symbols_for_line_chart = user_currently_holding_symbols
            else: # Không nhập custom, lấy tất cả mã đang nắm giữ
                symbols_for_line_chart = user_currently_holding_symbols
        else: 
            symbols_for_line_chart = []


        line_chart_data_output = {'labels': [], 'datasets': []}
        user_symbols_for_legend = [] 
        missing_data_message = None
        bar_chart_individual_data = {'labels': [], 'data': []} 

        if not symbols_for_line_chart:
            if view_mode == 'vn100' and not load_vn100_symbols():
                 missing_data_message = "Không thể tải danh sách mã VN100 hoặc danh sách rỗng. Vui lòng kiểm tra file VN100.md."
            elif view_mode == 'user_held' and not processed_custom_symbols : # Mã theo dõi mặc định và không có mã nào đang nắm giữ
                 missing_data_message = "Bạn hiện không nắm giữ mã cổ phiếu nào (trạng thái Mở)."
            elif view_mode == 'user_held' and processed_custom_symbols and not symbols_for_line_chart: # Nhập custom nhưng không có mã nào hợp lệ
                 missing_data_message = f"Không có mã nào hợp lệ hoặc đang nắm giữ từ danh sách bạn nhập: {custom_symbols_input_str}."
            else: # Các trường hợp khác
                 missing_data_message = "Không có mã nào được chọn hoặc hợp lệ để hiển thị."
            if missing_data_message: flash(missing_data_message, "info")
        else:
            query_conditions = [
                StockForeignDailyData.symbol.in_(symbols_for_line_chart),
                StockForeignDailyData.date >= start_date_chart,
                StockForeignDailyData.date <= end_date_chart,
                StockForeignDailyData.net_foreign_value.isnot(None),
                StockForeignDailyData.user_id == current_user.id # Luôn lọc theo user_id vì dữ liệu GDNN được lưu theo user
            ]

            foreign_data_for_charts = StockForeignDailyData.query.filter(and_(*query_conditions)).order_by(
                StockForeignDailyData.date.asc(), StockForeignDailyData.symbol.asc()
            ).all()

            if foreign_data_for_charts:
                unique_dates_from_db = sorted(list(set(entry.date for entry in foreign_data_for_charts)))
                line_chart_data_output['labels'] = [d.strftime('%d/%m') for d in unique_dates_from_db]
                
                symbols_with_data_in_period = sorted(list(set(entry.symbol for entry in foreign_data_for_charts)))
                user_symbols_for_legend = symbols_with_data_in_period 

                datasets_map_line = {}
                symbol_totals_for_bar_chart = {symbol: Decimal('0.0') for symbol in symbols_with_data_in_period}

                for symbol_name in symbols_with_data_in_period:
                    datasets_map_line[symbol_name] = [None] * len(unique_dates_from_db)

                for entry in foreign_data_for_charts:
                    if entry.symbol in symbols_with_data_in_period: 
                        try:
                            date_index = unique_dates_from_db.index(entry.date)
                            net_value_decimal = Decimal(str(entry.net_foreign_value))
                            datasets_map_line[entry.symbol][date_index] = float(net_value_decimal / Decimal('1000000000.0'))
                            symbol_totals_for_bar_chart[entry.symbol] += net_value_decimal
                        except ValueError:
                            logging.warning(f"Ngày {entry.date} (charts) không tìm thấy. Bỏ qua {entry.symbol}")
                        except (TypeError, InvalidOperation) as e_conv:
                            logging.warning(f"Giá trị net_foreign_value '{entry.net_foreign_value}' cho {entry.symbol} (charts) lỗi. Lỗi: {e_conv}")
                
                colors = ['#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF', '#FF9F40',
                          '#E7E9ED', '#800000', '#008000', '#000080', '#FF00FF', '#00FFFF',
                          '#8B4513', '#FFD700', '#ADFF2F', '#FF69B4', '#7FFFD4', '#D2691E']
                color_index = 0
                for symbol_name, data_points in datasets_map_line.items():
                    if any(dp is not None for dp in data_points): 
                        border_color = colors[color_index % len(colors)]
                        try:
                            r,g,b = tuple(int(border_color.lstrip('#')[i:i+2], 16) for i in (0,2,4))
                            bg_color = f'rgba({r},{g},{b},0.1)'
                        except: bg_color = 'rgba(0,0,0,0.1)'
                        
                        line_chart_data_output['datasets'].append({
                            'label': symbol_name, 'data': data_points, 'borderColor': border_color,
                            'backgroundColor': bg_color, 'fill': False, 'tension': 0.1, 'hidden': False 
                        })
                        color_index += 1
                
                sorted_symbol_totals = sorted(symbol_totals_for_bar_chart.items(), key=lambda item: item[1], reverse=True)
                bar_chart_individual_data['labels'] = [item[0] for item in sorted_symbol_totals if item[1] != Decimal('0.0')] 
                bar_chart_individual_data['data'] = [float(item[1] / Decimal('1000000000.0')) for item in sorted_symbol_totals if item[1] != Decimal('0.0')]

            elif not missing_data_message: # Nếu symbols_for_line_chart có mã nhưng query không ra data
                current_display_type = "VN100" if view_mode == 'vn100' else ("các mã tùy chỉnh" if processed_custom_symbols else "các mã bạn đang nắm giữ")
                missing_data_message = f"Không có dữ liệu GDNN cho {current_display_type} trong {days_to_show} ngày gần nhất."
                flash(missing_data_message, "info")

        return render_template('foreign_investment_charts.html',
                               line_chart_data=line_chart_data_output if line_chart_data_output['datasets'] else None,
                               bar_chart_individual_data=bar_chart_individual_data if bar_chart_individual_data['labels'] else None,
                               user_symbols_for_legend=user_symbols_for_legend, # Sẽ là các mã thực sự có data trong kỳ
                               days_shown=days_to_show,
                               start_date_display=start_date_chart.strftime('%d/%m/%Y'),
                               end_date_display=end_date_chart.strftime('%d/%m/%Y'),
                               missing_data_message=missing_data_message,
                               current_view_mode=view_mode,
                               current_custom_symbols=custom_symbols_input_str)

    except Exception as e:
        logging.error(f"Lỗi tải trang biểu đồ GDNN: {e}", exc_info=True)
        flash("Đã xảy ra lỗi khi tải dữ liệu cho biểu đồ.", "danger")
        today_render = date.today()
        empty_bar_data = {'labels': [], 'data': []}
        return render_template('foreign_investment_charts.html',
                               line_chart_data=None, 
                               bar_chart_individual_data=empty_bar_data, user_symbols_for_legend=[],
                               days_shown=30, start_date_display=(today_render - timedelta(days=29)).strftime('%d/%m/%Y'),
                               end_date_display=today_render.strftime('%d/%m/%Y'),
                               missing_data_message="Lỗi máy chủ khi tải biểu đồ.",
                               current_view_mode='user_held', current_custom_symbols='')

# === KẾT THÚC ROUTES GIAO DỊCH CHỨNG KHOÁN ===

# === ROUTES QUẢN LÝ THẺ ===
@app.route('/cards', methods=['GET'])
@login_required
@role_required(['admin', 'card_user'])
def card_management_index():
    try:
        page = request.args.get('page', 1, type=int)
        keyword = request.args.get('keyword', default='', type=str).strip()
        department = request.args.get('department', default='', type=str).strip()
        status = request.args.get('status', default='', type=str).strip()
        issue_date_start_str = request.args.get('issue_date_start', default='', type=str).strip()
        issue_date_end_str = request.args.get('issue_date_end', default='', type=str).strip()

        filters_orm = build_card_filters_orm(keyword, department, status, issue_date_start_str, issue_date_end_str)

        query = CardRecord.query
        # Hiện tại, CardRecord không có user_id của người tạo.
        # Nếu bạn muốn mỗi user chỉ quản lý thẻ của mình, bạn cần thêm trường user_id (FK đến User) vào CardRecord
        # và filter ở đây: query = CardRecord.query.filter_by(user_id=current_user.id)

        if filters_orm:
            query = query.filter(and_(*filters_orm))

        query = query.order_by(desc(CardRecord.created_at)) # Sắp xếp theo ngày tạo mới nhất
        
        CARDS_PER_PAGE = current_app.config.get('CARDS_PER_PAGE', 15)
        
        pagination = query.paginate(page=page, per_page=CARDS_PER_PAGE, error_out=False)
        cards_to_display = pagination.items

        chart_stats = get_card_stats_for_charts()

        current_filters = {
            'keyword': keyword,
            'department': department,
            'status': status,
            'issue_date_start': issue_date_start_str,
            'issue_date_end': issue_date_end_str
        }
        
        return render_template('cards_management.html',
                               cards=cards_to_display,
                               pagination=pagination,
                               chart_stats=chart_stats,
                               filters=current_filters, 
                               page=page,
                               total_pages=pagination.pages,
                               total_cards=pagination.total)

    except Exception as e:
        logging.error(f"Lỗi trong route card_management_index: {e}", exc_info=True)
        flash("Đã xảy ra lỗi khi tải trang quản lý thẻ. Vui lòng thử lại.", "danger")
        empty_pagination = type('Pagination', (), {'items': [], 'page': 1, 'pages': 0, 'total': 0, 'has_prev': False, 'has_next': False, 'prev_num':0, 'next_num':0, 'iter_pages': lambda **k: []})()
        return render_template('cards_management.html',
                               cards=[],
                               pagination=empty_pagination,
                               chart_stats={'overall': {'total': 0, 'using': 0, 'available': 0}, 
                                            'Customer': {'total': 0, 'using': 0, 'available': 0},
                                            'Employee': {'total': 0, 'using': 0, 'available': 0},
                                            'Temp_Worker': {'total': 0, 'using': 0, 'available': 0}},
                               filters={},
                               page=1,
                               total_pages=0,
                               total_cards=0,
                               error_message="Không thể tải dữ liệu thẻ.")

@app.route('/cards/add', methods=['POST'])
@login_required
@role_required(['admin', 'card_user'])
def add_card_record():
    if request.method == 'POST':
        card_number = request.form.get('card_number', '').strip()
        department = request.form.get('department', '').strip()
        user_id_assigned = request.form.get('user_id_assigned', '').strip() or None
        user_name_assigned = request.form.get('user_name_assigned', '').strip() or None
        status = request.form.get('status', 'Available').strip()
        issue_date_str = request.form.get('issue_date', '').strip()
        details = request.form.get('details', '').strip() or None

        errors = []
        if not card_number:
            errors.append("Số thẻ là bắt buộc.")
        else:
            existing_card = CardRecord.query.filter_by(card_number=card_number).first()
            if existing_card:
                errors.append(f"Số thẻ '{card_number}' đã tồn tại.")
        
        if not department:
            errors.append("Bộ phận là bắt buộc.")
        
        # Cập nhật kiểm tra trạng thái để bao gồm 'Lost'
        if status not in ['Available', 'Using', 'Lost']:
            errors.append("Trạng thái thẻ không hợp lệ. Chỉ chấp nhận 'Available', 'Using', hoặc 'Lost'.")
            status = 'Available' # Mặc định lại nếu không hợp lệ

        issue_date_db = None
        if issue_date_str:
            issue_date_db = format_date_for_storage(issue_date_str)
            if not issue_date_db:
                errors.append(f"Định dạng ngày cấp '{issue_date_str}' không hợp lệ (dd/mm/yyyy hoặc yyyy-mm-dd).")
        
        # Xử lý logic dựa trên trạng thái
        if status == 'Using':
            if not user_id_assigned:
                errors.append("UserID người được cấp là bắt buộc khi trạng thái là 'Using'.")
            if not user_name_assigned:
                errors.append("UserName người được cấp là bắt buộc khi trạng thái là 'Using'.")
            if not issue_date_db:
                errors.append("Ngày cấp là bắt buộc khi trạng thái là 'Using'.")
        elif status == 'Lost':
            user_id_assigned = None
            user_name_assigned = None
            # issue_date_db = None # Tùy chọn: giữ lại ngày cấp nếu đã có, hoặc xóa đi
                                 # Hiện tại, nếu thẻ được thêm mới là Lost, ngày cấp sẽ là None nếu không nhập.
                                 # Nếu thẻ được chuyển sang Lost từ Using, ngày cấp có thể vẫn còn.
        elif status == 'Available': # Đảm bảo các trường này là None cho Available
            user_id_assigned = None
            user_name_assigned = None
            issue_date_db = None


        if errors:
            for error in errors:
                flash(error, 'danger')
        else:
            try:
                new_card = CardRecord(
                    card_number=card_number,
                    department=department,
                    user_id_assigned=user_id_assigned,
                    user_name_assigned=user_name_assigned,
                    status=status,
                    issue_date=issue_date_db,
                    details=details
                )
                db.session.add(new_card)
                db.session.commit()
                flash(f"Đã thêm thẻ '{card_number}' với trạng thái '{status}' thành công!", 'success')
                log_audit_action('add_card_record', 'card_records', new_card.id, 
                                 f"User {current_user.username} added card: {card_number}, Dept: {department}, Status: {status}")
            except Exception as e:
                db.session.rollback()
                logging.error(f"Lỗi khi thêm thẻ mới: {e}", exc_info=True)
                flash(f"Lỗi khi lưu thẻ: {str(e)}", 'danger')
    return redirect(url_for('card_management_index'))

@app.route('/cards/delete/<int:card_id>', methods=['POST'])
@login_required
@role_required(['admin', 'card_user']) # Đảm bảo decorator này đúng và hoạt động
def delete_card_record(card_id):
    card_to_delete = db.session.get(CardRecord, card_id)
    
    # Lấy các tham số để redirect về đúng trang và bộ lọc từ form
    page_str = request.form.get('page', '1')
    try:
        page = int(page_str)
        if page < 1:
            page = 1
    except ValueError:
        page = 1
        current_app.logger.warning(f"Giá trị 'page' không hợp lệ từ form: '{page_str}'. Đặt lại thành 1.")

    keyword = request.form.get('keyword', '')
    department_filter = request.form.get('department', '')
    status_filter = request.form.get('status', '')
    issue_date_start_filter = request.form.get('issue_date_start', '')
    issue_date_end_filter = request.form.get('issue_date_end', '')

    redirect_url = url_for('card_management_index', 
                           page=page, 
                           keyword=keyword, 
                           department=department_filter, 
                           status=status_filter, 
                           issue_date_start=issue_date_start_filter,
                           issue_date_end=issue_date_end_filter)

    if not card_to_delete:
        flash(f"Không tìm thấy thẻ với ID {card_id} để xóa.", "warning")
        return redirect(redirect_url)

    try:
        card_number_deleted = card_to_delete.card_number # Lưu lại để thông báo
        db.session.delete(card_to_delete)
        db.session.commit()
        flash(f"Đã xóa thẻ '{card_number_deleted}' thành công!", 'success')
        # Ghi log hành động nếu cần
        log_audit_action('delete_card_record', 'card_records', card_id, 
                         f"User {current_user.username} deleted card: {card_number_deleted} (ID: {card_id})")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Lỗi khi xóa thẻ ID {card_id}: {e}", exc_info=True)
        flash(f"Lỗi khi xóa thẻ: {str(e)}", 'danger')
    
    return redirect(redirect_url)

# === HÀM GÁN THẺ HÀNG LOẠT (batch_assign_cards) ===
@app.route('/cards/batch_assign', methods=['POST'])
@login_required
@role_required(['admin', 'card_user'])
def batch_assign_cards():
    card_ids_str = request.form.get('selected_card_ids_assign')
    user_id = request.form.get('assign_user_id', '').strip()
    user_name = request.form.get('assign_user_name', '').strip()
    issue_date_str = request.form.get('assign_issue_date', '').strip()
    department_assign = request.form.get('assign_department', '').strip() # Department cho các thẻ được gán
    page = request.form.get('page', 1, type=int)
    keyword = request.form.get('keyword', '')
    department_filter_redirect = request.form.get('department_filter_redirect', '')
    status_filter_redirect = request.form.get('status_filter_redirect', '')
    issue_date_start_filter_redirect = request.form.get('issue_date_start_filter_redirect', '')
    issue_date_end_filter_redirect = request.form.get('issue_date_end_filter_redirect', '')
    redirect_url = url_for('card_management_index', 
                           page=page, keyword=keyword, department=department_filter_redirect, 
                           status=status_filter_redirect, issue_date_start=issue_date_start_filter_redirect,
                           issue_date_end=issue_date_end_filter_redirect)
    if not card_ids_str:
        flash("Không có thẻ nào được chọn để gán.", "warning")
        return redirect(redirect_url)
    try:
        card_ids = [int(id_str) for id_str in card_ids_str.split(',') if id_str.strip()]
        if not card_ids: raise ValueError("Danh sách ID thẻ rỗng.")
    except ValueError:
        flash("Định dạng ID thẻ không hợp lệ.", "danger")
        return redirect(redirect_url)
    errors = []
    if not user_id: errors.append("UserID người được cấp là bắt buộc.")
    if not user_name: errors.append("UserName người được cấp là bắt buộc.")
    if not department_assign: errors.append("Bộ phận cho thẻ được gán là bắt buộc.") # Thêm kiểm tra department
    issue_date_db = None
    if not issue_date_str: errors.append("Ngày cấp là bắt buộc.")
    else:
        issue_date_db = format_date_for_storage(issue_date_str)
        if not issue_date_db: errors.append(f"Định dạng ngày cấp '{issue_date_str}' không hợp lệ.")
    if errors:
        for error in errors: flash(error, 'danger')
        return redirect(redirect_url)
    updated_count = 0
    skipped_count = 0
    cards_to_update = CardRecord.query.filter(CardRecord.id.in_(card_ids)).all()
    if not cards_to_update:
        flash("Không tìm thấy thẻ nào hợp lệ từ danh sách đã chọn.", "warning")
        return redirect(redirect_url)
    utc_now = datetime.now(timezone.utc)
    gmt7 = timezone(timedelta(hours=7))
    timestamp_gmt7_str = utc_now.astimezone(gmt7).strftime('%Y-%m-%d %H:%M')
    user_performing_action = current_user.username if current_user and current_user.is_authenticated else "System"
    for card in cards_to_update:
        if card.status.lower() == 'available': # So sánh không phân biệt hoa thường
            card.status = 'Using'
            card.user_id_assigned = user_id
            card.user_name_assigned = user_name
            card.issue_date = issue_date_db
            card.department = department_assign # Cập nhật bộ phận cho thẻ
            
            # --- GHI NHẬT KÝ VÀO DETAILS ---
            log_entry = f"[{timestamp_gmt7_str} by {user_performing_action}]: Gán cho {user_name} ({user_id})."
            current_details = card.details or ""
            # Lấy phần details gốc (không bao gồm các log cũ)
            base_details = current_details.split("\n[")[0].strip()
            
            if base_details: # Nếu có details gốc
                 card.details = f"{base_details}\n{log_entry}"
            else: # Nếu details gốc rỗng
                 card.details = log_entry
            
            # Nối thêm các log cũ nếu có
            old_log_entries = [line for line in current_details.splitlines() if line.strip().startswith('[') and line.strip() != log_entry]
            if old_log_entries:
                 card.details += "\n" + "\n".join(old_log_entries)
            # --- KẾT THÚC GHI NHẬT KÝ ---

            updated_count += 1
            log_audit_action('batch_assign_card', 'card_records', card.id,
                             f"User {user_performing_action} assigned card {card.card_number} to {user_name} ({user_id})")
        else:
            skipped_count += 1
            flash(f"Thẻ '{card.card_number}' không ở trạng thái 'Available' nên không thể gán.", "info")
    if updated_count > 0:
        try:
            db.session.commit()
            flash(f"Đã gán thành công {updated_count} thẻ.", "success")
        except Exception as e:
            db.session.rollback()
            logging.error(f"Lỗi khi gán thẻ hàng loạt: {e}", exc_info=True)
            flash("Lỗi CSDL khi thực hiện gán thẻ hàng loạt.", "danger")
    return redirect(redirect_url)

# === HÀM THU HỒI THẺ HÀNG LOẠT (batch_return_cards) ===
@app.route('/cards/batch_return', methods=['POST'])
@login_required
@role_required(['admin', 'card_user'])
def batch_return_cards():
    card_ids_str = request.form.get('selected_card_ids_return')
    return_details_note = request.form.get('return_details', '').strip() 

    page = request.form.get('page', 1, type=int)
    keyword = request.form.get('keyword', '')
    department_filter_redirect = request.form.get('department_filter_redirect', '')
    status_filter_redirect = request.form.get('status_filter_redirect', '')
    issue_date_start_filter_redirect = request.form.get('issue_date_start_filter_redirect', '')
    issue_date_end_filter_redirect = request.form.get('issue_date_end_filter_redirect', '')

    redirect_url = url_for('card_management_index', 
                           page=page, keyword=keyword, department=department_filter_redirect,
                           status=status_filter_redirect, issue_date_start=issue_date_start_filter_redirect,
                           issue_date_end=issue_date_end_filter_redirect)

    if not card_ids_str:
        flash("Không có thẻ nào được chọn để thu hồi.", "warning")
        return redirect(redirect_url)
    try:
        card_ids = [int(id_str) for id_str in card_ids_str.split(',') if id_str.strip()]
        if not card_ids: raise ValueError("Danh sách ID thẻ rỗng.")
    except ValueError:
        flash("Định dạng ID thẻ không hợp lệ.", "danger")
        return redirect(redirect_url)

    updated_count = 0
    skipped_count = 0
    cards_to_update = CardRecord.query.filter(CardRecord.id.in_(card_ids)).all()

    if not cards_to_update:
        flash("Không tìm thấy thẻ nào hợp lệ từ danh sách đã chọn.", "warning")
        return redirect(redirect_url)

    utc_now = datetime.now(timezone.utc)
    gmt7 = timezone(timedelta(hours=7))
    timestamp_gmt7_str = utc_now.astimezone(gmt7).strftime('%Y-%m-%d %H:%M')
    user_performing_action = current_user.username if current_user and current_user.is_authenticated else "System"

    for card in cards_to_update:
        if card.status.lower() == 'using': # So sánh không phân biệt hoa thường
            original_user_info = f"{card.user_name_assigned or ''} ({card.user_id_assigned or ''})"
            
            card.status = 'Available'
            card.user_id_assigned = None
            card.user_name_assigned = None
            card.issue_date = None 
            
            # --- GHI NHẬT KÝ VÀO DETAILS ---
            log_entry = f"[{timestamp_gmt7_str} by {user_performing_action}]: Thu hồi từ {original_user_info}."
            if return_details_note:
                log_entry += f" Ghi chú: {return_details_note}"
            
            current_details = card.details or ""
            base_details = current_details.split("\n[")[0].strip() # Lấy phần details gốc

            if base_details:
                 card.details = f"{base_details}\n{log_entry}"
            else:
                 card.details = log_entry
            
            old_log_entries = [line for line in current_details.splitlines() if line.strip().startswith('[') and line.strip() != log_entry]
            if old_log_entries:
                 card.details += "\n" + "\n".join(old_log_entries)
            # --- KẾT THÚC GHI NHẬT KÝ ---
            
            updated_count += 1
            log_audit_action('batch_return_card', 'card_records', card.id,
                             f"User {user_performing_action} returned card {card.card_number} from {original_user_info}. Note: {return_details_note or 'N/A'}")
        else:
            skipped_count += 1
            flash(f"Thẻ '{card.card_number}' không ở trạng thái 'Using' nên không thể thu hồi.", "info")
            
    if updated_count > 0:
        try:
            db.session.commit()
            flash(f"Đã thu hồi thành công {updated_count} thẻ.", "success")
        except Exception as e:
            db.session.rollback()
            logging.error(f"Lỗi khi thu hồi thẻ hàng loạt: {e}", exc_info=True)
            flash("Lỗi CSDL khi thực hiện thu hồi thẻ hàng loạt.", "danger")
    
    return redirect(redirect_url)

@app.route('/cards/import', methods=['POST'])
@login_required
@role_required(['admin', 'card_user'])
def import_cards():
    if 'file' not in request.files:
        flash('Không tìm thấy file trong yêu cầu.', 'danger')
        return redirect(url_for('card_management_index'))
    
    file = request.files['file']
    if file.filename == '':
        flash('Chưa chọn file nào.', 'warning')
        return redirect(url_for('card_management_index'))

    if file and allowed_import_file(file.filename):
        filename = secure_filename(file.filename)
        logging.info(f"User {current_user.username} bắt đầu import thẻ từ file: {filename}")
        
        inserted_count = 0
        updated_count = 0
        skipped_count = 0
        error_details_list = [] 

        try:
            df = pd.read_excel(file, dtype=str, keep_default_na=False) 
            original_columns = df.columns.tolist() # Lưu lại tên cột gốc để debug
            df.columns = df.columns.str.strip().str.lower()
            processed_columns = df.columns.tolist()
            logging.info(f"Import Cards - Original columns: {original_columns}")
            logging.info(f"Import Cards - Processed (lowercased) columns: {processed_columns}")

            # Cập nhật column_mapping để khớp với tên cột trong file Excel (chữ thường, không dấu)
            # và tên trường trong model CardRecord.
            column_mapping = {
                # Tiếng Anh (ưu tiên)
                'card_number': 'card_number',
                'department': 'department',
                'user_id_assigned': 'user_id_assigned',
                'user_name_assigned': 'user_name_assigned',
                'status': 'status',
                'issue_date': 'issue_date',
                'details': 'details',
                
                # Tiếng Việt không dấu (phổ biến)
                'so the': 'card_number',
                'bo phan': 'department',
                'userid nguoi cap': 'user_id_assigned', # Key này sẽ được dùng nếu 'user_id_assigned' không có
                'username nguoi cap': 'user_name_assigned', # Key này sẽ được dùng nếu 'user_name_assigned' không có
                'trang thai': 'status',
                'ngay cap': 'issue_date',
                'chi tiet': 'details',
                'ghi chu': 'details',

                # Tiếng Việt có dấu (ít phổ biến hơn cho tên cột kỹ thuật, nhưng thêm cho chắc)
                'số thẻ': 'card_number', # Có dấu 'ố'
                'bộ phận': 'department',  # Có dấu 'ộ'
                'userid người cấp': 'user_id_assigned', # Có dấu 'ư', 'ờ', 'ấ'
                'username người cấp': 'user_name_assigned', # Có dấu 'ư', 'ờ', 'ấ'
                'trạng thái': 'status', # Có dấu 'ạ', 'á'
                'ngày cấp': 'issue_date', # Có dấu 'à', 'ấ'
                'chi tiết': 'details',   # Có dấu 'ế'
                'ghi chú': 'details'     # Có dấu 'ú'
            }
            
            # Đổi tên cột trong DataFrame dựa trên mapping
            # Tạo một mapping mới chỉ chứa các key có trong df.columns
            actual_rename_mapping = {k: v for k, v in column_mapping.items() if k in df.columns}
            df.rename(columns=actual_rename_mapping, inplace=True)
            renamed_columns = df.columns.tolist()
            logging.info(f"Import Cards - Columns after rename: {renamed_columns}")


            # Kiểm tra các cột bắt buộc sau khi rename (sử dụng tên cột chuẩn của model)
            required_cols_model = ['card_number', 'department'] 
            missing_cols = [col for col in required_cols_model if col not in df.columns]
            if missing_cols:
                flash(f"File Excel thiếu các cột bắt buộc sau khi chuẩn hóa: {', '.join(missing_cols)}. Các cột tìm thấy sau khi xử lý: {df.columns.tolist()}", 'danger')
                logging.error(f"Import cards failed: Missing required columns after rename: {missing_cols}. Found columns: {df.columns.tolist()}")
                return redirect(url_for('card_management_index'))

            utc_now_import = datetime.now(timezone.utc) 
            gmt7_import = timezone(timedelta(hours=7))
            timestamp_gmt7_str_import = utc_now_import.astimezone(gmt7_import).strftime('%Y-%m-%d %H:%M')
            user_performing_action_import = current_user.username if current_user and current_user.is_authenticated else "System"

            for index, row in df.iterrows():
                row_num = index + 2
                # Lấy dữ liệu bằng tên cột đã được chuẩn hóa (tên trường trong model)
                card_number_excel = str(row.get('card_number', '')).strip()
                department_excel = str(row.get('department', '')).strip()

                if not card_number_excel or not department_excel:
                    error_details_list.append(f"Dòng {row_num}: Thiếu 'Số Thẻ' hoặc 'Bộ Phận'. Bỏ qua.")
                    skipped_count += 1
                    continue
                
                # Lấy user_id_assigned và user_name_assigned, đảm bảo là None nếu rỗng
                # Sử dụng tên cột chuẩn của model (đã được rename)
                user_id_assigned_excel = str(row.get('user_id_assigned', '')).strip()
                user_id_assigned_excel = user_id_assigned_excel if user_id_assigned_excel else None

                user_name_assigned_excel = str(row.get('user_name_assigned', '')).strip()
                user_name_assigned_excel = user_name_assigned_excel if user_name_assigned_excel else None
                
                logging.debug(f"Row {row_num} data: card_number='{card_number_excel}', user_id_assigned='{user_id_assigned_excel}', user_name_assigned='{user_name_assigned_excel}'")

                status_excel_raw = str(row.get('status', '')).strip()
                issue_date_str_excel = str(row.get('issue_date', '')).strip()
                details_excel_raw = str(row.get('details', '')).strip()
                details_excel_raw = details_excel_raw if details_excel_raw else None


                status_excel = 'Available' 
                if status_excel_raw: 
                    if status_excel_raw.lower() in ['available', 'using', 'lost']:
                        status_excel = status_excel_raw.capitalize() 
                    else:
                        error_details_list.append(f"Dòng {row_num} (Thẻ: {card_number_excel}): Trạng thái '{status_excel_raw}' không hợp lệ. Sẽ dùng 'Available'.")
                
                issue_date_db_excel = None
                if issue_date_str_excel:
                    issue_date_db_excel = format_date_for_storage(issue_date_str_excel)
                    if not issue_date_db_excel:
                        error_details_list.append(f"Dòng {row_num} (Thẻ: {card_number_excel}): Định dạng ngày cấp '{issue_date_str_excel}' không hợp lệ. Bỏ qua ngày cấp.")
                
                if status_excel == 'Using':
                    if not user_id_assigned_excel: 
                        error_details_list.append(f"Dòng {row_num} (Thẻ: {card_number_excel}): UserID là bắt buộc khi trạng thái là 'Using'. Thẻ sẽ được đặt là 'Available'.")
                        status_excel = 'Available'
                    if not user_name_assigned_excel: 
                        error_details_list.append(f"Dòng {row_num} (Thẻ: {card_number_excel}): UserName là bắt buộc khi trạng thái là 'Using'. Thẻ sẽ được đặt là 'Available'.")
                        status_excel = 'Available'
                    if not issue_date_db_excel: 
                        error_details_list.append(f"Dòng {row_num} (Thẻ: {card_number_excel}): Ngày cấp hợp lệ là bắt buộc khi trạng thái là 'Using'. Thẻ sẽ được đặt là 'Available'.")
                        status_excel = 'Available'
                
                if status_excel != 'Using':
                    user_id_assigned_excel = None
                    user_name_assigned_excel = None
                    if status_excel == 'Available': 
                        issue_date_db_excel = None

                card = CardRecord.query.filter_by(card_number=card_number_excel).first()
                log_import_details = "" 

                if card: 
                    action_type = "Cập nhật"
                    if card.status != status_excel or \
                       card.user_id_assigned != user_id_assigned_excel or \
                       card.user_name_assigned != user_name_assigned_excel or \
                       card.department != department_excel or \
                       card.issue_date != issue_date_db_excel: # Thêm kiểm tra thay đổi department và issue_date
                        log_parts = []
                        if card.department != department_excel:
                            log_parts.append(f"bộ phận từ '{card.department}' thành '{department_excel}'")
                        if card.status != status_excel:
                            log_parts.append(f"trạng thái từ '{card.status}' thành '{status_excel}'")
                        
                        if status_excel == 'Using':
                            if card.user_id_assigned != user_id_assigned_excel:
                                log_parts.append(f"UserID từ '{card.user_id_assigned or 'N/A'}' thành '{user_id_assigned_excel or 'N/A'}'")
                            if card.user_name_assigned != user_name_assigned_excel:
                                log_parts.append(f"UserName từ '{card.user_name_assigned or 'N/A'}' thành '{user_name_assigned_excel or 'N/A'}'")
                            if card.issue_date != issue_date_db_excel:
                                old_date_str = card.issue_date.strftime('%d/%m/%Y') if card.issue_date else 'N/A'
                                new_date_str = issue_date_db_excel.strftime('%d/%m/%Y') if issue_date_db_excel else 'N/A'
                                log_parts.append(f"ngày cấp từ '{old_date_str}' thành '{new_date_str}'")
                        elif status_excel == 'Available' and card.status == 'Using':
                            log_parts.append(f"thu hồi từ {card.user_name_assigned or ''} ({card.user_id_assigned or 'N/A'})")
                        elif status_excel == 'Lost' and card.status == 'Using':
                            log_parts.append(f"báo mất từ {card.user_name_assigned or ''} ({card.user_id_assigned or 'N/A'})")
                        
                        if log_parts:
                             log_import_details = f"[{timestamp_gmt7_str_import} by {user_performing_action_import} via Import]: {', '.join(log_parts)}."
                    
                    card.department = department_excel
                    card.user_id_assigned = user_id_assigned_excel 
                    card.user_name_assigned = user_name_assigned_excel 
                    card.status = status_excel
                    card.issue_date = issue_date_db_excel
                    
                    current_card_details = card.details or ""
                    manual_card_details_part = current_card_details.split("\n[")[0].strip()
                    auto_card_log_part = "\n".join([line for line in current_card_details.splitlines() if line.strip().startswith('[')])

                    final_details_parts_import = []
                    if details_excel_raw is not None and details_excel_raw != manual_card_details_part: 
                        final_details_parts_import.append(details_excel_raw)
                    elif manual_card_details_part: 
                        final_details_parts_import.append(manual_card_details_part)

                    if log_import_details:
                        final_details_parts_import.append(log_import_details)
                    
                    if auto_card_log_part and log_import_details not in auto_card_log_part: 
                        filtered_old_logs_import = [log for log in auto_card_log_part.splitlines() if log.strip() != log_import_details.strip()]
                        if filtered_old_logs_import:
                            final_details_parts_import.append("\n".join(filtered_old_logs_import))
                    
                    card.details = "\n".join(filter(None, final_details_parts_import)).strip() or None
                    updated_count += 1
                    log_audit_action('import_update_card', 'card_records', card.id, 
                                     f"User {current_user.username} updated card {card_number_excel} via import. New status: {status_excel}. UserID: {user_id_assigned_excel}, UserName: {user_name_assigned_excel}. Log: {log_import_details or 'No changes detected to log'}")
                else: 
                    action_type = "Thêm mới"
                    if status_excel == 'Using':
                        log_import_details = f"[{timestamp_gmt7_str_import} by {user_performing_action_import} via Import]: Gán cho {user_name_assigned_excel or ''} ({user_id_assigned_excel or ''})."
                    elif status_excel == 'Lost':
                         log_import_details = f"[{timestamp_gmt7_str_import} by {user_performing_action_import} via Import]: Thẻ được thêm với trạng thái Mất."
                    
                    final_details_new_card = details_excel_raw or ""
                    if log_import_details:
                        if final_details_new_card:
                            final_details_new_card += f"\n{log_import_details}"
                        else:
                            final_details_new_card = log_import_details
                    
                    card = CardRecord(
                        card_number=card_number_excel,
                        department=department_excel,
                        user_id_assigned=user_id_assigned_excel, 
                        user_name_assigned=user_name_assigned_excel, 
                        status=status_excel,
                        issue_date=issue_date_db_excel,
                        details=final_details_new_card.strip() or None
                    )
                    db.session.add(card)
                    inserted_count += 1
                    db.session.flush() 
                    log_audit_action('import_insert_card', 'card_records', card.id, 
                                     f"User {current_user.username} inserted card {card_number_excel} via import. Status: {status_excel}. UserID: {user_id_assigned_excel}, UserName: {user_name_assigned_excel}. Log: {log_import_details or 'No specific log for new card'}")
                
                logging.info(f"Import Card - {action_type}: {card_number_excel}, Dept: {department_excel}, Status: {status_excel}, UserID: {user_id_assigned_excel}, UserName: {user_name_assigned_excel}, Date: {issue_date_db_excel}, Details Log: {log_import_details or 'N/A'}")

            db.session.commit()
            flash_message = f"Import hoàn tất từ file '{filename}': "
            if inserted_count > 0: flash_message += f"Đã thêm mới {inserted_count} thẻ. "
            if updated_count > 0: flash_message += f"Đã cập nhật {updated_count} thẻ. "
            if skipped_count > 0: flash_message += f"Đã bỏ qua {skipped_count} dòng do thiếu thông tin hoặc lỗi. "
            
            flash(flash_message.strip(), 'success')

            if error_details_list:
                flash("Một số cảnh báo/lỗi chi tiết trong quá trình import:", 'warning')
                for detail in error_details_list[:10]: 
                    flash(f"- {detail}", 'warning')
                if len(error_details_list) > 10:
                    flash("- ... và các cảnh báo/lỗi khác (kiểm tra log để biết thêm).", 'warning')
            
            log_audit_action('import_cards_completed', 'card_records', None, 
                             f"User {current_user.username} completed import from {filename}. Inserted: {inserted_count}, Updated: {updated_count}, Skipped: {skipped_count}, Warnings/Errors: {len(error_details_list)}")

        except pd.errors.EmptyDataError:
            flash("Lỗi: File Excel rỗng hoặc không có dữ liệu.", 'danger')
            logging.error(f"Import cards failed: Empty Excel file '{filename}'.")
        except Exception as e:
            db.session.rollback()
            logging.error(f"Lỗi nghiêm trọng khi import thẻ từ file {filename}: {e}", exc_info=True)
            flash(f"Đã xảy ra lỗi không mong muốn trong quá trình nhập file: {str(e)}", "danger")
            log_audit_action('import_cards_failed', 'card_records', None, 
                             f"User {current_user.username} failed import from {filename}: {str(e)}")
    else:
        flash('Định dạng file không hợp lệ. Chỉ chấp nhận file .xlsx', 'danger')

    return redirect(url_for('card_management_index'))

@app.route('/cards/export/<string:format>', methods=['GET'])
@login_required
@role_required(['admin', 'card_user'])
# @role_required(['admin', 'card_manager']) # Cân nhắc phân quyền nếu cần
def export_card_data(format):
    # Lấy các tham số lọc từ URL query string
    keyword = request.args.get('keyword', default='', type=str).strip()
    department = request.args.get('department', default='', type=str).strip()
    status = request.args.get('status', default='', type=str).strip()
    issue_date_start_str = request.args.get('issue_date_start', default='', type=str).strip()
    issue_date_end_str = request.args.get('issue_date_end', default='', type=str).strip()

    try:
        query = CardRecord.query # Bắt đầu query từ model CardRecord

        # Áp dụng các bộ lọc hiện tại (tương tự như trong card_management_index)
        # Đảm bảo bạn có hàm build_card_filters_orm và nó hoạt động chính xác
        # Hàm này nên trả về một list các điều kiện SQLAlchemy
        filters_orm = build_card_filters_orm(keyword, department, status, issue_date_start_str, issue_date_end_str)
        if filters_orm:
            query = query.filter(and_(*filters_orm)) # Sử dụng and_ để kết hợp các điều kiện
        
        # Sắp xếp kết quả (ví dụ: theo ngày tạo mới nhất)
        query = query.order_by(desc(CardRecord.created_at))
        cards_to_export = query.all() # Lấy tất cả các bản ghi phù hợp

        if not cards_to_export:
            flash("Không có dữ liệu thẻ nào phù hợp với bộ lọc để xuất.", 'info')
            # Redirect về trang quản lý thẻ với các filter hiện tại
            return redirect(url_for('card_management_index', 
                                    keyword=keyword, 
                                    department=department, 
                                    status=status, 
                                    issue_date_start=issue_date_start_str, 
                                    issue_date_end=issue_date_end_str))

        # Chuẩn bị dữ liệu cho DataFrame Pandas
        data_for_df = []
        for card in cards_to_export:
            data_for_df.append({
                'Số Thẻ': card.card_number,
                'Bộ Phận': card.department,
                'UserID Người Cấp': card.user_id_assigned or '',
                'UserName Người Cấp': card.user_name_assigned or '',
                'Trạng Thái': card.status,
                'Ngày Cấp': card.issue_date.strftime('%d/%m/%Y') if card.issue_date else '',
                'Chi Tiết/Ghi Chú': card.details or '',
                'Ngày Tạo': card.created_at.strftime('%d/%m/%Y %H:%M:%S') if card.created_at else '',
                'Ngày Cập Nhật': card.updated_at.strftime('%d/%m/%Y %H:%M:%S') if card.updated_at else ''
            })
        
        df = pd.DataFrame(data_for_df) # Tạo DataFrame
        output = io.BytesIO() # Tạo một buffer BytesIO để lưu file trong memory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S") # Timestamp cho tên file
        
        filename_prefix = 'danh_sach_the'
        mimetype_resp = '' # Khởi tạo mimetype

        if format.lower() == 'excel':
            filename = f'{filename_prefix}_{timestamp}.xlsx'
            mimetype_resp ='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            # Sử dụng ExcelWriter để có thể tùy chỉnh sheet
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                 df.to_excel(writer, index=False, sheet_name='DanhSachThe')
                 worksheet = writer.sheets['DanhSachThe']
                 # Tự động điều chỉnh độ rộng cột
                 for column_cells in worksheet.columns:
                     try:
                         length = max(len(str(cell.value)) for cell in column_cells if cell.value is not None)
                         col_letter = column_cells[0].column_letter # Lấy ký tự cột (A, B, C...)
                         # Đặt độ rộng, có giới hạn min và max
                         worksheet.column_dimensions[col_letter].width = min(max(length + 2, 15), 50) 
                     except Exception as e_width:
                         logging.warning(f"Lỗi chỉnh độ rộng cột {column_cells[0].column_letter if column_cells else 'N/A'} khi export thẻ: {e_width}")
                         pass # Bỏ qua nếu cột rỗng hoặc có lỗi
        elif format.lower() == 'csv':
            filename = f'{filename_prefix}_{timestamp}.csv'
            # Đảm bảo CSV được mã hóa UTF-8 (đặc biệt với BOM cho Excel đọc tiếng Việt)
            csv_data = df.to_csv(index=False, encoding='utf-8-sig', sep=',') 
            output.write(csv_data.encode('utf-8-sig')) # Ghi byte vào BytesIO
            mimetype_resp ='text/csv; charset=utf-8-sig'
        else:
            flash('Định dạng export không hỗ trợ. Chỉ chấp nhận "excel" hoặc "csv".', 'warning')
            return redirect(url_for('card_management_index', 
                                    keyword=keyword, department=department, status=status, 
                                    issue_date_start=issue_date_start_str, issue_date_end=issue_date_end_str))

        output.seek(0) # Đưa con trỏ về đầu buffer
        
        # Ghi log hành động export
        log_audit_action('export_card_data', 
                         target_table='card_records', 
                         target_id=None, 
                         details=f"User {current_user.username} exported {len(cards_to_export)} card records (format: {format}). Filters: K={keyword},D={department},S={status},DS={issue_date_start_str},DE={issue_date_end_str}")
        
        # Gửi file về cho người dùng
        return send_file(output, mimetype=mimetype_resp, download_name=filename, as_attachment=True)

    except Exception as e:
        logging.error(f"Lỗi khi export dữ liệu thẻ (format {format}): {e}", exc_info=True)
        flash(f"Lỗi tạo file export thẻ: {str(e)}", "danger")
        # Redirect về trang quản lý thẻ với các filter hiện tại nếu có lỗi
        return redirect(url_for('card_management_index', 
                                keyword=keyword, department=department, status=status, 
                                issue_date_start=issue_date_start_str, issue_date_end=issue_date_end_str))

# === HÀM CHỈNH SỬA THẺ (edit_card_record) ===
@app.route('/cards/edit/<int:card_id>', methods=['POST'])
@login_required
@role_required(['admin', 'card_user'])
def edit_card_record(card_id):
    card_to_edit = db.session.get(CardRecord, card_id)

    page = request.args.get('page', 1, type=int)
    keyword = request.args.get('keyword', '')
    department_filter = request.args.get('department', '')
    status_filter_arg = request.args.get('status', '') # Đổi tên để tránh xung đột với biến status
    issue_date_start_filter = request.args.get('issue_date_start', '')
    issue_date_end_filter = request.args.get('issue_date_end', '')

    redirect_url = url_for('card_management_index',
                           page=page,
                           keyword=keyword,
                           department=department_filter,
                           status=status_filter_arg, # Sử dụng tên đã đổi
                           issue_date_start=issue_date_start_filter,
                           issue_date_end=issue_date_end_filter)

    if not card_to_edit:
        flash(f"Không tìm thấy thẻ với ID {card_id} để chỉnh sửa.", "warning")
        return redirect(redirect_url)

    if request.method == 'POST':
        original_status = card_to_edit.status
        original_user_id = card_to_edit.user_id_assigned
        original_user_name = card_to_edit.user_name_assigned
        original_issue_date = card_to_edit.issue_date

        new_card_number = request.form.get('card_number', '').strip()
        new_department = request.form.get('department', '').strip()
        new_user_id_assigned = request.form.get('user_id_assigned', '').strip() or None
        new_user_name_assigned = request.form.get('user_name_assigned', '').strip() or None
        new_status = request.form.get('status', '').strip()
        new_issue_date_str = request.form.get('issue_date', '').strip()
        new_details_from_form = request.form.get('details', '').strip() or None

        errors = []
        if not new_card_number: errors.append("Số thẻ là bắt buộc.")
        elif new_card_number != card_to_edit.card_number:
            existing_card = CardRecord.query.filter(CardRecord.card_number == new_card_number, CardRecord.id != card_id).first()
            if existing_card: errors.append(f"Số thẻ '{new_card_number}' đã tồn tại.")
        
        if not new_department: errors.append("Bộ phận là bắt buộc.")
        
        # Cập nhật kiểm tra trạng thái để bao gồm 'Lost'
        if new_status not in ['Available', 'Using', 'Lost']:
            errors.append("Trạng thái thẻ không hợp lệ. Chỉ chấp nhận 'Available', 'Using', hoặc 'Lost'.")
            new_status = original_status # Giữ lại trạng thái cũ nếu nhập sai

        new_issue_date_db = original_issue_date # Giữ lại ngày cấp cũ nếu không có thay đổi
        if new_issue_date_str: # Nếu người dùng nhập ngày mới
            parsed_date = format_date_for_storage(new_issue_date_str)
            if not parsed_date: 
                errors.append(f"Định dạng ngày cấp '{new_issue_date_str}' không hợp lệ.")
            else: 
                new_issue_date_db = parsed_date
        elif not new_issue_date_str and new_status == 'Using' and not original_issue_date: 
            # Nếu chuyển sang Using, không có ngày mới và cũng không có ngày cũ -> lỗi
            errors.append("Ngày cấp là bắt buộc khi trạng thái là 'Using'.")


        # Logic xử lý dựa trên trạng thái mới
        if new_status == 'Using':
            if not new_user_id_assigned: errors.append("UserID người được cấp là bắt buộc khi trạng thái là 'Using'.")
            if not new_user_name_assigned: errors.append("UserName người được cấp là bắt buộc khi trạng thái là 'Using'.")
            if not new_issue_date_db: errors.append("Ngày cấp hợp lệ là bắt buộc khi trạng thái là 'Using'.")
        elif new_status == 'Available':
            new_user_id_assigned = None
            new_user_name_assigned = None
            new_issue_date_db = None # Thẻ Available không có ngày cấp
        elif new_status == 'Lost':
            new_user_id_assigned = None
            new_user_name_assigned = None
            # new_issue_date_db = None # Tùy chọn: Xóa ngày cấp khi báo mất, hoặc giữ lại ngày cấp cuối cùng.
                                     # Hiện tại, nếu ngày cấp được nhập vào form, nó sẽ được giữ. Nếu không, ngày cấp cũ sẽ được giữ (nếu có).
                                     # Nếu muốn xóa ngày cấp khi chuyển sang Lost, thêm: new_issue_date_db = None ở đây.

        if errors:
            for error in errors: flash(error, 'danger')
            # Không redirect ở đây, để template edit có thể hiển thị lại form với lỗi
            # Cần truyền lại các giá trị cho template edit nếu muốn giữ lại input của người dùng
            # Tuy nhiên, với cấu trúc hiện tại, redirect về danh sách là đơn giản hơn
            return redirect(redirect_url) 
        
        # --- GHI NHẬT KÝ VÀO DETAILS ---
        log_entry_details = ""
        utc_now = datetime.now(timezone.utc)
        gmt7 = timezone(timedelta(hours=7))
        timestamp_gmt7_str = utc_now.astimezone(gmt7).strftime('%Y-%m-%d %H:%M')
        user_performing_action = current_user.username if current_user and current_user.is_authenticated else "System"

        if new_status == 'Using' and original_status != 'Using': # Gán mới hoặc từ Lost/Available sang Using
            log_entry_details = f"[{timestamp_gmt7_str} by {user_performing_action}]: Gán cho {new_user_name_assigned or ''} ({new_user_id_assigned or ''})."
        elif new_status == 'Available' and original_status == 'Using': # Thu hồi từ Using
            log_entry_details = f"[{timestamp_gmt7_str} by {user_performing_action}]: Thu hồi từ {original_user_name or ''} ({original_user_id or ''})."
        elif new_status == 'Lost' and original_status != 'Lost': # Báo mất (từ Available hoặc Using)
            log_entry_details = f"[{timestamp_gmt7_str} by {user_performing_action}]: Thẻ được báo mất (trước đó: {original_status})."
            if original_status == 'Using' and original_user_name:
                 log_entry_details += f" Người dùng cuối: {original_user_name} ({original_user_id or 'N/A'})."
        elif new_status != original_status: # Các thay đổi trạng thái khác không cụ thể ở trên
             log_entry_details = f"[{timestamp_gmt7_str} by {user_performing_action}]: Trạng thái đổi từ '{original_status}' thành '{new_status}'."
        
        # Xử lý nếu người dùng thay đổi thông tin người được cấp khi thẻ vẫn là 'Using'
        if new_status == 'Using' and original_status == 'Using':
            changed_fields = []
            if new_user_id_assigned != original_user_id: changed_fields.append(f"UserID từ '{original_user_id or 'N/A'}' thành '{new_user_id_assigned or 'N/A'}'")
            if new_user_name_assigned != original_user_name: changed_fields.append(f"UserName từ '{original_user_name or 'N/A'}' thành '{new_user_name_assigned or 'N/A'}'")
            if new_issue_date_db != original_issue_date:
                original_date_str = original_issue_date.strftime('%d/%m/%Y') if original_issue_date else 'N/A'
                new_date_str = new_issue_date_db.strftime('%d/%m/%Y') if new_issue_date_db else 'N/A'
                changed_fields.append(f"Ngày cấp từ '{original_date_str}' thành '{new_date_str}'")
            
            if changed_fields:
                log_entry_details_assignment_change = f"[{timestamp_gmt7_str} by {user_performing_action}]: Cập nhật thông tin cấp phát: {'; '.join(changed_fields)}."
                if log_entry_details: # Nếu đã có log thay đổi trạng thái
                    log_entry_details += f"\n{log_entry_details_assignment_change}"
                else:
                    log_entry_details = log_entry_details_assignment_change


        current_details_text = card_to_edit.details or ""
        # Tách phần details do người dùng nhập và phần log tự động
        manual_details_part = current_details_text.split("\n[")[0].strip()
        auto_log_part = "\n".join([line for line in current_details_text.splitlines() if line.strip().startswith('[')])

        # Nếu người dùng sửa phần details thủ công
        if new_details_from_form is not None and new_details_from_form != manual_details_part:
            final_details_parts = [new_details_from_form]
        else:
            final_details_parts = [manual_details_part] if manual_details_part else []

        if log_entry_details:
            final_details_parts.append(log_entry_details)
        
        if auto_log_part and log_entry_details not in auto_log_part: # Chỉ thêm log cũ nếu log mới không trùng
            # Lọc bỏ log_entry_details nếu nó đã có trong auto_log_part (tránh trùng lặp khi chỉ sửa details)
            filtered_old_logs = [log for log in auto_log_part.splitlines() if log.strip() != log_entry_details.strip()]
            if filtered_old_logs:
                final_details_parts.append("\n".join(filtered_old_logs))
        
        card_to_edit.details = "\n".join(filter(None, final_details_parts)).strip() or None


        card_to_edit.card_number = new_card_number
        card_to_edit.department = new_department
        card_to_edit.user_id_assigned = new_user_id_assigned
        card_to_edit.user_name_assigned = new_user_name_assigned
        card_to_edit.status = new_status
        card_to_edit.issue_date = new_issue_date_db
        
        try:
            db.session.commit()
            flash(f"Đã cập nhật thẻ '{card_to_edit.card_number}' thành công!", 'success')
            log_audit_action('edit_card_record', 'card_records', card_id,
                                f"User {user_performing_action} edited card: {card_to_edit.card_number}. New status: {new_status}. Log detail: {log_entry_details or 'No status/assignment change'}")
        except Exception as e:
            db.session.rollback()
            logging.error(f"Lỗi khi cập nhật thẻ ID {card_id}: {e}", exc_info=True)
            flash(f"Lỗi khi lưu thay đổi cho thẻ: {str(e)}", 'danger')
        
        return redirect(redirect_url)
    else: # GET request (thường không xảy ra vì form edit nằm trong modal của trang danh sách)
        return redirect(redirect_url)


# === THÊM ROUTE MỚI ĐỂ XÓA TOÀN BỘ THẺ ===
@app.route('/cards/delete_all', methods=['POST'])
@login_required
@role_required(['admin']) # Chỉ admin mới có quyền này
def delete_all_cards():
    """Xóa toàn bộ dữ liệu trong bảng CardRecord."""
    password = request.form.get('password')
    # Lấy mật khẩu xóa từ config (nên đặt trong config.py hoặc biến môi trường)
    # Ví dụ: correct_password = current_app.config.get('DELETE_ALL_CARDS_PASSWORD', 'your_strong_default_password_here')
    # Để đơn giản, bạn cần đảm bảo current_app.config['DELETE_PASSWORD'] đã được thiết lập
    correct_password = current_app.config.get('DELETE_PASSWORD') 

    if not correct_password:
        flash('Chức năng xóa toàn bộ thẻ chưa được cấu hình mật khẩu bảo vệ đúng cách.', 'danger')
        current_app.logger.error(f"Attempted delete_all_cards but DELETE_PASSWORD for cards is not properly set or accessible.")
        return redirect(url_for('card_management_index'))

    if not password or password != correct_password:
        flash('Mật khẩu xác nhận không đúng.', 'danger')
        current_app.logger.warning(f"Thất bại xóa toàn bộ thẻ: Sai MK từ IP {request.remote_addr} cho user '{current_user.username}'.")
        log_audit_action('delete_all_cards_failed', 
                         target_table='card_records', 
                         target_id=None, 
                         details=f"User {current_user.username} failed delete all cards: Incorrect password.")
        return redirect(url_for('card_management_index'))

    deleted_count = 0
    try:
        # Xóa tất cả các bản ghi trong bảng CardRecord
        # Lưu ý: Nếu có các bảng khác liên kết với CardRecord qua khóa ngoại và có ràng buộc,
        # bạn cần xử lý các liên kết đó trước hoặc đảm bảo CSDL được cấu hình để xóa theo kiểu cascade.
        num_deleted = CardRecord.query.delete(synchronize_session=False) # synchronize_session=False thường dùng cho delete hàng loạt
        db.session.commit()
        
        deleted_count = num_deleted if num_deleted is not None else 0
        
        flash(f"Đã xóa thành công {deleted_count} bản ghi thẻ.", 'success')
        log_audit_action('delete_all_cards_success', 
                         target_table='card_records', 
                         target_id=None, 
                         details=f"User {current_user.username} deleted {deleted_count} card records.")
        current_app.logger.info(f"User '{current_user.username}' (ID: {current_user.id}) deleted {deleted_count} card records.")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Lỗi khi xóa toàn bộ dữ liệu thẻ cho user {current_user.id}: {e}", exc_info=True)
        flash(f'Lỗi CSDL khi xóa toàn bộ dữ liệu thẻ: {str(e)}', 'danger')
        log_audit_action('delete_all_cards_error', 
                         target_table='card_records', 
                         target_id=None, 
                         details=f"User {current_user.username} encountered error deleting all cards: {str(e)}")

    return redirect(url_for('card_management_index'))

# === THÊM ROUTE MỚI ĐỂ XEM CHI TIẾT THẺ ===
@app.route('/cards/view/<int:card_id>')
@login_required
@role_required(['admin', 'card_user']) # Hoặc quyền phù hợp bạn đã định nghĩa
def view_card_detail(card_id):
    """
    Hiển thị trang chi tiết cho một thẻ CardRecord cụ thể.
    """
    try:
        card = db.session.get(CardRecord, card_id)
        if not card:
            flash(f"Không tìm thấy thẻ với ID {card_id}.", "warning")
            # Chuyển hướng về trang danh sách thẻ, cố gắng giữ lại các filter nếu có
            return redirect(url_for('card_management_index', 
                                    page=request.args.get('page', 1, type=int),
                                    keyword=request.args.get('keyword', ''),
                                    department=request.args.get('department', ''),
                                    status=request.args.get('status', ''),
                                    issue_date_start=request.args.get('issue_date_start', ''),
                                    issue_date_end=request.args.get('issue_date_end', '')
                                    ))
        
        # Lấy các tham số filter và page từ URL để truyền lại cho nút "Quay lại"
        # Các tham số này được truyền từ link của nút "Xem" trong cards_management.html
        # và sẽ được sử dụng trong view_card_detail.html
        current_filters = {
            'page': request.args.get('page', 1, type=int),
            'keyword': request.args.get('keyword', ''),
            'department': request.args.get('department', ''),
            'status': request.args.get('status', ''),
            'issue_date_start': request.args.get('issue_date_start', ''),
            'issue_date_end': request.args.get('issue_date_end', '')
        }

        # Ghi log audit (tùy chọn)
        # log_audit_action('view_card_detail', 'card_records', card_id, 
        #                  f"User {current_user.username} viewed card detail: {card.card_number}")

        return render_template('view_card_detail.html', 
                               card=card, 
                               current_filters=current_filters)

    except Exception as e:
        current_app.logger.error(f"Lỗi khi tải trang xem chi tiết thẻ ID {card_id}: {e}", exc_info=True)
        flash('Đã xảy ra lỗi khi tải chi tiết thẻ. Vui lòng thử lại.', 'danger')
        return redirect(url_for('card_management_index'))

# === THÊM ROUTE MỚI ĐỂ BÁO MẤT THẺ ===
@app.route('/cards/report-lost/<int:card_id>', methods=['POST'])
@login_required
@role_required(['admin', 'card_user']) # Hoặc quyền phù hợp
def report_lost_card(card_id):
    card_to_report = db.session.get(CardRecord, card_id)

    # Lấy các tham số để redirect về đúng trang và bộ lọc từ form (nếu có)
    # Giả sử các tham số này được truyền qua hidden input trong form báo mất
    page_str = request.form.get('page', '1')
    try:
        page = int(page_str)
        if page < 1: page = 1
    except ValueError:
        page = 1
        current_app.logger.warning(f"Giá trị 'page' không hợp lệ từ form báo mất: '{page_str}'. Đặt lại thành 1.")

    keyword = request.form.get('keyword', '')
    department_filter = request.form.get('department', '')
    status_filter = request.form.get('status', '') # Có thể là 'Lost' sau khi báo mất
    issue_date_start_filter = request.form.get('issue_date_start', '')
    issue_date_end_filter = request.form.get('issue_date_end', '')
    
    # Tham số redirect URL nên được xây dựng cẩn thận để giữ lại bộ lọc
    # Nếu không có các tham số này trong form, bạn có thể bỏ qua chúng hoặc lấy từ request.referrer
    redirect_url = url_for('card_management_index', 
                           page=page, 
                           keyword=keyword, 
                           department=department_filter, 
                           status=status_filter, 
                           issue_date_start=issue_date_start_filter,
                           issue_date_end=issue_date_end_filter)

    if not card_to_report:
        flash(f"Không tìm thấy thẻ với ID {card_id} để báo mất.", "warning")
        return redirect(redirect_url)

    if card_to_report.status == 'Lost':
        flash(f"Thẻ '{card_to_report.card_number}' đã ở trạng thái 'Lost'.", "info")
        return redirect(redirect_url)

    try:
        original_status = card_to_report.status
        original_user_id = card_to_report.user_id_assigned
        original_user_name = card_to_report.user_name_assigned

        card_to_report.status = 'Lost'
        card_to_report.user_id_assigned = None
        card_to_report.user_name_assigned = None
        # card_to_report.issue_date = None # Ngày cấp có thể giữ lại hoặc xóa tùy yêu cầu

        # Ghi nhận vào details
        utc_now = datetime.now(timezone.utc)
        gmt7 = timezone(timedelta(hours=7))
        timestamp_gmt7_str = utc_now.astimezone(gmt7).strftime('%Y-%m-%d %H:%M')
        user_performing_action = current_user.username if current_user and current_user.is_authenticated else "System"
        
        reason_from_form = request.form.get('lost_reason', 'Không rõ lý do').strip() # Lấy lý do từ form
        log_entry = f"[{timestamp_gmt7_str} by {user_performing_action}]: Báo mất thẻ. Lý do: {reason_from_form}."
        if original_status == 'Using' and original_user_name:
            log_entry += f" (Trước đó được cấp cho: {original_user_name} ({original_user_id or 'N/A'}))."

        current_details = card_to_report.details or ""
        base_details = current_details.split("\n[")[0].strip() # Lấy phần details gốc

        if base_details:
            card_to_report.details = f"{base_details}\n{log_entry}"
        else:
            card_to_report.details = log_entry
        
        old_log_entries = [line for line in current_details.splitlines() if line.strip().startswith('[') and line.strip() != log_entry]
        if old_log_entries:
            card_to_report.details += "\n" + "\n".join(old_log_entries)
        
        card_to_report.details = card_to_report.details.strip()

        db.session.commit()
        flash(f"Đã báo mất thẻ '{card_to_report.card_number}' thành công.", 'success')
        log_audit_action('report_lost_card', 'card_records', card_id,
                         f"User {user_performing_action} reported card {card_to_report.card_number} as Lost. Reason: {reason_from_form}. Prev status: {original_status}")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Lỗi khi báo mất thẻ ID {card_id}: {e}", exc_info=True)
        flash(f"Lỗi khi xử lý báo mất thẻ: {str(e)}", 'danger')
    
    return redirect(redirect_url)
# === Kết thúc các ROUTES QUẢN LÝ THẺ ===

# === Các ROUTES QUẢN LÝ CHẤM CÔNG SUẤT ĂN ===
def process_timekeeping_file_only(file_path):
    """
    Xử lý "File Kết quả trích xuất từ phần mềm chấm công" (File 2) khi chỉ file này được upload.
    Trích xuất các lượt chấm công thành công và chuẩn bị dữ liệu cho Báo cáo 1 và Báo cáo 2.
    Cấu trúc cột File 2: Date, Device ID, Device, Event, T&A Event, User ID, User, Status.
    CẬP NHẬT: Thêm cột "Số lần chấm thành công" vào Báo cáo 1.
    """
    try:
        df_cham_cong = pd.read_excel(file_path, dtype=str)
        df_cham_cong.columns = df_cham_cong.columns.str.strip().str.lower()
        
        required_cols = ['date', 'event', 'user id', 'user']
        
        missing_cols = [col for col in required_cols if col not in df_cham_cong.columns]
        if missing_cols:
            flash(f"File chấm công thiếu các cột bắt buộc: {', '.join(missing_cols)}.", 'danger')
            logging.error(f"Meal Management (File 2 only): File thiếu cột: {', '.join(missing_cols)}")
            return None, None

        df_success = df_cham_cong[df_cham_cong['event'].astype(str).str.contains('Success', case=False, na=False)].copy()

        if df_success.empty:
            flash("Không tìm thấy bản ghi chấm công thành công nào trong file.", "info")
            return pd.DataFrame(columns=['Số thứ tự', 'Ngày giờ', 'Mã nhân viên', 'Họ tên', 'Số lần chấm thành công']), pd.DataFrame()

        # --- CẬP NHẬT CHO BÁO CÁO 1: Tính "Số lần chấm thành công" ---
        if 'user id' in df_success.columns:
            success_counts = df_success.groupby('user id').size().reset_index(name='Số lần chấm thành công')
            # Đổi tên 'user id' trong success_counts để merge cho đúng
            success_counts.rename(columns={'user id': 'Mã nhân viên'}, inplace=True)
        else:
            # Nếu không có cột 'user id', không thể tính số lần chấm
            success_counts = pd.DataFrame(columns=['Mã nhân viên', 'Số lần chấm thành công'])
            logging.warning("Meal Management (File 2 only): Thiếu cột 'user id' trong df_success để tính số lần chấm thành công.")


        report1_data_raw = df_success[['date', 'user id', 'user']].copy()
        report1_data_raw.rename(columns={
            'date': 'Ngày giờ',
            'user id': 'Mã nhân viên',
            'user': 'Họ tên'
        }, inplace=True)

        # Loại bỏ các bản ghi trùng lặp hoàn toàn TRƯỚC KHI MERGE số lần chấm
        # để mỗi nhân viên chỉ xuất hiện một lần trong bảng chi tiết (với lần chấm đầu tiên hoặc cuối cùng tùy logic sort sau này)
        # Tuy nhiên, yêu cầu là "danh sách các lượt chấm công thành công", nên có thể giữ lại tất cả các lượt.
        # Nếu muốn mỗi nhân viên chỉ 1 dòng trong Report 1, bạn cần quyết định giữ dòng nào (VD: lần chấm sớm nhất/muộn nhất)
        # Hiện tại, để đơn giản và khớp với "danh sách các lượt", ta sẽ merge số lần chấm vào mỗi lượt.
        # Điều này có nghĩa là cột "Số lần chấm thành công" sẽ lặp lại cho cùng một nhân viên nếu họ có nhiều lượt.
        #
        # ĐỂ HIỂN THỊ ĐÚNG YÊU CẦU "Báo cáo 1: Chi tiết Chấm công Thành công" với mỗi dòng là một lượt chấm,
        # và cột "Số lần chấm thành công" hiển thị tổng số lần của User ID đó:
        if not success_counts.empty:
            report1_data = pd.merge(report1_data_raw, success_counts, on='Mã nhân viên', how='left')
            report1_data['Số lần chấm thành công'] = report1_data['Số lần chấm thành công'].fillna(0).astype(int)
        else:
            report1_data = report1_data_raw.copy()
            report1_data['Số lần chấm thành công'] = 0 # Gán mặc định nếu không tính được

        # Sắp xếp report1_data (ví dụ theo ngày giờ, rồi đến mã nhân viên)
        # Cần parse 'Ngày giờ' sang datetime để sort đúng
        def parse_datetime_for_sort(datetime_str_series):
            # Thử các định dạng phổ biến
            formats_to_try = [
                '%Y-%m-%d %H:%M:%S', '%d/%m/%Y %H:%M', '%m/%d/%Y %H:%M:%S', 
                '%Y-%m-%d %H:%M', '%d/%m/%Y %H:%M:%S', '%m/%d/%Y %H:%M',
                '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y'
            ]
            parsed_series = pd.Series([None] * len(datetime_str_series), index=datetime_str_series.index, dtype='datetime64[ns]')
            for fmt in formats_to_try:
                try:
                    # Chỉ parse những giá trị chưa được parse thành công
                    to_parse_mask = parsed_series.isnull() & datetime_str_series.notnull()
                    if to_parse_mask.any():
                         parsed_values_fmt = pd.to_datetime(datetime_str_series[to_parse_mask], format=fmt, errors='coerce')
                         parsed_series.loc[to_parse_mask & parsed_values_fmt.notnull()] = parsed_values_fmt[parsed_values_fmt.notnull()]
                except Exception: # Bắt lỗi rộng hơn nếu pd.to_datetime có vấn đề với một định dạng cụ thể
                    continue
            return parsed_series

        if 'Ngày giờ' in report1_data.columns:
            report1_data['parsed_ngay_gio_sort'] = parse_datetime_for_sort(report1_data['Ngày giờ'].astype(str))
            report1_data.sort_values(by=['parsed_ngay_gio_sort', 'Mã nhân viên'], inplace=True, na_position='first')
            report1_data.drop(columns=['parsed_ngay_gio_sort'], inplace=True, errors='ignore')


        # Thêm cột Số thứ tự sau khi đã sắp xếp
        report1_data.insert(0, 'Số thứ tự', range(1, len(report1_data) + 1))
        # -----------------------------------------------------------------

        df_summary_shifts = df_success.copy() # df_success đã chứa các lượt chấm công thành công
        
        def parse_datetime_flexible(datetime_str):
            if pd.isna(datetime_str): return None
            formats_to_try = [
                '%Y-%m-%d %H:%M:%S', '%d/%m/%Y %H:%M', '%m/%d/%Y %H:%M:%S', 
                '%Y-%m-%d %H:%M', '%d/%m/%Y %H:%M:%S', '%m/%d/%Y %H:%M',
                '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y'
            ]
            for fmt in formats_to_try:
                try: return datetime.strptime(str(datetime_str), fmt)
                except ValueError: continue
            logging.warning(f"Không thể parse ngày giờ: '{datetime_str}' với các định dạng đã thử.")
            return None

        df_summary_shifts['parsed_datetime'] = df_summary_shifts['date'].apply(parse_datetime_flexible)
        df_summary_shifts.dropna(subset=['parsed_datetime'], inplace=True)

        if df_summary_shifts.empty:
            flash("Không có dữ liệu ngày giờ hợp lệ để tạo báo cáo tóm lược theo ca.", "warning")
            return report1_data, pd.DataFrame(columns=['Ngày', 'Ca', 'Số lượng người thực tế'])


        def assign_shift(dt_object):
            if not isinstance(dt_object, datetime): return "Ngoài ca"
            event_time = dt_object.time()
            if time(11, 0) <= event_time <= time(13, 0): return "Ca sáng"
            elif time(17, 0) <= event_time <= time(18, 0): return "Ca chiều"
            return "Ngoài ca"

        df_summary_shifts['Ca'] = df_summary_shifts['parsed_datetime'].apply(assign_shift)
        df_summary_shifts['Ngày'] = df_summary_shifts['parsed_datetime'].dt.date
        df_summary_shifts_in_shift = df_summary_shifts[df_summary_shifts['Ca'] != 'Ngoài ca'].copy()

        if df_summary_shifts_in_shift.empty:
            flash("Không có dữ liệu chấm công nào thuộc Ca sáng hoặc Ca chiều.", "info")
            return report1_data, pd.DataFrame(columns=['Ngày', 'Ca', 'Số lượng người thực tế'])

        actual_attendance_by_shift = df_summary_shifts_in_shift.groupby(['Ngày', 'Ca'])['user id'].nunique().reset_index()
        actual_attendance_by_shift.rename(columns={'user id': 'Số lượng người thực tế'}, inplace=True)
        
        actual_attendance_by_shift['Ngày'] = pd.to_datetime(actual_attendance_by_shift['Ngày'])
        actual_attendance_by_shift.sort_values(by=['Ngày', 'Ca'], inplace=True)
        actual_attendance_by_shift['Ngày'] = actual_attendance_by_shift['Ngày'].dt.strftime('%d/%m/%Y')

        return report1_data, actual_attendance_by_shift

    except pd.errors.EmptyDataError:
        flash("Lỗi: File chấm công rỗng.", 'danger')
        logging.error(f"Meal Management (File 2 only): File rỗng: {file_path}")
        return None, None
    except Exception as e:
        flash(f"Lỗi xử lý file chấm công: {str(e)}", 'danger')
        logging.error(f"Meal Management (File 2 only): Lỗi xử lý file '{file_path}': {e}", exc_info=True)
        return None, None

def generate_timekeeping_report_excel(report1_data_df, report2_data_df, filename_base="BaoCaoChamCong"):
    """
    Tạo file Excel từ dữ liệu Báo cáo 1 và Báo cáo 2.
    CẬP NHẬT: Bao gồm cột "Số lần chấm thành công" trong Sheet 1.
    """
    try:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            if report1_data_df is not None and not report1_data_df.empty:
                # Đảm bảo cột "Số lần chấm thành công" có mặt trước khi xuất
                cols_report1 = ['Số thứ tự', 'Ngày giờ', 'Mã nhân viên', 'Họ tên', 'Số lần chấm thành công']
                # Lấy các cột thực sự có trong report1_data_df để tránh lỗi KeyError
                existing_cols_report1 = [col for col in cols_report1 if col in report1_data_df.columns]
                report1_data_df[existing_cols_report1].to_excel(writer, sheet_name='ChiTietChamCongThanhCong', index=False)
                
                ws1 = writer.sheets['ChiTietChamCongThanhCong']
                for col_idx, column_name in enumerate(existing_cols_report1): # Lặp qua các cột đã xuất
                    column_letter = ws1.cell(row=1, column=col_idx + 1).column_letter
                    try:
                        # Lấy max length của header và data
                        header_len = len(str(column_name))
                        data_len = max(len(str(cell.value)) for cell in ws1[column_letter] if cell.value is not None and cell.row > 1) if len(ws1[column_letter]) > 1 else 0
                        length = max(header_len, data_len)
                        adjusted_width = min(max(12, length + 2), 50)
                        ws1.column_dimensions[column_letter].width = adjusted_width
                    except Exception as e_width: 
                        logging.warning(f"Excel Report (Sheet1): Lỗi chỉnh độ rộng cột '{column_name}': {e_width}")
            
            if report2_data_df is not None and not report2_data_df.empty:
                report2_data_df_export = report2_data_df.copy()
                report2_data_df_export.insert(2, 'Số lượng người đăng kí', "N/A")

                report2_data_df_export.to_excel(writer, sheet_name='TomLuocSuatAnTheoCa', index=False)
                ws2 = writer.sheets['TomLuocSuatAnTheoCa']
                for col_idx, column_name in enumerate(report2_data_df_export.columns): # Lặp qua các cột đã xuất
                    column_letter = ws2.cell(row=1, column=col_idx + 1).column_letter
                    try:
                        header_len = len(str(column_name))
                        data_len = max(len(str(cell.value)) for cell in ws2[column_letter] if cell.value is not None and cell.row > 1) if len(ws2[column_letter]) > 1 else 0
                        length = max(header_len, data_len)
                        adjusted_width = min(max(12, length + 2), 30)
                        ws2.column_dimensions[column_letter].width = adjusted_width
                    except Exception as e_width: 
                        logging.warning(f"Excel Report (Sheet2): Lỗi chỉnh độ rộng cột '{column_name}': {e_width}")
            
            if (report1_data_df is None or report1_data_df.empty) and \
               (report2_data_df is None or report2_data_df.empty):
                workbook = writer.book
                if not workbook.sheetnames:
                    workbook.create_sheet(title="KhongCoDuLieu")
        
        output.seek(0)
        return output
    except Exception as e:
        flash(f"Lỗi tạo file Excel báo cáo chấm công: {str(e)}", 'danger')
        logging.error(f"Lỗi trong generate_timekeeping_report_excel: {e}", exc_info=True)
        return None

def log_audit_action(action, target_table=None, target_id=None, details=None):
    """
    Ghi lại một hành động của người dùng vào bảng AuditLog.
    """
    # Bỏ qua logging cho các request file tĩnh hoặc file upload trực tiếp để tránh nhiễu
    # và các endpoint không xác định (thường là lỗi 404 trước khi request có endpoint)
    if not request or not hasattr(request, 'endpoint') or not request.endpoint or \
       (request.endpoint.startswith('static') or request.endpoint == 'uploaded_file'):
        return

    try:
        # Lấy địa chỉ IP, xử lý trường hợp có proxy
        ip_addr = request.headers.get('X-Forwarded-For', request.remote_addr)
        if ip_addr and ',' in ip_addr: # Nếu có nhiều IP (qua proxy), lấy IP đầu tiên
            ip_addr = ip_addr.split(',')[0].strip()

        # Lấy user_id từ current_user nếu đã đăng nhập và có thuộc tính id
        user_id_for_log = None
        if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated and hasattr(current_user, 'id'):
            user_id_for_log = current_user.id

        audit_entry = AuditLog(
            user_id=user_id_for_log, 
            ip_address=ip_addr,
            action=action or request.endpoint, # Nếu action không được cung cấp, dùng tên endpoint
            target_table=target_table,
            target_id=target_id,
            details=details
        )
        db.session.add(audit_entry)
        db.session.commit()
    except Exception as e:
        # Rollback session nếu có lỗi xảy ra trong quá trình commit
        try:
            db.session.rollback()
        except Exception as rb_exc:
            logging.error(f"Lỗi khi rollback session trong log_audit_action: {rb_exc}", exc_info=True)
        
        # Ghi log lỗi vào file log của ứng dụng thay vì làm crash app
        logging.error(f"Lỗi khi ghi audit log cho action '{action}': {str(e)}", exc_info=True)
        # Không nên flash message ở đây vì đây là hàm tiện ích nền và có thể được gọi từ nhiều nơi
        # Việc flash message có thể gây ra hành vi không mong muốn nếu hàm được gọi từ một background task.

# --- ROUTE CHÍNH CHO QUẢN LÝ SUẤT ĂN (ĐÃ CẬP NHẬT) ---
@app.route('/meal_management', methods=['GET', 'POST'])
@login_required
@role_required(['admin', 'card_user'])
def meal_management_dashboard():
    report1_paginated_data = None
    report1_pagination_obj = None
    report2_summary_data = None
    # Lấy processing_mode từ session. Đây sẽ là cơ sở để quyết định hiển thị gì.
    current_session_processing_mode = session.get('meal_processing_mode')

    if request.method == 'GET':
        # Nếu người dùng yêu cầu reset, hoặc đây là lần đầu vào trang và không có session cũ
        if request.args.get('action') == 'reset' or \
           ('page' not in request.args and not current_session_processing_mode):
            
            if request.args.get('action') == 'reset':
                logging.info("Meal Management (GET): 'action=reset' detected. Clearing session data.")
            elif not current_session_processing_mode:
                 logging.info("Meal Management (GET): Fresh load (no 'page' arg, no active session). Clearing (though likely already empty).")

            old_temp_report1_filepath = session.pop('temp_report1_filepath', None)
            old_temp_report2_filepath = session.pop('temp_report2_filepath', None)
            session.pop('meal_processing_mode', None)
            current_session_processing_mode = None # Quan trọng: cập nhật biến cục bộ sau khi pop

            if old_temp_report1_filepath and os.path.exists(old_temp_report1_filepath):
                try:
                    os.remove(old_temp_report1_filepath)
                    logging.info(f"Đã xóa file tạm cũ (GET reset/fresh): {old_temp_report1_filepath}")
                except Exception as e_del_old:
                    logging.warning(f"Lỗi khi xóa file tạm cũ {old_temp_report1_filepath} (GET reset/fresh): {e_del_old}")
            if old_temp_report2_filepath and os.path.exists(old_temp_report2_filepath):
                try:
                    os.remove(old_temp_report2_filepath)
                    logging.info(f"Đã xóa file tạm cũ (GET reset/fresh): {old_temp_report2_filepath}")
                except Exception as e_del_old:
                    logging.warning(f"Lỗi khi xóa file tạm cũ {old_temp_report2_filepath} (GET reset/fresh): {e_del_old}")
        # else: current_session_processing_mode giữ nguyên giá trị từ session (cho phân trang hoặc redirect sau POST)

    if request.method == 'POST':
        logging.info("Meal Management (POST): Clearing previous report session data and temp files.")
        old_temp_report1_filepath = session.pop('temp_report1_filepath', None)
        old_temp_report2_filepath = session.pop('temp_report2_filepath', None)
        session.pop('meal_processing_mode', None)
        current_session_processing_mode = None # Reset cho logic POST

        if old_temp_report1_filepath and os.path.exists(old_temp_report1_filepath):
            try: os.remove(old_temp_report1_filepath); logging.info(f"Đã xóa file tạm cũ (POST): {old_temp_report1_filepath}")
            except Exception as e_del_old: logging.warning(f"Lỗi khi xóa file tạm cũ {old_temp_report1_filepath} (POST): {e_del_old}")
        if old_temp_report2_filepath and os.path.exists(old_temp_report2_filepath):
            try: os.remove(old_temp_report2_filepath); logging.info(f"Đã xóa file tạm cũ (POST): {old_temp_report2_filepath}")
            except Exception as e_del_old: logging.warning(f"Lỗi khi xóa file tạm cũ {old_temp_report2_filepath} (POST): {e_del_old}")

        file_dang_ky = request.files.get('file_dang_ky')
        file_cham_cong = request.files.get('file_cham_cong')
        upload_folder_abs = current_app.config.get('UPLOAD_FOLDER_ABSOLUTE')

        if not upload_folder_abs or not os.path.exists(upload_folder_abs):
            flash('Lỗi: Thư mục upload chưa được cấu hình hoặc không tồn tại.', 'danger')
            logging.error("Meal Management: Upload folder not configured or does not exist.")
            return redirect(url_for('meal_management_dashboard', action='reset')) # Redirect với reset

        if file_cham_cong and file_cham_cong.filename and allowed_import_file(file_cham_cong.filename):
            logging.info("Meal Management: Bắt đầu xử lý với File Chấm Công (File 2), lưu vào file tạm.")
            filepath_cham_cong_original = ""
            temp_report1_filename = f"temp_report1_{uuid.uuid4().hex}.csv"
            temp_report2_filename = f"temp_report2_{uuid.uuid4().hex}.csv"
            
            try:
                filename_cham_cong_original_secure = "temp_cham_cong_original_" + datetime.now().strftime("%Y%m%d%H%M%S") + "_" + secure_filename(file_cham_cong.filename)
                filepath_cham_cong_original = os.path.join(upload_folder_abs, filename_cham_cong_original_secure)
                file_cham_cong.save(filepath_cham_cong_original)
                report1_df, report2_df = process_timekeeping_file_only(filepath_cham_cong_original)

                if report1_df is not None and report2_df is not None:
                    temp_report1_full_path = os.path.join(upload_folder_abs, temp_report1_filename)
                    temp_report2_full_path = os.path.join(upload_folder_abs, temp_report2_filename)
                    report1_df.to_csv(temp_report1_full_path, index=False, encoding='utf-8-sig')
                    report2_df.to_csv(temp_report2_full_path, index=False, encoding='utf-8-sig')
                    
                    session['temp_report1_filepath'] = temp_report1_full_path
                    session['temp_report2_filepath'] = temp_report2_full_path
                    session['meal_processing_mode'] = 'timekeeping_only'
                    if not report1_df.empty or not report2_df.empty:
                         flash("Đã xử lý file chấm công. Kết quả sẽ được hiển thị.", "success")
                else: 
                    session['meal_processing_mode'] = None
            except Exception as e:
                logging.error(f"Meal Management (File 2 only with temp files): Lỗi xử lý: {e}", exc_info=True)
                flash(f'Lỗi khi xử lý file chấm công: {str(e)}', 'danger')
                session['meal_processing_mode'] = None
            finally:
                if filepath_cham_cong_original and os.path.exists(filepath_cham_cong_original):
                    try: os.remove(filepath_cham_cong_original)
                    except Exception as e_del_orig: logging.warning(f"Could not delete original uploaded file {filepath_cham_cong_original}: {e_del_orig}")
            return redirect(url_for('meal_management_dashboard')) 

        elif file_dang_ky and file_dang_ky.filename and allowed_import_file(file_dang_ky.filename) and \
             file_cham_cong and file_cham_cong.filename and allowed_import_file(file_cham_cong.filename):
            logging.info("Meal Management: Bắt đầu xử lý với cả File Đăng Ký và File Chấm Công (Logic cũ).")
            # ... (LOGIC CŨ CỦA BẠN, cũng nên set session['meal_processing_mode'] = 'both_files' và redirect) ...
            flash("Logic xử lý cả hai file (cũ) đang được xem xét.", "info")
            return redirect(url_for('meal_management_dashboard'))
        else:
            if not file_cham_cong or not file_cham_cong.filename:
                 flash('Vui lòng tải lên "File Kết quả trích xuất từ phần mềm chấm công".', 'warning')
            # ... (các else if khác cho lỗi upload) ...
            return redirect(url_for('meal_management_dashboard'))

    # --- Phần này thực thi cho GET request (bao gồm cả sau redirect từ POST và phân trang) ---
    # current_session_processing_mode đã được cập nhật ở khối GET ở trên nếu là reset.
    # Nếu là redirect sau POST, nó sẽ lấy giá trị mới từ session.
    # Nếu là phân trang, nó sẽ lấy giá trị từ session.
    if current_session_processing_mode == 'timekeeping_only':
        temp_report1_filepath_from_session = session.get('temp_report1_filepath')
        temp_report2_filepath_from_session = session.get('temp_report2_filepath')

        if temp_report1_filepath_from_session and os.path.exists(temp_report1_filepath_from_session) and \
           temp_report2_filepath_from_session and os.path.exists(temp_report2_filepath_from_session):
            try:
                report1_df_from_file = pd.read_csv(temp_report1_filepath_from_session, keep_default_na=False, na_filter=False)
                report2_df_from_file = pd.read_csv(temp_report2_filepath_from_session, keep_default_na=False, na_filter=False)
                
                if 'Ngày' in report2_df_from_file.columns:
                    try: report2_df_from_file['Ngày'] = pd.to_datetime(report2_df_from_file['Ngày']).dt.strftime('%d/%m/%Y')
                    except Exception as e_date_conv: logging.warning(f"Lỗi chuyển đổi cột 'Ngày' trong report2 khi đọc từ CSV: {e_date_conv}")

                page = request.args.get('page', 1, type=int)
                RECORDS_PER_PAGE_REPORT1 = 5

                if not report1_df_from_file.empty:
                    start_index = (page - 1) * RECORDS_PER_PAGE_REPORT1
                    end_index = start_index + RECORDS_PER_PAGE_REPORT1
                    report1_paginated_data_list = report1_df_from_file.iloc[start_index:end_index].to_dict(orient='records')
                    class SimplePagination: 
                        def __init__(self, page, per_page, total_count, items):
                            self.page = page; self.per_page = per_page; self.total = total_count; self.items = items
                            self.pages = math.ceil(total_count / per_page) if per_page > 0 else 0
                            self.has_prev = page > 1; self.has_next = page < self.pages
                            self.prev_num = page - 1 if self.has_prev else None; self.next_num = page + 1 if self.has_next else None
                        def iter_pages(self, left_edge=2, left_current=2, right_current=2, right_edge=2):
                            last = 0
                            for num in range(1, self.pages + 1):
                                if num <= left_edge or \
                                   (num > self.page - left_current - 1 and num < self.page + right_current + 1) or \
                                   num > self.pages - right_edge:
                                    if last + 1 != num and num != 1 and last !=0 : yield None
                                    yield num; last = num
                            if last != self.pages and self.pages > left_edge + right_edge + left_current + right_current -1 : yield None
                    report1_pagination_obj = SimplePagination(page, RECORDS_PER_PAGE_REPORT1, len(report1_df_from_file), report1_paginated_data_list)
                    report1_paginated_data = report1_paginated_data_list
                else:
                    report1_paginated_data = []; report1_pagination_obj = SimplePagination(1, RECORDS_PER_PAGE_REPORT1, 0, [])
                report2_summary_data = report2_df_from_file.to_dict(orient='records') if not report2_df_from_file.empty else []
            except FileNotFoundError:
                logging.error(f"Meal Management (GET): File tạm không tìm thấy khi tải: {temp_report1_filepath_from_session} hoặc {temp_report2_filepath_from_session}")
                flash("Dữ liệu báo cáo tạm thời không tìm thấy. Vui lòng thử xử lý lại file.", "warning")
                session.pop('temp_report1_filepath', None); session.pop('temp_report2_filepath', None); session.pop('meal_processing_mode', None)
                current_session_processing_mode = None
            except Exception as e_load_temp:
                logging.error(f"Meal Management (GET): Lỗi khi đọc file tạm: {e_load_temp}", exc_info=True)
                flash("Có lỗi khi tải dữ liệu báo cáo từ file tạm. Vui lòng thử xử lý lại file.", "warning")
                session.pop('temp_report1_filepath', None); session.pop('temp_report2_filepath', None); session.pop('meal_processing_mode', None)
                current_session_processing_mode = None
        elif current_session_processing_mode == 'timekeeping_only': # Mode đúng nhưng file/path lỗi
             logging.warning("Meal Management (GET): Mode là 'timekeeping_only' nhưng file tạm không hợp lệ/thiếu.")
             flash("Dữ liệu báo cáo không nhất quán hoặc file tạm đã bị xóa. Vui lòng xử lý lại.", "info")
             session.pop('temp_report1_filepath', None); session.pop('temp_report2_filepath', None); session.pop('meal_processing_mode', None)
             current_session_processing_mode = None

    return render_template('meal_management.html',
                           title="Quản lý Suất Ăn",
                           report1_data=report1_paginated_data,
                           report1_pagination=report1_pagination_obj,
                           report2_data=report2_summary_data,
                           processing_mode=current_session_processing_mode
                          )


# --- ROUTE xuất file báo cáo CHO QUẢN LÝ SUẤT ĂN (ĐÃ CẬP NHẬT) ---
@app.route('/meal_management/export_current_report')
@login_required
@role_required(['admin', 'card_user'])
def export_current_meal_report():
    temp_report1_filepath = session.get('temp_report1_filepath')
    temp_report2_filepath = session.get('temp_report2_filepath')
    current_processing_mode = session.get('meal_processing_mode')

    logging.info(f"Export current report attempt: Mode='{current_processing_mode}', File1Path='{temp_report1_filepath}', File2Path='{temp_report2_filepath}'")
    if temp_report1_filepath:
        logging.info(f"Export: File1 Exists on disk? {os.path.exists(temp_report1_filepath)}")
    if temp_report2_filepath:
        logging.info(f"Export: File2 Exists on disk? {os.path.exists(temp_report2_filepath)}")


    if current_processing_mode == 'timekeeping_only' and \
       temp_report1_filepath and os.path.exists(temp_report1_filepath) and \
       temp_report2_filepath and os.path.exists(temp_report2_filepath):
        
        logging.info(f"Export: Conditions met. Proceeding to read CSVs for Excel generation.")
        try:
            report1_df = pd.read_csv(temp_report1_filepath, keep_default_na=False, na_filter=False)
            report2_df = pd.read_csv(temp_report2_filepath, keep_default_na=False, na_filter=False)
            
            if 'Ngày' in report2_df.columns:
                try:
                    report2_df['Ngày'] = pd.to_datetime(report2_df['Ngày']).dt.strftime('%d/%m/%Y')
                except Exception as e_date_conv_export:
                    logging.warning(f"Lỗi chuyển đổi cột 'Ngày' trong report2 khi export: {e_date_conv_export}")

            excel_output_io = generate_timekeeping_report_excel(report1_df, report2_df)
            if excel_output_io:
                report_filename = f"BaoCaoChamCong_Viewed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                log_audit_action('export_viewed_timekeeping_report', details=f"Exported viewed timekeeping report: {report_filename}")
                logging.info(f"Export: Successfully generated Excel file '{report_filename}'. Sending file.")
                return send_file(
                    excel_output_io,
                    as_attachment=True,
                    download_name=report_filename,
                    mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                )
            else:
                flash("Lỗi khi tạo file Excel từ dữ liệu đã xem.", "danger")
                logging.error("Export: generate_timekeeping_report_excel returned None.")
        except FileNotFoundError:
            logging.error(f"Meal Management (Export): Một hoặc cả hai file tạm không tìm thấy khi xuất: {temp_report1_filepath}, {temp_report2_filepath}")
            flash("Dữ liệu báo cáo tạm thời không tìm thấy để xuất. Vui lòng thử xử lý lại file.", "warning")
        except Exception as e:
            logging.error(f"Meal Management (Export): Lỗi khi xuất báo cáo đã xem từ file tạm: {e}", exc_info=True)
            flash("Có lỗi khi tạo file Excel. Vui lòng thử xử lý lại file.", "danger")
    else:
        log_msg = "Export: Conditions for export not met. "
        if not (current_processing_mode == 'timekeeping_only'):
            log_msg += f"Incorrect mode ('{current_processing_mode}'). "
        if not temp_report1_filepath:
            log_msg += "File1 path missing from session. "
        elif not os.path.exists(temp_report1_filepath):
            log_msg += f"File1 path '{temp_report1_filepath}' does not exist on disk. "
        if not temp_report2_filepath:
            log_msg += "File2 path missing from session. "
        elif not os.path.exists(temp_report2_filepath):
            log_msg += f"File2 path '{temp_report2_filepath}' does not exist on disk. "
        logging.warning(log_msg)
        flash("Không có dữ liệu báo cáo nào trong phiên làm việc hiện tại để xuất hoặc file tạm đã bị xóa. Vui lòng xử lý file trước.", "info")

    return redirect(url_for('meal_management_dashboard'))



# === KẾT THÚC Các ROUTES QUẢN LÝ CHẤM CÔNG SUẤT ĂN ===

# === Chạy ứng dụng ===
if __name__ == '__main__':
    # Kiểm tra thư viện
    missing_libs = []
    try: import pandas; import openpyxl; import flask_sqlalchemy; import flask_migrate; import dateutil
    except ImportError as imp_err: missing_libs = str(imp_err).split("'")[1::2] # Lấy tên thư viện thiếu
    if missing_libs:
        print("="*50 + "\nLỖI: Thiếu thư viện:")
        for lib in missing_libs: print(f"- {lib}")
        print(f"\nCài đặt bằng lệnh:\npip install --upgrade {' '.join(missing_libs)}\n" + "="*50)
        exit()
    # Chạy app
    logging.info("Khởi động ứng dụng Flask...")
    app.run(debug=True, host='0.0.0.0', port=5000)