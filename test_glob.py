import pathlib
from config import DATA_LAKE

print('DATA_LAKE.glob:', list(DATA_LAKE.glob("daily_cache/feargreed_*.txt")))
print('(DATA_LAKE / "daily_cache").glob:', list((DATA_LAKE / "daily_cache").glob("feargreed_*.txt")))
