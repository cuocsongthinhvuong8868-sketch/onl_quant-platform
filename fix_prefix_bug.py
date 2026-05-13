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

files = glob.glob('tools/*/page.py')
for f in files:
    tool_name = f.split(os.sep)[1] if os.sep in f else f.split('/')[1]
    prefix = PREFIX_MAP.get(tool_name, tool_name)
    
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
        
    if '{prefix}' in content:
        print(f"Fixing {f} with prefix {prefix}")
        content = content.replace('{prefix}', prefix)
        with open(f, 'w', encoding='utf-8') as file:
            file.write(content)
