import pandas as pd
from tqdm import tqdm

from coingecko_data_utils import DATA_DIR, RAW_DATA_DIR, load_config


OUTPUT_PATH = DATA_DIR / "crypto_panel_2020_2025.parquet"
REQUIRED_COLUMNS = ["date", "price", "market_cap", "volume", "coin_id"]


def main():
    config = load_config()
    start_date = pd.Timestamp(config["data"]["start_date"]).normalize()
    end_date = pd.Timestamp(config["data"]["end_date"]).normalize()

    files = sorted(RAW_DATA_DIR.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(
            "No raw parquet files found. Run the download scripts first."
        )

    frames = []
    for file_path in tqdm(files, desc="Merging"):
        frame = pd.read_parquet(file_path)
        missing = [col for col in REQUIRED_COLUMNS if col not in frame.columns]
        if missing:
            raise ValueError(f"{file_path} is missing columns: {missing}")
        frames.append(frame[REQUIRED_COLUMNS])

    panel = pd.concat(frames, ignore_index=True)
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel[(panel["date"] >= start_date) & (panel["date"] <= end_date)]
    if panel.empty:
        raise RuntimeError(
            "Raw parquet files contain no rows within the configured date range"
        )

    panel = panel.sort_values(["coin_id", "date"])
    panel = panel.drop_duplicates(["coin_id", "date"], keep="last")
    panel["ret"] = panel.groupby("coin_id")["price"].pct_change()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(OUTPUT_PATH, index=False)

    print(f"Panel 数据已保存到 {OUTPUT_PATH}")
    print(f"共 {len(panel)} 行，{panel['coin_id'].nunique()} 个币种")
    print(panel.head())


if __name__ == "__main__":
    main()
