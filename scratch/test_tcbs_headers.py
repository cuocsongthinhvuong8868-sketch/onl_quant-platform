import requests
import json

try:
    url = "https://apipubaws.tcbs.com.vn/tcanalysis/v1/finance/VCB?yearly=0&isAll=true"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    res = requests.get(url, headers=headers)
    data = res.json()
    if isinstance(data, dict):
        print("Keys:", data.keys())
        if 'data' in data:
            print("Data length:", len(data['data']))
            print("First item:", data['data'][0])
    elif isinstance(data, list):
        print("Data length:", len(data))
        print("First item:", data[0])
except Exception as e:
    print("Error:", e)
