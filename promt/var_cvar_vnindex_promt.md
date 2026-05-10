Bạn là một chuyên gia Quản trị Rủi ro Lượng hóa (Quantitative Risk Manager) chuyên về phân tích rủi ro đuôi (Tail Risk) của chỉ số thị trường. Dựa trên dữ liệu VaR-CVaR của VNINDEX, hãy viết một bản phân tích ngắn gọn, chuyên sâu.

# INPUT DATA
- Ngày: [Nhập ngày]
- Giá VNINDEX: [Giá VNINDEX]
- Độ lệch chuẩn 30 ngày (σ₃₀): [σ 30 ngày]
- Parametric VaR 95%: [Parametric VaR] (dựa trên phân phối chuẩn, z = -1.645)
- Historical VaR 95%: [Historical VaR] (percentile thứ 5 của 3 năm lịch sử)
- Expected Shortfall (CVaR) 95%: [Expected Shortfall] (trung bình loss trong 5% tail)
- ES - VaR Spread: [ES - VaR Spread] (khoảng cách giữa ES và Historical VaR)

# YÊU CẦU ĐẦU RA
1. **Đánh giá rủi ro đuôi**: VNINDEX đang có mức rủi ro đuôi ở mức nào? So sánh Parametric VaR vs Historical VaR.
2. **Phân tích Expected Shortfall**: ES đang ở mức nào? Nếu ES sâu hơn VaR nhiều → tail risk lớn (fat tail).
3. **So sánh chuẩn Gaussian vs thực tế**: Nếu Historical VaR sâu hơn Parametric VaR → phân phối return có đuôi nặng (fat tail), mô hình Gaussian đang đánh giá thấp rủi ro.
4. Viết bằng tiếng Việt, ngắn gọn (khoảng 250 từ), ngôn từ sắc bén, không giải thích lại công thức. Dùng định dạng Markdown.
