# Vietlott Lotto 5/35 — Dashboard thống kê

## Chức năng
- Dashboard thống kê 100 kỳ gần nhất
- Phân tích tần suất, số nóng/lạnh, khoảng số, chẵn/lẻ, số đặc biệt
- Gợi ý tổ hợp tham khảo (không phải dự đoán chắc chắn)
- Tự động cập nhật dữ liệu từ nguồn mở
- Nhập CSV dự phòng nếu cần

## Nguồn dữ liệu
Dữ liệu lấy từ **open dataset** [vietvudanh/vietlott-data](https://github.com/vietvudanh/vietlott-data) (NDJSON, cập nhật hàng ngày, MIT license).

Lý do không scrape trực tiếp `vietlott.vn`: trang bị Cloudflare Challenge, scraper cũ dễ hỏng khi HTML thay đổi.

Mỗi kỳ gồm:
- Mã kỳ
- Ngày quay
- 5 số chính (01–35)
- Số đặc biệt (01–12)

## Chạy local (Python 3.10+)

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
uvicorn main:app --reload
```

Mở http://127.0.0.1:8000  
Bấm **Cập nhật kết quả thật** để đồng bộ 100 kỳ.

### Kiểm tra API
```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/draws?limit=5
curl -X POST http://127.0.0.1:8000/api/sync
```

## Triển khai trên Render
1. Đẩy thư mục lên GitHub.
2. Render → New → Blueprint → chọn repo có `render.yaml`.
3. Render cài dependency và chạy FastAPI.
4. Persistent disk `/var/data` lưu SQLite (có thể cần gói trả phí).
5. Mở URL do Render cấp → bấm **Cập nhật kết quả thật**.

### Cập nhật định kỳ
Tạo Cron Job trên Render (hoặc dịch vụ khác) gọi:
```bash
curl -X POST https://TEN-MIEN-CUA-BAN/api/sync
```
Khuyến nghị 1–2 lần/ngày (sau 13h và 21h).

## Xác minh dữ liệu
Trước khi dùng công khai, so sánh ít nhất 3 kỳ gần nhất với:
- https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/535
- hoặc các trang thống kê uy tín (xsmn.net, minhchinh.com…)

## Lưu ý quan trọng
- Thống kê chỉ mô tả quá khứ. Không tăng xác suất trúng.
- Không mua vé / đặt cược dựa trên gợi ý của trang này.
- Nguồn dữ liệu mở có thể chậm vài giờ so với trang chính thức.


## Analytics nâng cao & Machine Learning

### Endpoint mới
- `GET /api/analytics`: tần suất, top cặp/bộ ba đồng xuất hiện, gap hiện tại/trung bình, streak hiện tại và tần suất số đặc biệt.
- `GET /api/model/recommend`: gợi ý từ RandomForestRegressor đa đầu ra.
- `GET /api/model/backtest?min_train=40&max_draws=60`: walk-forward backtest, so sánh số trùng trung bình với baseline tần suất 20 kỳ và kỳ vọng ngẫu nhiên.

### Mô hình và giới hạn
Random Forest dùng các đặc trưng tần suất cửa sổ 20 kỳ, tần suất 5 kỳ, khoảng cách từ lần xuất hiện gần nhất và ngữ cảnh tần suất số đặc biệt. Mô hình chỉ là thử nghiệm xếp hạng, không phải mô hình xác suất đã hiệu chuẩn. Backtest mở rộng cửa sổ huấn luyện theo thời gian: khi dự đoán kỳ *t*, chỉ sử dụng dữ liệu trước *t*. Không shuffle dữ liệu và không đưa kết quả tương lai vào feature.

Kết quả số trùng cần đọc cùng baseline, số kỳ đánh giá và kỳ vọng ngẫu nhiên (5×5/35 ≈ 0,714 số chính mỗi kỳ cho một bộ 5 số cố định). Chênh lệch trên mẫu nhỏ có thể do ngẫu nhiên. Không có bảo đảm cải thiện xác suất trúng; với xổ số công bằng, mọi tổ hợp hợp lệ có xác suất như nhau.

### Chạy test
```bash
pip install -r requirements.txt
pytest -q
```

### Triển khai Render
1. Push toàn bộ thư mục dự án lên GitHub.
2. Render → **New +** → **Blueprint** → chọn repository và áp dụng `render.yaml`.
3. Kiểm tra Build Logs; chờ cài `scikit-learn`.
4. Đảm bảo persistent disk được mount tại `/var/data`; biến `DB_PATH=/var/data/vietlott.db` đã có trong blueprint.
5. Mở URL service, gọi `POST /api/sync`, sau đó kiểm tra `/api/health`, `/api/analytics`.
6. Có thể tạo Render Cron Job gọi `POST https://<service>/api/sync` định kỳ. Không công khai endpoint sync nếu cần kiểm soát truy cập; nên thêm auth/rate limit trước khi mở rộng.

Lưu ý vận hành: SQLite phù hợp dashboard nhỏ và một instance. Với nhiều instance/ghi đồng thời, chuyển sang PostgreSQL. Backtest Random Forest có thể tốn CPU; chạy thủ công khi cần, không chạy ở mỗi request dashboard.
