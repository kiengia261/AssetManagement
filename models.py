# === models.py ===
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from datetime import datetime, date # Đảm bảo date được import
from decimal import Decimal
from sqlalchemy import UniqueConstraint, Index # Import UniqueConstraint và Index

db = SQLAlchemy()

# --- Hàm tiện ích ---
def format_date_for_display(date_obj):
    """Định dạng đối tượng date/datetime thành chuỗi dd/mm/YYYY."""
    if not date_obj: return ""
    try:
        # Nếu là datetime, chỉ lấy phần date
        if isinstance(date_obj, datetime):
            date_obj = date_obj.date()
        return date_obj.strftime('%d/%m/%Y')
    except AttributeError: # Xử lý nếu date_obj không phải là đối tượng date/datetime hợp lệ
        try: # Thử xử lý nếu đầu vào là chuỗi YYYY-MM-DD
            dt_obj = datetime.strptime(str(date_obj), '%Y-%m-%d').date()
            return dt_obj.strftime('%d/%m/%Y')
        except ValueError:
             try: # Thử xử lý nếu đầu vào là chuỗi có cả giờ phút
                 dt_obj = datetime.strptime(str(date_obj).split()[0], '%Y-%m-%d').date()
                 return dt_obj.strftime('%d/%m/%Y')
             except (ValueError, TypeError):
                 return str(date_obj) # Trả về chuỗi gốc nếu không thể parse
    except Exception: # Bắt các lỗi khác
        return str(date_obj) # Trả về chuỗi gốc nếu có lỗi khác


# --- Model User (Người dùng) ---
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    # CẬP NHẬT: Thêm vai trò 'device_log_user'
    role = db.Column(db.String(50), nullable=False, default='basic_user') # Vai trò: admin, stock_user, basic_user, card_user, device_log_user

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256', salt_length=16)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def has_role(self, required_role):
        if isinstance(required_role, list):
            return self.role in required_role
        return self.role == required_role

    def __repr__(self):
        return f'<User {self.username} (Role: {self.role})>'

# --- Model Record (Thiết bị) ---
class Record(db.Model):
    __tablename__ = 'records'
    id = db.Column(db.Integer, primary_key=True)
    mac_address = db.Column(db.String(17), unique=True, nullable=False, index=True)
    ip_address = db.Column(db.String(45), nullable=True) # Hỗ trợ IPv6
    username = db.Column(db.String(100), nullable=True)
    device_type = db.Column(db.String(100), nullable=True)
    status = db.Column(db.Text, nullable=True)
    record_date = db.Column(db.Date, nullable=True, index=True)
    details = db.Column(db.Text, nullable=True)
    images = db.relationship('Image', backref='record', lazy='dynamic', cascade="all, delete-orphan")

    # === THÊM MỚI: Thêm user_id để xác định chủ sở hữu ===
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_record_user_id'), nullable=True, index=True)
    owner = db.relationship('User', backref=db.backref('records', lazy='dynamic'))
    # === KẾT THÚC THÊM MỚI ===

    @property
    def record_date_display(self):
        return format_date_for_display(self.record_date)

    @property
    def first_image_path(self):
        first_image = self.images.order_by(Image.id.asc()).first()
        return first_image.image_path if first_image else None

    @property
    def is_valid_ip_format(self):
        import re
        if self.ip_address:
            ip_str = self.ip_address.strip()
            if re.match(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$", ip_str): # IPv4
                parts = ip_str.split('.')
                if len(parts) == 4 and all(0 <= int(p) <= 255 for p in parts):
                    return True
        return False

    def __repr__(self):
        return f'<Record {self.mac_address}>'

# --- Model Image (Ảnh của Thiết bị) ---
class Image(db.Model):
    __tablename__ = 'images'
    id = db.Column(db.Integer, primary_key=True)
    record_id = db.Column(db.Integer, db.ForeignKey('records.id', name='fk_image_record_id', ondelete='CASCADE'), nullable=False, index=True)
    image_path = db.Column(db.String(255), nullable=False)

    def __repr__(self):
        return f'<Image {self.image_path} for Record ID {self.record_id}>'

# --- Model WorkLog (Nhật ký Công việc) ---
class WorkLog(db.Model):
    __tablename__ = 'work_logs'
    id = db.Column(db.Integer, primary_key=True)
    log_date = db.Column(db.Date, nullable=False, index=True)
    activity_type = db.Column(db.String(150), nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    device_identifier = db.Column(db.String(100), nullable=True, index=True)
    cost = db.Column(db.Float, nullable=True, default=0.0)
    technician = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    images = db.relationship('WorkLogImage', backref='work_log', lazy='select', cascade="all, delete-orphan")

    # === THÊM MỚI: Thêm user_id để xác định chủ sở hữu ===
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_worklog_user_id'), nullable=True, index=True)
    owner = db.relationship('User', backref=db.backref('work_logs', lazy='dynamic'))
    # === KẾT THÚC THÊM MỚI ===

    @property
    def log_date_display(self):
        return format_date_for_display(self.log_date)

    @property
    def first_image_path(self):
        if self.images:
             return self.images[0].image_path
        return None

    @property
    def cost_display(self):
        return f"{self.cost:,.0f} ₫" if self.cost is not None else "0 ₫"

    def __repr__(self):
        return f'<WorkLog ID {self.id} - {self.activity_type} on {self.log_date_display}>'


# --- Model WorkLogImage (Ảnh của Nhật ký Công việc) ---
class WorkLogImage(db.Model):
    __tablename__ = 'work_log_images'
    id = db.Column(db.Integer, primary_key=True)
    work_log_id = db.Column(db.Integer, db.ForeignKey('work_logs.id', name='fk_worklogimage_worklog_id', ondelete='CASCADE'), nullable=False, index=True)
    image_path = db.Column(db.String(255), nullable=False)

    def __repr__(self):
        return f'<WorkLogImage {self.image_path} for WorkLog ID {self.work_log_id}>'

# --- Model StockTransaction (Giao dịch Chứng khoán) ---
class StockTransaction(db.Model):
    __tablename__ = 'stock_transactions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_stocktransaction_user_id'), nullable=False, index=True)
    symbol = db.Column(db.String(20), nullable=True, index=True)
    transaction_date = db.Column(db.Date, nullable=False, index=True)
    transaction_type = db.Column(db.String(20), nullable=False, index=True)
    quantity = db.Column(db.Numeric(precision=18, scale=4), nullable=False)
    price = db.Column(db.Numeric(precision=18, scale=4), nullable=False)
    fees = db.Column(db.Numeric(precision=18, scale=4), default=Decimal('0.0'), nullable=False)
    sell_price = db.Column(db.Numeric(precision=18, scale=4), nullable=True)
    sell_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), nullable=True, default=None, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    owner = db.relationship('User', backref=db.backref('stock_transactions', lazy='dynamic', cascade="all, delete-orphan"))

    @property
    def transaction_date_display(self):
        return format_date_for_display(self.transaction_date)

    @property
    def sell_date_display(self):
        return format_date_for_display(self.sell_date) if self.sell_date else None
        
    def __repr__(self):
        status_str = f" Status: {self.status}" if self.status else ""
        return f'<StockTransaction {self.id} User {self.user_id} - {self.transaction_type} {self.symbol or "Cash"} on {self.transaction_date_display}{status_str}>'

