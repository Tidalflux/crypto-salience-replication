import time
from datetime import datetime, timezone

import pandas as pd
from pycoingecko import CoinGeckoAPI
from tqdm import tqdm

from coingecko_data_utils import (
    DATA_DIR,
    RAW_DATA_DIR,
    load_config,
    add_public_api_hint,
    market_chart_to_daily_frame,
    parquet_covers_date_range,
    to_unix_timestamp,
)


FAILURE_LOG = DATA_DIR / "download_failures.txt"


def append_failure(coin_id, error):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    with FAILURE_LOG.open("a", encoding="utf-8") as f:
        f.write(f"{timestamp}\t{coin_id}\t{error}\n")


def download_one_coin(cg, coin_id, start_ts, end_ts):
    data = cg.get_coin_market_chart_range_by_id(
        id=coin_id,
        vs_currency="usd",
        from_timestamp=start_ts,
        to_timestamp=end_ts,
    )
    daily = market_chart_to_daily_frame(data, coin_id)
    if daily.empty:
        raise RuntimeError("CoinGecko returned no history")
    return daily


def main():
    config = load_config()
    data_config = config["data"]

    coin_list_path = DATA_DIR / "coin_list.parquet"
    if not coin_list_path.exists():
        raise FileNotFoundError(
            "Missing data/coin_list.parquet. Run python src/get_coin_list.py first."
        )

    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    coin_list = pd.read_parquet(coin_list_path)
    coin_ids = coin_list["id"].dropna().drop_duplicates().tolist()

    start_ts = to_unix_timestamp(data_config["start_date"])
    end_ts = to_unix_timestamp(data_config["end_date"], end_of_day=True)
    sleep_between = float(data_config.get("sleep_between_coins", 10))
    sleep_every = float(data_config.get("sleep_every_n_coins", 60))
    batch_size = int(data_config.get("batch_size", 20))

    cg = CoinGeckoAPI()
    attempted = 0
    downloaded = 0
    skipped = 0
    failed = 0

    for coin_id in tqdm(coin_ids, desc="Downloading coins"):
        output_path = RAW_DATA_DIR / f"{coin_id}.parquet"
        if parquet_covers_date_range(
            output_path, data_config["start_date"], data_config["end_date"]
        ):
            skipped += 1
            continue
        if output_path.exists():
            tqdm.write(f"{coin_id} 已存在但日期范围不匹配，将重新下载")

        attempted += 1
        try:
            daily = download_one_coin(cg, coin_id, start_ts, end_ts)
            daily.to_parquet(output_path, index=False)
            downloaded += 1
        except Exception as exc:
            failed += 1
            error_message = add_public_api_hint(exc)
            append_failure(coin_id, error_message)
            tqdm.write(f"下载 {coin_id} 失败: {error_message}")

        time.sleep(sleep_between)

        if batch_size > 0 and attempted % batch_size == 0:
            tqdm.write(
                f"已尝试下载 {attempted} 个币种，休息 {sleep_every:g} 秒..."
            )
            time.sleep(sleep_every)

    print(
        "下载结束: "
        f"downloaded={downloaded}, skipped={skipped}, failed={failed}, "
        f"raw_dir={RAW_DATA_DIR}"
    )
    if failed:
        print(f"失败记录已写入 {FAILURE_LOG}")


if __name__ == "__main__":
    main()
