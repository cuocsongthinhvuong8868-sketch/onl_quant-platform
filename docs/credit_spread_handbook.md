# Credit Spread Bank vs Bất động sản

## Mục tiêu

Dashboard so sánh chi phí huy động trái phiếu doanh nghiệp của ngành Ngân hàng và Bất động sản từ dữ liệu báo cáo VBMA. Nguồn chính là các đợt phát hành có `coupon_rate_pct` xác định được.

## Công thức

Với mỗi kỳ báo cáo `t`:

- `Bank yield`: bình quân coupon của các đợt phát hành Bank.
- `Real-estate yield`: bình quân coupon của các đợt phát hành BĐS.
- `Signed spread = Bank yield - Real-estate yield`.
- `Risk premium = Real-estate yield - Bank yield = -signed spread`.
- `Return = (signed spread[t] - signed spread[t-1]) / abs(signed spread[t-1]) * 100`.

Signed spread thường âm vì BĐS thường phải trả lãi suất cao hơn Bank. Dashboard hiển thị risk premium theo basis point (`1 điểm % = 100 bps`) để khoảng cách dương dễ đọc hơn.

## Diễn giải

- `WIDENING`: risk premium BĐS tăng so với kỳ matched trước, phản ánh khoảng cách chi phí vốn nới rộng.
- `NARROWING`: risk premium BĐS giảm, phản ánh khoảng cách chi phí vốn co hẹp.
- Chỉ các kỳ có coupon hợp lệ đồng thời ở cả Bank và BĐS mới được dùng trong đường spread.

## Phương pháp bình quân

- `Bình quân mỗi đợt phát hành`: đúng với công thức gốc, mỗi đợt có trọng số như nhau.
- `Theo giá trị phát hành`: coupon được gia quyền theo `issue_value_bn_vnd`; các dòng thiếu hoặc có giá trị phát hành không dương bị loại khỏi phép tính weighted.

## Kỳ hạn và benchmark

Lọc kỳ hạn giúp hạn chế sai lệch do duration mix. Tab TPCP dùng proxy:

| Bucket doanh nghiệp | Benchmark TPCP |
|---|---|
| Đến 3 năm | 3Y |
| Trên 3 đến 5 năm | 5Y |
| Trên 5 năm | 10Y |

Benchmark chỉ ghép quan sát TPCP cùng ngày hoặc trước ngày báo cáo doanh nghiệp, tối đa 21 ngày. Không dùng dữ liệu tương lai.

## Giới hạn

- Coupon thả nổi không quy đổi được thành số cố định bị loại.
- Đây là spread của thị trường phát hành sơ cấp, không phải option-adjusted spread trên thị trường thứ cấp.
- Sample nhỏ hoặc thay đổi cơ cấu issuer/kỳ hạn có thể tạo biến động lớn.
- Mean coupon không điều chỉnh rating, tài sản bảo đảm, seniority, quyền mua lại hoặc cấu trúc covenant.

## Cập nhật dữ liệu

```bash
python command/update_credit_spread_data.py
```

Có thể chọn nguồn khác:

```bash
python command/update_credit_spread_data.py --source-dir "C:\\path\\to\\LTMM\\data\\silver"
```

## AI Analysis và AI CIO

- Tab `AI` dùng snapshot chuẩn: bình quân đều từng đợt, tất cả bucket kỳ hạn và toàn bộ lịch sử matched. Bộ lọc hiển thị không thay đổi snapshot AI.
- Cache AI có version methodology và ngày dữ liệu. Cache cũ hoặc cache sinh trước khi dữ liệu đổi không được tái sử dụng.
- AI CIO nhận structured metrics trước, gồm premium, thay đổi 1 kỳ/3 kỳ, percentile, sample count và data quality. Báo cáo LLM chỉ là supporting prose.
- Deterministic adapter hạ confidence về trung tính nếu có dưới 8 kỳ matched hoặc một ngành có dưới 2 đợt ở kỳ gần nhất.
- AI không được suy diễn rating, default probability, collateral, covenant, chính sách SBV hoặc nguyên nhân doanh nghiệp khi input không chứa các biến này.
