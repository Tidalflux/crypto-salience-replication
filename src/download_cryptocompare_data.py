import re
import time
from datetime import timedelta

import pandas as pd
import requests
from tqdm import tqdm

from cryptocompare_data_utils import (
    PROJECT_ROOT,
    load_config,
    load_cryptocompare_api_key,
)


HISTODAY_LIMIT = 2000
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
COIN_LIST_PATH = DATA_DIR / "cryptocompare_coin_list.parquet"
FAILURE_LOG = DATA_DIR / "cryptocompare_download_failures.txt"


def safe_filename(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def is_rate_limit_error(message):
    return "rate limit" in message.lower() or "too many requests" in message.lower()


def request_json(url, params, timeout=30, max_retries=3, retry_wait=10):
    last_error = None

    for attempt in range(max_retries + 1):
        response = requests.get(url, params=params, timeout=timeout)
        if response.status_code == 429:
            last_error = f"HTTP 429: {response.text[:300]}"
            if attempt < max_retries:
                time.sleep(retry_wait * (attempt + 1))
                continue
            raise RuntimeError(last_error)

        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")

        data = response.json()
        if data.get("Response") == "Error":
            message = data.get("Message", "CryptoCompare returned an error")
            last_error = message
            if is_rate_limit_error(message) and attempt < max_retries:
                time.sleep(retry_wait * (attempt + 1))
                continue
            raise RuntimeError(message)

        return data

    raise RuntimeError(last_error or "CryptoCompare request failed")


def get_top_coins(base_url, api_key, top_n):
    url = f"{base_url}/top/mktcapfull"
    params = {
        "limit": top_n,
        "tsym": "USD",
        "api_key": api_key,
    }
    data = request_json(url, params)

    coins = []
    for item in data.get("Data", []):
        coin_info = item.get("CoinInfo", {})
        raw_usd = item.get("RAW", {}).get("USD", {})
        symbol = coin_info.get("Name")
        if not symbol:
            continue

        coins.append(
            {
                "id": symbol,
                "symbol": symbol,
                "name": coin_info.get("FullName"),
                "market_cap": raw_usd.get("MKTCAP"),
            }
        )

    coin_list = pd.DataFrame(coins)
    if coin_list.empty:
        raise RuntimeError("CryptoCompare returned no top coins")

    return coin_list


def normalize_histoday_payload(data):
    payload = data.get("Data", [])
    if isinstance(payload, dict):
        payload = payload.get("Data", [])
    return payload


def download_coin_history(base_url, api_key, coin_symbol, start_date, end_date):
    url = f"{base_url}/histoday"
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    current_end = end
    chunks = []

    while current_end >= start:
        days_needed = max((current_end - start).days, 1)
        limit = min(HISTODAY_LIMIT, days_needed)
        params = {
            "fsym": coin_symbol,
            "tsym": "USD",
            "limit": limit,
            "toTs": int(current_end.timestamp()),
            "api_key": api_key,
        }

        data = request_json(url, params)
        payload = normalize_histoday_payload(data)
        if not payload:
            break

        chunk = pd.DataFrame(payload)
        if chunk.empty or "time" not in chunk.columns:
            break

        chunk["date"] = pd.to_datetime(chunk["time"], unit="s").dt.normalize()
        chunks.append(chunk)

        earliest_date = chunk["date"].min()
        if earliest_date <= start:
            break

        current_end = earliest_date - timedelta(days=1)

    if not chunks:
        return pd.DataFrame()

    history = pd.concat(chunks, ignore_index=True)
    history = history.rename(
        columns={
            "close": "price",
            "volumeto": "volume",
        }
    )

    for column in ["price", "high", "low", "open", "volume"]:
        if column not in history.columns:
            history[column] = pd.NA

    history = history[["date", "price", "high", "low", "open", "volume"]]
    history = history[(history["date"] >= start) & (history["date"] <= end)]
    history = history.drop_duplicates("date", keep="last").sort_values("date")
    history["coin_id"] = coin_symbol
    history["date"] = history["date"].dt.date

    return history


def parquet_covers_date_range(path, start_date, end_date):
    if not path.exists():
        return False

    try:
        dates = pd.read_parquet(path, columns=["date"])
    except Exception:
        return False

    if dates.empty:
        return False

    observed_dates = pd.to_datetime(dates["date"])
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()

    return observed_dates.min() <= start and observed_dates.max() >= end


def log_failure(coin_symbol, error):
    with FAILURE_LOG.open("a", encoding="utf-8") as f:
        f.write(f"{pd.Timestamp.utcnow().isoformat()}\t{coin_symbol}\t{error}\n")


def main():
    config = load_config()
    api_key = load_cryptocompare_api_key(config)
    base_url = config["cryptocompare"]["base_url"]
    data_config = config["data"]

    start_date = data_config["start_date"]
    end_date = data_config["end_date"]
    top_n = int(data_config["top_n_coins"])
    sleep_time = float(data_config.get("sleep_between_requests", 1.5))

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    print("开始获取币种列表...")
    coin_list = get_top_coins(base_url, api_key, top_n)
    coin_list.to_parquet(COIN_LIST_PATH, index=False)
    print(f"共获取 {len(coin_list)} 个币种，已保存到 {COIN_LIST_PATH}")
    time.sleep(sleep_time)

    downloaded = 0
    skipped = 0
    failed = 0

    for _, row in tqdm(
        coin_list.iterrows(), total=len(coin_list), desc="Downloading coins"
    ):
        coin_symbol = row["symbol"]
        save_path = RAW_DIR / f"{safe_filename(coin_symbol)}.parquet"

        if parquet_covers_date_range(save_path, start_date, end_date):
            skipped += 1
            continue

        try:
            frame = download_coin_history(base_url, api_key, coin_symbol, start_date, end_date)
            if frame.empty:
                raise RuntimeError("empty history")

            frame.to_parquet(save_path, index=False)
            downloaded += 1
        except Exception as exc:
            failed += 1
            log_failure(coin_symbol, exc)
            tqdm.write(f"下载 {coin_symbol} 失败: {exc}")

        time.sleep(sleep_time)

    print(
        "\n数据下载完成: "
        f"downloaded={downloaded}, skipped={skipped}, failed={failed}, "
        f"raw_dir={RAW_DIR}"
    )
    if failed:
        print(f"失败记录已保存到 {FAILURE_LOG}")


if __name__ == "__main__":
    main()
