"""
pages/1_Fear_Greed.py — Entry point cho Streamlit multi-page.
Logic thực tế nằm trong tools/fear_greed/.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.fear_greed.page import render
render()
