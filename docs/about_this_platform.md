# About This Platform - Tóm tắt Methodology

`onl_quant-platform` là một research workbench cho thị trường cổ phiếu Việt Nam. Nền tảng không phải trading bot tự động; mục tiêu là biến dữ liệu vĩ mô, dòng tiền, rủi ro, định giá, factor và sentiment thành bằng chứng có cấu trúc để hỗ trợ quyết định đầu tư.

## 1. Research Pipeline

1. **Thu thập dữ liệu**
   - Giá và khối lượng cổ phiếu từ universe `tickers.csv`.
   - VNINDEX/VN30, VNIBOR, FRED/Yahoo macro series, Mozyfin/WiData news, BCTC JSON và các snapshot trong `data_lake/`.
   - Các updater trong `command/` ghi snapshot về local data lake để app và report đọc lại một cách lặp lại được.

2. **Chuẩn hóa và kiểm soát chất lượng**
   - `shared/data_loader.py`, `src/data_manager.py` và `config/data_rules.yaml` tách việc đọc dữ liệu, freshness check, missing-date detection và source rules.
   - Volume không bị forward-fill trong các path cần đo liquidity/risk để tránh làm méo tín hiệu stress.
   - Cache tính toán dùng `shared/daily_cache.py` với key hash theo tham số và methodology version.

3. **Biến đổi thành evidence**
   - Rolling z-score, percentile rank, PCA point-in-time, EVT, HMM, IC validation, factor ranking, valuation spread và sentiment taxonomy tạo thành các evidence packet.
   - Streamlit page chỉ render UI; logic định lượng nằm trong `tools/*/quant/`, chart/sidebar nằm trong `tools/*/ui/`, report snapshot nằm trong `tools/*/report.py`.

4. **Tổng hợp AI-CIO**
   - `shared/ai_cio.py` đọc các child reports, macro overlays, history ledger và humility/falsification context.
   - LLM chỉ đóng vai trò tổng hợp trên evidence đã tính sẵn; score/regime và hard constraints vẫn được tạo từ deterministic context.

## 2. Các lớp methodology chính

| Lớp | Công cụ | Phương pháp |
| --- | --- | --- |
| Macro liquidity | Fed Liquidity, GFCM, VNIBOR, LTMM | Net liquidity, interbank rates, 11-indicator global stress, PCA core, percentile regime, liquidity transmission |
| Market internals & behavior | Fear & Greed, Breadth, Dispersion, ESR, VaRES, VaR/CVaR, ABM, sentiment feed | PCA, EGARCH/GARCH/EWMA fallback, HMM/rule regimes, CSAD/CSSD, EVT POT-GPD, Hill tail diagnostic, news taxonomy |
| Micro research | Factor Examination, Pairs Trading, Risk-Adjusted Growth | Sector-neutral factor z-score, IC validation, Engle-Granger/Johansen, OU half-life, Hurst, bank growth quality |
| Valuation & fundamentals | Bank Valuation, VN100 Corporate Health, PVGO | Adjusted book value, sustainable ROE, residual income, justified P/B, earnings health matrix, P/E-PVGO context |
| Reporting & audit | AI-CIO, Data Health, Humility/Falsification | Evidence packets, decision-state ledger, stale-data checks, falsification rules, PDF/Telegram/GitHub automation |

## 3. Nguyên tắc quan trọng

- **Point-in-time first**: các PCA/regime path quan trọng tránh dùng covariance từ tương lai.
- **Evidence before narrative**: AI report chỉ được tổng hợp từ metrics, report snapshot và context có sẵn.
- **Human-in-the-loop**: kết quả là decision support, không phải lệnh mua bán tự động.
- **Model humility**: có layer để kiểm tra điều kiện phủ định, stale data, confidence haircut và tail-risk override.
- **Traceability**: data lake, daily cache, generated reports và AI-CIO ledger giữ lại dấu vết để review lại.

## 4. Giới hạn hiện tại

- `shared/ai_cio.py` đang là module lớn, nên tách thành registry/adapters nếu thêm nhiều công cụ.
- Một số path UI/report vẫn bắt `Exception` rộng; nên thay bằng exception cụ thể và logging có cấu trúc.
- Pairs trading cần adjusted-price pipeline tốt hơn cho dividends/splits/corporate actions.
- Cache một số report còn dựa vào ngày chạy local; data-date-aware cache sẽ tốt hơn cho cloud và timezone.
- Kết quả strategy cần thêm out-of-sample, walk-forward, transaction-cost sensitivity và leakage audit trước khi dùng live.
