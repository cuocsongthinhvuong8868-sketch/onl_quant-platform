import os
import glob

def append_history(file_path, prefix):
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
        if "with tab_history:" in content:
            print(f"{file_path} already has tab_history.")
            return
            
    # Determine the indentation of the AI block
    # Typically, the AI block is under an `if st.button(...)` or just `else:`
    # For va_res and var_cvar_vnindex, it's inside `with col2:` or `with tab_current:`
    # We will use 4 spaces for most, and 8 spaces if we detect it's deeper.
    indent = "    "
    if "va_res" in file_path or "var_cvar_vnindex" in file_path:
        indent = "        "

    history_logic = f"""
{indent}with tab_history:
{indent}    _all_caches = sorted(
{indent}        list(DATA_LAKE.glob(f"daily_cache/{{prefix}}_*.txt")),
{indent}        key=lambda p: p.stat().st_mtime,
{indent}        reverse=True,
{indent}    )
{indent}    _all_caches = _all_caches[:10]
{indent}    if not _all_caches:
{indent}        st.info("ℹ️ Chưa có dữ liệu phân tích lịch sử.")
{indent}    else:
{indent}        _options = {{}}
{indent}        for _fp in _all_caches:
{indent}            _fname = _fp.name
{indent}            _parts = _fname.replace(".txt", "").split("_")
{indent}            if len(_parts) >= 3:
{indent}                _date_str = _parts[-1]
{indent}                _provider_parts = _parts[1:-1]
{indent}                if "{{prefix}}".count("_") > 0:
{indent}                    prefix_parts_count = len("{{prefix}}".split("_"))
{indent}                    _provider_parts = _parts[prefix_parts_count:-1]
{indent}                _provider = "_".join(_provider_parts)
{indent}                if len(_date_str) == 6 and _date_str.isdigit():
{indent}                    _date_display = f"{{_date_str[:2]}}/{{_date_str[2:4]}}/{{_date_str[4:]}}"
{indent}                    _provider_display = AI_PROVIDER_MAP.get(_provider, {{}}).get("display", _provider)
{indent}                    _label = f"{{_date_display}} — {{_provider_display}}"
{indent}                    _options[_label] = _fp
{indent}        
{indent}        if _options:
{indent}            _selected_label = st.selectbox(
{indent}                "📅 Chọn ngày và model:",
{indent}                options=list(_options.keys()),
{indent}                index=0,
{indent}                key="{{prefix}}_history_selector"
{indent}            )
{indent}            _sel_path = _options[_selected_label]
{indent}            with st.container(border=True):
{indent}                try:
{indent}                    with open(_sel_path, "r", encoding="utf-8") as f:
{indent}                        st.markdown(f.read())
{indent}                except Exception as e:
{indent}                    st.error(f"Lỗi đọc file: {{e}}")
{indent}        else:
{indent}            st.info("ℹ️ Không thể đọc được danh sách lịch sử.")
"""
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(history_logic)
    print(f"Appended history to {file_path}")

PREFIX_MAP = {
    'dispersion': 'dispersion',
    'esr_monitor': 'esr_monitor',
    'fear_greed': 'feargreed',
    'manipulation': 'manipulation',
    'market_breadth': 'market_breadth',
    'risk_adjusted_growth': 'risk_adjusted_growth',
    'upside_ratio': 'upside_ratio',
    'va_res': 'va_res',
    'var_cvar_vnindex': 'var_cvar_vnindex'
}

files = glob.glob('tools/*/page.py')
for f in files:
    tool_name = f.split(os.sep)[1] if os.sep in f else f.split('/')[1]
    prefix = PREFIX_MAP.get(tool_name, tool_name)
    append_history(f, prefix)
