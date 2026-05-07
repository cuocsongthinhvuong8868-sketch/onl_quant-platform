# onl_quant_platform

Phiên bản deploy online của Quant Platform cho **GitHub + Streamlit Community Cloud**.

## Mục tiêu
- Chạy app trực tiếp từ repo GitHub.
- Dùng `data_lake/` trong repo làm nguồn dữ liệu read-only khi deploy.
- Phù hợp free tier GitHub (không cần dịch vụ lưu trữ ngoài).

## Cấu trúc
- `app.py`: trang chủ
- `pages/`, `tools/`, `shared/`: logic ứng dụng
- `data_lake/`: dữ liệu CSV được commit lên repo
- `tickers.csv`: universe xuyên suốt platform

## Deploy lên Streamlit Cloud
1. Push toàn bộ thư mục `onl_quant_platform` lên GitHub.
2. Vào Streamlit Community Cloud, tạo app mới từ repo đó.
3. Main file path: `app.py`.
4. Deploy.

## Cập nhật dữ liệu (workflow chuẩn)
Vì bản cloud chạy read-only, bạn cập nhật dữ liệu trên máy local rồi commit:
1. Chạy pipeline update ở local (project local quant_platform).
2. Copy/đồng bộ các file mới trong `data_lake/` sang repo `onl_quant_platform/data_lake/`.
3. Commit + push GitHub.
4. Streamlit Cloud tự nhận dữ liệu mới theo commit.

## Lưu ý free tier GitHub
- Tránh commit file > 100MB (GitHub chặn).
- Giữ `data_lake` ở mức gọn, chỉ lưu file cần cho app.
- Không commit `.env`.
