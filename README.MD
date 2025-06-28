# Hệ thống Quản lý Tổng Hợp
**Ngày cập nhật:** 18 tháng 6 năm 2025
**Phiên bản:** 2.0

## Mục lục

1.  [Giới thiệu](#1-giới-thiệu)
    * [Mục tiêu Dự án](#mục-tiêu-dự-án)
    * [Tổng quan các Module](#tổng-quan-các-module)
2.  [Công nghệ sử dụng](#2-công-nghệ-sử-dụng)
3.  [Cấu trúc Thư mục](#3-cấu-trúc-thư-mục)
4.  [Kiến trúc Cơ sở dữ liệu](#4-kiến-trúc-cơ-sở-dữ-liệu)
    * [Sơ đồ Quan hệ (ERD) - Mô tả Logic](#sơ-đồ-quan-hệ-erd---mô-tả-logic)
    * [Mô tả Chi tiết các Bảng](#mô-tả-chi-tiết-các-bảng)
5.  [Phân tích Backend (app.py)](#5-phân-tích-backend-apppy)
    * [Luồng Khởi tạo và Cấu hình](#luồng-khởi-tạo-và-cấu-hình)
    * [Kiến trúc Bảo mật: Xác thực, Phân quyền và Cách ly Dữ liệu](#kiến-trúc-bảo-mật-xác-thực-phân-quyền-và-cách-ly-dữ-liệu)
    * [Phân tích Chi tiết các Route theo Module](#phân-tích-chi-tiết-các-route-theo-module)
6.  [Phân tích Frontend (Templates & Static)](#6-phân-tích-frontend-templates--static)
7.  [Các Luồng công việc Chi tiết (Workflows)](#7-các-luồng-công-việc-chi-tiết-workflows)
8.  [Hướng dẫn Cài đặt & Vận hành](#8-hướng-dẫn-cài-đặt--vận-hành)
9.  [Quy trình Đóng góp & Phát triển](#9-quy-trình-đóng-góp--phát-triển)
10. [Logging và Xử lý lỗi](#10-logging-và-xử-lý-lỗi)

---

## 1. Giới thiệu

### Mục tiêu Dự án
Dự án này được xây dựng nhằm giải quyết nhu cầu quản lý tập trung nhiều nghiệp vụ khác nhau trong một tổ chức, từ hạ tầng kỹ thuật, công việc hàng ngày, đến tài chính cá nhân và quản lý nhân sự cấp cơ sở. Mục tiêu chính là cung cấp một công cụ web duy nhất, an toàn, dễ sử dụng, giúp giảm thiểu sai sót, tăng tính minh bạch và cải thiện hiệu quả hoạt động.

### Tổng quan các Module
* **Quản lý Hạ tầng Mạng & Công việc:** Số hóa việc theo dõi tài sản mạng và lịch sử bảo trì, thay thế cho các file Excel phân mảnh.
* **Quản lý Danh mục Đầu tư:** Một công cụ cá nhân hóa cho phép người dùng theo dõi và phân tích hiệu suất đầu tư chứng khoán một cách chi tiết và tự động.
* **Quản lý Thẻ & Suất Ăn:** Các công cụ hỗ trợ nghiệp vụ nhân sự, giúp quản lý việc cấp phát thẻ và đối chiếu suất ăn một cách nhanh chóng.

## 2. Công nghệ sử dụng

* **Backend:**
    * **Python 3 & Flask:** Nền tảng chính, nhẹ và linh hoạt để xây dựng web application.
    * **SQLAlchemy:** ORM (Object-Relational Mapper) mạnh mẽ, giúp tương tác với cơ sở dữ liệu thông qua các đối tượng Python thay vì viết SQL thuần.
    * **Flask-Migrate (Alembic):** Quản lý việc thay đổi và cập nhật schema của cơ sở dữ liệu một cách có phiên bản.
    * **Flask-Login:** Xử lý các tác vụ phức tạp của việc quản lý phiên đăng nhập người dùng (login, logout, session).
    * **Pandas & openpyxl:** Thư viện chủ lực cho các tác vụ xử lý dữ liệu hàng loạt, đặc biệt là đọc và ghi file Excel trong các chức năng Import/Export.
* **Frontend:**
    * **Jinja2:** Template engine tích hợp sẵn trong Flask, cho phép nhúng logic Python vào HTML để tạo các trang web động.
    * **Bootstrap 5:** Framework CSS/JS giúp xây dựng giao diện responsive, hiện đại một cách nhanh chóng.
    * **Chart.js:** Thư viện JavaScript dùng để vẽ các biểu đồ tương tác, trực quan hóa dữ liệu.

## 3. Cấu trúc Thư mục

├── migrations/         # Chứa các script di trú CSDL do Flask-Migrate tạo ra.├── static/             # Chứa các file tĩnh không thay đổi (CSS, JS tùy chỉnh, ảnh giao diện).├── templates/          # Chứa các file mẫu HTML (Jinja2).│   └── navbar.html     # Component thanh điều hướng, được include trong base.html.├── uploads/            # Thư mục lưu trữ file do người dùng tải lên (ảnh, file import).├── app.py              # File trung tâm của ứng dụng: định nghĩa routes, xử lý logic nghiệp vụ.├── config.py           # File cấu hình: chứa các biến như SECRET_KEY, đường dẫn DB, mật khẩu.├── models.py           # Định nghĩa cấu trúc các bảng CSDL dưới dạng các lớp Python (Models).├── requirements.txt    # Liệt kê các thư viện Python cần thiết cho dự án.├── app_errors.log      # File ghi lại các lỗi và cảnh báo của ứng dụng khi hoạt động.└── README.md           # Tài liệu hướng dẫn này.
## 4. Kiến trúc Cơ sở dữ liệu

### Sơ đồ Quan hệ (ERD) - Mô tả Logic
Về mặt logic, CSDL được thiết kế xoay quanh bảng `users`. Mỗi người dùng sở hữu dữ liệu riêng của mình trong các module nghiệp vụ.

* `users` là trung tâm.
* Một `user` có thể có nhiều `records` (thiết bị) và nhiều `work_logs` (nhật ký). Đây là nền tảng của cơ chế **Cách ly Dữ liệu**.
* Một `user` có thể có nhiều `stock_transactions`, `performance_data`, `stock_foreign_daily_data`.
* Một `record` có thể có nhiều `images`.
* Một `work_log` có thể có nhiều `work_log_images`.
* Bảng `card_records` hiện tại đứng độc lập và không có liên kết cứng tới `users`, cho phép quản lý thẻ của toàn bộ tổ chức.
* `audit_logs` ghi lại hành động và có thể liên kết tới `user` đã thực hiện hành động đó.

### Mô tả Chi tiết các Bảng
* **`users`**:
    * `role`: Quyết định các quyền hạn. Các vai trò gồm: `admin`, `stock_user`, `basic_user`, `card_user`, `device_log_user`.
* **`records`**, **`work_logs`**:
    * **`user_id`**: Cột khóa ngoại, liên kết đến `users.id`. Đây là trường **cốt lõi** cho việc phân quyền và đảm bảo người dùng chỉ thấy dữ liệu của mình.
* **`card_records`**:
    * `details`: Trường văn bản này được sử dụng một cách đặc biệt. Ngoài việc lưu ghi chú do người dùng nhập, hệ thống sẽ tự động ghi thêm các dòng log có định dạng `[YYYY-MM-DD HH:MM by username]: Action details.` khi có các sự kiện quan trọng như Gán thẻ, Thu hồi, Báo mất, hoặc Cập nhật qua Import. Điều này tạo ra một lịch sử thay đổi ngay trên bản ghi.
* Các bảng khác có cấu trúc như đã mô tả trong phiên bản trước.

## 5. Phân tích Backend (app.py)

### Luồng Khởi tạo và Cấu hình
Khi ứng dụng khởi động, `app.py` thực hiện các bước sau:
1.  **Tải Cấu hình:** Đọc các biến từ `config.py` (ví dụ: `SECRET_KEY`, `SQLALCHEMY_DATABASE_URI`).
2.  **Khởi tạo Extensions:** Gắn các extension như `SQLAlchemy`, `Migrate`, `LoginManager` vào ứng dụng Flask.
3.  **Định nghĩa User Loader:** Cung cấp hàm `load_user` cho Flask-Login để nó biết cách tìm người dùng trong CSDL ở mỗi request.
4.  **Đăng ký Context Processors & Filters:** Cung cấp các hàm và biến tiện ích cho tất cả các template.
5.  **Đăng ký Blueprints/Routes:** Nạp các định nghĩa route để ứng dụng biết cách xử lý các URL request.

### Kiến trúc Bảo mật: Xác thực, Phân quyền và Cách ly Dữ liệu

Đây là ba lớp bảo vệ của ứng dụng.

1.  **Xác thực (Authentication):** Ai là bạn?
    * Được xử lý bởi Flask-Login.
    * Các route được đánh dấu `@login_required` sẽ tự động chuyển hướng người dùng chưa đăng nhập về trang `/login`.
    * Thông tin người dùng đăng nhập được lưu trong session và có thể truy cập qua biến `current_user`.

2.  **Phân quyền (Authorization):** Bạn được làm gì?
    * Được xử lý bởi decorator tùy chỉnh `@role_required(['role1', 'role2'])`.
    * Decorator này được đặt sau `@login_required`.
    * Nó kiểm tra `current_user.role` có nằm trong danh sách các vai trò được phép không. Nếu không, trả về lỗi 403 Forbidden, ngăn chặn truy cập.

3.  **Cách ly Dữ liệu (Data Isolation):** Bạn được thấy những gì?
    * Đây là lớp bảo vệ sâu nhất, đảm bảo người dùng không thấy dữ liệu của nhau ngay cả khi họ có quyền truy cập vào chức năng.
    * **Ví dụ logic trong `app.py`:**
        ```python
        # Trong route hiển thị danh sách thiết bị
        def index():
            query = Record.query
            # Nếu không phải admin, thêm bộ lọc
            if current_user.role != 'admin':
                query = query.filter(Record.user_id == current_user.id)
            # ... phần còn lại của query
            records = query.all()
            return render_template('index.html', records=records)

        # Trong route thêm mới thiết bị
        def add_record():
            # ... lấy dữ liệu từ form ...
            new_record = Record(
                mac_address=mac,
                # ... các trường khác ...
                user_id=current_user.id # Tự động gán chủ sở hữu
            )
            db.session.add(new_record)
            db.session.commit()
        ```

### Phân tích Chi tiết các Route theo Module
*(Mở rộng từ phiên bản trước)*

* **Quản lý Thiết bị & Công việc:**
    * Các route CRUD (`/add`, `/update`, `/delete`,...) đều tuân thủ nghiêm ngặt 3 lớp bảo mật ở trên.
    * Logic xử lý upload ảnh tạo tên file duy nhất kết hợp ID bản ghi và timestamp để tránh xung đột.

* **Quản lý Chứng khoán:**
    * Route `/stock`: Là route phức tạp nhất, tổng hợp nhiều nguồn dữ liệu:
        1.  Truy vấn giao dịch từ DB.
        2.  Gọi `get_fireant_last_prices()` để lấy giá thị trường.
        3.  Lặp qua các giao dịch để tính P&L hiển thị trên bảng.
        4.  Gọi `calculate_performance_for_listed_symbols()` để có phân tích sâu cho các mã đang mở.
        5.  Truy vấn lịch sử NAV/VNI, tính toán % thay đổi để chuẩn bị dữ liệu cho biểu đồ.
        6.  Tính toán tổng hợp danh mục và XIRR.
        7.  Truyền tất cả dữ liệu đã xử lý vào `stock_journal.html`.
    * Route `/stock/execute_sell/<id>`: Cập nhật một lệnh `BUY` đang `OPENED` thành `CLOSED` và điền thông tin bán.

* **Quản lý Thẻ:**
    * Các route thao tác hàng loạt (`/cards/batch_assign`, `/cards/batch_return`): Nhận một danh sách ID thẻ, lặp qua từng thẻ, kiểm tra điều kiện (ví dụ: thẻ phải `Available` để gán), và cập nhật thông tin.
    * Tất cả các route thay đổi trạng thái thẻ đều thực hiện ghi log tự động vào trường `details` của thẻ.

* **Quản lý Suất Ăn:**
    * Sử dụng `session` của Flask để lưu trạng thái xử lý và đường dẫn đến các file báo cáo tạm thời. Điều này cho phép người dùng xem kết quả, phân trang mà không cần upload lại file.
    * Khi người dùng nhấn "Xử lý", file chấm công sẽ được xử lý bởi `process_timekeeping_file_only`, kết quả (2 DataFrame) được lưu thành 2 file CSV tạm trong thư mục `uploads/`, và đường dẫn được lưu vào `session`. Sau đó, trang được redirect.
    * Khi trang được tải lại (sau redirect hoặc khi phân trang), route sẽ kiểm tra `session`, đọc dữ liệu từ các file CSV tạm và hiển thị.
    * Khi người dùng nhấn "Reset" hoặc truy cập lại từ menu, `session` và các file tạm sẽ bị xóa.

## 6. Tổng quan Frontend (Templates & Static)
* **Luồng Render:** Một request tới URL -> `app.py` tìm route tương ứng -> hàm xử lý của route truy vấn, tính toán dữ liệu -> Dữ liệu được truyền vào `render_template('template.html', data=my_data)` -> Jinja2 trong `template.html` dùng `{{ data }}` và vòng lặp `{% for item in data %}` để dựng lên HTML cuối cùng -> Trình duyệt nhận và hiển thị HTML.
* **Tương tác JavaScript:**
    * **Modal:** Các form phức tạp (thêm, sửa, bán cổ phiếu, gán thẻ...) được đặt trong các modal của Bootstrap để không làm rối giao diện chính. JS được dùng để truyền dữ liệu (ví dụ: ID của bản ghi) vào modal trước khi hiển thị.
    * **Biểu đồ:** `app.py` chuẩn bị dữ liệu (labels, datasets) và truyền vào template dưới dạng chuỗi JSON. JavaScript trong template sẽ parse chuỗi JSON này và dùng Chart.js để vẽ biểu đồ.
    * **Refresh động:** Trang chứng khoán có nút "Làm mới giá", nút này gọi một API endpoint (`/stock/api/get_prices`) bằng JS (fetch), nhận về giá mới và cập nhật giao diện mà không cần tải lại toàn bộ trang.

## 7. Các Luồng công việc chi tiết (Workflows)

1.  **Workflow Phân quyền & Cách ly Dữ liệu:**
    1.  Admin đăng nhập, vào CLI, chạy: `flask create-user mrLinh --role device_log_user`.
    2.  `mrLinh` đăng nhập. `navbar.html` kiểm tra `current_user.role` và chỉ hiển thị menu "Dashboard TB" và "Nhật ký Công việc".
    3.  `mrLinh` vào "Dashboard TB", `app.py` tại route `index()` thực thi `query.filter(Record.user_id == mrLinh.id)`. Danh sách trống.
    4.  `mrLinh` thêm một thiết bị "Router-01". Bản ghi này được lưu vào CSDL với `user_id` của `mrLinh`.
    5.  `mrLinh` tải lại trang, giờ đây anh ta thấy "Router-01" trong danh sách.
    6.  Một `basic_user` khác đăng nhập, cũng vào "Dashboard TB", nhưng câu lệnh `query.filter(Record.user_id == basic_user.id)` của anh ta không trả về "Router-01". Anh ta không thấy dữ liệu của `mrLinh`.
    7.  Admin đăng nhập, vào "Dashboard TB". Vì `current_user.role == 'admin'`, bộ lọc `user_id` bị bỏ qua. Admin thấy tất cả thiết bị, bao gồm cả "Router-01".

2.  **Workflow Quản lý Thẻ từ A-Z:**
    1.  Admin/Card User vào "Quản lý Thẻ", bấm "Thêm Thẻ Mới". Nhập số thẻ, chọn bộ phận. Thẻ được tạo với trạng thái "Available".
    2.  Chọn thẻ vừa tạo và một vài thẻ "Available" khác từ danh sách.
    3.  Bấm "Gán Thẻ Hàng Loạt". Điền thông tin người dùng (UserID, UserName), ngày cấp, bộ phận mới cho các thẻ này.
    4.  Hệ thống cập nhật trạng thái các thẻ thành "Using", điền thông tin người dùng và ghi log "Gán cho..." vào trường `details` của từng thẻ.
    5.  Sau một thời gian, nhân viên đó nghỉ việc. Người quản lý chọn thẻ của nhân viên đó, bấm "Thu Hồi Thẻ".
    6.  Hệ thống cập nhật trạng thái về "Available", xóa thông tin người dùng, ngày cấp và ghi log "Thu hồi từ..." vào `details`.
    7.  Tất cả các thay đổi đều được phản ánh trên các biểu đồ thống kê.

## 8. Hướng dẫn Cài đặt & Vận hành

1.  **Clone Repository & Di chuyển vào thư mục:**
    ```bash
    git clone <repository_url> && cd <project_directory>
    ```
2.  **Tạo và Kích hoạt Môi trường ảo:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # Trên Linux/macOS
    # venv\Scripts\activate    # Trên Windows
    ```
3.  **Cài đặt các Gói Phụ thuộc:**
    ```bash
    pip install -r requirements.txt
    ```
4.  **Cấu hình (`config.py`):**
    * Sao chép `config.py.example` thành `config.py` (nếu có).
    * **CỰC KỲ QUAN TRỌNG:** Mở `config.py` và thay đổi `SECRET_KEY` và `DELETE_PASSWORD` thành các chuỗi ký tự ngẫu nhiên, phức tạp.
5.  **Khởi tạo & Cập nhật Cơ sở dữ liệu:**
    ```bash
    # Chỉ chạy lần đầu tiên nếu chưa có thư mục 'migrations'
    flask db init

    # Sau khi tạo mới hoặc thay đổi models.py, chạy hai lệnh sau
    flask db migrate -m "Mô tả thay đổi, ví dụ: Add user_id to records"
    flask db upgrade
    ```
6.  **Tạo Người dùng Quản trị:**
    ```bash
    flask create-user <tên_admin> --role admin
    # Nhập mật khẩu khi được yêu cầu
    ```
7.  **Chạy ứng dụng (cho môi trường phát triển):**
    ```bash
    flask run --host=0.0.0.0 --port=5000
    ```

## 9. Quy trình Đóng góp & Phát triển

Khi muốn thêm một tính năng mới, một lập trình viên nên tuân theo quy trình sau:

1.  **Phân tích Yêu cầu:** Hiểu rõ yêu cầu nghiệp vụ.
2.  **Model:** Nếu cần lưu dữ liệu mới, mở `models.py` và thêm/sửa các lớp Model.
3.  **Migration:** Chạy `flask db migrate` và `flask db upgrade` để cập nhật CSDL.
4.  **Backend (Route):** Mở `app.py`, tạo một route mới. Viết logic xử lý, truy vấn CSDL, và chuẩn bị dữ liệu. Đừng quên thêm decorator `@login_required` và `@role_required`.
5.  **Frontend (Template):** Tạo một file HTML mới trong `templates/`. Sử dụng Jinja2 để hiển thị dữ liệu được truyền từ backend.
6.  **Điều hướng:** Mở `templates/navbar.html` và thêm một link menu mới trỏ đến route vừa tạo, đặt trong khối `if` kiểm tra vai trò phù hợp.
7.  **Kiểm thử:** Chạy ứng dụng và kiểm tra kỹ lưỡng chức năng ở các vai trò người dùng khác nhau.
8.  **Tài liệu:** Cập nhật file `README.MD` này để phản ánh các thay đổi.

## 10. Logging và Xử lý lỗi

* **File Logging:** Mọi lỗi không mong muốn (`Exception`) và các thông tin hoạt động quan trọng đều được ghi vào `app_errors.log`. Khi có sự cố, đây là nơi đầu tiên cần kiểm tra.
* **Error Handler:** `@app.errorhandler(Exception)` trong `app.py` là một "lưới an toàn cuối cùng". Nó sẽ bắt các lỗi chưa được xử lý, rollback session CSDL (để tránh dữ liệu không nhất quán), ghi log lỗi và hiển thị một trang báo lỗi thân thiện thay vì làm sập ứng dụng.
* **Flash Messages:** Là cơ chế giao tiếp chính với người dùng trên giao diện, thông báo các lỗi validation (ví dụ: "Số thẻ là bắt buộc") hoặc kết quả thành công của một hành động.
