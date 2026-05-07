import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from tools.esr_monitor.page import render
render()
