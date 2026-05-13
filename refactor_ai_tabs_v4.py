import glob
import os

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

def process_file(file_path):
    tool_name = file_path.split(os.sep)[1] if os.sep in file_path else file_path.split('/')[1]
    prefix = PREFIX_MAP.get(tool_name, tool_name)
    
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    out_lines = []
    i = 0
    in_ai_block = False
    indent_spaces = 0
    indent_str = ""
    
    while i < len(lines):
        line = lines[i]
        
        # start of AI cache logic
        if "today_str = date.today().strftime('%d%m%y')" in line and not in_ai_block:
            indent_str = line[:len(line) - len(line.lstrip())]
            indent_spaces = len(indent_str)
            out_lines.append(line)
            
            i += 1
            ai_cache_line = lines[i]
            if 'ai_cache_file =' in ai_cache_line:
                new_ai_cache = f'{indent_str}ai_cache_file = DATA_LAKE / "daily_cache" / f"{prefix}_{{ai_provider}}_{{today_str}}.txt"\n'
                out_lines.append(new_ai_cache)
            else:
                out_lines.append(ai_cache_line)
                
            # Read until if ai_cache_file.exists():
            while i + 1 < len(lines) and "if ai_cache_file.exists():" not in lines[i+1]:
                i += 1
                out_lines.append(lines[i])
                
            in_ai_block = True
            
            out_lines.append(f'{indent_str}tab_current, tab_history = st.tabs(["🚀 Phân tích hiện tại", "📅 Xem lại phân tích cũ"])\n')
            out_lines.append(f'{indent_str}with tab_current:\n')
            
            i += 1
            seen_else = False
            
            while i < len(lines):
                curr_line = lines[i]
                curr_stripped = curr_line.lstrip()
                curr_indent = len(curr_line) - len(curr_stripped)
                
                if curr_stripped.startswith("else:"):
                    seen_else = True
                
                # Check if we exited the block
                if curr_stripped and curr_indent <= indent_spaces and seen_else and not curr_stripped.startswith("else:"):
                    history_logic = f"""{indent_str}with tab_history:
{indent_str}    _all_caches = sorted(
{indent_str}        list(DATA_LAKE.glob(f"daily_cache/{prefix}_*.txt")),
{indent_str}        key=lambda p: p.stat().st_mtime,
{indent_str}        reverse=True,
{indent_str}    )
{indent_str}    _all_caches = _all_caches[:10]
{indent_str}    if not _all_caches:
{indent_str}        st.info("ℹ️ Chưa có dữ liệu phân tích lịch sử.")
{indent_str}    else:
{indent_str}        _options = {{}}
{indent_str}        for _fp in _all_caches:
{indent_str}            _fname = _fp.name
{indent_str}            _parts = _fname.replace(".txt", "").split("_")
{indent_str}            if len(_parts) >= 3:
{indent_str}                _date_str = _parts[-1]
{indent_str}                _provider_parts = _parts[1:-1]
{indent_str}                if "{prefix}".count("_") > 0:
{indent_str}                    prefix_parts_count = len("{prefix}".split("_"))
{indent_str}                    _provider_parts = _parts[prefix_parts_count:-1]
{indent_str}                _provider = "_".join(_provider_parts)
{indent_str}                if len(_date_str) == 6 and _date_str.isdigit():
{indent_str}                    _date_display = f"{{_date_str[:2]}}/{{_date_str[2:4]}}/{{_date_str[4:]}}"
{indent_str}                    _provider_display = AI_PROVIDER_MAP.get(_provider, {{}}).get("display", _provider)
{indent_str}                    _label = f"{{_date_display}} — {{_provider_display}}"
{indent_str}                    _options[_label] = _fp
{indent_str}        
{indent_str}        if _options:
{indent_str}            _selected_label = st.selectbox(
{indent_str}                "📅 Chọn ngày và model:",
{indent_str}                options=list(_options.keys()),
{indent_str}                index=0,
{indent_str}                key="{prefix}_history_selector"
{indent_str}            )
{indent_str}            _sel_path = _options[_selected_label]
{indent_str}            with st.container(border=True):
{indent_str}                try:
{indent_str}                    with open(_sel_path, "r", encoding="utf-8") as f:
{indent_str}                        st.markdown(f.read())
{indent_str}                except Exception as e:
{indent_str}                    st.error(f"Lỗi đọc file: {{e}}")
{indent_str}        else:
{indent_str}            st.info("ℹ️ Không thể đọc được danh sách lịch sử.")\n"""
                    out_lines.append(history_logic)
                    
                    out_lines.append(curr_line)
                    break
                
                # Removing GH Sync blocks
                if "try:" in curr_stripped and "from shared.github_sync import upload_file" in "".join(lines[i:i+4]):
                    try_indent = curr_indent
                    i += 1
                    while i < len(lines):
                        check_line = lines[i]
                        if check_line.lstrip() and len(check_line) - len(check_line.lstrip()) <= try_indent:
                            if check_line.lstrip().startswith("except"):
                                i += 1
                                while i < len(lines):
                                    check_line_2 = lines[i]
                                    if check_line_2.lstrip() and len(check_line_2) - len(check_line_2.lstrip()) <= try_indent:
                                        break
                                    i += 1
                            break
                        i += 1
                    continue
                elif "from shared.github_sync import upload_file" in curr_stripped:
                    i += 1
                    continue
                elif "[GH Sync Error]" in curr_stripped:
                    i += 1
                    continue
                
                if curr_stripped == "":
                    out_lines.append("\n")
                else:
                    out_lines.append("    " + curr_line)
                i += 1
            
        else:
            out_lines.append(line)
            i += 1

    with open(file_path, 'w', encoding='utf-8') as f:
        f.writelines(out_lines)
    print(f"Processed {file_path}")

if __name__ == '__main__':
    files = glob.glob('tools/*/page.py')
    for f in files:
        process_file(f)