import time

import pandas as pd
from pycoingecko import CoinGeckoAPI

from coingecko_data_utils import DATA_DIR, load_config


MAX_COINS_PER_PAGE = 250


def fetch_top_coins(cg, top_n):
    records = []
    page = 1

    while len(records) < top_n:
        per_page = min(MAX_COINS_PER_PAGE, top_n - len(records))
        coins = cg.get_coins_markets(
            vs_currency="usd",
            order="market_cap_desc",
            per_page=per_page,
            page=page,
            sparkline=False,
        )

        if not coins:
            break

        records.extend(coins)
        page += 1

        if len(records) < top_n:
            time.sleep(1)

    return records[:top_n]


def main():
    config = load_config()
    top_n = int(config["data"]["top_n_coins"])
    if top_n <= 0:
        raise ValueError("data.top_n_coins must be a positive integer")

    cg = CoinGeckoAPI()
    coins = fetch_top_coins(cg, top_n)

    coin_df = pd.DataFrame(coins).reindex(
        columns=["id", "symbol", "name", "market_cap"]
    )
    if coin_df.empty:
        raise RuntimeError("CoinGecko returned no coins")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DATA_DIR / "coin_list.parquet"
    coin_df.to_parquet(output_path, index=False)

    print(f"已获取 {len(coin_df)} 个币种")
    print(f"已保存到 {output_path}")
    print(coin_df.head())


if __name__ == "__main__":
    main()
