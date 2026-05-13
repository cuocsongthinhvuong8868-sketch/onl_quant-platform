import pathlib
import json

AI_PROVIDER_MAP = {
    "kimi-2.6": {
        "display": "Kimi 2.6",
    },
    "deepseek-v4-pro": {
        "display": "DeepSeek V4 Pro",
    },
}

prefix = 'feargreed'
_all_caches = [
    pathlib.Path('data_lake/daily_cache/feargreed_deepseek-v4-pro_100526.txt'),
    pathlib.Path('data_lake/daily_cache/feargreed_deepseek-v4-pro_110526.txt'),
    pathlib.Path('data_lake/daily_cache/feargreed_kimi-2.6_120526.txt')
]

_options = {}
for _fp in _all_caches:
    _fname = _fp.name
    _parts = _fname.replace(".txt", "").split("_")
    print(_fname, _parts)
    if len(_parts) >= 3:
        _date_str = _parts[-1]
        _provider_parts = _parts[1:-1]
        if prefix.count("_") > 0:
            prefix_parts_count = len(prefix.split("_"))
            _provider_parts = _parts[prefix_parts_count:-1]
            print('adjusted provider parts', _provider_parts)
        _provider = "_".join(_provider_parts)
        print('provider', _provider, 'date', _date_str)
        if len(_date_str) == 6 and _date_str.isdigit():
            _date_display = f"{_date_str[:2]}/{_date_str[2:4]}/{_date_str[4:]}"
            _provider_display = AI_PROVIDER_MAP.get(_provider, {}).get("display", _provider)
            _label = f"{_date_display} — {_provider_display}"
            _options[_label] = _fp

print(_options)
