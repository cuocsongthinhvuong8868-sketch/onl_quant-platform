# 📊 Quant Platform

Nền tảng phân tích định lượng (Quantitative Analysis) cho thị trường chứng khoán Việt Nam, được xây dựng trên **Streamlit**.

🔗 **Deploy trên Streamlit Cloud**: [Hướng dẫn bên dưới](#-deploy-lên-streamlit-cloud)

---

## 🚀 Tính năng chính

| # | Công cụ | Mô tả |
|---|---------|-------|
| 1 | **Fear & Greed Index** | Đánh giá tâm lý thị trường |
| 2 | **Upside Ratio** | Tỷ lệ tăng trưởng tiềm năng |
| 3 | **Risk Adjusted Growth** | Tăng trưởng điều chỉnh theo rủi ro |
| 4 | **Market Breadth** | Độ rộng thị trường |
| 5 | **ESR Monitor** | Theo dõi Earnings Surprise Ratio |
| 6 | **Dispersion** | Phân tán giá & tương quan |
| 7 | **Manipulation Detection** | Phát hiện dấu hiệu thao túng |
| 8 | **AI CIO Report** | Báo cáo tổng hợp bằng AI (Kimi/OpenAI) |

---

## 📁 Cấu trúc thư mục

```
onl_quant_platform/
├── app.py                    # Trang chủ Streamlit
├── config.py                 # Cấu hình toàn cục
├── requirements.txt          # Dependencies
├── tickers.csv               # Danh sách mã cổ phiếu
├── pages/                    # Các trang Streamlit
│   ├── 1_Fear_Greed.py
│   ├── 2_Upside_Ratio.py
│   ├── 3_Risk_Adjusted_Growth.py
│   ├── 4_Market_Breadth.py
│   ├── 5_ESR_Monitor.py
│   ├── 6_Dispersion.py
│   └── 8_Manipulation.py
├── tools/                    # Logic tính toán & UI từng công cụ
├── shared/                   # Module dùng chung (data loader, AI CIO, layout)
├── command/                  # Script cập nhật dữ liệu & báo cáo
├── data_lake/                # Dữ liệu thị trường (CSV)
├── reports/                  # Báo cáo PDF xuất ra
├── promt/                    # Prompt templates cho AI
└── fonts/                    # Font DejaVu cho PDF
```

---

## 🛠️ Cài đặt Local

### 1. Clone repository

```bash
git clone https://github.com/<your-username>/onl_quant_platform.git
cd onl_quant_platform
```

### 2. Tạo môi trường ảo

```bash
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows
```

### 3. Cài dependencies

```bash
pip install -r requirements.txt
```

### 4. Cấu hình biến môi trường

Tạo file `.env` ở thư mục gốc:

```bash
VNSTOCK_API_KEY="your_vnstock_api_key"
```

> ⚠️ **Lưu ý**: File `.env` đã được thêm vào `.gitignore`, đảm bảo không bị commit lên GitHub.
> 
> API Key của Kimi AI không cần đặt trong `.env` — ngườidùng sẽ nhập trực tiếp trên giao diện Streamlit.

### 5. Cập nhật dữ liệu

```bash
python command/update_data.py
```

### 6. Chạy ứng dụng

```bash
streamlit run app.py
```

---

## ☁️ Deploy lên Streamlit Cloud

### Bước 1: Push lên GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<your-username>/<repo-name>.git
git push -u origin main
```

> **Lưu ý quan trọng**: Đảm bảo `.env` không được push lên GitHub. File này đã có trong `.gitignore`.

### Bước 2: Kết nối Streamlit Cloud

1. Truy cập [share.streamlit.io](https://share.streamlit.io)
2. Đăng nhập bằng GitHub
3. Click **"New app"** → Chọn repository của bạn
4. File chính: `app.py`

### Bước 3: Cấu hình Secrets

Trong Streamlit Cloud, vào **Settings → Secrets**, thêm:

```toml
VNSTOCK_API_KEY = "your_vnstock_api_key"
```

> **Lưu ý**: Kimi API Key không bắt buộc trong Secrets vì ngườidùng nhập trực tiếp trên UI. Tuy nhiên, nếu bạn muốn dùng model khác, hãy thêm `AI_MODEL` và `AI_TEMPERATURE`.

### Bước 4: Khởi động lại app

Click **"Reboot"** để áp dụng secrets.

---

## 🔄 Cập nhật dữ liệu thị trường

Dữ liệu không tự động cập nhật trên Streamlit Cloud. Bạn có thể:

- **Cách 1**: Chạy `python command/update_data.py` trên local → push `data_lake/*.csv` lên GitHub
- **Cách 2**: Thêm chức năng "Update Data" vào app (cần xử lý rate limit API và thờigian chạy ~5 phút)

---

## 🧰 Dependencies chính

| Package | Mục đích |
|---------|----------|
| `streamlit` | Web UI |
| `pandas` / `numpy` | Xử lý dữ liệu |
| `plotly` | Biểu đồ tương tác |
| `vnstock` | Dữ liệu chứng khoán VN |
| `openai` | Tích hợp AI CIO |
| `fpdf2` | Xuất báo cáo PDF |
| `arch` / `scikit-learn` | Mô hình định lượng |

---

## ⚠️ Lưu ý

- **Dữ liệu thị trường** trong `data_lake/` được push lên GitHub để app chạy ngay trên Streamlit Cloud. Bạn nên cập nhật thường xuyên.
- **API Key** là bắt buộc cho chức năng AI CIO và cập nhật dữ liệu qua VNStock.
- **Cache**: Các file cache (`.pkl`, `daily_cache/`) đã được loại bỏ và ignore để giữ repo gọn nhẹ.

---

## 📄 License

Dự án sử dụng cho mục đích nghiên cứu & phân tích cá nhân.
