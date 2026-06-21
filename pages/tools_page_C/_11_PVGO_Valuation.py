import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.page_layout import setup_page
from tools.pvgo.page import render


setup_page("Quant Platform - PVGO Valuation")
render()

