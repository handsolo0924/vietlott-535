# Bàn giao — Vietlott 5/35 Analytics + ML

Đã bổ sung endpoint analytics, Random Forest thử nghiệm, walk-forward backtest, tab Analytics & ML trên dashboard, logging cơ bản và bộ test tự động. Gợi ý ML cần tối thiểu 35 kỳ; backtest mặc định cần hơn 40 kỳ.

Chạy: `pip install -r requirements.txt`, `pytest -q`, `uvicorn main:app --reload`.
Xem `README.md` để biết endpoint, giới hạn thống kê và hướng dẫn Render.

Không có claim về độ chính xác cao. Mọi điểm số chỉ phục vụ phân tích lịch sử; không đảm bảo tăng xác suất trúng.
