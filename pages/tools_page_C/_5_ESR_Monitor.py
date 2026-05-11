import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.page_layout import setup_page
setup_page("Quant Platform")

from tools.esr_monitor.page import render
render()
