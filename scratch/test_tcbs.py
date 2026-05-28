import requests

try:
    url = "https://apipubaws.tcbs.com.vn/tcanalysis/v1/finance/VCB?yearly=0&isAll=true"
    res = requests.get(url)
    data = res.json()
    if isinstance(data, dict):
        print("Keys:", data.keys())
        if 'data' in data:
            print(data['data'][:2])
    elif isinstance(data, list):
        print(data[:2])
except Exception as e:
    print("Error:", e)
