from pycoingecko import CoinGeckoAPI

from coingecko_data_utils import (
    RAW_DATA_DIR,
    add_public_api_hint,
    load_config,
    market_chart_to_daily_frame,
    parquet_covers_date_range,
    to_unix_timestamp,
)


BTC_COIN_ID = "bitcoin"


def main():
    config = load_config()
    data_config = config["data"]

    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RAW_DATA_DIR / f"{BTC_COIN_ID}.parquet"
    if parquet_covers_date_range(
        output_path, data_config["start_date"], data_config["end_date"]
    ):
        print(f"BTC 数据已存在，跳过: {output_path}")
        return
    if output_path.exists():
        print(f"BTC 数据已存在但日期范围不匹配，将重新下载: {output_path}")

    start_ts = to_unix_timestamp(data_config["start_date"])
    end_ts = to_unix_timestamp(data_config["end_date"], end_of_day=True)

    cg = CoinGeckoAPI()
    try:
        data = cg.get_coin_market_chart_range_by_id(
            id=BTC_COIN_ID,
            vs_currency="usd",
            from_timestamp=start_ts,
            to_timestamp=end_ts,
        )
    except Exception as exc:
        print(f"下载 {BTC_COIN_ID} 失败: {add_public_api_hint(exc)}")
        raise SystemExit(1) from None
    daily = market_chart_to_daily_frame(data, BTC_COIN_ID)
    if daily.empty:
        raise RuntimeError("CoinGecko returned no BTC history")

    daily.to_parquet(output_path, index=False)
    print(f"BTC 数据已保存到 {output_path}，共 {len(daily)} 行")


if __name__ == "__main__":
    main()
