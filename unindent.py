import re

with open('tools/var_cvar_vnindex/page.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

ai_start = -1
for i, line in enumerate(lines):
    if "st.subheader(\"✨ Trợ lý AI Phân tích VaR-CVaR VNINDEX\")" in line:
        ai_start = i - 1 
        break

if ai_start != -1:
    new_lines = lines[:ai_start]
    ai_lines = lines[ai_start:]
    unindented_ai_lines = []
    for line in ai_lines:
        if line.startswith("        "): # unindent 4 spaces from 8 spaces to 4 spaces, wait, the whole block is at 8 spaces!
            unindented_ai_lines.append(line[4:])
        elif line.startswith("    ") and len(line.strip()) == 0:
            unindented_ai_lines.append("\n")
        else:
            # what if it's already 4 spaces?
            if line.startswith("    ") and not line.startswith("        "):
                unindented_ai_lines.append(line)
            else:
                unindented_ai_lines.append(line)
    
    with open('tools/var_cvar_vnindex/page.py', 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
        f.writelines(unindented_ai_lines)
    print("Fixed var_cvar_vnindex/page.py")
