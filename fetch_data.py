import os
import requests
from EIAOpenData import EIAOpenData

my_api_key = os.environ["EIA_API_KEY"]
eia = EIAOpenData(my_api_key)


def fetch_all(url, params):
    rows = []
    offset = 0
    while True:
        p = {**params, "length": 5000, "offset": offset}
        r = requests.get(url, params=p)
        r.raise_for_status()
        payload = r.json()["response"]
        rows.extend(payload["data"])
        offset += 5000
        if offset >= int(payload["total"]):
            break
    return rows
