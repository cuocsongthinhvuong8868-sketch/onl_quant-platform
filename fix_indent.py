import re

with open('tools/var_cvar_vnindex/page.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

out = []
in_block = False
for line in lines:
    if "date_str = latest_date.strftime" in line:
        in_block = True
        out.append(line)
        continue
    
    if in_block:
        if "except Exception as e:" in line:
            in_block = False
            out.append("                            except Exception as e:\n")
            continue
        
        # fix indentation
        if line.startswith("                            ") and not line.startswith("                                "):
            out.append("    " + line)
        elif line.startswith("                                ") and not line.startswith("                                    "):
            out.append("    " + line)
        elif line.startswith("                                    ") and not line.startswith("                                        "):
            out.append("    " + line)
        else:
            out.append("    " + line if line.strip() else line)
    else:
        out.append(line)

with open('tools/var_cvar_vnindex/page.py', 'w', encoding='utf-8') as f:
    f.writelines(out)
print("Fixed indent")
