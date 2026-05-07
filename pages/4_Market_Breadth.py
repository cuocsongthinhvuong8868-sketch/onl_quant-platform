"""
pages/4_Market_Breadth.py — Entry point cho Market Breadth tool.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.market_breadth.page import render

render()
