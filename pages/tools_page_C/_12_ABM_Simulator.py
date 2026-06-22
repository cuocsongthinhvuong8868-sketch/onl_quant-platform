import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.page_layout import setup_page
from tools.abm_simulator.page import render


setup_page("Quant Platform - ABM Simulator")
render()

