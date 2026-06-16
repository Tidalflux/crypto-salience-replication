import pandas as pd
from tqdm import tqdm

from coingecko_data_utils import DATA_DIR, RAW_DATA_DIR, load_config


OUTPUT_PATH = DATA_DIR / "crypto_panel_365days.parquet"
BTC_OUTPUT_PATH = DATA_DIR / "btc_daily.parquet"
COIN_LIST_PATH = DATA_DIR / "coingecko_365days_coin_list.parquet"
REQUIRED_COLUMNS = ["date", "price", "market_cap", "volume", "coin_id"]


def get_raw_files():
    files = sorted(RAW_DATA_DIR.glob("*.parquet"))
    if not COIN_LIST_PATH.exists():
        return files

    coin_list = pd.read_parquet(COIN_LIST_PATH)
    coin_ids = set(coin_list["id"].dropna().astype(str))
    return [file_path for file_path in files if file_path.stem in coin_ids]


def main():
    config = load_config()
    start_date = pd.Timestamp(config["data"]["start_date"]).normalize()
    end_date = pd.Timestamp(config["data"]["end_date"]).normalize()

    print("开始合并所有币种数据...")
    files = get_raw_files()
    print(f"共发现 {len(files)} 个文件")
    if not files:
        raise FileNotFoundError("No raw parquet files found in data/raw")

    frames = []
    skipped = 0
    for file_path in tqdm(files, desc="Merging files"):
        frame = pd.read_parquet(file_path)
        missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
        if missing:
            skipped += 1
            tqdm.write(f"跳过旧格式文件 {file_path.name}: missing {missing}")
            continue
        frames.append(frame[REQUIRED_COLUMNS])

    if not frames:
        raise RuntimeError("No valid CoinGecko raw parquet files found")

    panel = pd.concat(frames, ignore_index=True)
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel[(panel["date"] >= start_date) & (panel["date"] <= end_date)]
    if panel.empty:
        raise RuntimeError("Raw parquet files contain no rows in the config date range")

    panel = panel.sort_values(["coin_id", "date"]).reset_index(drop=True)
    panel = panel.drop_duplicates(["coin_id", "date"], keep="last")
    panel["ret"] = panel.groupby("coin_id")["price"].pct_change()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(OUTPUT_PATH, index=False)
    print(f"\nPanel 数据已保存: {OUTPUT_PATH}")
    print(f"总行数: {len(panel)}")
    print(f"币种数量: {panel['coin_id'].nunique()}")
    print(f"时间范围: {panel['date'].min().date()} ~ {panel['date'].max().date()}")
    if skipped:
        print(f"跳过旧格式文件: {skipped}")

    btc = panel[panel["coin_id"] == "bitcoin"].copy()
    if not btc.empty:
        btc = btc[["date", "price", "volume", "market_cap", "ret"]]
        btc.to_parquet(BTC_OUTPUT_PATH, index=False)
        print(f"\nBTC 数据已单独保存: {BTC_OUTPUT_PATH}")
    else:
        print("\n未找到 bitcoin 数据，请检查币种 ID 是否为 'bitcoin'")


if __name__ == "__main__":
    main()
