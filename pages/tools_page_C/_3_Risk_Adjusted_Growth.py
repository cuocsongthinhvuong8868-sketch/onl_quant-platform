"""
pages/3_Risk_Adjusted_Growth.py — Entry point cho Risk-Adjusted Growth tool.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.page_layout import setup_page

setup_page("Quant Platform")

from tools.risk_adjusted_growth.page import render

render()
