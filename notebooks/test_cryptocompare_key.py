import os

import requests
import yaml
from dotenv import load_dotenv


load_dotenv()

with open("config.yaml", encoding="utf-8") as f:
    config = yaml.safe_load(f)

api_key = os.getenv(config["cryptocompare"]["api_key_env"])

url = f"{config['cryptocompare']['base_url']}/price"
params = {
    "fsym": "BTC",
    "tsyms": "USD",
    "api_key": api_key,
}

response = requests.get(url, params=params, timeout=30)
print("Status Code:", response.status_code)
print("Response:", response.json())
