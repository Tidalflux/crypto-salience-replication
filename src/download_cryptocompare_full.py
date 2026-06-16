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
TOP_COINS_LIMIT = 100
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
COIN_LIST_PATH = DATA_DIR / "cryptocompare_coin_list.parquet"
FAILURE_LOG = DATA_DIR / "cryptocompare_full_failures.txt"


def safe_filename(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def is_rate_limit_error(message):
    message = message.lower()
    return "rate limit" in message or "too many requests" in message


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
    coins = []
    page = 0

    while len(coins) < top_n:
        limit = min(TOP_COINS_LIMIT, top_n - len(coins))
        params = {
            "limit": limit,
            "page": page,
            "tsym": "USD",
            "api_key": api_key,
        }
        data = request_json(url, params)
        items = data.get("Data", [])
        if not items:
            break

        for item in items:
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

        page += 1
        time.sleep(0.5)

    coin_list = pd.DataFrame(coins)
    if coin_list.empty:
        raise RuntimeError("CryptoCompare returned no top coins")

    return coin_list


def normalize_histoday_payload(data):
    payload = data.get("Data", [])
    if isinstance(payload, dict):
        payload = payload.get("Data", [])
    return payload


def fetch_histoday_page(base_url, api_key, coin_symbol, to_ts, limit=HISTODAY_LIMIT):
    url = f"{base_url}/histoday"
    params = {
        "fsym": coin_symbol,
        "tsym": "USD",
        "limit": limit,
        "toTs": to_ts,
        "api_key": api_key,
    }
    data = request_json(url, params)
    payload = normalize_histoday_payload(data)
    if not payload:
        return pd.DataFrame(), None

    page = pd.DataFrame(payload)
    if page.empty or "time" not in page.columns:
        return pd.DataFrame(), None

    earliest_ts = int(page["time"].min())
    page["date"] = pd.to_datetime(page["time"], unit="s").dt.normalize()
    page = page.rename(columns={"close": "price", "volumeto": "volume"})

    for column in ["price", "high", "low", "open", "volume"]:
        if column not in page.columns:
            page[column] = pd.NA

    page = page[["date", "price", "high", "low", "open", "volume"]]
    page["coin_id"] = coin_symbol

    return page, earliest_ts


def download_full_history(base_url, api_key, coin_symbol, start_date, end_date, sleep_time):
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    current_to_ts = int(end.timestamp())
    start_ts = int(start.timestamp())
    pages = []

    while True:
        current_to_date = pd.Timestamp(current_to_ts, unit="s").normalize()
        days_needed = max((current_to_date - start).days, 1)
        limit = min(HISTODAY_LIMIT, days_needed)

        page, earliest_ts = fetch_histoday_page(
            base_url, api_key, coin_symbol, current_to_ts, limit=limit
        )
        if page.empty or earliest_ts is None:
            break

        pages.append(page)
        if earliest_ts <= start_ts:
            break

        current_to_ts = earliest_ts - 1
        time.sleep(sleep_time)

    if not pages:
        return pd.DataFrame()

    history = pd.concat(pages, ignore_index=True)
    history = history[(history["date"] >= start) & (history["date"] <= end)]
    history = history.drop_duplicates("date", keep="last").sort_values("date")
    history["date"] = history["date"].dt.date

    return history[["date", "price", "high", "low", "open", "volume", "coin_id"]]


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

    print("正在获取 Top 币种列表...")
    coin_list = get_top_coins(base_url, api_key, top_n)
    coin_list.to_parquet(COIN_LIST_PATH, index=False)
    print(f"共获取 {len(coin_list)} 个币种，开始下载历史数据...\n")
    time.sleep(sleep_time)

    downloaded = 0
    skipped = 0
    failed = 0

    for _, row in tqdm(
        coin_list.iterrows(), total=len(coin_list), desc="Downloading full history"
    ):
        coin_symbol = row["symbol"]
        save_path = RAW_DIR / f"{safe_filename(coin_symbol)}.parquet"

        if parquet_covers_date_range(save_path, start_date, end_date):
            skipped += 1
            continue

        try:
            history = download_full_history(
                base_url, api_key, coin_symbol, start_date, end_date, sleep_time
            )
            if history.empty:
                raise RuntimeError("empty history")

            history.to_parquet(save_path, index=False)
            downloaded += 1
        except Exception as exc:
            failed += 1
            log_failure(coin_symbol, exc)
            tqdm.write(f"下载 {coin_symbol} 失败: {exc}")

        time.sleep(sleep_time)

    print(
        "\n完整历史数据下载完成: "
        f"downloaded={downloaded}, skipped={skipped}, failed={failed}, "
        f"raw_dir={RAW_DIR}"
    )
    if failed:
        print(f"失败记录已保存到 {FAILURE_LOG}")


if __name__ == "__main__":
    main()