# --- Model PerformanceData (Dữ liệu NAV và VNIndex) ---
class PerformanceData(db.Model):
    __tablename__ = 'performance_data'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_performancedata_user_id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    nav_value = db.Column(db.Numeric(precision=20, scale=4), nullable=True)
    vnindex_value = db.Column(db.Numeric(precision=10, scale=2), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('performance_entries', lazy='dynamic', cascade="all, delete-orphan"))

    __table_args__ = (
        UniqueConstraint('user_id', 'date', name='uq_performance_user_date'),
        Index('idx_performance_user_date', 'user_id', 'date'),
    )

    def __repr__(self):
        return f'<PerformanceData User {self.user_id} Date {self.date.strftime("%Y-%m-%d")}: NAV={self.nav_value}, VNIndex={self.vnindex_value}>'

# --- Model StockForeignDailyData (Dữ liệu Giao dịch Nước Ngoài Hàng Ngày) ---
class StockForeignDailyData(db.Model):
    __tablename__ = 'stock_foreign_daily_data'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_foreigndata_user_id'), nullable=False, index=True)
    symbol = db.Column(db.String(20), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    buy_foreign_value = db.Column(db.Numeric(20, 2), nullable=True)
    sell_foreign_value = db.Column(db.Numeric(20, 2), nullable=True)
    net_foreign_value = db.Column(db.Numeric(20, 2), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('foreign_daily_data', lazy='dynamic', cascade="all, delete-orphan"))

    __table_args__ = (UniqueConstraint('user_id', 'symbol', 'date', name='uq_user_symbol_date_foreign_data'),)

    def __repr__(self):
        return f'<StockForeignDailyData User {self.user_id}-{self.symbol}-{self.date.strftime("%Y-%m-%d")}: Net {self.net_foreign_value}>'

# --- Model AuditLog (Nhật ký Kiểm toán) ---
class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_auditlog_user_id_explicit'), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    action = db.Column(db.String(255), nullable=False, index=True)
    target_table = db.Column(db.String(100), nullable=True)
    target_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.Text, nullable=True)

    audited_user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('action_logs', lazy='dynamic'))

    def __repr__(self):
        user_info = f"UserID {self.user_id}" if self.user_id else "System"
        if self.audited_user:
             user_info = f"User {self.audited_user.username}"
        return f'<AuditLog {self.timestamp.strftime("%Y-%m-%d %H:%M:%S")} - {self.action} by {user_info}>'

# --- Model CardRecord (Quản lý Thẻ) ---
class CardRecord(db.Model):
    __tablename__ = 'card_records'

    id = db.Column(db.Integer, primary_key=True)
    card_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    department = db.Column(db.String(100), nullable=False, index=True)
    user_id_assigned = db.Column(db.String(100), nullable=True)
    user_name_assigned = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='Available', index=True)
    issue_date = db.Column(db.Date, nullable=True)
    details = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<CardRecord {self.card_number} - {self.department} - {self.status}>'

    @property
    def issue_date_display(self):
        return format_date_for_display(self.issue_date) if self.issue_date else ''

    @property
    def created_at_display(self):
        return self.created_at.strftime('%d/%m/%Y %H:%M:%S') if self.created_at else ''

    @property
    def updated_at_display(self):
        return self.updated_at.strftime('%d/%m/%Y %H:%M:%S') if self.updated_at else ''
