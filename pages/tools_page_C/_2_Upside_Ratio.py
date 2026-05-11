"""
pages/2_Upside_Ratio.py — Entry point cho Upside Ratio tool.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.page_layout import setup_page

setup_page("Quant Platform")

from tools.upside_ratio.page import render

render()
