import time
from datetime import datetime, timezone

import pandas as pd
import requests
from tqdm import tqdm

from coingecko_data_utils import (
    DATA_DIR,
    RAW_DATA_DIR,
    load_config,
    market_chart_to_daily_frame,
    parquet_covers_date_range,
    to_unix_timestamp,
)


FAILURE_LOG = DATA_DIR / "coingecko_365days_failures.txt"
MAX_RETRIES = 6
RATE_LIMIT_WAIT = 75


def get_retry_wait(response, attempt):
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return max(float(retry_after), RATE_LIMIT_WAIT)
        except ValueError:
            pass
    return RATE_LIMIT_WAIT * attempt


def request_json(url, params, timeout=30, max_retries=MAX_RETRIES):
    last_error = None

    for attempt in range(1, max_retries + 2):
        try:
            response = requests.get(url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            last_error = exc
            if attempt <= max_retries:
                wait_seconds = 10 * attempt
                tqdm.write(f"请求异常，{wait_seconds:g} 秒后重试: {exc}")
                time.sleep(wait_seconds)
                continue
            raise RuntimeError(f"Request failed: {exc}") from exc

        if response.status_code == 200:
            return response.json()

        last_error = f"HTTP {response.status_code}: {response.text[:300]}"
        if response.status_code == 429 and attempt <= max_retries:
            wait_seconds = get_retry_wait(response, attempt)
            tqdm.write(f"触发 CoinGecko 限流，{wait_seconds:g} 秒后重试...")
            time.sleep(wait_seconds)
            continue

        if 500 <= response.status_code < 600 and attempt <= max_retries:
            wait_seconds = 20 * attempt
            tqdm.write(f"CoinGecko 服务端错误 {response.status_code}，{wait_seconds:g} 秒后重试...")
            time.sleep(wait_seconds)
            continue

        raise RuntimeError(last_error)

    raise RuntimeError(last_error or "CoinGecko request failed")


def get_top_coins(base_url, top_n):
    """Fetch current top coins by market capitalization from CoinGecko."""
    url = f"{base_url}/coins/markets"
    coins = []
    page = 1
    per_page = min(250, top_n)

    while len(coins) < top_n:
        params = {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": min(per_page, top_n - len(coins)),
            "page": page,
            "sparkline": "false",
        }
        data = request_json(url, params=params)
        if not data:
            break

        coins.extend(
            {
                "id": coin.get("id"),
                "symbol": coin.get("symbol"),
                "name": coin.get("name"),
                "market_cap": coin.get("market_cap"),
            }
            for coin in data
            if coin.get("id")
        )
        page += 1

    coin_list = pd.DataFrame(coins).drop_duplicates("id").head(top_n)
    if coin_list.empty:
        raise RuntimeError("CoinGecko returned no top coins")

    return coin_list


def download_coin_history(base_url, coin_id, start_date, end_date):
    """Download one coin's recent 365-day market chart."""
    url = f"{base_url}/coins/{coin_id}/market_chart/range"
    params = {
        "vs_currency": "usd",
        "from": to_unix_timestamp(start_date),
        "to": to_unix_timestamp(end_date, end_of_day=True),
    }
    data = request_json(url, params=params)
    daily = market_chart_to_daily_frame(data, coin_id)
    if daily.empty:
        raise RuntimeError("CoinGecko returned no history")
    return daily


def append_failure(coin_id, error):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    with FAILURE_LOG.open("a", encoding="utf-8") as f:
        f.write(f"{timestamp}\t{coin_id}\t{error}\n")


def main():
    config = load_config()
    data_config = config["data"]
    base_url = config["coingecko"]["base_url"]

    start_date = data_config["start_date"]
    end_date = data_config["end_date"]
    top_n = int(data_config["top_n_coins"])
    sleep_between = float(data_config.get("sleep_between_coins", 8))
    sleep_batch = float(data_config.get("sleep_every_n_coins", 40))
    batch_size = int(data_config.get("batch_size", 15))

    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("正在获取 Top 币种列表...")
    coin_list = get_top_coins(base_url, top_n)
    coin_list_path = DATA_DIR / "coingecko_365days_coin_list.parquet"
    coin_list.to_parquet(coin_list_path, index=False)
    print(f"共获取 {len(coin_list)} 个币种，开始下载最近 365 天数据...\n")

    downloaded = 0
    skipped = 0
    failed = 0

    for i, row in enumerate(
        tqdm(coin_list.itertuples(index=False), total=len(coin_list), desc="CoinGecko 365d"),
        start=1,
    ):
        coin_id = row.id
        save_path = RAW_DATA_DIR / f"{coin_id}.parquet"

        if parquet_covers_date_range(save_path, start_date, end_date):
            skipped += 1
            continue

        try:
            history = download_coin_history(base_url, coin_id, start_date, end_date)
            history.to_parquet(save_path, index=False)
            downloaded += 1
        except Exception as exc:
            failed += 1
            append_failure(coin_id, exc)
            tqdm.write(f"下载 {coin_id} 失败: {exc}")

        time.sleep(sleep_between)

        if batch_size > 0 and i % batch_size == 0:
            tqdm.write(f"已处理 {i} 个，休息 {sleep_batch:g} 秒...")
            time.sleep(sleep_batch)

    print(
        "\nCoinGecko 最近 365 天数据下载完成: "
        f"downloaded={downloaded}, skipped={skipped}, failed={failed}, "
        f"raw_dir={RAW_DATA_DIR}"
    )
    if failed:
        print(f"失败记录已写入 {FAILURE_LOG}")


if __name__ == "__main__":
    main()
