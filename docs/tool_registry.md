# Tool Registry Baseline

`shared/tool_registry.py` là nguồn metadata chung cho các công cụ trong app. Các hub page, report discovery và các bước nâng cấp tiếp theo nên đọc từ registry này thay vì tự giữ danh sách riêng.

## Contract Chung

Mỗi tool nên có các metadata sau:

| Field | Ý nghĩa |
| --- | --- |
| `id` | Khóa ổn định cho cache, report, workflow và AI CIO evidence. |
| `branch` | Nhánh hiển thị: `macro`, `micro`, `behavioral`, `data`, hoặc `engine`. |
| `page_module` / `render_func` | Entry Streamlit để hub render động. |
| `package` | Python package chính của tool. |
| `page_entry` | File entry cũ trong `pages/tools_page_*` nếu có. |
| `has_report` | Tool có `tools/<id>/report.py:snapshot(...)` cho report discovery. |
| `update_commands` | CLI liên quan để refresh dữ liệu hoặc precompute cache. |
| `cache_namespaces` | Namespace cache đang dùng trong `data_lake/daily_cache`. |
| `ai_cio_role` | Vai trò trong AI CIO: scoring, child report, context, audit, gate, research. |

## Inventory Theo Nhánh

| Branch | Tool ID | Package | Report | AI CIO role |
| --- | --- | --- | --- | --- |
| Macro | `fed_liquidity` | `tools.fed_liquidity` | yes | `macro_child_report` |
| Macro | `global_financial_conditions` | `tools.global_financial_conditions` | yes | `macro_child_report` |
| Macro | `humility_falsification` | `tools.humility_falsification` | yes | `audit_evidence` |
| Macro | `vnibor` | `tools.vnibor` | yes | `macro_child_report` |
| Macro | `bank_valuation` | `tools.bank_valuation` | yes | `executive_scoring` |
| Macro | `ltmm` | `tools.ltmm` | yes | `macro_context` |
| Macro | `vn100_earnings_health` | `tools.vn100_earnings_health` | yes | `macro_context` |
| Macro | `credit_spread` | `tools.credit_spread` | yes | `macro_child_report` |
| Micro | `pairs_trading` | `tools.pairs_trading` | yes | `research_tool` |
| Micro | `factor_examination` | `tools.factor_examination` | yes | `standalone_ai` |
| Micro | `risk_adjusted_growth` | `tools.risk_adjusted_growth` | yes | `executive_scoring` |
| Behavioral | `fear_greed` | `tools.fear_greed` | yes | `executive_scoring` |
| Behavioral | `sentiment_factor_news` | `tools.sentiment_factor_news` | yes | `executive_scoring` |
| Behavioral | `pvgo` | `tools.pvgo` | yes | `valuation_context` |
| Behavioral | `upside_ratio` | `tools.upside_ratio` | yes | `executive_scoring` |
| Behavioral | `market_breadth` | `tools.market_breadth` | yes | `executive_scoring` |
| Behavioral | `esr_monitor` | `tools.esr_monitor` | yes | `executive_scoring` |
| Behavioral | `dispersion` | `tools.dispersion` | yes | `executive_scoring` |
| Behavioral | `va_res` | `tools.va_res` | yes | `executive_scoring` |
| Behavioral | `manipulation` | `tools.manipulation` | yes | `executive_scoring` |
| Behavioral | `var_cvar_vnindex` | `tools.var_cvar_vnindex` | yes | `executive_scoring` |
| Behavioral | `abm_simulator` | `tools.abm_simulator` | yes | `structured_context` |
| Behavioral | `backtest` | `tools.backtest` | no | `research_tool` |
| Data | `data_health` | `tools.data_health` | yes | `operations` |
| Engine | `capitulation_regime` | `tools.capitulation_regime` | yes | `diagnostic_gate` |

## Chuẩn Nâng Cấp Từng Tool

Khi chuẩn hóa một tool, đi theo thứ tự:

1. Đảm bảo registry đúng: branch, page module, update command, cache namespace và AI CIO role.
2. Tách rõ `quant/`, `ui/`, `page.py`; giữ `page.py` là adapter Streamlit mỏng.
3. Nếu tool cần report tổng hợp, thêm `report.py:snapshot(df_close, load_custom) -> dict`.
4. Dùng `shared/daily_cache.py` cho cache tính toán có `data_date` và key deterministic.
5. Thêm test cho contract dữ liệu, cache key, methodology version và edge case của model.
